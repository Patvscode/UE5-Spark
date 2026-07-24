#include "FayCore27EpicAnimInstance.h"

#include "Animation/AnimInstanceProxy.h"
#include "Animation/Skeleton.h"
#include "BoneContainer.h"
#include "BonePose.h"
#include "Engine/SkeletalMesh.h"
#include "FayArdyCoordinateConversion.h"
#include "FayCore27Skeleton.h"
#include "Misc/ScopeLock.h"

namespace
{
struct FFayEpicBoneMap
{
    const TCHAR* TargetBone;
    int32 Core27JointIndex;
};

// Core27 has four articulated spine joints after Hips while the UE5 Epic
// skeleton has five.  spine_05 follows spine_04 through its unchanged local
// reference transform, avoiding a duplicated final-spine rotation.
constexpr FFayEpicBoneMap EpicBoneMap[] = {
    {TEXT("pelvis"), 0},
    {TEXT("spine_01"), 1},
    {TEXT("spine_02"), 2},
    {TEXT("spine_03"), 3},
    {TEXT("spine_04"), 4},
    {TEXT("clavicle_r"), 7},
    {TEXT("upperarm_r"), 8},
    {TEXT("lowerarm_r"), 9},
    {TEXT("hand_r"), 10},
    {TEXT("clavicle_l"), 13},
    {TEXT("upperarm_l"), 14},
    {TEXT("lowerarm_l"), 15},
    {TEXT("hand_l"), 16},
    {TEXT("thigh_r"), 19},
    {TEXT("calf_r"), 20},
    {TEXT("foot_r"), 21},
    {TEXT("ball_r"), 22},
    {TEXT("thigh_l"), 23},
    {TEXT("calf_l"), 24},
    {TEXT("foot_l"), 25},
    {TEXT("ball_l"), 26},
};

constexpr const TCHAR* RequiredEpicBones[] = {
    TEXT("root"), TEXT("pelvis"),
    TEXT("spine_01"), TEXT("spine_02"), TEXT("spine_03"),
    TEXT("spine_04"), TEXT("spine_05"), TEXT("neck_01"), TEXT("head"),
    TEXT("clavicle_l"), TEXT("upperarm_l"), TEXT("lowerarm_l"), TEXT("hand_l"),
    TEXT("clavicle_r"), TEXT("upperarm_r"), TEXT("lowerarm_r"), TEXT("hand_r"),
    TEXT("thigh_l"), TEXT("calf_l"), TEXT("foot_l"), TEXT("ball_l"),
    TEXT("thigh_r"), TEXT("calf_r"), TEXT("foot_r"), TEXT("ball_r"),
};

struct FFayRequiredEpicParent
{
    const TCHAR* Bone;
    const TCHAR* Parent;
};

constexpr FFayRequiredEpicParent RequiredEpicParents[] = {
    {TEXT("pelvis"), TEXT("root")},
    {TEXT("spine_01"), TEXT("pelvis")},
    {TEXT("spine_02"), TEXT("spine_01")},
    {TEXT("spine_03"), TEXT("spine_02")},
    {TEXT("spine_04"), TEXT("spine_03")},
    {TEXT("spine_05"), TEXT("spine_04")},
    {TEXT("clavicle_l"), TEXT("spine_05")},
    {TEXT("upperarm_l"), TEXT("clavicle_l")},
    {TEXT("lowerarm_l"), TEXT("upperarm_l")},
    {TEXT("hand_l"), TEXT("lowerarm_l")},
    {TEXT("clavicle_r"), TEXT("spine_05")},
    {TEXT("upperarm_r"), TEXT("clavicle_r")},
    {TEXT("lowerarm_r"), TEXT("upperarm_r")},
    {TEXT("hand_r"), TEXT("lowerarm_r")},
    {TEXT("thigh_l"), TEXT("pelvis")},
    {TEXT("calf_l"), TEXT("thigh_l")},
    {TEXT("foot_l"), TEXT("calf_l")},
    {TEXT("ball_l"), TEXT("foot_l")},
    {TEXT("thigh_r"), TEXT("pelvis")},
    {TEXT("calf_r"), TEXT("thigh_r")},
    {TEXT("foot_r"), TEXT("calf_r")},
    {TEXT("ball_r"), TEXT("foot_r")},
};

bool IsFiniteQuaternion(const FQuat& Rotation)
{
    return !Rotation.ContainsNaN() && FMath::IsFinite(Rotation.SizeSquared()) &&
        Rotation.SizeSquared() > SMALL_NUMBER;
}
}

class FFayCore27EpicAnimProxy final : public FAnimInstanceProxy
{
public:
    explicit FFayCore27EpicAnimProxy(UAnimInstance* Instance)
        : FAnimInstanceProxy(Instance)
    {
    }

protected:
    virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override
    {
        FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
        const UFayCore27EpicAnimInstance* Source =
            Cast<UFayCore27EpicAnimInstance>(InAnimInstance);
        if (Source != nullptr)
        {
            Source->CopyPendingPose(Pose);
        }
        else
        {
            Pose = FFayCore27EpicPoseSnapshot();
        }
    }

    virtual bool Evaluate(FPoseContext& Output) override
    {
        Output.ResetToRefPose();
        const TArray<FFayCore27Bone>& Hierarchy = FayGetCore27Hierarchy();
        const float Weight = FMath::Clamp(Pose.BlendWeight, 0.0f, 1.0f);
        if (!Pose.bValid || Weight <= KINDA_SMALL_NUMBER ||
            Pose.JointRotations.Num() != Hierarchy.Num())
        {
            return true;
        }

        TArray<FQuat, TInlineAllocator<27>> SourceComponentRotations;
        SourceComponentRotations.SetNum(Hierarchy.Num());
        for (int32 JointIndex = 0; JointIndex < Hierarchy.Num(); ++JointIndex)
        {
            FQuat LocalRotation = FayConvertArdyQuaternionToUnreal(
                JointIndex == 0
                    ? Pose.RootRotation
                    : Pose.JointRotations[JointIndex]);
            if (!IsFiniteQuaternion(LocalRotation))
            {
                return true;
            }
            LocalRotation.Normalize();
            const int32 ParentIndex = Hierarchy[JointIndex].ParentIndex;
            SourceComponentRotations[JointIndex] = ParentIndex == INDEX_NONE
                ? LocalRotation
                : LocalRotation * SourceComponentRotations[ParentIndex];
            SourceComponentRotations[JointIndex].Normalize();
        }

        const FBoneContainer& RequiredBones = Output.Pose.GetBoneContainer();
        TMap<int32, int32, TInlineSetAllocator<32>> SourceByCompactIndex;
        for (const FFayEpicBoneMap& Mapping : EpicBoneMap)
        {
            const int32 MeshPoseIndex = RequiredBones.GetPoseBoneIndexForBoneName(
                FName(Mapping.TargetBone));
            if (MeshPoseIndex == INDEX_NONE)
            {
                continue;
            }
            const FCompactPoseBoneIndex CompactIndex =
                RequiredBones.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshPoseIndex));
            if (CompactIndex.GetInt() != INDEX_NONE)
            {
                SourceByCompactIndex.Add(
                    CompactIndex.GetInt(), Mapping.Core27JointIndex);
            }
        }

        const int32 BoneCount = Output.Pose.GetNumBones();
        TArray<FQuat, TInlineAllocator<256>> ReferenceComponentRotations;
        TArray<FQuat, TInlineAllocator<256>> OutputComponentRotations;
        ReferenceComponentRotations.SetNum(BoneCount);
        OutputComponentRotations.SetNum(BoneCount);

        for (const FCompactPoseBoneIndex BoneIndex :
             Output.Pose.ForEachBoneIndex())
        {
            FTransform& LocalTransform = Output.Pose[BoneIndex];
            const FQuat ReferenceLocal = LocalTransform.GetRotation();
            const FCompactPoseBoneIndex ParentIndex =
                RequiredBones.GetParentBoneIndex(BoneIndex);
            const bool bHasParent = ParentIndex.GetInt() != INDEX_NONE;
            const FQuat ReferenceParent = bHasParent
                ? ReferenceComponentRotations[ParentIndex.GetInt()]
                : FQuat::Identity;
            const FQuat OutputParent = bHasParent
                ? OutputComponentRotations[ParentIndex.GetInt()]
                : FQuat::Identity;
            FQuat ReferenceComponent = ReferenceLocal * ReferenceParent;
            ReferenceComponent.Normalize();
            ReferenceComponentRotations[BoneIndex.GetInt()] = ReferenceComponent;

            FQuat OutputLocal = ReferenceLocal;
            if (const int32* SourceJoint =
                    SourceByCompactIndex.Find(BoneIndex.GetInt()))
            {
                // The generated Core27 source has identity reference
                // rotations, so its component rotation is the component-space
                // delta to layer onto the target reference frame.
                FQuat DesiredComponent =
                    ReferenceComponent * SourceComponentRotations[*SourceJoint];
                DesiredComponent.Normalize();
                FQuat DesiredLocal = bHasParent
                    ? DesiredComponent * OutputParent.Inverse()
                    : DesiredComponent;
                DesiredLocal.Normalize();
                OutputLocal = FQuat::Slerp(
                    ReferenceLocal, DesiredLocal, Weight).GetNormalized();
                LocalTransform.SetRotation(OutputLocal);

                if (*SourceJoint == 0 &&
                    !Pose.RootOffsetCentimetres.ContainsNaN())
                {
                    LocalTransform.AddToTranslation(
                        Pose.RootOffsetCentimetres * Weight);
                }
            }

            FQuat OutputComponent = OutputLocal * OutputParent;
            OutputComponent.Normalize();
            OutputComponentRotations[BoneIndex.GetInt()] = OutputComponent;
        }

        Output.Pose.NormalizeRotations();
        return true;
    }

private:
    FFayCore27EpicPoseSnapshot Pose;
};

bool UFayCore27EpicAnimInstance::SupportsExactEpicSkeleton(
    const USkeletalMesh* SkeletalMesh,
    FString& OutReason)
{
    OutReason.Reset();
    if (!IsValid(SkeletalMesh))
    {
        OutReason = TEXT("the target skeletal mesh is null");
        return false;
    }

    const USkeleton* Skeleton = SkeletalMesh->GetSkeleton();
    if (!IsValid(Skeleton) || Skeleton->GetName() != TEXT("SK_Mannequin"))
    {
        OutReason = TEXT(
            "the target does not use the reviewed SK_Mannequin skeleton");
        return false;
    }

    const FReferenceSkeleton& ReferenceSkeleton = SkeletalMesh->GetRefSkeleton();
    for (const TCHAR* RequiredBone : RequiredEpicBones)
    {
        if (ReferenceSkeleton.FindBoneIndex(FName(RequiredBone)) == INDEX_NONE)
        {
            OutReason = FString::Printf(
                TEXT("the target is missing required UE5 Epic bone '%s'"),
                RequiredBone);
            return false;
        }
    }
    for (const FFayRequiredEpicParent& Requirement : RequiredEpicParents)
    {
        const int32 BoneIndex = ReferenceSkeleton.FindBoneIndex(
            FName(Requirement.Bone));
        const int32 ParentIndex = BoneIndex != INDEX_NONE
            ? ReferenceSkeleton.GetParentIndex(BoneIndex)
            : INDEX_NONE;
        if (ParentIndex == INDEX_NONE ||
            ReferenceSkeleton.GetBoneName(ParentIndex) !=
                FName(Requirement.Parent))
        {
            OutReason = FString::Printf(
                TEXT("UE5 Epic bone '%s' does not have required parent '%s'"),
                Requirement.Bone,
                Requirement.Parent);
            return false;
        }
    }
    return true;
}

void UFayCore27EpicAnimInstance::SubmitPose(
    const FFayArdyPoseFrame& Pose,
    const FVector& RootOffsetCentimetres,
    const float BlendWeight)
{
    FScopeLock Lock(&PoseMutex);
    PendingPose.RootRotation = Pose.RootRotation;
    PendingPose.JointRotations = Pose.JointRotations;
    PendingPose.RootOffsetCentimetres = RootOffsetCentimetres;
    PendingPose.BlendWeight = FMath::IsFinite(BlendWeight)
        ? FMath::Clamp(BlendWeight, 0.0f, 1.0f)
        : 0.0f;
    PendingPose.bValid =
        Pose.JointRotations.Num() == FayGetCore27Hierarchy().Num() &&
        !RootOffsetCentimetres.ContainsNaN();
}

void UFayCore27EpicAnimInstance::ResetPose()
{
    FScopeLock Lock(&PoseMutex);
    PendingPose = FFayCore27EpicPoseSnapshot();
}

void UFayCore27EpicAnimInstance::CopyPendingPose(
    FFayCore27EpicPoseSnapshot& OutPose) const
{
    FScopeLock Lock(&PoseMutex);
    OutPose = PendingPose;
}

FAnimInstanceProxy* UFayCore27EpicAnimInstance::CreateAnimInstanceProxy()
{
    return new FFayCore27EpicAnimProxy(this);
}

void UFayCore27EpicAnimInstance::DestroyAnimInstanceProxy(
    FAnimInstanceProxy* InProxy)
{
    delete InProxy;
}

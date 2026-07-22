#include "FayCore27SourceAnimInstance.h"

#include "Animation/AnimInstanceProxy.h"
#include "BoneContainer.h"
#include "BonePose.h"
#include "FayArdyCoordinateConversion.h"
#include "FayCore27Skeleton.h"
#include "Misc/ScopeLock.h"

namespace
{
constexpr int32 Core27SourceNeckJointIndex = 5;
constexpr int32 Core27SourceHeadJointIndex = 6;
}

class FFayCore27SourceAnimProxy final : public FAnimInstanceProxy
{
public:
    explicit FFayCore27SourceAnimProxy(UAnimInstance* Instance)
        : FAnimInstanceProxy(Instance)
    {
    }

protected:
    virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override
    {
        FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
        const UFayCore27SourceAnimInstance* Source =
            Cast<UFayCore27SourceAnimInstance>(InAnimInstance);
        if (Source != nullptr)
        {
            Source->CopyPendingPose(Pose);
        }
        else
        {
            Pose = FFayCore27SourcePoseSnapshot();
        }
    }

    virtual bool Evaluate(FPoseContext& Output) override
    {
        Output.ResetToRefPose();
        const TArray<FFayCore27Bone>& Hierarchy = FayGetCore27Hierarchy();
        if (!Pose.bValid || Pose.JointRotations.Num() != Hierarchy.Num())
        {
            return true;
        }

        const FBoneContainer& RequiredBones = Output.Pose.GetBoneContainer();
        for (int32 JointIndex = 0; JointIndex < Hierarchy.Num(); ++JointIndex)
        {
            // StreamingADA/input-pose ownership is preserved by defense in
            // depth: generated source neck/head remain at exact reference pose.
            if (JointIndex == Core27SourceNeckJointIndex ||
                JointIndex == Core27SourceHeadJointIndex)
            {
                continue;
            }

            const int32 MeshPoseIndex = RequiredBones.GetPoseBoneIndexForBoneName(
                Hierarchy[JointIndex].Name);
            if (MeshPoseIndex == INDEX_NONE)
            {
                continue;
            }
            const FCompactPoseBoneIndex CompactIndex =
                RequiredBones.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshPoseIndex));
            if (CompactIndex.GetInt() == INDEX_NONE)
            {
                continue;
            }

            FTransform& LocalTransform = Output.Pose[CompactIndex];
            const FQuat SourceRotation = FayConvertArdyQuaternionToUnreal(
                JointIndex == 0 ? Pose.RootRotation : Pose.JointRotations[JointIndex]);
            LocalTransform.SetRotation(SourceRotation);
            if (JointIndex == 0)
            {
                LocalTransform.AddToTranslation(Pose.RootOffsetCentimetres);
            }
        }
        Output.Pose.NormalizeRotations();
        return true;
    }

private:
    FFayCore27SourcePoseSnapshot Pose;
};

void UFayCore27SourceAnimInstance::SubmitPose(
    const FFayArdyPoseFrame& Pose,
    const FVector& RootOffsetCentimetres)
{
    FScopeLock Lock(&PoseMutex);
    PendingPose.RootRotation = Pose.RootRotation;
    PendingPose.JointRotations = Pose.JointRotations;
    PendingPose.RootOffsetCentimetres = RootOffsetCentimetres;
    PendingPose.bValid = Pose.JointRotations.Num() == FayGetCore27Hierarchy().Num() &&
        !RootOffsetCentimetres.ContainsNaN();
}

void UFayCore27SourceAnimInstance::ResetPose()
{
    FScopeLock Lock(&PoseMutex);
    PendingPose = FFayCore27SourcePoseSnapshot();
}

void UFayCore27SourceAnimInstance::CopyPendingPose(
    FFayCore27SourcePoseSnapshot& OutPose) const
{
    FScopeLock Lock(&PoseMutex);
    OutPose = PendingPose;
}

FAnimInstanceProxy* UFayCore27SourceAnimInstance::CreateAnimInstanceProxy()
{
    return new FFayCore27SourceAnimProxy(this);
}

void UFayCore27SourceAnimInstance::DestroyAnimInstanceProxy(
    FAnimInstanceProxy* InProxy)
{
    delete InProxy;
}

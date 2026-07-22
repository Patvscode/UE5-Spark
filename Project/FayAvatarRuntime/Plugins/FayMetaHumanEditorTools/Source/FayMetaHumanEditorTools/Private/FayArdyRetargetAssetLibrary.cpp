#include "FayArdyRetargetAssetLibrary.h"

#include "Animation/AnimInstance.h"
#include "Animation/BlendProfile.h"
#include "Animation/Skeleton.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/SkeletalMesh.h"
#include "Components/SkeletalMeshComponent.h"
#include "FayArdyRetargetProfile.h"
#include "FayCore27Skeleton.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayArdyRetargetAssets, Log, All);

namespace
{
const FName BodyMaskName(TEXT("FayArdyV30_BodyOnly"));
const FString CandidateAssetPrefix(TEXT("/Game/FayMetaHumans/Built/FayArdyV30/"));
constexpr int32 V30ContractVersion = 2;

const TSet<FName>& ApprovedBodyBones()
{
    static const TSet<FName> Names = {
        TEXT("pelvis"),
        TEXT("spine_01"), TEXT("spine_02"), TEXT("spine_03"),
        TEXT("spine_04"), TEXT("spine_05"),
        TEXT("clavicle_l"), TEXT("upperarm_l"), TEXT("lowerarm_l"),
        TEXT("hand_l"),
        TEXT("clavicle_r"), TEXT("upperarm_r"), TEXT("lowerarm_r"),
        TEXT("hand_r"),
        TEXT("thigh_l"), TEXT("calf_l"), TEXT("foot_l"), TEXT("ball_l"),
        TEXT("thigh_r"), TEXT("calf_r"), TEXT("foot_r"), TEXT("ball_r"),
    };
    return Names;
}

int32 CountBindingsInBlueprintHierarchy(
    const UBlueprint* Blueprint,
    UFayArdyRetargetBindingComponent*& OutLocalTemplate)
{
    OutLocalTemplate = nullptr;
    int32 Count = 0;
    const UClass* CurrentClass = IsValid(Blueprint)
        ? Blueprint->GeneratedClass
        : nullptr;
    TSet<const UBlueprint*> Visited;

    while (IsValid(CurrentClass))
    {
        const UBlueprintGeneratedClass* GeneratedClass =
            Cast<UBlueprintGeneratedClass>(CurrentClass);
        const UBlueprint* OwnerBlueprint = GeneratedClass != nullptr
            ? Cast<UBlueprint>(GeneratedClass->ClassGeneratedBy)
            : nullptr;
        if (!IsValid(OwnerBlueprint) || Visited.Contains(OwnerBlueprint))
        {
            break;
        }
        Visited.Add(OwnerBlueprint);

        const USimpleConstructionScript* Script =
            OwnerBlueprint->SimpleConstructionScript;
        if (IsValid(Script))
        {
            for (USCS_Node* Node : Script->GetAllNodes())
            {
                if (!IsValid(Node) || !IsValid(Node->ComponentClass) ||
                    !Node->ComponentClass->IsChildOf(
                        UFayArdyRetargetBindingComponent::StaticClass()))
                {
                    continue;
                }
                ++Count;
                if (OwnerBlueprint == Blueprint)
                {
                    OutLocalTemplate = Cast<UFayArdyRetargetBindingComponent>(
                        Node->ComponentTemplate);
                }
            }
        }
        CurrentClass = CurrentClass->GetSuperClass();
    }
    return Count;
}

bool ValidateZeroVectorProperty(
    const UAnimInstance* Instance,
    const FName PropertyName,
    FString& OutReason)
{
    const FStructProperty* Property = FindFProperty<FStructProperty>(
        Instance->GetClass(), PropertyName);
    if (Property == nullptr || Property->Struct != TBaseStructure<FVector>::Get())
    {
        OutReason = FString::Printf(
            TEXT("post-process input '%s' must be an FVector"),
            *PropertyName.ToString());
        return false;
    }
    const FVector* Value = Property->ContainerPtrToValuePtr<FVector>(Instance);
    if (Value == nullptr || !Value->IsNearlyZero())
    {
        OutReason = FString::Printf(
            TEXT("post-process input '%s' must default to zero"),
            *PropertyName.ToString());
        return false;
    }
    return true;
}

bool ValidateZeroFloatProperty(
    const UAnimInstance* Instance,
    const FName PropertyName,
    FString& OutReason)
{
    const FFloatProperty* Property = FindFProperty<FFloatProperty>(
        Instance->GetClass(), PropertyName);
    if (Property == nullptr)
    {
        OutReason = FString::Printf(
            TEXT("post-process input '%s' must be a float"),
            *PropertyName.ToString());
        return false;
    }
    if (!FMath::IsNearlyZero(
            Property->GetPropertyValue_InContainer(Instance)))
    {
        OutReason = FString::Printf(
            TEXT("post-process input '%s' must default to zero"),
            *PropertyName.ToString());
        return false;
    }
    return true;
}
}

bool UFayArdyRetargetAssetLibrary::ValidateExactCore27Source(
    USkeletalMesh* SourceMesh,
    FString& OutReason)
{
    return FayValidateExactCore27Mesh(SourceMesh, OutReason);
}

bool UFayArdyRetargetAssetLibrary::RebindPrivateTargetMeshSkeleton(
    USkeletalMesh* CandidateBodyMesh,
    USkeleton* CandidateSkeleton,
    FString& OutReason)
{
    OutReason.Reset();
    if (!IsValid(CandidateBodyMesh) || !IsValid(CandidateSkeleton) ||
        !CandidateBodyMesh->GetOutermost()->GetName().StartsWith(CandidateAssetPrefix) ||
        !CandidateSkeleton->GetOutermost()->GetName().StartsWith(CandidateAssetPrefix))
    {
        OutReason = TEXT(
            "the mesh and skeleton must both be private FayArdyV30 duplicates");
        return false;
    }

    const FReferenceSkeleton& MeshReference = CandidateBodyMesh->GetRefSkeleton();
    const FReferenceSkeleton& SkeletonReference =
        CandidateSkeleton->GetReferenceSkeleton();
    for (const FName RequiredBone : ApprovedBodyBones())
    {
        if (MeshReference.FindBoneIndex(RequiredBone) == INDEX_NONE ||
            SkeletonReference.FindBoneIndex(RequiredBone) == INDEX_NONE)
        {
            OutReason = FString::Printf(
                TEXT("the private target clone is missing required bone '%s'"),
                *RequiredBone.ToString());
            return false;
        }
    }

    if (CandidateBodyMesh->GetSkeleton() != CandidateSkeleton)
    {
        CandidateBodyMesh->Modify();
        CandidateBodyMesh->SetSkeleton(CandidateSkeleton);
        CandidateBodyMesh->MarkPackageDirty();
    }
    if (CandidateBodyMesh->GetSkeleton() != CandidateSkeleton)
    {
        OutReason = TEXT("Unreal did not retain the private target skeleton binding");
        return false;
    }
    return true;
}

UBlendProfile* UFayArdyRetargetAssetLibrary::EnsureBodyOnlyBlendMask(
    USkeletalMesh* TargetBodyMesh,
    const bool bReviewedRebuild,
    FString& OutReason)
{
    OutReason.Reset();
    if (!IsValid(TargetBodyMesh) || !IsValid(TargetBodyMesh->GetSkeleton()))
    {
        OutReason = TEXT("the reviewed MetaHuman target body mesh/skeleton is missing");
        return nullptr;
    }
    if (!TargetBodyMesh->GetOutermost()->GetName().StartsWith(CandidateAssetPrefix) ||
        !TargetBodyMesh->GetSkeleton()->GetOutermost()->GetName().StartsWith(
            CandidateAssetPrefix))
    {
        OutReason = TEXT(
            "the body mask may be created only on private FayArdyV30 clones");
        return nullptr;
    }

    const FReferenceSkeleton& ReferenceSkeleton = TargetBodyMesh->GetRefSkeleton();
    for (const FName RequiredBone : ApprovedBodyBones())
    {
        if (ReferenceSkeleton.FindBoneIndex(RequiredBone) == INDEX_NONE)
        {
            OutReason = FString::Printf(
                TEXT("the target body skeleton is missing required bone '%s'"),
                *RequiredBone.ToString());
            return nullptr;
        }
    }
    if (ReferenceSkeleton.FindBoneIndex(TEXT("root")) == INDEX_NONE ||
        ReferenceSkeleton.FindBoneIndex(TEXT("neck_01")) == INDEX_NONE)
    {
        OutReason = TEXT("the target is not the reviewed MetaHuman body skeleton");
        return nullptr;
    }

    USkeleton* Skeleton = TargetBodyMesh->GetSkeleton();
    const FReferenceSkeleton& SkeletonReference = Skeleton->GetReferenceSkeleton();
    UBlendProfile* Mask = Skeleton->GetBlendProfile(BodyMaskName);
    if (IsValid(Mask) && !bReviewedRebuild)
    {
        OutReason = TEXT(
            "the FayArdyV30 body mask already exists; set the exact reviewed "
            "rebuild flag only after inspecting the candidate assets");
        return nullptr;
    }

    if (!IsValid(Mask))
    {
        Skeleton->Modify();
        Mask = Skeleton->CreateNewBlendProfile(BodyMaskName);
        if (!IsValid(Mask))
        {
            OutReason = TEXT("Unreal could not create the sealed body-only Blend Mask");
            return nullptr;
        }
        Mask->Mode = EBlendProfileMode::BlendMask;
        Mask->ClearEntries();
        for (int32 Index = 0; Index < SkeletonReference.GetNum(); ++Index)
        {
            const FName BoneName = SkeletonReference.GetBoneName(Index);
            const float Weight = ApprovedBodyBones().Contains(BoneName) ? 1.0f : 0.0f;
            Mask->SetBoneBlendScale(BoneName, Weight, false, true);
        }
        Skeleton->MarkPackageDirty();
    }

    if (!Mask->IsBlendMask())
    {
        OutReason = TEXT("the existing FayArdyV30 profile is not a Blend Mask");
        return nullptr;
    }
    for (int32 Index = 0; Index < SkeletonReference.GetNum(); ++Index)
    {
        const FName BoneName = SkeletonReference.GetBoneName(Index);
        const float Expected = ApprovedBodyBones().Contains(BoneName) ? 1.0f : 0.0f;
        const float Actual = Mask->GetBoneBlendScale(Index);
        if (!FMath::IsNearlyEqual(Actual, Expected))
        {
            OutReason = FString::Printf(
                TEXT("body mask bone '%s' is %.3f instead of sealed value %.1f"),
                *BoneName.ToString(), Actual, Expected);
            return nullptr;
        }
    }

    return Mask;
}

bool UFayArdyRetargetAssetLibrary::EnsureExactlyOneRetargetBinding(
    UBlueprint* CandidateBlueprint,
    UFayArdyRetargetProfile* SharedProfile,
    const bool bReviewedRebuild,
    FString& OutReason)
{
    OutReason.Reset();
    if (!IsValid(CandidateBlueprint) || !IsValid(SharedProfile) ||
        !IsValid(CandidateBlueprint->SimpleConstructionScript))
    {
        OutReason = TEXT("a valid candidate Actor Blueprint and shared profile are required");
        return false;
    }

    UFayArdyRetargetBindingComponent* LocalTemplate = nullptr;
    const int32 ExistingCount = CountBindingsInBlueprintHierarchy(
        CandidateBlueprint, LocalTemplate);
    if (ExistingCount > 1 || (ExistingCount == 1 && !IsValid(LocalTemplate)))
    {
        OutReason = TEXT(
            "the candidate Blueprint hierarchy contains duplicate or inherited "
            "FayArdyRetargetBinding components");
        return false;
    }
    if (ExistingCount == 1)
    {
        if (!bReviewedRebuild)
        {
            OutReason = TEXT(
                "the candidate already has a retarget binding; a reviewed "
                "rebuild is required to reuse it");
            return false;
        }
        if (LocalTemplate->Profile.Get() != SharedProfile)
        {
            OutReason = TEXT("the existing binding does not reference the sealed shared profile");
            return false;
        }
        return true;
    }

    CandidateBlueprint->Modify();
    USCS_Node* Node = CandidateBlueprint->SimpleConstructionScript->CreateNode(
        UFayArdyRetargetBindingComponent::StaticClass(),
        TEXT("FayArdyRetargetBinding"));
    UFayArdyRetargetBindingComponent* Binding = IsValid(Node)
        ? Cast<UFayArdyRetargetBindingComponent>(Node->ComponentTemplate)
        : nullptr;
    if (!IsValid(Node) || !IsValid(Binding))
    {
        OutReason = TEXT("Unreal could not create the reviewed retarget binding node");
        return false;
    }
    Binding->Profile = SharedProfile;
    CandidateBlueprint->SimpleConstructionScript->AddNode(Node);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(CandidateBlueprint);
    FKismetEditorUtilities::CompileBlueprint(CandidateBlueprint);
    if (CandidateBlueprint->Status == BS_Error)
    {
        OutReason = TEXT("the duplicated candidate Blueprint failed to compile after binding");
        return false;
    }

    LocalTemplate = nullptr;
    if (CountBindingsInBlueprintHierarchy(CandidateBlueprint, LocalTemplate) != 1 ||
        !IsValid(LocalTemplate) || LocalTemplate->Profile.Get() != SharedProfile)
    {
        OutReason = TEXT("the candidate did not compile to exactly one sealed binding");
        return false;
    }
    return true;
}

bool UFayArdyRetargetAssetLibrary::ValidateV30PostProcessInputs(
    const TSubclassOf<UAnimInstance> PostProcessAnimClass,
    FString& OutReason)
{
    OutReason.Reset();
    const UClass* Class = PostProcessAnimClass.Get();
    const UAnimInstance* Instance = IsValid(Class)
        ? Cast<UAnimInstance>(Class->GetDefaultObject())
        : nullptr;
    if (!IsValid(Instance))
    {
        OutReason = TEXT("the reviewed post-process AnimBP class is missing");
        return false;
    }

    const FIntProperty* Version = FindFProperty<FIntProperty>(
        Class, TEXT("FayArdyContractVersion"));
    const FBoolProperty* ExcludesHead = FindFProperty<FBoolProperty>(
        Class, TEXT("FayArdyExcludesNeckAndHead"));
    const FBoolProperty* PreservesFingers = FindFProperty<FBoolProperty>(
        Class, TEXT("FayArdyPreservesFingerPose"));
    const FBoolProperty* UsesFootContactOffsets = FindFProperty<FBoolProperty>(
        Class, TEXT("FayArdyUsesFootContactOffsets"));
    const FObjectPropertyBase* SourceMesh = FindFProperty<FObjectPropertyBase>(
        Class, TEXT("FayArdySourceMeshComponent"));
    const FNameProperty* ProceduralBehavior = FindFProperty<FNameProperty>(
        Class, TEXT("FayProceduralBehavior"));
    if (Version == nullptr ||
        Version->GetPropertyValue_InContainer(Instance) != V30ContractVersion ||
        ExcludesHead == nullptr ||
        !ExcludesHead->GetPropertyValue_InContainer(Instance) ||
        PreservesFingers == nullptr ||
        !PreservesFingers->GetPropertyValue_InContainer(Instance) ||
        UsesFootContactOffsets == nullptr ||
        !UsesFootContactOffsets->GetPropertyValue_InContainer(Instance) ||
        SourceMesh == nullptr ||
        !SourceMesh->PropertyClass->IsChildOf(USkeletalMeshComponent::StaticClass()) ||
        ProceduralBehavior == nullptr)
    {
        OutReason = TEXT(
            "the post-process AnimBP failed the sealed v2 version/source/head/"
            "finger/procedural input contract");
        return false;
    }

    for (const FName FloatName : {
             FName(TEXT("FayArdyBlendWeight")),
             FName(TEXT("FayProceduralProgress")),
             FName(TEXT("FayProceduralIntensity")),
             FName(TEXT("FayArdyLeftHeelContact")),
             FName(TEXT("FayArdyLeftToeContact")),
             FName(TEXT("FayArdyRightHeelContact")),
             FName(TEXT("FayArdyRightToeContact"))})
    {
        if (!ValidateZeroFloatProperty(Instance, FloatName, OutReason))
        {
            return false;
        }
    }
    for (const FName VectorName : {
             FName(TEXT("FayArdyLeftHeelOffset")),
             FName(TEXT("FayArdyLeftToeOffset")),
             FName(TEXT("FayArdyRightHeelOffset")),
             FName(TEXT("FayArdyRightToeOffset"))})
    {
        if (!ValidateZeroVectorProperty(Instance, VectorName, OutReason))
        {
            return false;
        }
    }
    return true;
}

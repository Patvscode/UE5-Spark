#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Engine/DataAsset.h"
#include "FayArdyRetargetProfile.generated.h"

class UAnimInstance;
class USkeletalMesh;

/** Root translation remains opt-in and bounded; actor locomotion is not exposed. */
UENUM(BlueprintType)
enum class EFayArdyRootMotionPolicy : uint8
{
    /** Keep the generated character at the reviewed spawn transform. */
    LockedInPlace,

    /** Apply per-action displacement only, clamped to the profile's small bound. */
    BoundedInPlace
};

/**
 * Reviewed asset contract for Core27 -> character runtime IK retargeting.
 *
 * This source-only plugin never guesses skeleton axes or asset paths. An Editor
 * build must create these assets, review the IK chains/rest poses/blend mask,
 * and attach a binding component to the character Blueprint. Until then ARDY
 * remains disabled and ordinary face/body evaluation is left untouched.
 */
UCLASS(BlueprintType)
class FAYBODYMOTION_API UFayArdyRetargetProfile final : public UDataAsset
{
    GENERATED_BODY()

public:
    bool ValidateAssetReferences(FString& OutReason) const;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    FName ProfileId = NAME_None;

    /** Exact 27-bone nv-tlabs/ardy source mesh in converted Unreal coordinates. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    TSoftObjectPtr<USkeletalMesh> Core27SourceMesh;

    /**
     * Reviewed target post-process AnimBP. It must retain the existing input
     * pose, run Retarget Pose From Mesh, and blend only the approved body mask.
     */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    TSoftClassPtr<UAnimInstance> TargetPostProcessAnimClass;

    /** Reviewed UIKRetargeter asset; kept generic to avoid an Editor-only dependency. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    TSoftObjectPtr<UObject> IKRetargeterAsset;

    /** Blend profile that excludes neck/head and preserves existing finger poses. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    TSoftObjectPtr<UObject> TargetBodyBlendMask;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    FName SourceRetargetPose = TEXT("ARDY_Core27_TPose");

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    FName TargetRetargetPose = TEXT("MetaHuman_A_Pose");

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    EFayArdyRootMotionPolicy RootMotionPolicy =
        EFayArdyRootMotionPolicy::LockedInPlace;

    UPROPERTY(
        EditDefaultsOnly,
        BlueprintReadOnly,
        Category = "Fay|ARDY Retarget",
        meta = (ClampMin = "0.0", ClampMax = "20.0"))
    float MaximumRootOffsetCentimetres = 20.0f;
};

/** Character Blueprint opt-in. Absence or duplication disables generated motion. */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYBODYMOTION_API UFayArdyRetargetBindingComponent final
    : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayArdyRetargetBindingComponent();

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Fay|ARDY Retarget")
    TSoftObjectPtr<UFayArdyRetargetProfile> Profile;
};


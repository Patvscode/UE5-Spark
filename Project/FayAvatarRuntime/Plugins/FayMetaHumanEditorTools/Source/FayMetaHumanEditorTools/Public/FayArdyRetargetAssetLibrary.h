#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"

#include "FayArdyRetargetAssetLibrary.generated.h"

class UAnimInstance;
class UBlendProfile;
class UBlueprint;
class UFayArdyRetargetProfile;
class USkeletalMesh;
class USkeleton;

/**
 * Fail-closed Editor helpers used by the sealed Fay ARDY v30 asset builder.
 *
 * Asset orchestration stays in the accompanying Python script because Epic's
 * UE 5.8 IK Rig/Retargeter controllers are exposed there as supported Editor
 * scripting APIs. These helpers cover the checks and Blueprint operations
 * which are not safely reflected to Python.
 */
UCLASS()
class FAYMETAHUMANEDITORTOOLS_API UFayArdyRetargetAssetLibrary final
    : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Validate the exact ordered 27-bone ARDY source hierarchy. */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARDY v30")
    static bool ValidateExactCore27Source(
        USkeletalMesh* SourceMesh,
        FString& OutReason);

    /** Rebind only a private v30 target-mesh duplicate to its private skeleton. */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARDY v30")
    static bool RebindPrivateTargetMeshSkeleton(
        USkeletalMesh* CandidateBodyMesh,
        USkeleton* CandidateSkeleton,
        FString& OutReason);

    /**
     * Create or validate the one sealed body-only Blend Mask on the supplied
     * MetaHuman body skeleton. Existing content is accepted only during an
     * explicitly reviewed rebuild and is still validated rather than reset.
     */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARDY v30")
    static UBlendProfile* EnsureBodyOnlyBlendMask(
        USkeletalMesh* TargetBodyMesh,
        bool bReviewedRebuild,
        FString& OutReason);

    /**
     * Attach the shared draft profile to a duplicated candidate Blueprint.
     * The full Blueprint inheritance tree must contain zero bindings before
     * the first build, or exactly this one binding during a reviewed rebuild.
     */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARDY v30")
    static bool EnsureExactlyOneRetargetBinding(
        UBlueprint* CandidateBlueprint,
        UFayArdyRetargetProfile* SharedProfile,
        bool bReviewedRebuild,
        FString& OutReason);

    /**
     * Validate the reflected inputs/defaults of a manually reviewed v30
     * post-process AnimBP. This does not claim to validate AnimGraph topology;
     * the automated foundation builder therefore never finalizes the profile.
     */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARDY v30")
    static bool ValidateV30PostProcessInputs(
        TSubclassOf<UAnimInstance> PostProcessAnimClass,
        FString& OutReason);
};

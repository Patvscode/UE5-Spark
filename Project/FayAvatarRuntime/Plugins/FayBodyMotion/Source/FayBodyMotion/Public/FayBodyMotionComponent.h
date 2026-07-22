#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayArdyContactStabilizer.h"
#include "FayArdyRetargetProfile.h"
#include "FayBodyMotionTypes.h"
#include "FayBodyMotionComponent.generated.h"

class AActor;
class IFayBodyMotionProvider;
class UAnimMontage;
class UAnimInstance;
class UFayArdyPoseClientComponent;
class UFayCore27SourceAnimInstance;
class UFayAvatarBridgeComponent;
class USkeletalMeshComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FFayBodyMotionStateEvent,
    EFayBodyMotionState,
    State,
    EFayBodyMotionProvider,
    Provider);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FFayBodyMotionFallbackEvent,
    FName,
    Behavior,
    const FString&,
    Reason);

/**
 * Routes allowlisted Fay intent to interchangeable body-motion providers.
 *
 * StreamingADA retains exclusive ownership of facial controls. This component
 * never modifies the Face component, and generated poses may not contain the
 * neck/head chain until explicit conflict validation is complete.
 */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYBODYMOTION_API UFayBodyMotionComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayBodyMotionComponent();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

    void AttachBridge(UFayAvatarBridgeComponent* InBridge);
    void AttachArdyClient(UFayArdyPoseClientComponent* InClient);
    bool ConfigureAvatar(AActor* InAvatar, FName BodyComponentName);

    /** Public constrained action boundary used by Fay and the future MCP tool. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Body Motion")
    bool PerformAction(
        FName Behavior,
        float Intensity = 0.5f,
        float DurationSeconds = 1.0f,
        EFayBodyMotionRoutingMode RoutingMode = EFayBodyMotionRoutingMode::Hybrid);

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    static bool IsBehaviorAllowed(FName Behavior);

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    EFayBodyMotionState GetMotionState() const { return MotionState; }

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    EFayBodyMotionProvider GetActiveProvider() const { return ActiveProvider; }

    /** True only for configured idle with no montage, procedural, or generated work. */
    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion|Dormancy")
    bool CanEnterDormancy() const;

    /** Deterministic local clips. Missing entries fail safely to idle. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Body Motion")
    TMap<FName, TSoftObjectPtr<UAnimMontage>> BakedMontages;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Body Motion")
    FFayBodyMotionStateEvent OnMotionStateChanged;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Body Motion")
    FFayBodyMotionFallbackEvent OnMotionFallback;

private:
    UFUNCTION()
    void HandleAvatarMessage(const FFayAvatarMessage& Message);

    void SetState(EFayBodyMotionState NewState, EFayBodyMotionProvider Provider);
    bool Dispatch(const FFayBodyMotionRequest& Request);
    void EnterBakedIdle(FName FailedBehavior, const FString& Reason);
    void ResetProviders();
    bool ConfigureGeneratedRetarget();
    void TearDownGeneratedRetarget();
    void ResetGeneratedRetargetState();
    void UpdateGeneratedRetarget(float DeltaSeconds);
    bool IsGeneratedRetargetBindingIntact() const;
    FVector ComputeBoundedRootOffset(const FFayArdyPoseFrame& Pose);
    bool SetTargetObjectInput(FName PropertyName, UObject* Value);
    bool SetTargetFloatInput(FName PropertyName, float Value);
    bool SetTargetNameInput(FName PropertyName, FName Value);
    bool SetTargetVectorInput(FName PropertyName, const FVector& Value);
    bool ApplyFootContactOutput(const FFayArdyFootContactOutput& Output);
    void ClearFootContactOutput();
    void BeginProceduralGesture(const FFayBodyMotionRequest& Request);
    void StopProceduralGesture();
    void UpdateProceduralGestureBinding();
    void StartGeneratedAction(const FFayBodyMotionRequest& Request);
    void BeginGeneratedActionBlendOut(bool bProviderFailure, const FString& Reason);
    void CompleteGeneratedActionBlendOut();
    void StopGeneratedActionImmediately();

    UPROPERTY(Transient)
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(Transient)
    TObjectPtr<UFayArdyPoseClientComponent> ArdyClient;

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMeshComponent> BodyMesh;

    UPROPERTY(Transient)
    TObjectPtr<UFayArdyRetargetBindingComponent> RetargetBinding;

    UPROPERTY(Transient)
    TObjectPtr<UFayArdyRetargetProfile> RetargetProfile;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMeshComponent> ArdySourceMesh;

    UPROPERTY(Transient)
    TObjectPtr<UFayCore27SourceAnimInstance> ArdySourceAnimation;

    UPROPERTY(Transient)
    TObjectPtr<UAnimInstance> TargetPostProcessAnimation;

    UPROPERTY(Transient)
    TObjectPtr<UClass> OriginalBodyAnimClass;

    TUniquePtr<IFayBodyMotionProvider> BakedProvider;
    TUniquePtr<IFayBodyMotionProvider> ArdyProvider;
    EFayBodyMotionState MotionState = EFayBodyMotionState::Unconfigured;
    EFayBodyMotionProvider ActiveProvider = EFayBodyMotionProvider::Baked;
    bool bGeneratedRetargetReady = false;
    bool bSafeProceduralReady = false;
    bool bHasGeneratedRootOrigin = false;
    FVector3f GeneratedRootOriginMetres = FVector3f::ZeroVector;
    FFayArdyPoseFrame LastGeneratedPose;
    FFayArdyContactStabilizer ContactStabilizer;
    float GeneratedBlendWeight = 0.0f;
    bool bHasLastGeneratedPose = false;
    FName ProceduralBehavior = NAME_None;
    float ProceduralGestureElapsedSeconds = 0.0f;
    float ProceduralGestureDurationSeconds = 0.0f;
    float ProceduralGestureIntensity = 0.0f;
    FName GeneratedBehavior = NAME_None;
    float GeneratedActionElapsedSeconds = 0.0f;
    float GeneratedActionDurationSeconds = 0.0f;
    float GeneratedBlendOutElapsedSeconds = 0.0f;
    bool bGeneratedActionActive = false;
    bool bGeneratedBlendOutActive = false;
};

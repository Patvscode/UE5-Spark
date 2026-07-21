#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayBodyMotionTypes.h"
#include "FayBodyMotionComponent.generated.h"

class AActor;
class IFayBodyMotionProvider;
class UAnimMontage;
class UFayArdyPoseClientComponent;
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
    bool PerformAction(FName Behavior, float Intensity = 0.5f, float DurationSeconds = 1.0f);

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    static bool IsBehaviorAllowed(FName Behavior);

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    EFayBodyMotionState GetMotionState() const { return MotionState; }

    UFUNCTION(BlueprintPure, Category = "Fay|Body Motion")
    EFayBodyMotionProvider GetActiveProvider() const { return ActiveProvider; }

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

    UPROPERTY(Transient)
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(Transient)
    TObjectPtr<UFayArdyPoseClientComponent> ArdyClient;

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMeshComponent> BodyMesh;

    TUniquePtr<IFayBodyMotionProvider> BakedProvider;
    TUniquePtr<IFayBodyMotionProvider> ArdyProvider;
    EFayBodyMotionState MotionState = EFayBodyMotionState::Unconfigured;
    EFayBodyMotionProvider ActiveProvider = EFayBodyMotionProvider::Baked;
    bool bGeneratedRetargetReady = false;
};

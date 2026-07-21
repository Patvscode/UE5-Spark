#pragma once

#include "Components/ActorComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayBodyMotionTypes.h"
#include "FayAvatarDormancyComponent.generated.h"

class AActor;
class UFayAvatarBridgeComponent;
class UFayBodyMotionComponent;
class UFayMetaHumanSpeechDriverComponent;
class USkeletalMeshComponent;

/**
 * Default-off idle freezer for an already configured MetaHuman.
 *
 * The component preserves exact actor/component tick and skeletal pause state.
 * It never changes animation classes, Live Link configuration, visibility,
 * registration, rendering settings, or motion-provider ownership.
 */
UCLASS(ClassGroup = (Fay))
class FAYAVATARRUNTIME_API UFayAvatarDormancyComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayAvatarDormancyComponent();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

    void AttachBridge(UFayAvatarBridgeComponent* InBridge);
    void AttachSpeechDriver(UFayMetaHumanSpeechDriverComponent* InSpeechDriver);
    void AttachBodyMotion(UFayBodyMotionComponent* InBodyMotion);
    void ConfigureAvatar(AActor* InAvatar);

private:
    enum class EDormancyState : uint8
    {
        Awake,
        Preparing,
        Dormant
    };

    struct FComponentTickState
    {
        TWeakObjectPtr<UActorComponent> Component;
        bool bWasTickEnabled = false;
    };

    struct FSkeletalPauseState
    {
        TWeakObjectPtr<USkeletalMeshComponent> Component;
        bool bWasPaused = false;
    };

    UFUNCTION()
    void HandleAvatarMessage(const FFayAvatarMessage& Message);

    UFUNCTION()
    void HandleMotionStateChanged(
        EFayBodyMotionState State,
        EFayBodyMotionProvider Provider);

    bool CanPrepareForDormancy() const;
    void BeginPreparation();
    void FreezeAvatar();
    void WakeAvatar(const TCHAR* Reason);
    void ResetIdleTimer();

    UPROPERTY(Transient)
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(Transient)
    TObjectPtr<UFayMetaHumanSpeechDriverComponent> SpeechDriver;

    UPROPERTY(Transient)
    TObjectPtr<UFayBodyMotionComponent> BodyMotion;

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    TArray<FComponentTickState> SavedComponentTicks;
    TArray<FSkeletalPauseState> SavedSkeletalPauses;
    EDormancyState DormancyState = EDormancyState::Awake;
    float IdleElapsedSeconds = 0.0f;
    float IdleDelaySeconds = 5.0f;
    int32 PreparationFramesRemaining = 0;
    bool bSavedActorTickEnabled = false;
    bool bDormancyEnabled = false;
};

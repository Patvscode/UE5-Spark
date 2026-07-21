#include "FayAvatarDormancyComponent.h"

#include "Components/SkeletalMeshComponent.h"
#include "FayBodyMotionComponent.h"
#include "FayMetaHumanSpeechDriverComponent.h"
#include "GameFramework/Actor.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayAvatarDormancy, Log, All);

namespace
{
constexpr int32 NeutralPreparationFrames = 2;
constexpr float MinimumDormancyDelaySeconds = 2.0f;
constexpr float MaximumDormancyDelaySeconds = 60.0f;
}

UFayAvatarDormancyComponent::UFayAvatarDormancyComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UFayAvatarDormancyComponent::BeginPlay()
{
    Super::BeginPlay();

    int32 EnabledOverride = bDormancyEnabled ? 1 : 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayAvatarDormancy="),
            EnabledOverride))
    {
        if (EnabledOverride == 0 || EnabledOverride == 1)
        {
            bDormancyEnabled = EnabledOverride == 1;
        }
        else
        {
            UE_LOG(LogFayAvatarDormancy, Warning,
                TEXT("Ignored invalid FayAvatarDormancy value; expected 0 or 1."));
        }
    }

    float DelayOverride = IdleDelaySeconds;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayAvatarDormancyDelay="),
            DelayOverride))
    {
        if (FMath::IsFinite(DelayOverride))
        {
            IdleDelaySeconds = FMath::Clamp(
                DelayOverride,
                MinimumDormancyDelaySeconds,
                MaximumDormancyDelaySeconds);
        }
        else
        {
            UE_LOG(LogFayAvatarDormancy, Warning,
                TEXT("Ignored non-finite FayAvatarDormancyDelay value."));
        }
    }

    UE_LOG(LogFayAvatarDormancy, Display,
        TEXT("MetaHuman idle dormancy: %s (delay=%.2f seconds, neutral_prepare_frames=%d)."),
        bDormancyEnabled ? TEXT("enabled") : TEXT("disabled"),
        IdleDelaySeconds,
        NeutralPreparationFrames);
    if (!bDormancyEnabled)
    {
        SetComponentTickEnabled(false);
    }
}

void UFayAvatarDormancyComponent::EndPlay(
    const EEndPlayReason::Type EndPlayReason)
{
    WakeAvatar(TEXT("end play"));
    AttachBridge(nullptr);
    AttachBodyMotion(nullptr);
    SpeechDriver = nullptr;
    Avatar = nullptr;
    SavedComponentTicks.Reset();
    SavedSkeletalPauses.Reset();
    Super::EndPlay(EndPlayReason);
}

void UFayAvatarDormancyComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (!bDormancyEnabled || !IsValid(Avatar))
    {
        return;
    }

    if (!CanPrepareForDormancy())
    {
        if (DormancyState == EDormancyState::Preparing ||
            DormancyState == EDormancyState::Dormant)
        {
            WakeAvatar(TEXT("dormancy eligibility changed"));
        }
        else
        {
            ResetIdleTimer();
        }
        return;
    }

    if (DormancyState == EDormancyState::Preparing)
    {
        if (PreparationFramesRemaining > 0)
        {
            --PreparationFramesRemaining;
            return;
        }
        FreezeAvatar();
        return;
    }

    if (DormancyState == EDormancyState::Awake)
    {
        IdleElapsedSeconds += FMath::Max(0.0f, DeltaTime);
        if (IdleElapsedSeconds >= IdleDelaySeconds)
        {
            BeginPreparation();
        }
    }
}

void UFayAvatarDormancyComponent::AttachBridge(
    UFayAvatarBridgeComponent* InBridge)
{
    if (Bridge == InBridge)
    {
        return;
    }
    if (Bridge != nullptr)
    {
        Bridge->OnMessageReceived.RemoveDynamic(
            this,
            &UFayAvatarDormancyComponent::HandleAvatarMessage);
    }
    Bridge = InBridge;
    if (Bridge != nullptr && bDormancyEnabled)
    {
        Bridge->OnMessageReceived.AddUniqueDynamic(
            this,
            &UFayAvatarDormancyComponent::HandleAvatarMessage);
    }
}

void UFayAvatarDormancyComponent::AttachSpeechDriver(
    UFayMetaHumanSpeechDriverComponent* InSpeechDriver)
{
    SpeechDriver = InSpeechDriver;
}

void UFayAvatarDormancyComponent::AttachBodyMotion(
    UFayBodyMotionComponent* InBodyMotion)
{
    if (BodyMotion == InBodyMotion)
    {
        return;
    }
    if (BodyMotion != nullptr)
    {
        BodyMotion->OnMotionStateChanged.RemoveDynamic(
            this,
            &UFayAvatarDormancyComponent::HandleMotionStateChanged);
    }
    BodyMotion = InBodyMotion;
    if (BodyMotion != nullptr && bDormancyEnabled)
    {
        BodyMotion->OnMotionStateChanged.AddUniqueDynamic(
            this,
            &UFayAvatarDormancyComponent::HandleMotionStateChanged);
    }
}

void UFayAvatarDormancyComponent::ConfigureAvatar(AActor* InAvatar)
{
    if (Avatar != InAvatar || DormancyState != EDormancyState::Awake)
    {
        WakeAvatar(TEXT("avatar reconfiguration"));
    }
    Avatar = InAvatar;
    ResetIdleTimer();
    if (bDormancyEnabled && IsValid(Avatar))
    {
        SetComponentTickEnabled(true);
        UE_LOG(LogFayAvatarDormancy, Display,
            TEXT("Configured fail-open dormancy for the reviewed avatar."));
    }
}

void UFayAvatarDormancyComponent::HandleAvatarMessage(
    const FFayAvatarMessage& Message)
{
    (void)Message;
    WakeAvatar(TEXT("accepted Fay message"));
}

void UFayAvatarDormancyComponent::HandleMotionStateChanged(
    const EFayBodyMotionState State,
    const EFayBodyMotionProvider Provider)
{
    (void)Provider;
    if (State != EFayBodyMotionState::Idle)
    {
        WakeAvatar(TEXT("body motion"));
    }
}

bool UFayAvatarDormancyComponent::CanPrepareForDormancy() const
{
    return IsValid(Avatar) && Bridge != nullptr && SpeechDriver != nullptr &&
        BodyMotion != nullptr && !Bridge->HasPendingSpeechWork() &&
        SpeechDriver->IsFaceIdleForDormancy() && BodyMotion->CanEnterDormancy();
}

void UFayAvatarDormancyComponent::BeginPreparation()
{
    if (DormancyState != EDormancyState::Awake || SpeechDriver == nullptr ||
        !SpeechDriver->PrepareAvatarForDormancy())
    {
        ResetIdleTimer();
        return;
    }
    DormancyState = EDormancyState::Preparing;
    PreparationFramesRemaining = NeutralPreparationFrames;
    UE_LOG(LogFayAvatarDormancy, Display,
        TEXT("Preparing the idle avatar for dormancy after a neutral frame."));
}

void UFayAvatarDormancyComponent::FreezeAvatar()
{
    if (DormancyState != EDormancyState::Preparing || !CanPrepareForDormancy())
    {
        WakeAvatar(TEXT("freeze precondition changed"));
        return;
    }

    SavedComponentTicks.Reset();
    SavedSkeletalPauses.Reset();
    bSavedActorTickEnabled = Avatar->IsActorTickEnabled();

    TInlineComponentArray<UActorComponent*> Components(Avatar);
    SavedComponentTicks.Reserve(Components.Num());
    for (UActorComponent* Component : Components)
    {
        if (!IsValid(Component))
        {
            continue;
        }
        FComponentTickState TickState;
        TickState.Component = Component;
        TickState.bWasTickEnabled = Component->IsComponentTickEnabled();
        SavedComponentTicks.Add(TickState);

        if (USkeletalMeshComponent* SkeletalMesh =
                Cast<USkeletalMeshComponent>(Component))
        {
            FSkeletalPauseState PauseState;
            PauseState.Component = SkeletalMesh;
            PauseState.bWasPaused = SkeletalMesh->bPauseAnims != 0;
            SavedSkeletalPauses.Add(PauseState);
            SkeletalMesh->bPauseAnims = true;
        }
    }

    for (const FComponentTickState& TickState : SavedComponentTicks)
    {
        if (TickState.Component.IsValid() && TickState.bWasTickEnabled)
        {
            TickState.Component->SetComponentTickEnabled(false);
        }
    }
    if (bSavedActorTickEnabled)
    {
        Avatar->SetActorTickEnabled(false);
    }

    DormancyState = EDormancyState::Dormant;
    PreparationFramesRemaining = 0;
    UE_LOG(LogFayAvatarDormancy, Display,
        TEXT("Entered MetaHuman idle dormancy (components=%d, skeletal_meshes=%d)."),
        SavedComponentTicks.Num(),
        SavedSkeletalPauses.Num());
}

void UFayAvatarDormancyComponent::WakeAvatar(const TCHAR* Reason)
{
    const bool bSpeechDormancyWasPrepared =
        DormancyState == EDormancyState::Preparing ||
        DormancyState == EDormancyState::Dormant;
    if (DormancyState == EDormancyState::Dormant)
    {
        for (const FSkeletalPauseState& PauseState : SavedSkeletalPauses)
        {
            if (PauseState.Component.IsValid())
            {
                PauseState.Component->bPauseAnims = PauseState.bWasPaused;
            }
        }
        if (IsValid(Avatar))
        {
            Avatar->SetActorTickEnabled(bSavedActorTickEnabled);
        }
        for (const FComponentTickState& TickState : SavedComponentTicks)
        {
            if (TickState.Component.IsValid())
            {
                TickState.Component->SetComponentTickEnabled(
                    TickState.bWasTickEnabled);
            }
        }
        UE_LOG(LogFayAvatarDormancy, Display,
            TEXT("Woke the MetaHuman from idle dormancy (%s)."),
            Reason != nullptr ? Reason : TEXT("unspecified"));
    }
    else if (DormancyState == EDormancyState::Preparing)
    {
        UE_LOG(LogFayAvatarDormancy, Display,
            TEXT("Cancelled MetaHuman dormancy preparation (%s)."),
            Reason != nullptr ? Reason : TEXT("unspecified"));
    }

    if (bSpeechDormancyWasPrepared && SpeechDriver != nullptr)
    {
        SpeechDriver->WakeAvatarFromDormancy();
    }

    SavedComponentTicks.Reset();
    SavedSkeletalPauses.Reset();
    DormancyState = EDormancyState::Awake;
    PreparationFramesRemaining = 0;
    ResetIdleTimer();
    if (bDormancyEnabled && IsValid(Avatar))
    {
        SetComponentTickEnabled(true);
    }
}

void UFayAvatarDormancyComponent::ResetIdleTimer()
{
    IdleElapsedSeconds = 0.0f;
}

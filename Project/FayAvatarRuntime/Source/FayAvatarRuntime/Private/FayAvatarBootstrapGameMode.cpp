#include "FayAvatarBootstrapGameMode.h"

#include "Camera/CameraComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "FayArkitSpeechDriverComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayAvatarDormancyComponent.h"
#include "FayArdyPoseClientComponent.h"
#include "FayBodyMotionComponent.h"
#include "FayGameUserSettings.h"
#include "FayMetaHumanSpeechDriverComponent.h"
#include "FayWardrobeComponent.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformProcess.h"
#include "HAL/IConsoleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/Parse.h"
#include "UObject/SoftObjectPath.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayAvatarRuntime, Log, All);

namespace
{
constexpr TCHAR AvatarSettingsSection[] = TEXT("FayAvatar");
constexpr TCHAR DefaultCharacterId[] = TEXT("Ada");
constexpr TCHAR DefaultCameraFramingId[] = TEXT("Portrait");
constexpr TCHAR FullBodyCameraFramingId[] = TEXT("FullBody");
constexpr TCHAR MetaHumanAdapter[] = TEXT("UE58MetaHuman");
constexpr TCHAR EpicArkitAdapter[] = TEXT("UE5EpicArkit");
constexpr TCHAR ReviewedEpicArkitActorClass[] =
    TEXT("/Script/FayAvatarRuntime.FayCasualGirlActor");
constexpr float ReviewedMaximumFramesPerSecond = 30.0f;
constexpr float FrameRateLimitTolerance = 0.01f;
constexpr double FrameRatePolicyAuditIntervalSeconds = 5.0;
constexpr double LiveLinkRecoveryDelaysSeconds[] = {1.0, 2.0, 4.0, 8.0, 16.0};
constexpr double LiveLinkRecoveryHealthyResetSeconds = 10.0;
constexpr int32 MaximumLiveLinkRecoveryAttempts =
    UE_ARRAY_COUNT(LiveLinkRecoveryDelaysSeconds);

const TCHAR* GetLiveLinkFailureName(const EFayMetaHumanLiveLinkFailure Failure)
{
    switch (Failure)
    {
    case EFayMetaHumanLiveLinkFailure::None:
        return TEXT("none");
    case EFayMetaHumanLiveLinkFailure::PendingTimeout:
        return TEXT("pending-timeout");
    case EFayMetaHumanLiveLinkFailure::ConsumerLost:
        return TEXT("consumer-lost");
    case EFayMetaHumanLiveLinkFailure::AvatarUnavailable:
        return TEXT("avatar-unavailable");
    case EFayMetaHumanLiveLinkFailure::SourceUnavailable:
        return TEXT("source-unavailable");
    case EFayMetaHumanLiveLinkFailure::SubjectCollision:
        return TEXT("subject-collision");
    case EFayMetaHumanLiveLinkFailure::SubjectInvalid:
        return TEXT("subject-invalid");
    case EFayMetaHumanLiveLinkFailure::RestoreFailed:
        return TEXT("restore-failed");
    case EFayMetaHumanLiveLinkFailure::ConfigurationRejected:
        return TEXT("configuration-rejected");
    case EFayMetaHumanLiveLinkFailure::RecoveryExhausted:
        return TEXT("recovery-exhausted");
    default:
        return TEXT("unknown");
    }
}

bool IsReviewedCharacterId(const FString& Value)
{
    if (Value.IsEmpty() || Value.Len() > 32 || !FChar::IsAlpha(Value[0]))
    {
        return false;
    }
    for (const TCHAR Character : Value)
    {
        if (!FChar::IsAlnum(Character) && Character != TEXT('_') &&
            Character != TEXT('-'))
        {
            return false;
        }
    }
    return true;
}

bool IsReviewedActorClassPath(
    const FString& Value,
    const FString& Adapter)
{
    if (Adapter.Equals(MetaHumanAdapter, ESearchCase::CaseSensitive))
    {
        return Value.StartsWith(
                   TEXT("/Game/FayMetaHumans/Built/"),
                   ESearchCase::CaseSensitive) &&
            Value.EndsWith(TEXT("_C"), ESearchCase::CaseSensitive) &&
            !Value.Contains(TEXT("..")) && !Value.Contains(TEXT("\\"));
    }
    if (Adapter.Equals(EpicArkitAdapter, ESearchCase::CaseSensitive))
    {
        return Value.Equals(
            ReviewedEpicArkitActorClass,
            ESearchCase::CaseSensitive);
    }
    return false;
}
}

AFayAvatarBootstrapGameMode::AFayAvatarBootstrapGameMode()
{
    PrimaryActorTick.bCanEverTick = true;
    PrimaryActorTick.bStartWithTickEnabled = true;

    // AGameModeBase inherits AInfo, whose constructor hides the actor. This
    // bootstrap intentionally owns runtime camera and light components, so it
    // must opt back into scene visibility before those components register.
    SetHidden(false);

    // Avoid ADefaultPawn: its constructor loads an Engine static-mesh asset.
    bStartPlayersAsSpectators = true;
    DefaultPawnClass = nullptr;
    SpectatorClass = nullptr;
    HUDClass = nullptr;

    USceneComponent* SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
    SetRootComponent(SceneRoot);

    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
    Camera->SetupAttachment(SceneRoot);
    Camera->SetRelativeLocation(FVector(0.0, -220.0, 165.0));
    Camera->SetRelativeRotation(FRotator(0.0, 90.0, 0.0));
    Camera->FieldOfView = 42.0f;
    Camera->SetActive(true);

    Bridge = CreateDefaultSubobject<UFayAvatarBridgeComponent>(TEXT("FayAvatarBridge"));
    Dormancy = CreateDefaultSubobject<UFayAvatarDormancyComponent>(TEXT("FayAvatarDormancy"));
    ArdyPoseClient = CreateDefaultSubobject<UFayArdyPoseClientComponent>(TEXT("FayArdyPoseClient"));
    BodyMotion = CreateDefaultSubobject<UFayBodyMotionComponent>(TEXT("FayBodyMotion"));
    SpeechDriver = CreateDefaultSubobject<UFayMetaHumanSpeechDriverComponent>(TEXT("FayMetaHumanSpeechDriver"));
    ArkitSpeechDriver =
        CreateDefaultSubobject<UFayArkitSpeechDriverComponent>(TEXT("FayArkitSpeechDriver"));
    Wardrobe = CreateDefaultSubobject<UFayWardrobeComponent>(TEXT("FayWardrobe"));
    Dormancy->AddTickPrerequisiteComponent(SpeechDriver);
    Dormancy->AddTickPrerequisiteComponent(BodyMotion);

    KeyLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("KeyLight"));
    KeyLight->SetupAttachment(SceneRoot);
    KeyLight->SetRelativeLocation(FVector(-110.0, -120.0, 225.0));
    KeyLight->SetIntensity(2600.0f);
    KeyLight->SetLightColor(FLinearColor(1.0f, 0.78f, 0.62f));
    KeyLight->AttenuationRadius = 650.0f;

    FillLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("FillLight"));
    FillLight->SetupAttachment(SceneRoot);
    FillLight->SetRelativeLocation(FVector(120.0, -100.0, 185.0));
    FillLight->SetIntensity(1000.0f);
    FillLight->SetLightColor(FLinearColor(0.55f, 0.72f, 1.0f));
    FillLight->AttenuationRadius = 600.0f;

    RimLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("RimLight"));
    RimLight->SetupAttachment(SceneRoot);
    RimLight->SetRelativeLocation(FVector(0.0, 130.0, 225.0));
    RimLight->SetIntensity(1800.0f);
    RimLight->SetLightColor(FLinearColor(1.0f, 0.52f, 0.34f));
    RimLight->AttenuationRadius = 500.0f;

}

void AFayAvatarBootstrapGameMode::BeginPlay()
{
    Super::BeginPlay();
    const UGameUserSettings* RuntimeUserSettings =
        GEngine != nullptr ? GEngine->GetGameUserSettings() : nullptr;
    if (RuntimeUserSettings != nullptr &&
        RuntimeUserSettings->IsA<UFayGameUserSettings>())
    {
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("Verified project-owned FayGameUserSettings runtime policy."));
    }
    else
    {
        bFrameRatePolicyViolationLogged = true;
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("The packaged runtime is not using project-owned FayGameUserSettings."));
    }
    if (ApplyReviewedFrameRateLimit())
    {
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("Enforced reviewed runtime frame cap at 30.00 FPS after GameUserSettings initialization."));
    }
    else
    {
        bFrameRatePolicyViolationLogged = true;
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Could not enforce the reviewed 30.00 FPS runtime frame cap."));
    }
    if (IConsoleVariable* IdleWhenNotForeground =
            IConsoleManager::Get().FindConsoleVariable(TEXT("t.IdleWhenNotForeground")))
    {
        IdleWhenNotForeground->Set(0, ECVF_SetByCode);
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("Disabled Unreal's background-window idle throttle for real-time speech."));
    }
    else
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("Unreal's background-window idle control is unavailable; keep the avatar window focused during speech."));
    }
    if (Dormancy != nullptr)
    {
        Dormancy->AttachBridge(Bridge);
        Dormancy->AttachSpeechDriver(SpeechDriver);
        Dormancy->AttachBodyMotion(BodyMotion);
    }
    if (SpeechDriver != nullptr)
    {
        SpeechDriver->OnLiveLinkStateChanged.RemoveAll(this);
        SpeechDriver->OnLiveLinkStateChanged.AddUObject(
            this,
            &AFayAvatarBootstrapGameMode::HandleLiveLinkStateChanged);
        SpeechDriver->AttachBridge(Bridge);
    }
    if (BodyMotion != nullptr)
    {
        BodyMotion->AttachBridge(Bridge);
        BodyMotion->AttachArdyClient(ArdyPoseClient);
    }
    FString SceneOnlyValue;
    if (FParse::Value(FCommandLine::Get(), TEXT("FaySceneOnly="), SceneOnlyValue))
    {
        SceneOnlyValue.TrimStartAndEndInline();
        if (SceneOnlyValue == TEXT("1"))
        {
            bSceneOnlyDiagnostic = true;
            UE_LOG(LogFayAvatarRuntime, Display,
                TEXT("Fay scene-only diagnostic active (character_spawn=off, debug_draw=off, integrations=on)."));
            return;
        }
        if (SceneOnlyValue != TEXT("0"))
        {
            UE_LOG(LogFayAvatarRuntime, Warning,
                TEXT("Ignoring invalid FaySceneOnly value; expected 0 or 1."));
        }
    }
    bCharacterProfileValid = LoadCharacterProfile();
    if (bCharacterProfileValid && CharacterAdapter.Equals(
            EpicArkitAdapter,
            ESearchCase::CaseSensitive))
    {
        // Only the selected speech adapter may consume decoded speech. Keep
        // the MetaHuman path unchanged for MetaHuman and diagnostic profiles,
        // but disconnect it before activating the direct ARKit morph driver.
        if (SpeechDriver != nullptr)
        {
            SpeechDriver->OnLiveLinkStateChanged.RemoveAll(this);
            SpeechDriver->AttachBridge(nullptr);
        }
        if (ArkitSpeechDriver != nullptr)
        {
            ArkitSpeechDriver->AttachBridge(Bridge);
        }
    }
    TrySpawnMetaHuman();
}

void AFayAvatarBootstrapGameMode::EndPlay(
    const EEndPlayReason::Type EndPlayReason)
{
    bEndingPlay = true;
    bLiveLinkRecoveryScheduled = false;
    bLiveLinkRecoveryExhaustionPending = false;
    if (SpeechDriver != nullptr)
    {
        SpeechDriver->OnLiveLinkStateChanged.RemoveAll(this);
    }
    if (ArkitSpeechDriver != nullptr)
    {
        ArkitSpeechDriver->ClearAvatar();
        ArkitSpeechDriver->AttachBridge(nullptr);
    }
    Super::EndPlay(EndPlayReason);
}

void AFayAvatarBootstrapGameMode::Tick(const float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    TickFrameRatePolicy(DeltaSeconds);
    TickLiveLinkRecovery(DeltaSeconds);

    if (!bViewClaimed)
    {
        if (APlayerController* PlayerController = GetWorld()->GetFirstPlayerController())
        {
            PlayerController->SetViewTarget(this);
            if (PlayerController->GetViewTarget() == this)
            {
                bViewClaimed = true;
                UE_LOG(LogFayAvatarRuntime, Display,
                    TEXT("Activated the visible Spark studio camera and lighting rig."));
            }
        }
    }

    if (IsValid(MetaHumanActor))
    {
        if (CharacterAdapter.Equals(
                EpicArkitAdapter,
                ESearchCase::CaseSensitive) &&
            ArkitSpeechDriver != nullptr &&
            !ArkitSpeechDriver->IsConfigured())
        {
            // Fail open to the narrow amplitude jaw path if the reviewed face
            // component or mesh disappears after initial configuration.
            bJawFallbackActive = true;
        }
        DriveJawFallback();
    }
    else if (!bSceneOnlyDiagnostic)
    {
        DrawSmokeScene();
    }
}

bool AFayAvatarBootstrapGameMode::ApplyReviewedFrameRateLimit() const
{
    IConsoleVariable* MaximumFramesPerSecond =
        IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"));
    if (MaximumFramesPerSecond == nullptr)
    {
        return false;
    }

    // GameUserSettings can apply FrameRateLimit=0 after ConsoleVariables.ini.
    // Code priority handles the ordinary path. A console-priority diagnostic
    // can outrank it, so retry at the variable's current priority before the
    // verified readback. Neither path persists or applies user settings.
    MaximumFramesPerSecond->Set(
        ReviewedMaximumFramesPerSecond,
        ECVF_SetByCode);
    if (!FMath::IsNearlyEqual(
            MaximumFramesPerSecond->GetFloat(),
            ReviewedMaximumFramesPerSecond,
            FrameRateLimitTolerance))
    {
        MaximumFramesPerSecond->SetWithCurrentPriority(
            ReviewedMaximumFramesPerSecond);
    }
    return FMath::IsNearlyEqual(
        MaximumFramesPerSecond->GetFloat(),
        ReviewedMaximumFramesPerSecond,
        FrameRateLimitTolerance);
}

void AFayAvatarBootstrapGameMode::TickFrameRatePolicy(const float DeltaSeconds)
{
    FrameRatePolicyAuditElapsedSeconds += FMath::Max(0.0f, DeltaSeconds);
    if (FrameRatePolicyAuditElapsedSeconds < FrameRatePolicyAuditIntervalSeconds)
    {
        return;
    }
    FrameRatePolicyAuditElapsedSeconds = FMath::Fmod(
        FrameRatePolicyAuditElapsedSeconds,
        FrameRatePolicyAuditIntervalSeconds);

    IConsoleVariable* MaximumFramesPerSecond =
        IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"));
    const float ObservedMaximumFramesPerSecond =
        MaximumFramesPerSecond != nullptr
        ? MaximumFramesPerSecond->GetFloat()
        : 0.0f;
    if (MaximumFramesPerSecond != nullptr &&
        FMath::IsNearlyEqual(
            ObservedMaximumFramesPerSecond,
            ReviewedMaximumFramesPerSecond,
            FrameRateLimitTolerance))
    {
        return;
    }

    if (!bFrameRatePolicyViolationLogged)
    {
        bFrameRatePolicyViolationLogged = true;
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Reviewed runtime frame cap policy drifted (observed=%.2f, expected=30.00); attempting repair."),
            ObservedMaximumFramesPerSecond);
    }

    if (ApplyReviewedFrameRateLimit())
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("Restored the reviewed 30.00 FPS runtime frame cap after policy drift."));
    }
}

void AFayAvatarBootstrapGameMode::HandleLiveLinkStateChanged(
    const EFayMetaHumanLiveLinkState State,
    const EFayMetaHumanLiveLinkFailure Failure)
{
    if (bEndingPlay || !CharacterAdapter.Equals(
            MetaHumanAdapter,
            ESearchCase::CaseSensitive))
    {
        return;
    }

    const bool bWasJawFallbackActive = bJawFallbackActive;
    bLiveLinkConfigured = State == EFayMetaHumanLiveLinkState::Configured;
    bLiveLinkConfigurationRequested =
        State == EFayMetaHumanLiveLinkState::Configuring;

    if (State == EFayMetaHumanLiveLinkState::Configured)
    {
        if (bWasJawFallbackActive && IsValid(FaceMesh) &&
            !JawMorphTarget.IsNone())
        {
            // A skipped utterance may leave a non-zero fallback morph. Clear
            // it before learned Live Link takes exclusive facial ownership.
            FaceMesh->SetMorphTarget(JawMorphTarget, 0.0f, false);
        }
        bJawFallbackActive = false;
        bLiveLinkRecoveryScheduled = false;
        bLiveLinkRecoveryExhaustionPending = false;
        LiveLinkRecoveryDelayRemainingSeconds = 0.0;
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("Character '%s' has an enabled and evaluable Fay Live Link source."),
            *ActiveCharacterId);
        return;
    }

    if (State == EFayMetaHumanLiveLinkState::RecoveryBackoff)
    {
        bJawFallbackActive = true;
        bLiveLinkConfigurationRequested = false;
        if (LiveLinkRecoveryAttemptCount >= MaximumLiveLinkRecoveryAttempts)
        {
            bLiveLinkRecoveryScheduled = false;
            bLiveLinkRecoveryExhaustionPending = true;
            UE_LOG(LogFayAvatarRuntime, Error,
                TEXT("Character '%s' exhausted %d bounded Live Link recovery attempts; retaining the jaw fallback when available."),
                *ActiveCharacterId,
                MaximumLiveLinkRecoveryAttempts);
            return;
        }

        LiveLinkRecoveryDelayRemainingSeconds =
            LiveLinkRecoveryDelaysSeconds[LiveLinkRecoveryAttemptCount];
        bLiveLinkRecoveryScheduled = true;
        bLiveLinkRecoveryExhaustionPending = false;
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("Character '%s' entered degraded Live Link mode (failure=%s); retry %d/%d is scheduled in %.1f seconds and jaw fallback remains available."),
            *ActiveCharacterId,
            GetLiveLinkFailureName(Failure),
            LiveLinkRecoveryAttemptCount + 1,
            MaximumLiveLinkRecoveryAttempts,
            LiveLinkRecoveryDelayRemainingSeconds);
        return;
    }

    bLiveLinkRecoveryScheduled = false;
    bLiveLinkRecoveryExhaustionPending = false;
    LiveLinkRecoveryDelayRemainingSeconds = 0.0;
    bJawFallbackActive = State != EFayMetaHumanLiveLinkState::TerminalFailure ||
        Failure != EFayMetaHumanLiveLinkFailure::RestoreFailed;
    if (State == EFayMetaHumanLiveLinkState::TerminalFailure)
    {
        if (Failure == EFayMetaHumanLiveLinkFailure::RestoreFailed)
        {
            UE_LOG(LogFayAvatarRuntime, Error,
                TEXT("Character '%s' entered terminal Live Link degradation (failure=restore-failed); all further adapter avatar writes are blocked."),
                *ActiveCharacterId);
        }
        else
        {
            UE_LOG(LogFayAvatarRuntime, Error,
                TEXT("Character '%s' entered terminal Live Link degradation (failure=%s); retaining the jaw fallback when available."),
                *ActiveCharacterId,
                GetLiveLinkFailureName(Failure));
        }
    }
}

void AFayAvatarBootstrapGameMode::TickLiveLinkRecovery(const float DeltaSeconds)
{
    if (bEndingPlay || SpeechDriver == nullptr ||
        !CharacterAdapter.Equals(
            MetaHumanAdapter,
            ESearchCase::CaseSensitive))
    {
        return;
    }
    const double SafeDeltaSeconds =
        static_cast<double>(FMath::Max(DeltaSeconds, 0.0f));
    if (bLiveLinkConfigured)
    {
        if (!SpeechDriver->IsLiveLinkHealthyCached())
        {
            return;
        }
        if (LiveLinkRecoveryAttemptCount > 0)
        {
            const double HealthySeconds =
                SpeechDriver->GetConsecutiveLiveLinkHealthySeconds();
            if (HealthySeconds >=
                LiveLinkRecoveryHealthyResetSeconds)
            {
                UE_LOG(LogFayAvatarRuntime, Display,
                    TEXT("Character '%s' completed %.0f continuous healthy Live Link seconds; resetting the recovery episode."),
                    *ActiveCharacterId,
                    LiveLinkRecoveryHealthyResetSeconds);
                LiveLinkRecoveryAttemptCount = 0;
            }
        }
        return;
    }
    if (bLiveLinkRecoveryExhaustionPending)
    {
        bLiveLinkRecoveryExhaustionPending = false;
        SpeechDriver->AbandonAvatarRecovery();
        return;
    }
    if (!bLiveLinkRecoveryScheduled)
    {
        return;
    }
    if (!IsValid(MetaHumanActor))
    {
        bLiveLinkRecoveryScheduled = false;
        SpeechDriver->AbandonAvatarRecovery();
        return;
    }

    LiveLinkRecoveryDelayRemainingSeconds -= SafeDeltaSeconds;
    if (LiveLinkRecoveryDelayRemainingSeconds > 0.0)
    {
        return;
    }
    if (Bridge != nullptr && Bridge->HasPendingSpeechWork())
    {
        return;
    }
    if (BodyMotion == nullptr)
    {
        bLiveLinkRecoveryScheduled = false;
        SpeechDriver->AbandonAvatarRecovery();
        return;
    }
    if (!BodyMotion->CanEnterDormancy())
    {
        return;
    }

    bLiveLinkRecoveryScheduled = false;
    ++LiveLinkRecoveryAttemptCount;
    UE_LOG(LogFayAvatarRuntime, Display,
        TEXT("Attempting sealed Live Link recovery for character '%s' (%d/%d)."),
        *ActiveCharacterId,
        LiveLinkRecoveryAttemptCount,
        MaximumLiveLinkRecoveryAttempts);
    SpeechDriver->RetryLastAvatarConfiguration();
}

bool AFayAvatarBootstrapGameMode::LoadCharacterProfile()
{
    if (GConfig == nullptr)
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("The Unreal configuration cache is unavailable; refusing character loading."));
        return false;
    }

    FString RequestedId;
    if (!FParse::Value(FCommandLine::Get(), TEXT("FayCharacter="), RequestedId))
    {
        if (!GConfig->GetString(
                AvatarSettingsSection,
                TEXT("DefaultCharacter"),
                RequestedId,
                GGameIni))
        {
            RequestedId = DefaultCharacterId;
        }
    }
    RequestedId.TrimStartAndEndInline();
    if (!IsReviewedCharacterId(RequestedId))
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Requested character ID is not a reviewed identifier; using the diagnostic avatar."));
        return false;
    }

    FString RequestedCameraFraming = DefaultCameraFramingId;
    const FString CameraFramingArgumentPrefix = TEXT("-FayCameraFraming=");
    TArray<FString> CommandLineTokens;
    FString(FCommandLine::Get()).ParseIntoArrayWS(CommandLineTokens);
    int32 CameraFramingArgumentCount = 0;
    bool bMalformedCameraFramingArgument = false;
    for (const FString& Token : CommandLineTokens)
    {
        if (Token.Equals(TEXT("-FayCameraFraming"), ESearchCase::IgnoreCase))
        {
            bMalformedCameraFramingArgument = true;
            continue;
        }
        if (!Token.StartsWith(CameraFramingArgumentPrefix, ESearchCase::IgnoreCase))
        {
            continue;
        }
        ++CameraFramingArgumentCount;
        if (!Token.StartsWith(CameraFramingArgumentPrefix, ESearchCase::CaseSensitive))
        {
            bMalformedCameraFramingArgument = true;
            continue;
        }
        RequestedCameraFraming = Token.RightChop(CameraFramingArgumentPrefix.Len());
    }
    const bool bReviewedCameraFraming =
        CameraFramingArgumentCount <= 1 && !bMalformedCameraFramingArgument &&
        (RequestedCameraFraming.Equals(
             DefaultCameraFramingId, ESearchCase::CaseSensitive) ||
            RequestedCameraFraming.Equals(
                FullBodyCameraFramingId, ESearchCase::CaseSensitive));
    if (!bReviewedCameraFraming)
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Requested camera framing is unknown or ambiguous; expected at most one exact -FayCameraFraming=Portrait|FullBody argument and refusing character loading."));
        return false;
    }

    const FString Section = FString::Printf(TEXT("FayCharacter.%s"), *RequestedId);
    const bool bPortraitCameraFraming = RequestedCameraFraming.Equals(
        DefaultCameraFramingId, ESearchCase::CaseSensitive);
    const TCHAR* CameraLocationKey = bPortraitCameraFraming
        ? TEXT("CameraPortraitRelativeLocation")
        : TEXT("CameraFullBodyRelativeLocation");
    const TCHAR* CameraRotationKey = bPortraitCameraFraming
        ? TEXT("CameraPortraitRelativeRotation")
        : TEXT("CameraFullBodyRelativeRotation");
    const TCHAR* CameraFieldOfViewKey = bPortraitCameraFraming
        ? TEXT("CameraPortraitFieldOfView")
        : TEXT("CameraFullBodyFieldOfView");
    FString ActorClassPath;
    FString Adapter;
    FString FaceComponent;
    FString BodyComponent;
    FString SpawnLocation;
    FString SpawnRotation;
    FString CameraLocation;
    FString CameraRotation;
    float CameraFieldOfView = 0.0f;
    const bool bComplete =
        GConfig->GetString(*Section, TEXT("ActorClass"), ActorClassPath, GGameIni) &&
        GConfig->GetString(*Section, TEXT("Adapter"), Adapter, GGameIni) &&
        GConfig->GetString(*Section, TEXT("FaceComponent"), FaceComponent, GGameIni) &&
        GConfig->GetString(*Section, TEXT("BodyComponent"), BodyComponent, GGameIni) &&
        GConfig->GetString(*Section, TEXT("SpawnLocation"), SpawnLocation, GGameIni) &&
        GConfig->GetString(*Section, TEXT("SpawnRotation"), SpawnRotation, GGameIni) &&
        GConfig->GetString(*Section, CameraLocationKey, CameraLocation, GGameIni) &&
        GConfig->GetString(*Section, CameraRotationKey, CameraRotation, GGameIni) &&
        GConfig->GetFloat(*Section, CameraFieldOfViewKey, CameraFieldOfView, GGameIni);
    if (!bComplete)
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Character profile '%s' is missing required fields for camera framing '%s'; using the diagnostic avatar."),
            *RequestedId,
            *RequestedCameraFraming);
        return false;
    }
    const bool bReviewedAdapter =
        Adapter.Equals(MetaHumanAdapter, ESearchCase::CaseSensitive) ||
        Adapter.Equals(EpicArkitAdapter, ESearchCase::CaseSensitive);
    const bool bReviewedComponents =
        (Adapter.Equals(MetaHumanAdapter, ESearchCase::CaseSensitive) &&
            FaceComponent == TEXT("Face") && BodyComponent == TEXT("Body")) ||
        (Adapter.Equals(EpicArkitAdapter, ESearchCase::CaseSensitive) &&
            FaceComponent == TEXT("Body") && BodyComponent == TEXT("Body"));
    if (!bReviewedAdapter || !bReviewedComponents ||
        !IsReviewedActorClassPath(ActorClassPath, Adapter))
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Character profile '%s' is outside the reviewed adapter, component, or actor-path contract (adapter=%s)."),
            *RequestedId,
            *Adapter);
        return false;
    }

    FVector ParsedSpawnLocation;
    FRotator ParsedSpawnRotation;
    FVector ParsedCameraLocation;
    FRotator ParsedCameraRotation;
    if (!ParsedSpawnLocation.InitFromString(SpawnLocation) ||
        !ParsedSpawnRotation.InitFromString(SpawnRotation) ||
        !ParsedCameraLocation.InitFromString(CameraLocation) ||
        !ParsedCameraRotation.InitFromString(CameraRotation) ||
        CameraFieldOfView < 20.0f || CameraFieldOfView > 90.0f)
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Character profile '%s' contains invalid transforms or camera settings."),
            *RequestedId);
        return false;
    }

    ActiveCharacterId = RequestedId;
    ActiveCameraFramingId = RequestedCameraFraming;
    CharacterAdapter = Adapter;
    FaceComponentName = FName(*FaceComponent);
    BodyComponentName = FName(*BodyComponent);
    CharacterSpawnLocation = ParsedSpawnLocation;
    CharacterSpawnRotation = ParsedSpawnRotation;
    MetaHumanClass = TSoftClassPtr<AActor>(FSoftObjectPath(ActorClassPath));
    Camera->SetRelativeLocation(ParsedCameraLocation);
    Camera->SetRelativeRotation(ParsedCameraRotation);
    Camera->FieldOfView = CameraFieldOfView;
    UE_LOG(LogFayAvatarRuntime, Display,
        TEXT("Selected reviewed character profile '%s' (adapter=%s, camera_framing=%s)."),
        *ActiveCharacterId,
        *CharacterAdapter,
        *ActiveCameraFramingId);
    return true;
}

void AFayAvatarBootstrapGameMode::TrySpawnMetaHuman()
{
    UWorld* World = GetWorld();
    if (!bCharacterProfileValid)
    {
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("No valid character profile is active; retaining the diagnostic avatar."));
        return;
    }
    UClass* LoadedClass = MetaHumanClass.LoadSynchronous();
    if (World == nullptr || LoadedClass == nullptr || !LoadedClass->IsChildOf(AActor::StaticClass()))
    {
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("The assembled character '%s' is unavailable; retaining the diagnostic avatar."),
            *ActiveCharacterId);
        return;
    }

    FActorSpawnParameters SpawnParameters;
    SpawnParameters.SpawnCollisionHandlingOverride =
        ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    MetaHumanActor = World->SpawnActor<AActor>(
        LoadedClass,
        CharacterSpawnLocation,
        CharacterSpawnRotation,
        SpawnParameters);
    if (!IsValid(MetaHumanActor))
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("The assembled character '%s' loaded but could not be spawned."),
            *ActiveCharacterId);
        return;
    }

    ResolveFaceAndJawMorph();
    if (BodyMotion != nullptr)
    {
        BodyMotion->ConfigureAvatar(MetaHumanActor, BodyComponentName);
    }
    if (Wardrobe != nullptr)
    {
        Wardrobe->ConfigureFromReviewedBinding(MetaHumanActor);
    }
    if (CharacterAdapter.Equals(
            MetaHumanAdapter,
            ESearchCase::CaseSensitive))
    {
        LiveLinkRecoveryAttemptCount = 0;
        LiveLinkRecoveryDelayRemainingSeconds = 0.0;
        bLiveLinkRecoveryScheduled = false;
        bLiveLinkRecoveryExhaustionPending = false;
        bJawFallbackActive = true;
        bLiveLinkConfigured = false;
        bLiveLinkConfigurationRequested = SpeechDriver != nullptr &&
            SpeechDriver->IsSolverReady();
        if (bLiveLinkConfigurationRequested)
        {
            bLiveLinkConfigured = SpeechDriver->ConfigureAvatar(MetaHumanActor);
            bLiveLinkConfigurationRequested =
                !bLiveLinkConfigured && SpeechDriver->IsAvatarConfigurationPending();
        }
        if (Dormancy != nullptr)
        {
            Dormancy->ConfigureAvatar(MetaHumanActor);
        }
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("Spawned character '%s' (speech_live_link=%s)."),
            *ActiveCharacterId,
            bLiveLinkConfigured
                ? TEXT("configured")
                : (bLiveLinkConfigurationRequested ? TEXT("pending exact-source verification")
                                                   : TEXT("jaw fallback")));
        return;
    }

    // UE5EpicArkit bypasses the MetaHuman Live Link driver and its recovery
    // state machine. The direct morph driver owns only the exact Face mesh of
    // the sealed Casual Girl wrapper Blueprint.
    bLiveLinkConfigured = false;
    bLiveLinkConfigurationRequested = false;
    bLiveLinkRecoveryScheduled = false;
    bLiveLinkRecoveryExhaustionPending = false;
    LiveLinkRecoveryAttemptCount = 0;
    LiveLinkRecoveryDelayRemainingSeconds = 0.0;
    bool bArkitConfigured = false;
    if (ArkitSpeechDriver != nullptr)
    {
        ArkitSpeechDriver->AttachBridge(Bridge);
        ArkitSpeechDriver->ConfigureAvatar(MetaHumanActor, FaceComponentName);
        bArkitConfigured = ArkitSpeechDriver->IsConfigured();
    }
    bJawFallbackActive = !bArkitConfigured;
    UE_LOG(LogFayAvatarRuntime, Display,
        TEXT("Spawned character '%s' (speech_arkit_morphs=%s, speech_live_link=disabled)."),
        *ActiveCharacterId,
        bArkitConfigured ? TEXT("configured") : TEXT("jaw fallback"));
}

void AFayAvatarBootstrapGameMode::ResolveFaceAndJawMorph()
{
    if (!IsValid(MetaHumanActor))
    {
        return;
    }

    TInlineComponentArray<USkeletalMeshComponent*> SkeletalMeshes(MetaHumanActor);
    for (USkeletalMeshComponent* Mesh : SkeletalMeshes)
    {
        FString StableName = Mesh != nullptr ? Mesh->GetName() : FString();
        StableName.RemoveFromEnd(TEXT("_GEN_VARIABLE"));
        if (StableName == FaceComponentName.ToString())
        {
            FaceMesh = Mesh;
            break;
        }
    }
    if (FaceMesh == nullptr || FaceMesh->GetSkeletalMeshAsset() == nullptr)
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("Character '%s' did not expose its expected '%s' skeletal mesh."),
            *ActiveCharacterId,
            *FaceComponentName.ToString());
        return;
    }

    static const FName Candidates[] = {
        TEXT("CTRL_expressions_jawOpen"),
        TEXT("JawOpen"),
        TEXT("jawOpen"),
        TEXT("jaw_open"),
        TEXT("mouthOpen")};
    for (const FName Candidate : Candidates)
    {
        if (FaceMesh->GetSkeletalMeshAsset()->FindMorphTarget(Candidate) != nullptr)
        {
            JawMorphTarget = Candidate;
            FaceMesh->AddTickPrerequisiteActor(this);
            UE_LOG(LogFayAvatarRuntime, Display,
                TEXT("Resolved diagnostic jaw morph %s."),
                *JawMorphTarget.ToString());
            return;
        }
    }

    UE_LOG(LogFayAvatarRuntime, Display,
        TEXT("No direct jaw morph is exposed; the learned Live Link face path is required."));
}

void AFayAvatarBootstrapGameMode::DriveJawFallback() const
{
    if (!bJawFallbackActive || Bridge == nullptr || FaceMesh == nullptr ||
        JawMorphTarget.IsNone())
    {
        return;
    }
    FaceMesh->SetMorphTarget(
        JawMorphTarget,
        FMath::Clamp(Bridge->GetMouthAmplitude(), 0.0f, 1.0f),
        false);
}

void AFayAvatarBootstrapGameMode::DrawSmokeScene() const
{
    UWorld* World = GetWorld();
    if (World == nullptr || Bridge == nullptr)
    {
        return;
    }

    FColor StateColor = FColor::Orange;
    switch (Bridge->GetConnectionState())
    {
    case EFayAvatarBridgeState::Connected:
        StateColor = FColor::Green;
        break;
    case EFayAvatarBridgeState::Connecting:
    case EFayAvatarBridgeState::Reconnecting:
        StateColor = FColor::Yellow;
        break;
    case EFayAvatarBridgeState::Error:
        StateColor = FColor::Red;
        break;
    case EFayAvatarBridgeState::Disconnected:
    default:
        break;
    }

    constexpr bool bPersistent = false;
    constexpr float LifeTime = -1.0f;
    constexpr uint8 DepthPriority = 0;
    constexpr float LineThickness = 2.0f;

    // Ground grid.
    for (int32 Offset = -400; Offset <= 400; Offset += 100)
    {
        DrawDebugLine(World, FVector(-200.0, Offset, 0.0), FVector(400.0, Offset, 0.0),
            FColor(45, 70, 90), bPersistent, LifeTime, DepthPriority, 1.0f);
        DrawDebugLine(World, FVector(Offset, -400.0, 0.0), FVector(Offset, 400.0, 0.0),
            FColor(45, 70, 90), bPersistent, LifeTime, DepthPriority, 1.0f);
    }

    // A lightweight avatar silhouette. Head color exposes Fay connection state.
    DrawDebugSphere(World, FVector(0.0, 0.0, 220.0), 34.0f, 24, StateColor,
        bPersistent, LifeTime, DepthPriority, LineThickness);
    DrawDebugBox(World, FVector(0.0, 0.0, 135.0), FVector(22.0, 48.0, 55.0),
        FQuat::Identity, FColor::Cyan, bPersistent, LifeTime, DepthPriority, LineThickness);

    DrawDebugLine(World, FVector(0.0, -42.0, 172.0), FVector(0.0, -105.0, 105.0),
        FColor::Cyan, bPersistent, LifeTime, DepthPriority, LineThickness);
    DrawDebugLine(World, FVector(0.0, 42.0, 172.0), FVector(0.0, 105.0, 105.0),
        FColor::Cyan, bPersistent, LifeTime, DepthPriority, LineThickness);
    DrawDebugLine(World, FVector(0.0, -24.0, 82.0), FVector(0.0, -38.0, 0.0),
        FColor::Cyan, bPersistent, LifeTime, DepthPriority, LineThickness);
    DrawDebugLine(World, FVector(0.0, 24.0, 82.0), FVector(0.0, 38.0, 0.0),
        FColor::Cyan, bPersistent, LifeTime, DepthPriority, LineThickness);

    // RMS speech amplitude opens the two mouth lines in real time.
    const float MouthGap = 1.0f + FMath::Clamp(Bridge->GetMouthAmplitude(), 0.0f, 1.0f) * 9.0f;
    DrawDebugLine(World, FVector(-33.0, -12.0, 211.0 - MouthGap), FVector(-33.0, 12.0, 211.0 - MouthGap),
        FColor::White, bPersistent, LifeTime, DepthPriority, LineThickness);
    DrawDebugLine(World, FVector(-33.0, -12.0, 211.0 + MouthGap), FVector(-33.0, 12.0, 211.0 + MouthGap),
        FColor::White, bPersistent, LifeTime, DepthPriority, LineThickness);
}

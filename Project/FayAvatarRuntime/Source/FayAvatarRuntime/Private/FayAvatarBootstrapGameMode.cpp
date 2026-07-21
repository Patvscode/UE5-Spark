#include "FayAvatarBootstrapGameMode.h"

#include "Camera/CameraComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "FayAvatarBridgeComponent.h"
#include "FayMetaHumanSpeechDriverComponent.h"
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
constexpr TCHAR RequiredAdapter[] = TEXT("UE58MetaHuman");

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

bool IsReviewedActorClassPath(const FString& Value)
{
    return Value.StartsWith(TEXT("/Game/FayMetaHumans/Built/")) &&
        Value.EndsWith(TEXT("_C")) && !Value.Contains(TEXT("..")) &&
        !Value.Contains(TEXT("\\"));
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
    SpeechDriver = CreateDefaultSubobject<UFayMetaHumanSpeechDriverComponent>(TEXT("FayMetaHumanSpeechDriver"));

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
    if (SpeechDriver != nullptr)
    {
        SpeechDriver->AttachBridge(Bridge);
    }
    bCharacterProfileValid = LoadCharacterProfile();
    TrySpawnMetaHuman();
}

void AFayAvatarBootstrapGameMode::Tick(const float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

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

    if (bLiveLinkConfigurationRequested && !bLiveLinkConfigured && SpeechDriver != nullptr)
    {
        if (SpeechDriver->IsAvatarConfigured())
        {
            bLiveLinkConfigured = true;
            bLiveLinkConfigurationRequested = false;
            UE_LOG(LogFayAvatarRuntime, Display,
                TEXT("Character '%s' has an enabled and evaluable Fay Live Link source."),
                *ActiveCharacterId);
        }
        else if (!SpeechDriver->IsAvatarConfigurationPending())
        {
            bLiveLinkConfigurationRequested = false;
            UE_LOG(LogFayAvatarRuntime, Warning,
                TEXT("Character '%s' ended Live Link configuration without a verified consumer; "
                     "retaining the jaw fallback when available."),
                *ActiveCharacterId);
        }
    }

    if (IsValid(MetaHumanActor))
    {
        DriveJawFallback();
    }
    else
    {
        DrawSmokeScene();
    }
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

    const FString Section = FString::Printf(TEXT("FayCharacter.%s"), *RequestedId);
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
        GConfig->GetString(*Section, TEXT("CameraRelativeLocation"), CameraLocation, GGameIni) &&
        GConfig->GetString(*Section, TEXT("CameraRelativeRotation"), CameraRotation, GGameIni) &&
        GConfig->GetFloat(*Section, TEXT("CameraFieldOfView"), CameraFieldOfView, GGameIni);
    if (!bComplete)
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Character profile '%s' is missing required fields; using the diagnostic avatar."),
            *RequestedId);
        return false;
    }
    if (Adapter != RequiredAdapter || FaceComponent != TEXT("Face") ||
        BodyComponent != TEXT("Body") || !IsReviewedActorClassPath(ActorClassPath))
    {
        UE_LOG(LogFayAvatarRuntime, Error,
            TEXT("Character profile '%s' is outside the reviewed UE 5.8 MetaHuman contract."),
            *RequestedId);
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
        TEXT("Selected reviewed character profile '%s' (adapter=%s)."),
        *ActiveCharacterId,
        *CharacterAdapter);
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
    bLiveLinkConfigured = false;
    bLiveLinkConfigurationRequested = SpeechDriver != nullptr &&
        SpeechDriver->IsSolverReady();
    if (bLiveLinkConfigurationRequested)
    {
        bLiveLinkConfigured = SpeechDriver->ConfigureAvatar(MetaHumanActor);
        bLiveLinkConfigurationRequested =
            !bLiveLinkConfigured && SpeechDriver->IsAvatarConfigurationPending();
    }
    UE_LOG(LogFayAvatarRuntime, Display,
        TEXT("Spawned character '%s' (speech_live_link=%s)."),
        *ActiveCharacterId,
        bLiveLinkConfigured
            ? TEXT("configured")
            : (bLiveLinkConfigurationRequested ? TEXT("pending exact-source verification")
                                               : TEXT("jaw fallback")));
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
    if (bLiveLinkConfigured || Bridge == nullptr || FaceMesh == nullptr ||
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

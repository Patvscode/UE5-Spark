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
#include "HAL/IConsoleManager.h"
#include "UObject/SoftObjectPath.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayAvatarRuntime, Log, All);

namespace
{
constexpr TCHAR DefaultMetaHumanClassPath[] =
    TEXT("/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay.BP_AdaFay_C");
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

    MetaHumanClass = TSoftClassPtr<AActor>(FSoftObjectPath(DefaultMetaHumanClassPath));
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
                TEXT("Ada MetaHuman's exact Fay Live Link source is enabled and evaluable."));
        }
        else if (!SpeechDriver->IsAvatarConfigurationPending())
        {
            bLiveLinkConfigurationRequested = false;
            UE_LOG(LogFayAvatarRuntime, Warning,
                TEXT("Ada MetaHuman Live Link configuration ended without a verified consumer; "
                     "retaining the jaw fallback when available."));
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

void AFayAvatarBootstrapGameMode::TrySpawnMetaHuman()
{
    UWorld* World = GetWorld();
    UClass* LoadedClass = MetaHumanClass.LoadSynchronous();
    if (World == nullptr || LoadedClass == nullptr || !LoadedClass->IsChildOf(AActor::StaticClass()))
    {
        UE_LOG(LogFayAvatarRuntime, Display,
            TEXT("The assembled Ada MetaHuman is unavailable; retaining the diagnostic avatar."));
        return;
    }

    FActorSpawnParameters SpawnParameters;
    SpawnParameters.SpawnCollisionHandlingOverride =
        ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    MetaHumanActor = World->SpawnActor<AActor>(
        LoadedClass,
        FVector::ZeroVector,
        FRotator(0.0f, 180.0f, 0.0f),
        SpawnParameters);
    if (!IsValid(MetaHumanActor))
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("The assembled Ada class loaded but could not be spawned."));
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
        TEXT("Spawned Ada MetaHuman (speech_live_link=%s)."),
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
        if (StableName == TEXT("Face"))
        {
            FaceMesh = Mesh;
            break;
        }
    }
    if (FaceMesh == nullptr || FaceMesh->GetSkeletalMeshAsset() == nullptr)
    {
        UE_LOG(LogFayAvatarRuntime, Warning,
            TEXT("The assembled Ada actor did not expose its expected Face skeletal mesh."));
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

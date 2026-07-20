#include "FayAvatarBootstrapGameMode.h"

#include "Camera/CameraComponent.h"
#include "Components/SceneComponent.h"
#include "DrawDebugHelpers.h"
#include "FayAvatarBridgeComponent.h"
#include "GameFramework/PlayerController.h"

AFayAvatarBootstrapGameMode::AFayAvatarBootstrapGameMode()
{
    PrimaryActorTick.bCanEverTick = true;
    PrimaryActorTick.bStartWithTickEnabled = true;

    // Avoid ADefaultPawn: its constructor loads an Engine static-mesh asset.
    bStartPlayersAsSpectators = true;
    DefaultPawnClass = nullptr;
    SpectatorClass = nullptr;
    HUDClass = nullptr;

    USceneComponent* SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
    SetRootComponent(SceneRoot);

    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
    Camera->SetupAttachment(SceneRoot);
    Camera->SetRelativeLocation(FVector(-850.0, 0.0, 170.0));
    Camera->SetRelativeRotation(FRotator::ZeroRotator);
    Camera->FieldOfView = 55.0f;
    Camera->SetActive(true);

    Bridge = CreateDefaultSubobject<UFayAvatarBridgeComponent>(TEXT("FayAvatarBridge"));
}

void AFayAvatarBootstrapGameMode::Tick(const float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    if (!bViewClaimed)
    {
        if (APlayerController* PlayerController = GetWorld()->GetFirstPlayerController())
        {
            PlayerController->SetViewTarget(this);
            bViewClaimed = true;
        }
    }

    DrawSmokeScene();
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

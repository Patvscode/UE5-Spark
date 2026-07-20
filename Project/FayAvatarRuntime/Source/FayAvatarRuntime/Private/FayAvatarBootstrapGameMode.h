#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "FayAvatarBootstrapGameMode.generated.h"

class UCameraComponent;
class UFayAvatarBridgeComponent;

/**
 * Asset-free ARM64 smoke scene for the DGX Spark.
 *
 * The actor supplies a camera, owns the Fay bridge, and draws a simple
 * wireframe avatar with Unreal's debug line renderer. It proves the Vulkan
 * viewport and the live bridge without requiring cooked project content.
 */
UCLASS()
class FAYAVATARRUNTIME_API AFayAvatarBootstrapGameMode final : public AGameModeBase
{
    GENERATED_BODY()

public:
    AFayAvatarBootstrapGameMode();

    virtual void Tick(float DeltaSeconds) override;

private:
    void DrawSmokeScene() const;

    UPROPERTY(VisibleAnywhere, Category = "Spark Smoke Test")
    TObjectPtr<UCameraComponent> Camera;

    UPROPERTY(VisibleAnywhere, Category = "Spark Smoke Test")
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    bool bViewClaimed = false;
};

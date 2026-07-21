#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "FayAvatarBootstrapGameMode.generated.h"

class UCameraComponent;
class AActor;
class UFayAvatarBridgeComponent;
class UFayArdyPoseClientComponent;
class UFayBodyMotionComponent;
class UFayMetaHumanSpeechDriverComponent;
class UPointLightComponent;
class USkeletalMeshComponent;

/**
 * ARM64 MetaHuman scene with an asset-free diagnostic fallback for DGX Spark.
 *
 * The actor supplies a camera, owns the Fay bridge and learned speech driver,
 * and spawns the locally assembled Ada MetaHuman when that licensed content is
 * available. A wireframe avatar keeps the Vulkan and bridge tests useful before
 * MetaHuman content is generated or whenever loading fails.
 */
UCLASS()
class FAYAVATARRUNTIME_API AFayAvatarBootstrapGameMode final : public AGameModeBase
{
    GENERATED_BODY()

public:
    AFayAvatarBootstrapGameMode();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

private:
    void DrawSmokeScene() const;
    bool LoadCharacterProfile();
    void TrySpawnMetaHuman();
    void ResolveFaceAndJawMorph();
    void DriveJawFallback() const;

    UPROPERTY(VisibleAnywhere, Category = "Spark Smoke Test")
    TObjectPtr<UCameraComponent> Camera;

    UPROPERTY(VisibleAnywhere, Category = "Spark Smoke Test")
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman|Body Motion")
    TObjectPtr<UFayArdyPoseClientComponent> ArdyPoseClient;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman|Body Motion")
    TObjectPtr<UFayBodyMotionComponent> BodyMotion;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman")
    TObjectPtr<UFayMetaHumanSpeechDriverComponent> SpeechDriver;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman|Lighting")
    TObjectPtr<UPointLightComponent> KeyLight;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman|Lighting")
    TObjectPtr<UPointLightComponent> FillLight;

    UPROPERTY(VisibleAnywhere, Category = "MetaHuman|Lighting")
    TObjectPtr<UPointLightComponent> RimLight;

    UPROPERTY(EditDefaultsOnly, Category = "MetaHuman")
    TSoftClassPtr<AActor> MetaHumanClass;

    UPROPERTY(Transient)
    TObjectPtr<AActor> MetaHumanActor;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMeshComponent> FaceMesh;

    FName JawMorphTarget = NAME_None;
    FName FaceComponentName = TEXT("Face");
    FName BodyComponentName = TEXT("Body");
    FString ActiveCharacterId = TEXT("Ada");
    FString CharacterAdapter = TEXT("UE58MetaHuman");
    FVector CharacterSpawnLocation = FVector::ZeroVector;
    FRotator CharacterSpawnRotation = FRotator(0.0f, 180.0f, 0.0f);

    bool bViewClaimed = false;
    bool bSceneOnlyDiagnostic = false;
    bool bCharacterProfileValid = false;
    bool bLiveLinkConfigurationRequested = false;
    bool bLiveLinkConfigured = false;
};

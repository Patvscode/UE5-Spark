#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayArkitSpeechDriverComponent.generated.h"

class AActor;
class USkeletalMesh;
class USkeletalMeshComponent;

/**
 * Drives only a reviewed set of Apple ARKit facial morph targets from Fay.
 *
 * ConfigureAvatar requires one exact named skeletal-mesh component and the
 * complete reviewed morph contract. Runtime messages never select a mesh,
 * morph, asset, bone, or component. This adapter deliberately has no body,
 * head, neck, Control Rig, animation-blueprint, or transform write path.
 */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYARKITRUNTIME_API UFayArkitSpeechDriverComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayArkitSpeechDriverComponent();

    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

    /** Subscribe only to the already-validated events published by FayAvatarBridge. */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARKit")
    void AttachBridge(UFayAvatarBridgeComponent* InBridge);

    /**
     * Configure one exact skeletal face component on InAvatar.
     *
     * The component is accepted only when it exposes the complete, exact
     * sealed Apple/Unreal ARKit morph allowlist used by this adapter.
     * An invalid candidate is never mutated.
     */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARKit")
    bool ConfigureAvatar(AActor* InAvatar, FName FaceComponentName);

    /** Publish neutral values to the reviewed face, then forget it. */
    UFUNCTION(BlueprintCallable, Category = "Fay|ARKit")
    void ClearAvatar();

    /** True only while the exact reviewed actor, component, and mesh remain installed. */
    UFUNCTION(BlueprintPure, Category = "Fay|ARKit")
    bool IsConfigured() const;

    /** Exponential response speed for speech and expression curves. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "1.0", ClampMax = "60.0"))
    float MorphSmoothingSpeed = 24.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "0.0", ClampMax = "1.0"))
    float JawOpenScale = 0.88f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "0.0", ClampMax = "0.25"))
    float MouthCloseScale = 0.08f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "0.0", ClampMax = "0.25"))
    float MouthFunnelScale = 0.10f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "0.0", ClampMax = "0.25"))
    float MouthPuckerScale = 0.06f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Tuning",
        meta = (ClampMin = "0.0", ClampMax = "0.35"))
    float PositiveSmileScale = 0.18f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Blink")
    bool bEnableProceduralBlink = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Blink",
        meta = (ClampMin = "1.0", ClampMax = "30.0"))
    float MinimumBlinkIntervalSeconds = 2.6f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Blink",
        meta = (ClampMin = "1.0", ClampMax = "30.0"))
    float MaximumBlinkIntervalSeconds = 5.4f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Blink",
        meta = (ClampMin = "0.08", ClampMax = "0.5"))
    float BlinkDurationSeconds = 0.16f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|ARKit|Blink",
        meta = (ClampMin = "0.0", ClampMax = "1.0"))
    float BlinkStrength = 0.92f;

private:
    UFUNCTION()
    void HandleAvatarMessage(const FFayAvatarMessage& Message);

    UFUNCTION()
    void HandleSpeechStarted(const FFayAvatarMessage& Message, float DurationSeconds);

    UFUNCTION()
    void HandleSpeechFinished(const FFayAvatarMessage& Message);

    UFUNCTION()
    void HandleMouthAmplitude(float Amplitude);

    void ResetRuntimeState();
    void ResetDrivenMorphs(USkeletalMeshComponent* InFaceMesh) const;
    void ApplyDrivenMorphs();
    void InvalidateConfiguration(const TCHAR* Reason);
    void ScheduleNextBlink();
    float UpdateBlink(float DeltaTime);
    static float SmoothCurve(float Current, float Target, float Speed, float DeltaTime);

    UPROPERTY(Transient)
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMeshComponent> FaceMesh;

    /** Exact mesh asset accepted during ConfigureAvatar; any runtime swap invalidates the adapter. */
    UPROPERTY(Transient)
    TObjectPtr<USkeletalMesh> ReviewedSkeletalMeshAsset;

    FName ReviewedFaceComponentName = NAME_None;
    FName ResolvedJawOpenMorph = NAME_None;
    FName ResolvedMouthCloseMorph = NAME_None;
    FName ResolvedMouthFunnelMorph = NAME_None;
    FName ResolvedMouthPuckerMorph = NAME_None;
    FName ResolvedMouthSmileLeftMorph = NAME_None;
    FName ResolvedMouthSmileRightMorph = NAME_None;
    FName ResolvedEyeBlinkLeftMorph = NAME_None;
    FName ResolvedEyeBlinkRightMorph = NAME_None;
    FRandomStream BlinkRandomStream;
    float TargetMouthAmplitude = 0.0f;
    float TargetSmile = 0.0f;
    float SmileHoldRemainingSeconds = 0.0f;
    float SpeechArticulationPhase = 0.0f;
    float SecondsUntilNextBlink = 0.0f;
    float BlinkElapsedSeconds = -1.0f;
    float CurrentJawOpen = 0.0f;
    float CurrentMouthClose = 0.0f;
    float CurrentMouthFunnel = 0.0f;
    float CurrentMouthPucker = 0.0f;
    float CurrentMouthSmile = 0.0f;
    float CurrentBlink = 0.0f;
    bool bSpeechActive = false;
};

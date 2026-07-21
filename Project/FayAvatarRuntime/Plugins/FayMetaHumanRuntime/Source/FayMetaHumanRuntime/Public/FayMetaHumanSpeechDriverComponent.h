#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayAvatarBridgeComponent.h"
#include "FayMetaHumanSpeechDriverComponent.generated.h"

class AActor;
class UNNEModelData;
struct FFayMetaHumanSpeechRuntimeState;

/**
 * Converts Fay's decoded speech into UE 5.8 MetaHuman facial controls.
 *
 * The component runs Epic's local StreamingADA model with the ARM64-capable
 * ONNX Runtime CPU backend and publishes the resulting raw controls as a local
 * Live Link Basic subject. No microphone, cloud solve, or paid plugin is used.
 */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYMETAHUMANRUNTIME_API UFayMetaHumanSpeechDriverComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayMetaHumanSpeechDriverComponent();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

    /** Attach the already-configured Fay bridge that owns speech playback. */
    void AttachBridge(UFayAvatarBridgeComponent* InBridge);

    /**
     * Select this component's Live Link subject on an assembled MetaHuman.
     * Returns false when the expected UE 5.8 runtime members are unavailable.
     */
    bool ConfigureAvatar(AActor* InAvatar);

    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    bool IsSolverReady() const;

    /** True only after this component's exact Live Link source is driving the avatar. */
    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    bool IsAvatarConfigured() const;

    /** True while Live Link is processing the source needed for a requested avatar. */
    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    bool IsAvatarConfigurationPending() const;

    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    FName GetLiveLinkSubjectName() const { return LiveLinkSubjectName; }

    /** Name assigned to the local Live Link Basic subject. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|MetaHuman")
    FName LiveLinkSubjectName = TEXT("FayAudio");

    /** Model lookahead in milliseconds; UE 5.8 accepts 80 through 240. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman",
        meta = (ClampMin = "80", ClampMax = "240"))
    int32 LookaheadMilliseconds = 80;

    /** Normal synchronous 20 ms model-step budget for one game tick. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman",
        meta = (ClampMin = "1", ClampMax = "4"))
    int32 MaximumSolveStepsPerTick = 2;

    /**
     * Bounded catch-up budget used only when the 50 Hz solver falls behind.
     * Four steps sustain real time down to 12.5 game frames per second without
     * making every ordinary frame pay that cost.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay,
        meta = (ClampMin = "2", ClampMax = "8"))
    int32 MaximumCatchUpSolveStepsPerTick = 4;

    /**
     * Reset StreamingADA's internal history before each independent utterance.
     * The packaged runtime accepts -FayResetSpeechCache=0 or 1 so repeated-use
     * memory behavior can be compared without rebuilding the licensed package.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay)
    bool bResetSolverCacheBetweenUtterances = true;

    /**
     * Diagnostic fallback for SDK versions whose ClearCache implementation
     * retains per-utterance arenas. Enable with -FayRecreateSpeechSolver=1;
     * it is mutually exclusive with the lighter cache-reset path.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay)
    bool bRecreateSolverBetweenUtterances = false;

    /**
     * Return per-utterance allocator pools after the facial solve completes.
     * This is independent of solver reset policy and is controllable with
     * -FayTrimSpeechMemory=0 or 1 for bounded rendered-runtime diagnostics.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay)
    bool bTrimMemoryAfterUtterance = true;

    /** Publish the configured neutral Live Link frame at 10 Hz while idle. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay)
    bool bEnableIdleNeutralHeartbeat = true;

    /**
     * Seconds between full configured-consumer health audits. Zero preserves
     * the strict every-frame behavior; -FayLiveLinkHealthInterval overrides it.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman", AdvancedDisplay,
        meta = (ClampMin = "0.0", ClampMax = "60.0"))
    float LiveLinkHealthCheckIntervalSeconds = 0.0f;

    /** Convert supported Fay semantic actions into conservative head gestures. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman|Gestures")
    bool bEnableSemanticHeadGestures = true;

    /** Maximum head rotation used by semantic gestures, in degrees. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|MetaHuman|Gestures",
        meta = (ClampMin = "4.0", ClampMax = "12.0"))
    float MaximumHeadGestureDegrees = 10.0f;

private:
    void InitializeSolverAndSource();
    void ShutdownSource();
    void ResetSpeechState();
    bool TryConfigurePendingAvatar();
    bool ApplyAvatarConfiguration(AActor* InAvatar);
    bool RestoreConfiguredAvatar();
    bool SolveNextFrame();
    void HandleDecodedPcm(
        const FFayAvatarMessage& Message,
        const TArray<uint8>& Pcm16,
        int32 SampleRate,
        int32 NumChannels);

    UFUNCTION()
    void HandleAvatarMessage(const FFayAvatarMessage& Message);

    UFUNCTION()
    void HandleSpeechStarted(const FFayAvatarMessage& Message, float DurationSeconds);

    UFUNCTION()
    void HandleSpeechFinished(const FFayAvatarMessage& Message);

    UPROPERTY(Transient)
    TObjectPtr<UFayAvatarBridgeComponent> Bridge;

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    UPROPERTY(Transient)
    TObjectPtr<AActor> PendingAvatar;

    UPROPERTY(Transient)
    TObjectPtr<UNNEModelData> SpeechModel;

    TSharedPtr<FFayMetaHumanSpeechRuntimeState> RuntimeState;
    TArray<float> SpeechSamples;
    int32 SpeechSampleRate = 0;
    int32 SpeechNumChannels = 0;
    int32 SpeechFrameCursor = 0;
    int32 SpeechFramesPerStep = 0;
    int32 RemainingTailSteps = 0;
    int32 SolvedStepCount = 0;
    double AnimationElapsedSeconds = 0.0;
    TArray<float> SolveDurationsMilliseconds;
    float ExpectedSpeechDurationSeconds = 0.0f;
    float MoodIntensity = 1.0f;
    float HeadGestureStrength = 0.0f;
    float HeadGestureDurationSeconds = 0.0f;
    float ActionHeadGestureElapsedSeconds = 0.0f;
    float ActionHeadGestureStrength = 0.0f;
    float ActionHeadGestureDurationSeconds = 0.0f;
    float PendingMemoryTrimSeconds = -1.0f;
    uint8 MoodValue = 0;
    uint8 HeadGestureValue = 0;
    uint8 ActionHeadGestureValue = 0;
    FName OriginalActorLiveLinkSubject = NAME_None;

    UPROPERTY(Transient)
    TObjectPtr<UClass> OriginalBodyAnimClass;

    int32 OriginalBodyAnimationModeValue = 0;
    double LiveLinkHeartbeatElapsedSeconds = 0.0;
    double LiveLinkHealthCheckElapsedSeconds = 0.0;
    double LiveLinkPendingElapsedSeconds = 0.0;
    bool bOriginalUseLiveLink = false;
    bool bHasOriginalAvatarConfiguration = false;
    bool bLiveLinkPendingGraceLogged = false;
    bool bLiveLinkHealthPending = false;
    bool bPendingSubjectWaitLogged = false;
    bool bTerminalSubjectFailureLogged = false;
    bool bFirstSolverFrame = true;
    bool bSpeechPrepared = false;
    bool bSpeechStarted = false;
    bool bSpeechFinished = false;
    bool bActionHeadGestureActive = false;
};

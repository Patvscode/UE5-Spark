#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayBodyMotionTypes.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "FayArdyPoseClientComponent.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayArdyReadyEvent, bool, bReady);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayArdyBufferEvent, int32, BufferedFrames);

/** Strict loopback client and eight-frame playback buffer for ARDY Core27 poses. */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYBODYMOTION_API UFayArdyPoseClientComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayArdyPoseClientComponent();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

    bool StartBehavior(FName Behavior, float Intensity, float DurationSeconds);
    void StopBehavior();
    bool SamplePose(float DeltaSeconds, FFayArdyPoseFrame& OutPose);

    UFUNCTION(BlueprintPure, Category = "Fay|ARDY")
    bool IsReady() const { return bServiceReady; }

    UFUNCTION(BlueprintPure, Category = "Fay|ARDY")
    int32 GetBufferedFrameCount() const { return PoseBuffer.Num(); }

    UPROPERTY(BlueprintAssignable, Category = "Fay|ARDY")
    FFayArdyReadyEvent OnReadyChanged;

    UPROPERTY(BlueprintAssignable, Category = "Fay|ARDY")
    FFayArdyBufferEvent OnBufferUnderrun;

private:
    void ProbeHealth();
    void RequestPoseBatch();
    void RetireHealthRequest();
    void RetirePoseRequest();
    void HandleHealthResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bSucceeded);
    void HandlePoseResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bSucceeded);
    void SetReady(bool bReady);
    bool ParsePoseBatch(const FString& Json, FFayBodyPoseBatch& OutBatch, FString& OutError) const;
    bool IsEndpointSealed() const;

    FString BaseUrl = TEXT("http://127.0.0.1:8777");
    FName ActiveBehavior = TEXT("idle");
    TArray<FFayArdyPoseFrame> PoseBuffer;
    TSharedPtr<IHttpRequest, ESPMode::ThreadSafe> HealthRequest;
    TSharedPtr<IHttpRequest, ESPMode::ThreadSafe> PoseRequest;
    int64 LastSequence = 0;
    double PlaybackTimeSeconds = 0.0;
    double LastFrameTimeSeconds = -1.0;
    FVector3f LastRootTranslationMetres = FVector3f::ZeroVector;
    double HealthRetryElapsedSeconds = 0.0;
    float ActiveIntensity = 0.5f;
    float ActiveDurationSeconds = 1.0f;
    bool bClientEnabled = true;
    bool bAllowDiagnosticProvider = false;
    bool bServiceReady = false;
    bool bPlaybackStarted = false;
    bool bHasLastRootTranslation = false;
    bool bAllowActionTransitionGap = false;
};

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "TimerManager.h"
#include "FayAvatarBridgeComponent.generated.h"

class IHttpRequest;
class IWebSocket;
class UAudioComponent;
class USoundWaveProcedural;

UENUM(BlueprintType)
enum class EFayAvatarBridgeState : uint8
{
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error
};

USTRUCT(BlueprintType)
struct FAYAVATARBRIDGE_API FFayAvatarAction
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    bool bIsValid = false;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    FString Code;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    FString Behavior;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    FString Affect;

    /** Empty preserves the legacy hybrid route; otherwise baked or hybrid. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    FString Provider;

    /** Optional free-text body-motion condition forwarded unchanged to ARDY. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    FString Prompt;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    float Intensity = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    int32 Priority = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Action")
    float SentimentHint = 0.0f;
};

USTRUCT(BlueprintType)
struct FAYAVATARBRIDGE_API FFayAvatarViseme
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Lip Sync")
    FString Name;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Lip Sync")
    float DurationMilliseconds = 0.0f;
};

USTRUCT(BlueprintType)
struct FAYAVATARBRIDGE_API FFayAvatarMessage
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    FString Text;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    FString AudioUrl;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    FString ConversationId;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    int32 MessageNumber = INDEX_NONE;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    float DurationHintSeconds = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    float Sentiment = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    bool bIsFirst = false;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    bool bIsEnd = false;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    FFayAvatarAction Action;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Message")
    TArray<FFayAvatarViseme> Visemes;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayAvatarBridgeStateEvent, EFayAvatarBridgeState, State);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayAvatarMessageEvent, const FFayAvatarMessage&, Message);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FFayAvatarSpeechStartedEvent, const FFayAvatarMessage&, Message, float, DurationSeconds);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayAvatarSpeechFinishedEvent, const FFayAvatarMessage&, Message);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FFayAvatarMouthAmplitudeEvent, float, Amplitude);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FFayAvatarBridgeErrorEvent, const FString&, Stage, const FString&, Error);
DECLARE_MULTICAST_DELEGATE_FourParams(
    FFayAvatarDecodedPcmEvent,
    const FFayAvatarMessage&,
    const TArray<uint8>&,
    int32,
    int32);

/**
 * Attach this component to the actor that owns the avatar.
 *
 * It registers with Fay as a digital-human output, preserves audio message
 * order, downloads one WAV at a time, and plays PCM16 through a transient
 * USoundWaveProcedural. Blueprint events provide text, semantic actions,
 * optional Fay visemes, and a simple RMS mouth-amplitude fallback.
 */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYAVATARBRIDGE_API UFayAvatarBridgeComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayAvatarBridgeComponent();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    /** Fay's digital-human WebSocket endpoint; overridable with -FayWsUrl= or FAY_WS_URL. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection")
    FString WebSocketUrl = TEXT("ws://127.0.0.1:10002");

    /** Must match the user used to submit requests to Fay. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection")
    FString Username = TEXT("User");

    /** Fay registration flag that asks for digital-human output messages. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection")
    bool bRequestOutput = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection")
    bool bConnectOnBeginPlay = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection")
    bool bAutoReconnect = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection", meta = (ClampMin = "0.1"))
    float ReconnectInitialDelaySeconds = 1.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection", meta = (ClampMin = "0.1"))
    float ReconnectMaximumDelaySeconds = 15.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Connection", meta = (ClampMin = "1024", ClampMax = "8388608"))
    int32 MaximumJsonMessageBytes = 1024 * 1024;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", meta = (ClampMin = "1.0"))
    float HttpTimeoutSeconds = 20.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", meta = (ClampMin = "1024", ClampMax = "268435456"))
    int32 MaximumAudioBytes = 32 * 1024 * 1024;

    /** Maximum number of waiting speech messages kept behind the active message. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", AdvancedDisplay,
        meta = (ClampMin = "1", ClampMax = "1024"))
    int32 MaximumPendingAudioMessages = 64;

    /** Maximum number of conversation/message identifiers retained for duplicate suppression. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", AdvancedDisplay,
        meta = (ClampMin = "16", ClampMax = "65536"))
    int32 MaximumRememberedMessageKeys = 2048;

    /**
     * Exact trusted origin and path prefix for Fay-generated WAV files.
     * Audio messages must resolve to one simple .wav filename below this URL;
     * userinfo, query strings, fragments, escapes, and nested paths are rejected.
     * Overridable with -FayAudioBaseUrl= or FAY_AUDIO_BASE_URL.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio")
    FString AudioBaseUrl = TEXT("http://127.0.0.1:5000/audio/");

    /** Extra drain time after Unreal consumes the procedural PCM queue. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", AdvancedDisplay, meta = (ClampMin = "0.0", ClampMax = "0.5"))
    float PlaybackTailSeconds = 0.06f;

    /** Fallback grace period if Unreal never delivers OnAudioFinished. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Audio", AdvancedDisplay, meta = (ClampMin = "0.1", ClampMax = "30.0"))
    float PlaybackWatchdogGraceSeconds = 2.0f;

    /** Gain applied to the simple RMS jaw-open fallback. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Fay|Lip Sync", meta = (ClampMin = "0.0", ClampMax = "10.0"))
    float MouthAmplitudeGain = 3.0f;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarBridgeStateEvent OnConnectionStateChanged;

    /**
     * Broadcast synchronously; audio accepted for playback enters the queue
     * before this event is delivered.
     */
    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarMessageEvent OnMessageReceived;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarSpeechStartedEvent OnSpeechStarted;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarSpeechFinishedEvent OnSpeechFinished;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarMouthAmplitudeEvent OnMouthAmplitude;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Events")
    FFayAvatarBridgeErrorEvent OnBridgeError;

    /**
     * Native-only access to the trusted PCM16 payload immediately before
     * playback. Receivers must copy any data they retain after the callback.
     */
    FFayAvatarDecodedPcmEvent OnDecodedPcm;

    UFUNCTION(BlueprintCallable, Category = "Fay|Connection")
    void Connect();

    UFUNCTION(BlueprintCallable, Category = "Fay|Connection")
    void Disconnect();

    UFUNCTION(BlueprintPure, Category = "Fay|Connection")
    bool IsConnected() const;

    UFUNCTION(BlueprintPure, Category = "Fay|Connection")
    EFayAvatarBridgeState GetConnectionState() const { return ConnectionState; }

    UFUNCTION(BlueprintCallable, Category = "Fay|Audio")
    void CancelSpeech();

    UFUNCTION(BlueprintPure, Category = "Fay|Lip Sync")
    float GetMouthAmplitude() const { return MouthAmplitude; }

    UFUNCTION(BlueprintPure, Category = "Fay|Audio")
    float GetSpeechPlaybackSeconds() const;

    UFUNCTION(BlueprintPure, Category = "Fay|Audio")
    bool IsSpeechPlaying() const { return bSpeechPlaying; }

    /**
     * True from the moment accepted audio is queued until its download,
     * decode, and playback work has completely drained.
     */
    UFUNCTION(BlueprintPure, Category = "Fay|Audio")
    bool HasPendingSpeechWork() const;

private:
    void ApplyRuntimeEndpointOverrides();
    bool ValidateRuntimeEndpoints(FString& OutError);
    void SetConnectionState(EFayAvatarBridgeState NewState);
    void ReleaseSocket(bool bSendClose = true);
    void HandleSocketConnected(uint64 Generation);
    void HandleSocketError(uint64 Generation, const FString& Error);
    void HandleSocketClosed(uint64 Generation, int32 StatusCode, const FString& Reason, bool bWasClean);
    void HandleSocketMessage(uint64 Generation, const FString& JsonMessage);
    void SendRegistration();
    void ScheduleReconnect();
    void CancelReconnect();

    bool ParseAvatarMessage(const FString& JsonMessage, FFayAvatarMessage& OutMessage, FString& OutError) const;
    void AcceptAvatarMessage(FFayAvatarMessage&& Message);
    bool TryRememberMessageKey(const FString& MessageKey);
    void StartNextAudio();
    void StartAudioDownload(const FString& Url);
    void HandleAudioDownloadResult(uint64 Generation, bool bTransportSucceeded, int32 ResponseCode,
        const FString& RequestedUrl, const FString& EffectiveUrl, TArray<uint8>&& Content,
        bool bExceededSizeLimit, const FString& FailureReason);
    void FailCurrentAudio(const FString& Stage, const FString& Error);
    bool IsAudioUrlAllowed(const FString& Url) const;

    void EnsureAudioComponent();
    void RecreateAudioComponentAfterPlaybackFailure();
    void HandleAudioFinished(UAudioComponent* FinishedComponent);
    void StartProceduralPlayback(TArray<uint8>&& Pcm16, int32 SampleRate, int32 NumChannels, float DurationSeconds);
    void FinishCurrentPlayback(bool bCompletedNormally);
    void CancelAudioRequest();
    void ResetMouthAmplitude();
    void UpdateMouthAmplitude(float DeltaTime);
    void ReportError(const FString& Stage, const FString& Error);

    UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Fay|Connection", meta = (AllowPrivateAccess = "true"))
    EFayAvatarBridgeState ConnectionState = EFayAvatarBridgeState::Disconnected;

    UPROPERTY(Transient)
    TObjectPtr<UAudioComponent> VoiceAudioComponent;

    UPROPERTY(Transient)
    TObjectPtr<USoundWaveProcedural> CurrentSoundWave;

    TSharedPtr<IWebSocket> Socket;
    TSharedPtr<IHttpRequest, ESPMode::ThreadSafe> ActiveHttpRequest;
    FTimerHandle ReconnectTimerHandle;
    TArray<FFayAvatarMessage> PendingAudioMessages;
    TSet<FString> SeenMessageKeys;
    TArray<FString> SeenMessageKeyOrder;
    FFayAvatarMessage CurrentMessage;
    TArray<uint8> CurrentPcm16;
    FString ActiveConversationId;
    uint64 SocketGeneration = 0;
    uint64 HttpGeneration = 0;
    uint64 SpeechGeneration = 0;
    int32 ReconnectAttempt = 0;
    int32 CurrentSampleRate = 0;
    int32 CurrentNumChannels = 0;
    double PlaybackStartedAtSeconds = 0.0;
    float CurrentDurationSeconds = 0.0f;
    float PlaybackWatchdogElapsedSeconds = 0.0f;
    float PlaybackDrainTailElapsedSeconds = 0.0f;
    float PlaybackStopWaitSeconds = 0.0f;
    float MouthAmplitude = 0.0f;
    bool bHasCurrentMessage = false;
    bool bSpeechPlaying = false;
    bool bPlaybackStopRequested = false;
    bool bPendingQueueOverflowReported = false;
    bool bRuntimeEndpointOverridesApplied = false;
    bool bManualDisconnect = false;
    bool bEndingPlay = false;
};

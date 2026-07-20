#include "FayAvatarBridgeComponent.h"

#include "FayAvatarBridge.h"
#include "FayWavDecoder.h"

#include "Async/Async.h"
#include "Components/AudioComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/PlatformMisc.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/ScopeLock.h"
#include "IWebSocket.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Sound/SoundWaveProcedural.h"
#include "WebSocketsModule.h"

namespace
{
constexpr int32 HardMaximumPendingAudioMessages = 1024;
constexpr int32 HardMaximumRememberedMessageKeys = 65536;
constexpr int32 ProceduralSafetySilenceSamples = DEFAULT_PROCEDURAL_SOUNDWAVE_BUFFER_SIZE;
constexpr int32 MaximumTrustedUrlCharacters = 2048;
constexpr int32 MaximumWaveFilenameCharacters = 255;

enum class EFayEndpointSource : uint8
{
    Component,
    Environment,
    CommandLine
};

const TCHAR* EndpointSourceName(const EFayEndpointSource Source)
{
    switch (Source)
    {
    case EFayEndpointSource::Environment:
        return TEXT("environment");
    case EFayEndpointSource::CommandLine:
        return TEXT("command-line");
    case EFayEndpointSource::Component:
    default:
        return TEXT("component");
    }
}

EFayEndpointSource ResolveEndpointValue(
    const TCHAR* CommandLineKey,
    const TCHAR* EnvironmentVariable,
    const FString& ComponentValue,
    FString& OutValue)
{
    FString CommandLineValue;
    if (FParse::Value(FCommandLine::Get(), CommandLineKey, CommandLineValue))
    {
        OutValue = MoveTemp(CommandLineValue);
        return EFayEndpointSource::CommandLine;
    }

    FString EnvironmentValue = FPlatformMisc::GetEnvironmentVariable(EnvironmentVariable);
    if (!EnvironmentValue.IsEmpty())
    {
        OutValue = MoveTemp(EnvironmentValue);
        return EFayEndpointSource::Environment;
    }

    OutValue = ComponentValue;
    return EFayEndpointSource::Component;
}

struct FStrictUrl
{
    FString Scheme;
    FString Host;
    FString Path;
    int32 Port = 0;
};

bool TryParsePort(const FStringView Text, int32& OutPort)
{
    if (Text.IsEmpty() || Text.Len() > 5)
    {
        return false;
    }

    int32 Port = 0;
    for (const TCHAR Character : Text)
    {
        if (Character < TEXT('0') || Character > TEXT('9'))
        {
            return false;
        }

        Port = Port * 10 + (Character - TEXT('0'));
    }

    if (Port < 1 || Port > 65535)
    {
        return false;
    }

    OutPort = Port;
    return true;
}

bool TryParseStrictUrl(const FString& Url, const bool bAllowHttp, const bool bAllowWebSocket, FStrictUrl& OutUrl)
{
    OutUrl = FStrictUrl();
    if (Url.IsEmpty() || Url.Len() > MaximumTrustedUrlCharacters ||
        Url != Url.TrimStartAndEnd() || Url.Contains(TEXT("\\")))
    {
        return false;
    }
    for (const TCHAR Character : Url)
    {
        if (Character <= 0x20 || Character == 0x7f)
        {
            return false;
        }
    }

    int32 SchemeSeparator = INDEX_NONE;
    if (!Url.FindChar(TEXT(':'), SchemeSeparator) || SchemeSeparator <= 0 ||
        Url.Mid(SchemeSeparator, 3) != TEXT("://"))
    {
        return false;
    }

    OutUrl.Scheme = Url.Left(SchemeSeparator).ToLower();
    const bool bHttpScheme = bAllowHttp &&
        (OutUrl.Scheme == TEXT("http") || OutUrl.Scheme == TEXT("https"));
    const bool bWebSocketScheme = bAllowWebSocket &&
        (OutUrl.Scheme == TEXT("ws") || OutUrl.Scheme == TEXT("wss"));
    if (!bHttpScheme && !bWebSocketScheme)
    {
        return false;
    }

    const int32 AuthorityStart = SchemeSeparator + 3;
    int32 PathStart = Url.Len();
    for (int32 Index = AuthorityStart; Index < Url.Len(); ++Index)
    {
        const TCHAR Character = Url[Index];
        if (Character == TEXT('/') || Character == TEXT('?') || Character == TEXT('#'))
        {
            PathStart = Index;
            break;
        }
    }

    const FString Authority = Url.Mid(AuthorityStart, PathStart - AuthorityStart);
    if (Authority.IsEmpty() || Authority.Contains(TEXT("@")) || Authority.Contains(TEXT("%")))
    {
        return false;
    }

    FString PortText;
    bool bHasExplicitPort = false;
    if (Authority.StartsWith(TEXT("[")))
    {
        int32 ClosingBracket = INDEX_NONE;
        if (!Authority.FindChar(TEXT(']'), ClosingBracket) || ClosingBracket <= 1)
        {
            return false;
        }

        OutUrl.Host = Authority.Mid(1, ClosingBracket - 1).ToLower();
        if (!OutUrl.Host.Contains(TEXT(":")))
        {
            return false;
        }
        for (const TCHAR Character : OutUrl.Host)
        {
            const bool bValidIpv6Character =
                (Character >= TEXT('0') && Character <= TEXT('9')) ||
                (Character >= TEXT('a') && Character <= TEXT('f')) ||
                Character == TEXT(':') || Character == TEXT('.');
            if (!bValidIpv6Character)
            {
                return false;
            }
        }

        const FString Remainder = Authority.Mid(ClosingBracket + 1);
        if (!Remainder.IsEmpty())
        {
            if (!Remainder.StartsWith(TEXT(":")) || Remainder.Len() == 1)
            {
                return false;
            }
            PortText = Remainder.Mid(1);
            bHasExplicitPort = true;
        }
    }
    else
    {
        int32 Colon = INDEX_NONE;
        if (Authority.FindLastChar(TEXT(':'), Colon))
        {
            if (Authority.Left(Colon).Contains(TEXT(":")))
            {
                return false;
            }
            OutUrl.Host = Authority.Left(Colon).ToLower();
            PortText = Authority.Mid(Colon + 1);
            bHasExplicitPort = true;
        }
        else
        {
            OutUrl.Host = Authority.ToLower();
        }

        if (OutUrl.Host.IsEmpty())
        {
            return false;
        }
        for (const TCHAR Character : OutUrl.Host)
        {
            const bool bValidHostCharacter = Character <= 127 &&
                ((Character >= TEXT('a') && Character <= TEXT('z')) ||
                 (Character >= TEXT('0') && Character <= TEXT('9')) ||
                 Character == TEXT('.') || Character == TEXT('-'));
            if (!bValidHostCharacter)
            {
                return false;
            }
        }
    }

    if (bHasExplicitPort)
    {
        if (!TryParsePort(PortText, OutUrl.Port))
        {
            return false;
        }
    }
    else
    {
        OutUrl.Port = (OutUrl.Scheme == TEXT("https") || OutUrl.Scheme == TEXT("wss")) ? 443 : 80;
    }

    OutUrl.Path = PathStart < Url.Len() ? Url.Mid(PathStart) : TEXT("/");
    if (!OutUrl.Path.StartsWith(TEXT("/")) || OutUrl.Path.Contains(TEXT("?")) ||
        OutUrl.Path.Contains(TEXT("#")) || OutUrl.Path.Contains(TEXT("%")))
    {
        return false;
    }

    return true;
}

bool IsSimpleWaveFilename(const FStringView Filename)
{
    if (Filename.IsEmpty() || Filename.Len() > MaximumWaveFilenameCharacters ||
        !Filename.EndsWith(TEXT(".wav"), ESearchCase::IgnoreCase))
    {
        return false;
    }

    for (const TCHAR Character : Filename)
    {
        const bool bAllowed = Character <= 127 &&
            ((Character >= TEXT('a') && Character <= TEXT('z')) ||
             (Character >= TEXT('A') && Character <= TEXT('Z')) ||
             (Character >= TEXT('0') && Character <= TEXT('9')) ||
             Character == TEXT('_') || Character == TEXT('-') || Character == TEXT('.'));
        if (!bAllowed)
        {
            return false;
        }
    }

    return !Filename.Contains(TEXT(".."));
}

struct FBoundedAudioDownload
{
    explicit FBoundedAudioDownload(const int32 InMaximumBytes)
        : MaximumBytes(FMath::Max(InMaximumBytes, 1024))
    {
        Bytes.Reserve(FMath::Min(MaximumBytes, 256 * 1024));
    }

    bool Append(const void* Data, const int64 Length)
    {
        FScopeLock Lock(&CriticalSection);
        if (Length < 0 || Length > MaximumBytes - static_cast<int64>(Bytes.Num()))
        {
            bExceededSizeLimit = true;
            return false;
        }

        Bytes.Append(static_cast<const uint8*>(Data), static_cast<int32>(Length));
        return true;
    }

    void RejectDeclaredSize()
    {
        FScopeLock Lock(&CriticalSection);
        bExceededSizeLimit = true;
    }

    void TakeResult(TArray<uint8>& OutBytes, bool& bOutExceededSizeLimit)
    {
        FScopeLock Lock(&CriticalSection);
        OutBytes = MoveTemp(Bytes);
        bOutExceededSizeLimit = bExceededSizeLimit;
    }

private:
    FCriticalSection CriticalSection;
    TArray<uint8> Bytes;
    int64 MaximumBytes = 0;
    bool bExceededSizeLimit = false;
};

bool TryGetFlexibleBool(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, bool& OutValue)
{
    if (Object->TryGetBoolField(FieldName, OutValue))
    {
        return true;
    }

    int32 NumericValue = 0;
    if (Object->TryGetNumberField(FieldName, NumericValue))
    {
        OutValue = NumericValue != 0;
        return true;
    }

    return false;
}

FString MakeMessageKey(const FFayAvatarMessage& Message)
{
    if (Message.ConversationId.IsEmpty() || Message.MessageNumber == INDEX_NONE)
    {
        return FString();
    }

    return FString::Printf(TEXT("%s:%d"), *Message.ConversationId, Message.MessageNumber);
}
}

UFayAvatarBridgeComponent::UFayAvatarBridgeComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UFayAvatarBridgeComponent::BeginPlay()
{
    Super::BeginPlay();
    bEndingPlay = false;
    ApplyRuntimeEndpointOverrides();
    EnsureAudioComponent();

    if (bConnectOnBeginPlay)
    {
        Connect();
    }
}

void UFayAvatarBridgeComponent::ApplyRuntimeEndpointOverrides()
{
    if (bRuntimeEndpointOverridesApplied)
    {
        return;
    }

    bRuntimeEndpointOverridesApplied = true;
    FString ResolvedWebSocketUrl;
    const EFayEndpointSource WebSocketSource = ResolveEndpointValue(
        TEXT("FayWsUrl="),
        TEXT("FAY_WS_URL"),
        WebSocketUrl,
        ResolvedWebSocketUrl);

    FString ResolvedAudioBaseUrl;
    const EFayEndpointSource AudioSource = ResolveEndpointValue(
        TEXT("FayAudioBaseUrl="),
        TEXT("FAY_AUDIO_BASE_URL"),
        AudioBaseUrl,
        ResolvedAudioBaseUrl);

    WebSocketUrl = MoveTemp(ResolvedWebSocketUrl);
    AudioBaseUrl = MoveTemp(ResolvedAudioBaseUrl);
    UE_LOG(LogFayAvatarBridge, Display,
        TEXT("Resolved Fay endpoints (WebSocket source=%s, audio source=%s)."),
        EndpointSourceName(WebSocketSource),
        EndpointSourceName(AudioSource));
}

bool UFayAvatarBridgeComponent::ValidateRuntimeEndpoints(FString& OutError)
{
    OutError.Reset();
    FStrictUrl ParsedWebSocketUrl;
    if (!TryParseStrictUrl(WebSocketUrl, false, true, ParsedWebSocketUrl))
    {
        OutError = TEXT("The resolved Fay WebSocket endpoint must be a strict ws:// or wss:// URL without userinfo, escapes, a query, or a fragment.");
        return false;
    }

    FString NormalizedAudioBaseUrl = AudioBaseUrl;
    if (!NormalizedAudioBaseUrl.EndsWith(TEXT("/")))
    {
        NormalizedAudioBaseUrl.AppendChar(TEXT('/'));
    }

    FStrictUrl ParsedAudioBaseUrl;
    if (!TryParseStrictUrl(NormalizedAudioBaseUrl, true, false, ParsedAudioBaseUrl) ||
        !ParsedAudioBaseUrl.Path.EndsWith(TEXT("/")))
    {
        OutError = TEXT("The resolved Fay audio base must be a strict http:// or https:// URL without userinfo, escapes, a query, or a fragment.");
        return false;
    }

    AudioBaseUrl = MoveTemp(NormalizedAudioBaseUrl);
    return true;
}

void UFayAvatarBridgeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    bEndingPlay = true;
    bManualDisconnect = true;
    CancelReconnect();

    if (VoiceAudioComponent)
    {
        VoiceAudioComponent->OnAudioFinishedNative.RemoveAll(this);
    }

    CancelSpeech();
    ReleaseSocket();
    SetConnectionState(EFayAvatarBridgeState::Disconnected);

    if (VoiceAudioComponent)
    {
        VoiceAudioComponent->DestroyComponent();
        VoiceAudioComponent = nullptr;
    }

    Super::EndPlay(EndPlayReason);
}

void UFayAvatarBridgeComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    if (!bSpeechPlaying)
    {
        return;
    }

    UpdateMouthAmplitude(DeltaTime);
    if (!bSpeechPlaying || bEndingPlay)
    {
        // Mouth-amplitude listeners may cancel speech or end play.
        return;
    }

    const float SafeDeltaTime = FMath::Max(DeltaTime, 0.0f);
    const float GraceSeconds = FMath::Max(PlaybackWatchdogGraceSeconds, 0.1f);

    if (!bPlaybackStopRequested)
    {
        PlaybackWatchdogElapsedSeconds += SafeDeltaTime;

        const bool bPcmQueueDrained = CurrentSoundWave &&
            CurrentSoundWave->GetAvailableAudioByteCount() <= 0;
        PlaybackDrainTailElapsedSeconds = bPcmQueueDrained
            ? PlaybackDrainTailElapsedSeconds + SafeDeltaTime
            : 0.0f;

        if (bPcmQueueDrained &&
            PlaybackDrainTailElapsedSeconds >= FMath::Max(PlaybackTailSeconds, 0.0f))
        {
            bPlaybackStopRequested = true;
            PlaybackStopWaitSeconds = 0.0f;
            if (VoiceAudioComponent)
            {
                // USoundWaveProcedural pads underruns with silence instead of
                // producing an end-of-stream signal. Once Unreal has consumed
                // the queued PCM and the drain tail, Stop produces the native
                // completion event used to advance the queue.
                VoiceAudioComponent->Stop();
            }
            return;
        }

        const float SafetySilenceSeconds = CurrentSampleRate > 0 && CurrentNumChannels > 0
            ? static_cast<float>(ProceduralSafetySilenceSamples) /
                static_cast<float>(CurrentSampleRate * CurrentNumChannels)
            : 0.0f;
        const float DrainDeadlineSeconds = CurrentDurationSeconds + SafetySilenceSeconds +
            FMath::Max(PlaybackTailSeconds, 0.0f) + GraceSeconds;
        if (PlaybackWatchdogElapsedSeconds >= DrainDeadlineSeconds)
        {
            const uint64 Generation = SpeechGeneration;
            FinishCurrentPlayback(false);
            if (!bEndingPlay && Generation == SpeechGeneration)
            {
                RecreateAudioComponentAfterPlaybackFailure();
                ReportError(TEXT("Audio"), FString::Printf(
                    TEXT("Procedural PCM did not drain within %.2f seconds; advancing the speech queue."),
                    DrainDeadlineSeconds));
            }
            StartNextAudio();
        }
        return;
    }

    PlaybackStopWaitSeconds += SafeDeltaTime;
    if (PlaybackStopWaitSeconds >= GraceSeconds)
    {
        const uint64 Generation = SpeechGeneration;
        FinishCurrentPlayback(false);
        if (!bEndingPlay && Generation == SpeechGeneration)
        {
            RecreateAudioComponentAfterPlaybackFailure();
            ReportError(TEXT("Audio"), FString::Printf(
                TEXT("Unreal did not report audio completion within %.2f seconds after Stop; advancing the speech queue."),
                GraceSeconds));
        }
        StartNextAudio();
    }
}

void UFayAvatarBridgeComponent::Connect()
{
    if (bEndingPlay)
    {
        return;
    }

    bManualDisconnect = false;
    CancelReconnect();

    ApplyRuntimeEndpointOverrides();
    if (Socket.IsValid() && Socket->IsConnected())
    {
        return;
    }

    FString EndpointError;
    if (!ValidateRuntimeEndpoints(EndpointError))
    {
        ReleaseSocket();
        SetConnectionState(EFayAvatarBridgeState::Error);
        ReportError(TEXT("Configuration"), EndpointError);
        return;
    }

    ReleaseSocket();

#if WITH_WEBSOCKETS
    const uint64 Generation = ++SocketGeneration;
    Socket = FWebSocketsModule::Get().CreateWebSocket(WebSocketUrl);
    Socket->SetTextMessageMemoryLimit(static_cast<uint64>(FMath::Max(MaximumJsonMessageBytes, 1024)));

    const TWeakObjectPtr<UFayAvatarBridgeComponent> WeakThis(this);
    Socket->OnConnected().AddLambda([WeakThis, Generation]()
    {
        AsyncTask(ENamedThreads::GameThread, [WeakThis, Generation]()
        {
            if (UFayAvatarBridgeComponent* Self = WeakThis.Get())
            {
                Self->HandleSocketConnected(Generation);
            }
        });
    });

    Socket->OnConnectionError().AddLambda([WeakThis, Generation](const FString& Error)
    {
        AsyncTask(ENamedThreads::GameThread, [WeakThis, Generation, Error]()
        {
            if (UFayAvatarBridgeComponent* Self = WeakThis.Get())
            {
                Self->HandleSocketError(Generation, Error);
            }
        });
    });

    Socket->OnClosed().AddLambda([WeakThis, Generation](const int32 StatusCode, const FString& Reason, const bool bWasClean)
    {
        AsyncTask(ENamedThreads::GameThread, [WeakThis, Generation, StatusCode, Reason, bWasClean]()
        {
            if (UFayAvatarBridgeComponent* Self = WeakThis.Get())
            {
                Self->HandleSocketClosed(Generation, StatusCode, Reason, bWasClean);
            }
        });
    });

    Socket->OnMessage().AddLambda([WeakThis, Generation](const FString& Message)
    {
        AsyncTask(ENamedThreads::GameThread, [WeakThis, Generation, Message]()
        {
            if (UFayAvatarBridgeComponent* Self = WeakThis.Get())
            {
                Self->HandleSocketMessage(Generation, Message);
            }
        });
    });

    // Start the fully-bound attempt before publishing state. There is no
    // internal work after the broadcast for a reentrant Disconnect or Connect
    // call to undo.
    Socket->Connect();
    SetConnectionState(ReconnectAttempt > 0
        ? EFayAvatarBridgeState::Reconnecting
        : EFayAvatarBridgeState::Connecting);
#else
    SetConnectionState(EFayAvatarBridgeState::Error);
    ReportError(TEXT("WebSocket"), TEXT("This Unreal target was built without WebSockets support."));
#endif
}

void UFayAvatarBridgeComponent::Disconnect()
{
    bManualDisconnect = true;
    ReconnectAttempt = 0;
    CancelReconnect();
    ReleaseSocket();
    SetConnectionState(EFayAvatarBridgeState::Disconnected);
}

bool UFayAvatarBridgeComponent::IsConnected() const
{
    return Socket.IsValid() && Socket->IsConnected();
}

void UFayAvatarBridgeComponent::CancelSpeech()
{
    ++SpeechGeneration;
    PendingAudioMessages.Reset();
    bPendingQueueOverflowReported = false;
    CancelAudioRequest();
    FinishCurrentPlayback(false);
}

float UFayAvatarBridgeComponent::GetSpeechPlaybackSeconds() const
{
    if (!bSpeechPlaying)
    {
        return 0.0f;
    }

    return static_cast<float>(FMath::Max(0.0, FPlatformTime::Seconds() - PlaybackStartedAtSeconds));
}

void UFayAvatarBridgeComponent::SetConnectionState(const EFayAvatarBridgeState NewState)
{
    if (ConnectionState == NewState)
    {
        return;
    }

    ConnectionState = NewState;
    OnConnectionStateChanged.Broadcast(ConnectionState);
}

void UFayAvatarBridgeComponent::ReleaseSocket(const bool bSendClose)
{
    ++SocketGeneration;
    if (!Socket.IsValid())
    {
        return;
    }

    TSharedPtr<IWebSocket> SocketToClose = MoveTemp(Socket);
    if (bSendClose)
    {
        // UE 5.8's libwebsockets implementation accepts Close while a
        // connection attempt is still pending. That prevents an abandoned
        // attempt from surviving after this component moves to a new socket.
        SocketToClose->Close(1000, TEXT("Fay avatar bridge shutdown"));
    }
}

void UFayAvatarBridgeComponent::HandleSocketConnected(const uint64 Generation)
{
    if (Generation != SocketGeneration || bManualDisconnect || bEndingPlay ||
        !Socket.IsValid() || !Socket->IsConnected())
    {
        return;
    }

    ReconnectAttempt = 0;
    SetConnectionState(EFayAvatarBridgeState::Connected);

    // State listeners are allowed to disconnect or replace the connection.
    if (Generation != SocketGeneration || bManualDisconnect || bEndingPlay ||
        !Socket.IsValid() || !Socket->IsConnected())
    {
        return;
    }

    UE_LOG(LogFayAvatarBridge, Display, TEXT("Connected to the Fay avatar WebSocket."));
    SendRegistration();
}

void UFayAvatarBridgeComponent::HandleSocketError(const uint64 Generation, const FString& Error)
{
    if (Generation != SocketGeneration)
    {
        return;
    }

    ReleaseSocket();
    const uint64 ReleasedGeneration = SocketGeneration;
    SetConnectionState(EFayAvatarBridgeState::Error);
    ReportError(TEXT("WebSocket"), Error);

    if (ReleasedGeneration == SocketGeneration && !Socket.IsValid())
    {
        ScheduleReconnect();
    }
}

void UFayAvatarBridgeComponent::HandleSocketClosed(
    const uint64 Generation,
    const int32 StatusCode,
    const FString& Reason,
    const bool bWasClean)
{
    if (Generation != SocketGeneration)
    {
        return;
    }

    ReleaseSocket(false);
    const uint64 ReleasedGeneration = SocketGeneration;
    SetConnectionState(EFayAvatarBridgeState::Disconnected);

    if (!bManualDisconnect && !bWasClean)
    {
        ReportError(TEXT("WebSocket"), FString::Printf(TEXT("Closed with code %d: %s"), StatusCode, *Reason));
    }

    if (ReleasedGeneration == SocketGeneration && !Socket.IsValid())
    {
        ScheduleReconnect();
    }
}

void UFayAvatarBridgeComponent::HandleSocketMessage(const uint64 Generation, const FString& JsonMessage)
{
    if (Generation != SocketGeneration)
    {
        return;
    }

    FFayAvatarMessage Message;
    FString Error;
    if (!ParseAvatarMessage(JsonMessage, Message, Error))
    {
        if (!Error.IsEmpty())
        {
            ReportError(TEXT("JSON"), Error);
        }
        return;
    }

    AcceptAvatarMessage(MoveTemp(Message));
}

void UFayAvatarBridgeComponent::SendRegistration()
{
    if (!Socket.IsValid() || !Socket->IsConnected())
    {
        return;
    }

    TSharedRef<FJsonObject> Registration = MakeShared<FJsonObject>();
    Registration->SetStringField(TEXT("Username"), Username.IsEmpty() ? TEXT("User") : Username);
    Registration->SetBoolField(TEXT("Output"), bRequestOutput);

    FString Payload;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Payload);
    if (!FJsonSerializer::Serialize(Registration, Writer))
    {
        ReportError(TEXT("JSON"), TEXT("Could not serialize Fay registration."));
        return;
    }

    Socket->Send(Payload);
    UE_LOG(LogFayAvatarBridge, Display,
        TEXT("Sent Fay avatar registration (output_requested=%s)."),
        bRequestOutput ? TEXT("true") : TEXT("false"));
}

void UFayAvatarBridgeComponent::ScheduleReconnect()
{
    if (!bAutoReconnect || bManualDisconnect || bEndingPlay || Socket.IsValid() || !GetWorld())
    {
        return;
    }

    const int32 Exponent = FMath::Min(ReconnectAttempt, 8);
    const float Delay = FMath::Min(
        FMath::Max(ReconnectInitialDelaySeconds, 0.1f) * FMath::Pow(2.0f, static_cast<float>(Exponent)),
        FMath::Max(ReconnectMaximumDelaySeconds, 0.1f));
    ++ReconnectAttempt;

    // Install the timer before notifying Blueprint. If a listener disconnects
    // or connects immediately, those operations can now cancel this timer.
    GetWorld()->GetTimerManager().SetTimer(ReconnectTimerHandle, this, &UFayAvatarBridgeComponent::Connect, Delay, false);
    SetConnectionState(EFayAvatarBridgeState::Reconnecting);
}

void UFayAvatarBridgeComponent::CancelReconnect()
{
    if (GetWorld())
    {
        GetWorld()->GetTimerManager().ClearTimer(ReconnectTimerHandle);
    }
}

bool UFayAvatarBridgeComponent::ParseAvatarMessage(
    const FString& JsonMessage,
    FFayAvatarMessage& OutMessage,
    FString& OutError) const
{
    OutMessage = FFayAvatarMessage();
    OutError.Reset();

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonMessage);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutError = FString::Printf(TEXT("Malformed Fay JSON: %s"), *Reader->GetErrorMessage());
        return false;
    }

    FString Topic;
    if (!Root->TryGetStringField(TEXT("Topic"), Topic) || Topic != TEXT("human"))
    {
        return false;
    }

    const TSharedPtr<FJsonObject>* DataPtr = nullptr;
    if (!Root->TryGetObjectField(TEXT("Data"), DataPtr) || DataPtr == nullptr || !DataPtr->IsValid())
    {
        OutError = TEXT("A Fay human message did not contain a Data object.");
        return false;
    }

    const TSharedPtr<FJsonObject>& Data = *DataPtr;
    FString Key;
    if (!Data->TryGetStringField(TEXT("Key"), Key) || Key != TEXT("audio"))
    {
        return false;
    }

    Data->TryGetStringField(TEXT("Text"), OutMessage.Text);
    Data->TryGetStringField(TEXT("HttpValue"), OutMessage.AudioUrl);
    Data->TryGetStringField(TEXT("CONV_ID"), OutMessage.ConversationId);
    Data->TryGetNumberField(TEXT("CONV_MSG_NO"), OutMessage.MessageNumber);
    Data->TryGetNumberField(TEXT("Time"), OutMessage.DurationHintSeconds);
    Data->TryGetNumberField(TEXT("Sentiment"), OutMessage.Sentiment);
    TryGetFlexibleBool(Data, TEXT("IsFirst"), OutMessage.bIsFirst);
    TryGetFlexibleBool(Data, TEXT("IsEnd"), OutMessage.bIsEnd);

    const TSharedPtr<FJsonObject>* ActionPtr = nullptr;
    if (Data->TryGetObjectField(TEXT("Action"), ActionPtr) && ActionPtr != nullptr && ActionPtr->IsValid())
    {
        const TSharedPtr<FJsonObject>& Action = *ActionPtr;
        OutMessage.Action.bIsValid = true;
        Action->TryGetStringField(TEXT("code"), OutMessage.Action.Code);
        Action->TryGetStringField(TEXT("behavior"), OutMessage.Action.Behavior);
        Action->TryGetStringField(TEXT("affect"), OutMessage.Action.Affect);
        Action->TryGetNumberField(TEXT("intensity"), OutMessage.Action.Intensity);
        Action->TryGetNumberField(TEXT("priority"), OutMessage.Action.Priority);
        Action->TryGetNumberField(TEXT("sentimentHint"), OutMessage.Action.SentimentHint);
    }

    const TArray<TSharedPtr<FJsonValue>>* Lips = nullptr;
    if (Data->TryGetArrayField(TEXT("Lips"), Lips) && Lips != nullptr)
    {
        for (const TSharedPtr<FJsonValue>& LipValue : *Lips)
        {
            if (!LipValue.IsValid())
            {
                continue;
            }

            const TSharedPtr<FJsonObject>* LipPtr = nullptr;
            if (!LipValue->TryGetObject(LipPtr) || LipPtr == nullptr || !LipPtr->IsValid())
            {
                continue;
            }

            FFayAvatarViseme Viseme;
            (*LipPtr)->TryGetStringField(TEXT("Lip"), Viseme.Name);
            (*LipPtr)->TryGetNumberField(TEXT("Time"), Viseme.DurationMilliseconds);
            if (!Viseme.Name.IsEmpty() && Viseme.DurationMilliseconds > 0.0f)
            {
                OutMessage.Visemes.Add(MoveTemp(Viseme));
            }
        }
    }

    return true;
}

void UFayAvatarBridgeComponent::AcceptAvatarMessage(FFayAvatarMessage&& Message)
{
    if (bEndingPlay)
    {
        return;
    }

    if (Message.bIsFirst && !Message.ConversationId.IsEmpty() && Message.ConversationId != ActiveConversationId)
    {
        PendingAudioMessages.Reset();
        SeenMessageKeys.Reset();
        SeenMessageKeyOrder.Reset();
        bPendingQueueOverflowReported = false;
        ActiveConversationId = Message.ConversationId;
        CancelAudioRequest();
        const uint64 ConversationGeneration = SpeechGeneration;
        FinishCurrentPlayback(false);

        // ResetMouthAmplitude may invoke Blueprint while cancelling the old
        // speech. Respect a reentrant CancelSpeech or EndPlay request.
        if (bEndingPlay || ConversationGeneration != SpeechGeneration ||
            ActiveConversationId != Message.ConversationId)
        {
            return;
        }
    }

    const FString MessageKey = MakeMessageKey(Message);
    if (!MessageKey.IsEmpty() && SeenMessageKeys.Contains(MessageKey))
    {
        return;
    }

    // A no-audio IsEnd message is a conversation marker, not something to fetch.
    const bool bHasAudio = !Message.AudioUrl.IsEmpty();
    const int32 PendingLimit = FMath::Clamp(MaximumPendingAudioMessages, 1, HardMaximumPendingAudioMessages);
    if (bHasAudio && PendingAudioMessages.Num() >= PendingLimit)
    {
        if (!bPendingQueueOverflowReported)
        {
            bPendingQueueOverflowReported = true;
            ReportError(TEXT("AudioQueue"), FString::Printf(
                TEXT("Pending speech queue reached its %d-message limit; dropping new audio until it drains."),
                PendingLimit));
        }

        if (!bEndingPlay)
        {
            OnMessageReceived.Broadcast(Message);
        }
        return;
    }

    if (!TryRememberMessageKey(MessageKey))
    {
        return;
    }

    if (bHasAudio)
    {
        bPendingQueueOverflowReported = false;
    }

    // Queue before publishing the event so a reentrant CancelSpeech call can
    // reliably remove this message. Keep Message as a stable delegate argument.
    if (bHasAudio)
    {
        PendingAudioMessages.Add(Message);
    }

    OnMessageReceived.Broadcast(Message);
    if (!bEndingPlay && bHasAudio)
    {
        StartNextAudio();
    }
}

bool UFayAvatarBridgeComponent::TryRememberMessageKey(const FString& MessageKey)
{
    if (MessageKey.IsEmpty())
    {
        return true;
    }

    if (SeenMessageKeys.Contains(MessageKey))
    {
        return false;
    }

    const int32 RememberedLimit = FMath::Clamp(MaximumRememberedMessageKeys, 16, HardMaximumRememberedMessageKeys);
    while (SeenMessageKeyOrder.Num() >= RememberedLimit)
    {
        SeenMessageKeys.Remove(SeenMessageKeyOrder[0]);
        SeenMessageKeyOrder.RemoveAt(0, 1, EAllowShrinking::No);
    }

    SeenMessageKeys.Add(MessageKey);
    SeenMessageKeyOrder.Add(MessageKey);
    return true;
}

void UFayAvatarBridgeComponent::StartNextAudio()
{
    if (bEndingPlay || bSpeechPlaying || bHasCurrentMessage || ActiveHttpRequest.IsValid())
    {
        return;
    }

    if (PendingAudioMessages.IsEmpty())
    {
        return;
    }

    CurrentMessage = MoveTemp(PendingAudioMessages[0]);
    PendingAudioMessages.RemoveAt(0, 1, EAllowShrinking::No);
    UE_LOG(LogFayAvatarBridge, Display,
        TEXT("Accepted a Fay avatar audio message (sequence=%d, first=%s, end=%s, action=%s, visemes=%d)."),
        CurrentMessage.MessageNumber,
        CurrentMessage.bIsFirst ? TEXT("true") : TEXT("false"),
        CurrentMessage.bIsEnd ? TEXT("true") : TEXT("false"),
        CurrentMessage.Action.bIsValid ? TEXT("true") : TEXT("false"),
        CurrentMessage.Visemes.Num());
    const int32 PendingLimit = FMath::Clamp(MaximumPendingAudioMessages, 1, HardMaximumPendingAudioMessages);
    if (PendingAudioMessages.Num() < PendingLimit)
    {
        bPendingQueueOverflowReported = false;
    }
    bHasCurrentMessage = true;
    StartAudioDownload(CurrentMessage.AudioUrl);
}

void UFayAvatarBridgeComponent::StartAudioDownload(const FString& Url)
{
    if (!IsAudioUrlAllowed(Url))
    {
        FailCurrentAudio(TEXT("HTTP"), TEXT("The audio URL is outside the configured trusted WAV route."));
        return;
    }

    const uint64 Generation = ++HttpGeneration;
    const int32 MaximumBytes = FMath::Max(MaximumAudioBytes, 1024);
    const TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
    const TSharedRef<FBoundedAudioDownload, ESPMode::ThreadSafe> Download =
        MakeShared<FBoundedAudioDownload, ESPMode::ThreadSafe>(MaximumBytes);
    ActiveHttpRequest = Request;
    Request->SetURL(Url);
    Request->SetVerb(TEXT("GET"));
    Request->SetTimeout(FMath::Max(HttpTimeoutSeconds, 1.0f));
    Request->SetActivityTimeout(FMath::Max(HttpTimeoutSeconds * 0.5f, 1.0f));
    Request->SetDelegateThreadPolicy(EHttpRequestDelegateThreadPolicy::CompleteOnHttpThread);

    FHttpRequestStreamDelegateV2 StreamDelegate;
    StreamDelegate.BindLambda([Download](void* Data, int64& Length)
    {
        if (!Download->Append(Data, Length))
        {
            Length = 0;
        }
    });
    if (!Request->SetResponseBodyReceiveStreamDelegateV2(MoveTemp(StreamDelegate)))
    {
        ActiveHttpRequest.Reset();
        FailCurrentAudio(TEXT("HTTP"), TEXT("The HTTP backend does not support bounded response streaming."));
        return;
    }

    const TWeakObjectPtr<UFayAvatarBridgeComponent> WeakThis(this);
    Request->OnProcessRequestComplete().BindLambda(
        [WeakThis, Generation, Download, RequestedUrl = Url](FHttpRequestPtr CompletedRequest, FHttpResponsePtr Response, const bool bSucceeded)
        {
            const int32 ResponseCode = Response.IsValid() ? Response->GetResponseCode() : 0;
            const FString EffectiveUrl = Response.IsValid() ? Response->GetEffectiveURL() : FString();
            const FString FailureReason = CompletedRequest.IsValid()
                ? FString(LexToString(CompletedRequest->GetFailureReason()))
                : TEXT("Unknown");
            TArray<uint8> Content;
            bool bExceededSizeLimit = false;
            Download->TakeResult(Content, bExceededSizeLimit);

            AsyncTask(ENamedThreads::GameThread,
                [WeakThis, Generation, bSucceeded, ResponseCode, RequestedUrl, EffectiveUrl,
                 Content = MoveTemp(Content), bExceededSizeLimit,
                 FailureReason]() mutable
            {
                if (UFayAvatarBridgeComponent* Self = WeakThis.Get())
                {
                    Self->HandleAudioDownloadResult(
                        Generation,
                        bSucceeded,
                        ResponseCode,
                        RequestedUrl,
                        EffectiveUrl,
                        MoveTemp(Content),
                        bExceededSizeLimit,
                        FailureReason);
                }
            });
        });

    Request->OnHeaderReceived().BindLambda(
        [Download, MaximumBytes](FHttpRequestPtr HeaderRequest, const FString& HeaderName, const FString& HeaderValue)
        {
            bool bCancel = false;
            if (HeaderName.Equals(TEXT("Content-Length"), ESearchCase::IgnoreCase))
            {
                const FString CleanHeaderValue = HeaderValue.TrimStartAndEnd();
                int64 DeclaredSize = 0;
                for (const TCHAR Character : CleanHeaderValue)
                {
                    if (Character < TEXT('0') || Character > TEXT('9') ||
                        DeclaredSize > (TNumericLimits<int64>::Max() - (Character - TEXT('0'))) / 10)
                    {
                        DeclaredSize = TNumericLimits<int64>::Max();
                        break;
                    }
                    DeclaredSize = DeclaredSize * 10 + (Character - TEXT('0'));
                }

                if (DeclaredSize > MaximumBytes)
                {
                    Download->RejectDeclaredSize();
                    bCancel = true;
                }
            }

            if (bCancel && HeaderRequest.IsValid())
            {
                HeaderRequest->CancelRequest();
            }
        });

    if (!Request->ProcessRequest())
    {
        ActiveHttpRequest.Reset();
        FailCurrentAudio(TEXT("HTTP"), TEXT("Unreal could not start the audio request."));
    }
}

void UFayAvatarBridgeComponent::HandleAudioDownloadResult(
    const uint64 Generation,
    const bool bTransportSucceeded,
    const int32 ResponseCode,
    const FString& RequestedUrl,
    const FString& EffectiveUrl,
    TArray<uint8>&& Content,
    const bool bExceededSizeLimit,
    const FString& FailureReason)
{
    if (Generation != HttpGeneration)
    {
        return;
    }

    ActiveHttpRequest.Reset();

    if (bExceededSizeLimit)
    {
        FailCurrentAudio(TEXT("HTTP"), TEXT("The audio response exceeded MaximumAudioBytes."));
        return;
    }

    if (!bTransportSucceeded || !EHttpResponseCodes::IsOk(ResponseCode))
    {
        FailCurrentAudio(TEXT("HTTP"), FString::Printf(
            TEXT("Audio request failed (HTTP %d, %s)."), ResponseCode, *FailureReason));
        return;
    }

    if (EffectiveUrl != RequestedUrl || !IsAudioUrlAllowed(EffectiveUrl))
    {
        FailCurrentAudio(TEXT("HTTP"), TEXT("The audio request was redirected; redirects are not accepted."));
        return;
    }

    if (Content.IsEmpty() || Content.Num() > FMath::Max(MaximumAudioBytes, 1024))
    {
        FailCurrentAudio(TEXT("HTTP"), FString::Printf(
            TEXT("Audio payload size %d is empty or exceeds the configured limit."), Content.Num()));
        return;
    }

    FayAvatarBridge::FDecodedPcm16Wave Wave;
    FString DecodeError;
    if (!FayAvatarBridge::DecodePcm16Wave(Content, Wave, DecodeError))
    {
        FailCurrentAudio(TEXT("WAV"), DecodeError);
        return;
    }

    UE_LOG(LogFayAvatarBridge, Display,
        TEXT("Downloaded and decoded Fay audio (encoded_bytes=%d, sample_rate=%d, channels=%d, duration_seconds=%.3f)."),
        Content.Num(),
        Wave.SampleRate,
        Wave.NumChannels,
        Wave.DurationSeconds);

    StartProceduralPlayback(
        MoveTemp(Wave.Pcm16),
        Wave.SampleRate,
        Wave.NumChannels,
        Wave.DurationSeconds);
}

void UFayAvatarBridgeComponent::FailCurrentAudio(const FString& Stage, const FString& Error)
{
    ReportError(Stage, Error);
    bHasCurrentMessage = false;
    CurrentMessage = FFayAvatarMessage();
    StartNextAudio();
}

bool UFayAvatarBridgeComponent::IsAudioUrlAllowed(const FString& Url) const
{
    FStrictUrl AudioUrl;
    FStrictUrl BaseUrl;
    if (!TryParseStrictUrl(Url, true, false, AudioUrl) ||
        !TryParseStrictUrl(AudioBaseUrl, true, false, BaseUrl) ||
        !BaseUrl.Path.EndsWith(TEXT("/")))
    {
        return false;
    }

    if (AudioUrl.Scheme != BaseUrl.Scheme || AudioUrl.Host != BaseUrl.Host ||
        AudioUrl.Port != BaseUrl.Port ||
        !AudioUrl.Path.StartsWith(BaseUrl.Path, ESearchCase::CaseSensitive))
    {
        return false;
    }

    return IsSimpleWaveFilename(FStringView(AudioUrl.Path).RightChop(BaseUrl.Path.Len()));
}

void UFayAvatarBridgeComponent::EnsureAudioComponent()
{
    if (VoiceAudioComponent || !GetOwner())
    {
        return;
    }

    VoiceAudioComponent = NewObject<UAudioComponent>(GetOwner(), NAME_None, RF_Transient);
    GetOwner()->AddInstanceComponent(VoiceAudioComponent);
    VoiceAudioComponent->SetAutoActivate(false);
    VoiceAudioComponent->bAutoDestroy = false;
    VoiceAudioComponent->bStopWhenOwnerDestroyed = true;
    VoiceAudioComponent->bAllowSpatialization = false;
    VoiceAudioComponent->bIsUISound = false;
    VoiceAudioComponent->OnAudioFinishedNative.AddUObject(this, &UFayAvatarBridgeComponent::HandleAudioFinished);
    VoiceAudioComponent->RegisterComponent();
}

void UFayAvatarBridgeComponent::RecreateAudioComponentAfterPlaybackFailure()
{
    if (VoiceAudioComponent)
    {
        // A missing completion can leave UAudioComponent's internal active
        // count waiting on an audio-thread callback. Do not carry that stale
        // state into the next utterance.
        VoiceAudioComponent->OnAudioFinishedNative.RemoveAll(this);
        VoiceAudioComponent->Stop();
        VoiceAudioComponent->SetSound(nullptr);
        VoiceAudioComponent->DestroyComponent();
        VoiceAudioComponent = nullptr;
    }

    EnsureAudioComponent();
}

void UFayAvatarBridgeComponent::HandleAudioFinished(UAudioComponent* FinishedComponent)
{
    if (FinishedComponent != VoiceAudioComponent.Get() || !bSpeechPlaying)
    {
        return;
    }

    // Procedural waves have no natural end-of-stream marker. A normal finish
    // is therefore only the native completion raised by our controlled Stop
    // after the queued PCM has drained. Eviction, device loss, or an external
    // Stop must not be reported as successful speech completion.
    const bool bCompletedNormally = bPlaybackStopRequested;
    const uint64 CompletionGeneration = SpeechGeneration;
    FinishCurrentPlayback(bCompletedNormally);

    if (!bCompletedNormally && !bEndingPlay && CompletionGeneration == SpeechGeneration)
    {
        ReportError(TEXT("Audio"), TEXT("Procedural audio stopped before its PCM queue drained."));
    }

    StartNextAudio();
}

void UFayAvatarBridgeComponent::StartProceduralPlayback(
    TArray<uint8>&& Pcm16,
    const int32 SampleRate,
    const int32 NumChannels,
    const float DurationSeconds)
{
    EnsureAudioComponent();
    if (!VoiceAudioComponent)
    {
        FailCurrentAudio(TEXT("Audio"), TEXT("Could not create an Unreal audio component."));
        return;
    }

    CurrentSoundWave = NewObject<USoundWaveProcedural>(this, NAME_None, RF_Transient);
    CurrentSoundWave->NumChannels = NumChannels;
    CurrentSoundWave->SetSampleRate(static_cast<uint32>(SampleRate));
    // USoundWaveProcedural pads underruns instead of producing an EOS marker.
    // Keep it alive until Tick observes an empty FIFO and explicitly stops it.
    CurrentSoundWave->Duration = INDEFINITELY_LOOPING_DURATION;
    CurrentSoundWave->SoundGroup = SOUNDGROUP_Voice;
    CurrentSoundWave->bLooping = false;
    CurrentSoundWave->bCanProcessAsync = false;

    // AvailableAudioByteCount reaches zero when the final chunk is handed to
    // the audio mixer, not when the speakers finish rendering it. Append one
    // full procedural callback of silence so the last speech samples have
    // left the source buffer before Tick requests Stop.
    const int32 OriginalPcmBytes = Pcm16.Num();
    Pcm16.AddZeroed(ProceduralSafetySilenceSamples * static_cast<int32>(sizeof(int16)));
    CurrentSoundWave->QueueAudio(Pcm16.GetData(), Pcm16.Num());
    Pcm16.SetNum(OriginalPcmBytes, EAllowShrinking::No);

    VoiceAudioComponent->Stop();
    VoiceAudioComponent->SetSound(CurrentSoundWave);

    CurrentPcm16 = MoveTemp(Pcm16);
    CurrentSampleRate = SampleRate;
    CurrentNumChannels = NumChannels;
    CurrentDurationSeconds = DurationSeconds;
    PlaybackStartedAtSeconds = FPlatformTime::Seconds();
    PlaybackWatchdogElapsedSeconds = 0.0f;
    PlaybackDrainTailElapsedSeconds = 0.0f;
    PlaybackStopWaitSeconds = 0.0f;
    bPlaybackStopRequested = false;
    bSpeechPlaying = true;

    OnDecodedPcm.Broadcast(CurrentMessage, CurrentPcm16, CurrentSampleRate, CurrentNumChannels);
    VoiceAudioComponent->Play();
    if (bSpeechPlaying)
    {
        UE_LOG(LogFayAvatarBridge, Display,
            TEXT("Started Fay speech playback (sample_rate=%d, channels=%d, duration_seconds=%.3f)."),
            CurrentSampleRate,
            CurrentNumChannels,
            CurrentDurationSeconds);
        OnSpeechStarted.Broadcast(CurrentMessage, CurrentDurationSeconds);
    }
}

void UFayAvatarBridgeComponent::FinishCurrentPlayback(const bool bCompletedNormally)
{
    const uint64 CompletionGeneration = SpeechGeneration;
    const bool bWasPlaying = bSpeechPlaying;
    const float FinishedDurationSeconds = CurrentDurationSeconds;
    const FFayAvatarMessage FinishedMessage = CurrentMessage;

    bSpeechPlaying = false;
    bHasCurrentMessage = false;
    CurrentDurationSeconds = 0.0f;
    PlaybackStartedAtSeconds = 0.0;
    PlaybackWatchdogElapsedSeconds = 0.0f;
    PlaybackDrainTailElapsedSeconds = 0.0f;
    PlaybackStopWaitSeconds = 0.0f;
    bPlaybackStopRequested = false;
    CurrentSampleRate = 0;
    CurrentNumChannels = 0;
    CurrentPcm16.Reset();

    if (VoiceAudioComponent)
    {
        VoiceAudioComponent->Stop();
        VoiceAudioComponent->SetSound(nullptr);
    }

    if (CurrentSoundWave)
    {
        CurrentSoundWave->ResetAudio();
        CurrentSoundWave = nullptr;
    }

    // Clear all playback state before publishing an amplitude change. A
    // Blueprint listener may immediately queue and start the next message.
    CurrentMessage = FFayAvatarMessage();
    ResetMouthAmplitude();

    if (bWasPlaying && bCompletedNormally && !bEndingPlay &&
        CompletionGeneration == SpeechGeneration)
    {
        UE_LOG(LogFayAvatarBridge, Display,
            TEXT("Finished Fay speech playback (duration_seconds=%.3f)."),
            FinishedDurationSeconds);
        OnSpeechFinished.Broadcast(FinishedMessage);
    }
}

void UFayAvatarBridgeComponent::CancelAudioRequest()
{
    ++HttpGeneration;
    if (!ActiveHttpRequest.IsValid())
    {
        return;
    }

    ActiveHttpRequest->OnProcessRequestComplete().Unbind();
    ActiveHttpRequest->CancelRequest();
    ActiveHttpRequest.Reset();
    bHasCurrentMessage = false;
}

void UFayAvatarBridgeComponent::ResetMouthAmplitude()
{
    if (!FMath::IsNearlyZero(MouthAmplitude))
    {
        MouthAmplitude = 0.0f;
        OnMouthAmplitude.Broadcast(MouthAmplitude);
    }
}

void UFayAvatarBridgeComponent::UpdateMouthAmplitude(const float DeltaTime)
{
    if (CurrentSampleRate <= 0 || CurrentNumChannels <= 0 || CurrentPcm16.Num() < 2)
    {
        ResetMouthAmplitude();
        return;
    }

    const int64 TotalSamples = CurrentPcm16.Num() / static_cast<int32>(sizeof(int16));
    const int64 TotalFrames = TotalSamples / CurrentNumChannels;
    const int64 StartFrame = FMath::Clamp<int64>(
        static_cast<int64>(GetSpeechPlaybackSeconds() * static_cast<float>(CurrentSampleRate)),
        0,
        TotalFrames);
    const int64 WindowFrames = FMath::Max<int64>(1, CurrentSampleRate / 50); // 20 ms
    const int64 EndFrame = FMath::Min(StartFrame + WindowFrames, TotalFrames);

    double SumSquares = 0.0;
    int64 Count = 0;
    for (int64 Frame = StartFrame; Frame < EndFrame; ++Frame)
    {
        for (int32 Channel = 0; Channel < CurrentNumChannels; ++Channel)
        {
            const int64 SampleIndex = Frame * CurrentNumChannels + Channel;
            const int64 ByteIndex = SampleIndex * 2;
            const int32 ByteOffset = static_cast<int32>(ByteIndex);
            const uint16 UnsignedSample = static_cast<uint16>(CurrentPcm16[ByteOffset]) |
                (static_cast<uint16>(CurrentPcm16[ByteOffset + 1]) << 8);
            const int16 Sample = static_cast<int16>(UnsignedSample);
            const double Normalized = static_cast<double>(Sample) / 32768.0;
            SumSquares += Normalized * Normalized;
            ++Count;
        }
    }

    const float Target = Count > 0
        ? FMath::Clamp(static_cast<float>(FMath::Sqrt(SumSquares / static_cast<double>(Count))) * MouthAmplitudeGain, 0.0f, 1.0f)
        : 0.0f;
    const float Previous = MouthAmplitude;
    MouthAmplitude = FMath::FInterpTo(MouthAmplitude, Target, DeltaTime, 22.0f);

    if (!FMath::IsNearlyEqual(Previous, MouthAmplitude, 0.002f))
    {
        OnMouthAmplitude.Broadcast(MouthAmplitude);
    }
}

void UFayAvatarBridgeComponent::ReportError(const FString& Stage, const FString& Error)
{
    UE_LOG(LogFayAvatarBridge, Warning, TEXT("%s: %s"), *Stage, *Error);
    OnBridgeError.Broadcast(Stage, Error);
}

#include "FayArdyPoseClientComponent.h"

#include "Dom/JsonObject.h"
#include "FayBodyMotionComponent.h"
#include "HttpModule.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayArdyPoseClient, Log, All);

namespace
{
constexpr int32 ExpectedFramesPerSecond = 20;
constexpr int32 TargetBufferFrames = 8;
constexpr int32 MaximumBufferFrames = 32;
constexpr int32 ExpectedJointCount = 27;
constexpr int32 MaximumResponseBytes = 512 * 1024;
constexpr double HealthRetrySeconds = 2.0;

bool ReadFiniteNumber(const TArray<TSharedPtr<FJsonValue>>& Values, const int32 Index, double& Out)
{
    if (!Values.IsValidIndex(Index) || !Values[Index].IsValid() ||
        !Values[Index]->TryGetNumber(Out) || !FMath::IsFinite(Out))
    {
        return false;
    }
    return true;
}

bool ReadQuaternion(const TArray<TSharedPtr<FJsonValue>>& Values, FQuat4f& Out)
{
    double X = 0.0;
    double Y = 0.0;
    double Z = 0.0;
    double W = 0.0;
    if (Values.Num() != 4 || !ReadFiniteNumber(Values, 0, X) ||
        !ReadFiniteNumber(Values, 1, Y) || !ReadFiniteNumber(Values, 2, Z) ||
        !ReadFiniteNumber(Values, 3, W))
    {
        return false;
    }
    Out = FQuat4f(static_cast<float>(X), static_cast<float>(Y),
        static_cast<float>(Z), static_cast<float>(W));
    const float SizeSquared = Out.SizeSquared();
    if (!FMath::IsFinite(SizeSquared) || SizeSquared < 0.25f || SizeSquared > 2.25f)
    {
        return false;
    }
    Out.Normalize();
    return true;
}
}

UFayArdyPoseClientComponent::UFayArdyPoseClientComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UFayArdyPoseClientComponent::BeginPlay()
{
    Super::BeginPlay();
    int32 DisableArdyOverride = 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayDisableArdy="),
            DisableArdyOverride) &&
        DisableArdyOverride != 0)
    {
        bClientEnabled = false;
        SetComponentTickEnabled(false);
        UE_LOG(LogFayArdyPoseClient, Display,
            TEXT("ARDY client and health polling are disabled by reviewed runtime override."));
        return;
    }
    if (!IsEndpointSealed())
    {
        UE_LOG(LogFayArdyPoseClient, Error,
            TEXT("ARDY endpoint is outside the sealed loopback origin; client remains disabled."));
        return;
    }
    ProbeHealth();
}

void UFayArdyPoseClientComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (HealthRequest.IsValid())
    {
        HealthRequest->CancelRequest();
        HealthRequest.Reset();
    }
    if (PoseRequest.IsValid())
    {
        PoseRequest->CancelRequest();
        PoseRequest.Reset();
    }
    PoseBuffer.Reset();
    SetReady(false);
    Super::EndPlay(EndPlayReason);
}

void UFayArdyPoseClientComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (!bClientEnabled)
    {
        return;
    }
    if (!bServiceReady)
    {
        HealthRetryElapsedSeconds += FMath::Max(0.0f, DeltaTime);
        if (HealthRetryElapsedSeconds >= HealthRetrySeconds && !HealthRequest.IsValid())
        {
            HealthRetryElapsedSeconds = 0.0;
            ProbeHealth();
        }
        return;
    }
    if (!ActiveBehavior.IsNone() && PoseBuffer.Num() < TargetBufferFrames &&
        !PoseRequest.IsValid())
    {
        RequestPoseBatch();
    }
}

bool UFayArdyPoseClientComponent::StartBehavior(
    const FName Behavior,
    const float Intensity,
    const float DurationSeconds)
{
    if (!bClientEnabled || !bServiceReady ||
        !UFayBodyMotionComponent::IsBehaviorAllowed(Behavior))
    {
        return false;
    }
    ActiveBehavior = FName(*Behavior.ToString().TrimStartAndEnd().ToLower());
    ActiveIntensity = FMath::Clamp(FMath::IsFinite(Intensity) ? Intensity : 0.5f, 0.0f, 1.0f);
    ActiveDurationSeconds = FMath::Clamp(
        FMath::IsFinite(DurationSeconds) ? DurationSeconds : 1.0f,
        0.2f,
        10.0f);
    PoseBuffer.Reset();
    bPlaybackStarted = false;
    RequestPoseBatch();
    return true;
}

void UFayArdyPoseClientComponent::StopBehavior()
{
    ActiveBehavior = NAME_None;
    PoseBuffer.Reset();
    bPlaybackStarted = false;
    if (PoseRequest.IsValid())
    {
        PoseRequest->CancelRequest();
        PoseRequest.Reset();
    }
}

bool UFayArdyPoseClientComponent::SamplePose(
    const float DeltaSeconds,
    FFayArdyPoseFrame& OutPose)
{
    if (PoseBuffer.Num() < 2)
    {
        if (bPlaybackStarted)
        {
            OnBufferUnderrun.Broadcast(PoseBuffer.Num());
            bPlaybackStarted = false;
        }
        return false;
    }
    if (!bPlaybackStarted)
    {
        PlaybackTimeSeconds = PoseBuffer[0].TimeSeconds;
        bPlaybackStarted = true;
    }
    PlaybackTimeSeconds += FMath::Max(0.0f, DeltaSeconds);
    while (PoseBuffer.Num() > 2 && PoseBuffer[1].TimeSeconds <= PlaybackTimeSeconds)
    {
        PoseBuffer.RemoveAt(0, 1, EAllowShrinking::No);
    }
    const FFayArdyPoseFrame& A = PoseBuffer[0];
    const FFayArdyPoseFrame& B = PoseBuffer[1];
    const double Span = FMath::Max(B.TimeSeconds - A.TimeSeconds, 1.0 / ExpectedFramesPerSecond);
    const float Alpha = static_cast<float>(FMath::Clamp(
        (PlaybackTimeSeconds - A.TimeSeconds) / Span,
        0.0,
        1.0));
    OutPose.TimeSeconds = PlaybackTimeSeconds;
    OutPose.RootTranslationMetres = FMath::Lerp(A.RootTranslationMetres, B.RootTranslationMetres, Alpha);
    OutPose.RootRotation = FQuat4f::Slerp(A.RootRotation, B.RootRotation, Alpha);
    OutPose.JointRotations.SetNum(ExpectedJointCount);
    for (int32 Index = 0; Index < ExpectedJointCount; ++Index)
    {
        OutPose.JointRotations[Index] = FQuat4f::Slerp(
            A.JointRotations[Index],
            B.JointRotations[Index],
            Alpha);
    }
    OutPose.Contacts.SetNum(4);
    for (int32 Index = 0; Index < 4; ++Index)
    {
        OutPose.Contacts[Index] = FMath::Lerp(A.Contacts[Index], B.Contacts[Index], Alpha);
    }
    return true;
}

void UFayArdyPoseClientComponent::ProbeHealth()
{
    if (!IsEndpointSealed() || HealthRequest.IsValid())
    {
        return;
    }
    HealthRequest = FHttpModule::Get().CreateRequest();
    HealthRequest->SetURL(BaseUrl + TEXT("/healthz"));
    HealthRequest->SetVerb(TEXT("GET"));
    HealthRequest->SetTimeout(2.0f);
    HealthRequest->OnProcessRequestComplete().BindUObject(
        this,
        &UFayArdyPoseClientComponent::HandleHealthResponse);
    if (!HealthRequest->ProcessRequest())
    {
        HealthRequest.Reset();
    }
}

void UFayArdyPoseClientComponent::RequestPoseBatch()
{
    if (!bServiceReady || ActiveBehavior.IsNone() || PoseRequest.IsValid() ||
        PoseBuffer.Num() >= MaximumBufferFrames)
    {
        return;
    }
    TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("behavior"), ActiveBehavior.ToString());
    Payload->SetNumberField(TEXT("intensity"), ActiveIntensity);
    Payload->SetNumberField(TEXT("duration"), ActiveDurationSeconds);
    Payload->SetNumberField(TEXT("afterSequence"), static_cast<double>(LastSequence));
    FString Body;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Body);
    if (!FJsonSerializer::Serialize(Payload, Writer))
    {
        return;
    }
    PoseRequest = FHttpModule::Get().CreateRequest();
    PoseRequest->SetURL(BaseUrl + TEXT("/v1/poses"));
    PoseRequest->SetVerb(TEXT("POST"));
    PoseRequest->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    PoseRequest->SetContentAsString(Body);
    PoseRequest->SetTimeout(2.0f);
    PoseRequest->OnProcessRequestComplete().BindUObject(
        this,
        &UFayArdyPoseClientComponent::HandlePoseResponse);
    if (!PoseRequest->ProcessRequest())
    {
        PoseRequest.Reset();
    }
}

void UFayArdyPoseClientComponent::HandleHealthResponse(
    FHttpRequestPtr Request,
    FHttpResponsePtr Response,
    const bool bSucceeded)
{
    (void)Request;
    HealthRequest.Reset();
    bool bReady = false;
    if (bSucceeded && Response.IsValid() && Response->GetResponseCode() == 200 &&
        Response->GetContentLength() <= MaximumResponseBytes)
    {
        TSharedPtr<FJsonObject> Object;
        const TSharedRef<TJsonReader<>> Reader =
            TJsonReaderFactory<>::Create(Response->GetContentAsString());
        FString Status;
        int32 Version = 0;
        int32 FramesPerSecond = 0;
        int32 BufferFrames = 0;
        bReady = FJsonSerializer::Deserialize(Reader, Object) && Object.IsValid() &&
            Object->TryGetStringField(TEXT("status"), Status) && Status == TEXT("ready") &&
            Object->TryGetNumberField(TEXT("protocolVersion"), Version) && Version == 1 &&
            Object->TryGetNumberField(TEXT("fps"), FramesPerSecond) &&
            FramesPerSecond == ExpectedFramesPerSecond &&
            Object->TryGetNumberField(TEXT("bufferFrames"), BufferFrames) &&
            BufferFrames == TargetBufferFrames;
    }
    SetReady(bReady);
}

void UFayArdyPoseClientComponent::HandlePoseResponse(
    FHttpRequestPtr Request,
    FHttpResponsePtr Response,
    const bool bSucceeded)
{
    (void)Request;
    PoseRequest.Reset();
    if (!bSucceeded || !Response.IsValid() || Response->GetResponseCode() != 200 ||
        Response->GetContentLength() > MaximumResponseBytes)
    {
        SetReady(false);
        return;
    }
    FFayBodyPoseBatch Batch;
    FString Error;
    if (!ParsePoseBatch(Response->GetContentAsString(), Batch, Error) ||
        Batch.Sequence <= LastSequence)
    {
        UE_LOG(LogFayArdyPoseClient, Warning,
            TEXT("Rejected ARDY pose batch: %s."),
            Error.IsEmpty() ? TEXT("sequence is not increasing") : *Error);
        SetReady(false);
        return;
    }
    LastSequence = Batch.Sequence;
    for (FFayArdyPoseFrame& Frame : Batch.Frames)
    {
        if (PoseBuffer.Num() >= MaximumBufferFrames)
        {
            break;
        }
        if (PoseBuffer.IsEmpty() || Frame.TimeSeconds > PoseBuffer.Last().TimeSeconds)
        {
            PoseBuffer.Add(MoveTemp(Frame));
        }
    }
}

void UFayArdyPoseClientComponent::SetReady(const bool bReady)
{
    if (bServiceReady == bReady)
    {
        return;
    }
    bServiceReady = bReady;
    if (!bReady)
    {
        PoseBuffer.Reset();
        bPlaybackStarted = false;
    }
    OnReadyChanged.Broadcast(bServiceReady);
    UE_LOG(LogFayArdyPoseClient, Display,
        TEXT("ARDY loopback service is %s."),
        bServiceReady ? TEXT("ready") : TEXT("unavailable; baked fallback remains active"));
}

bool UFayArdyPoseClientComponent::ParsePoseBatch(
    const FString& Json,
    FFayBodyPoseBatch& OutBatch,
    FString& OutError) const
{
    TSharedPtr<FJsonObject> Object;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Object) || !Object.IsValid())
    {
        OutError = TEXT("invalid JSON");
        return false;
    }
    int32 Version = 0;
    int32 FramesPerSecond = 0;
    double SequenceNumber = 0.0;
    FString CoordinateSystem;
    const TArray<TSharedPtr<FJsonValue>>* Frames = nullptr;
    if (!Object->TryGetNumberField(TEXT("version"), Version) || Version != 1 ||
        !Object->TryGetNumberField(TEXT("sequence"), SequenceNumber) ||
        !FMath::IsFinite(SequenceNumber) || SequenceNumber < 1.0 ||
        SequenceNumber > static_cast<double>(MAX_int64) ||
        !Object->TryGetNumberField(TEXT("fps"), FramesPerSecond) ||
        FramesPerSecond != ExpectedFramesPerSecond ||
        !Object->TryGetStringField(TEXT("coordinateSystem"), CoordinateSystem) ||
        CoordinateSystem != TEXT("ardy-y-up-z-forward-meters") ||
        !Object->TryGetArrayField(TEXT("frames"), Frames) || Frames == nullptr ||
        Frames->Num() < 1 || Frames->Num() > TargetBufferFrames)
    {
        OutError = TEXT("invalid batch envelope");
        return false;
    }
    OutBatch.Version = Version;
    OutBatch.Sequence = static_cast<int64>(SequenceNumber);
    OutBatch.FramesPerSecond = FramesPerSecond;
    OutBatch.CoordinateSystem = CoordinateSystem;
    double PreviousTime = -1.0;
    for (const TSharedPtr<FJsonValue>& FrameValue : *Frames)
    {
        const TSharedPtr<FJsonObject>* FrameObject = nullptr;
        if (!FrameValue.IsValid() || !FrameValue->TryGetObject(FrameObject) ||
            FrameObject == nullptr || !FrameObject->IsValid())
        {
            OutError = TEXT("invalid frame object");
            return false;
        }
        FFayArdyPoseFrame Frame;
        const TArray<TSharedPtr<FJsonValue>>* Root = nullptr;
        const TArray<TSharedPtr<FJsonValue>>* Joints = nullptr;
        const TArray<TSharedPtr<FJsonValue>>* Contacts = nullptr;
        if (!(*FrameObject)->TryGetNumberField(TEXT("time"), Frame.TimeSeconds) ||
            !FMath::IsFinite(Frame.TimeSeconds) || Frame.TimeSeconds <= PreviousTime ||
            !(*FrameObject)->TryGetArrayField(TEXT("root"), Root) || Root == nullptr ||
            Root->Num() != 7 ||
            !(*FrameObject)->TryGetArrayField(TEXT("joints"), Joints) || Joints == nullptr ||
            Joints->Num() != ExpectedJointCount ||
            !(*FrameObject)->TryGetArrayField(TEXT("contacts"), Contacts) || Contacts == nullptr ||
            Contacts->Num() != 4)
        {
            OutError = TEXT("invalid frame envelope");
            return false;
        }
        PreviousTime = Frame.TimeSeconds;
        double X = 0.0;
        double Y = 0.0;
        double Z = 0.0;
        TArray<TSharedPtr<FJsonValue>> RootQuaternion;
        RootQuaternion.Append(Root->GetData() + 3, 4);
        if (!ReadFiniteNumber(*Root, 0, X) || !ReadFiniteNumber(*Root, 1, Y) ||
            !ReadFiniteNumber(*Root, 2, Z) ||
            !ReadQuaternion(RootQuaternion, Frame.RootRotation))
        {
            OutError = TEXT("invalid root transform");
            return false;
        }
        Frame.RootTranslationMetres = FVector3f(
            static_cast<float>(X), static_cast<float>(Y), static_cast<float>(Z));
        for (const TSharedPtr<FJsonValue>& JointValue : *Joints)
        {
            const TArray<TSharedPtr<FJsonValue>>* Rotation = nullptr;
            FQuat4f Quaternion;
            if (!JointValue.IsValid() || !JointValue->TryGetArray(Rotation) ||
                Rotation == nullptr || !ReadQuaternion(*Rotation, Quaternion))
            {
                OutError = TEXT("invalid joint quaternion");
                return false;
            }
            Frame.JointRotations.Add(Quaternion);
        }
        for (int32 Index = 0; Index < 4; ++Index)
        {
            double Contact = 0.0;
            if (!ReadFiniteNumber(*Contacts, Index, Contact))
            {
                OutError = TEXT("invalid contact value");
                return false;
            }
            Frame.Contacts.Add(static_cast<float>(Contact));
        }
        OutBatch.Frames.Add(MoveTemp(Frame));
    }
    return true;
}

bool UFayArdyPoseClientComponent::IsEndpointSealed() const
{
    return BaseUrl == TEXT("http://127.0.0.1:8777");
}

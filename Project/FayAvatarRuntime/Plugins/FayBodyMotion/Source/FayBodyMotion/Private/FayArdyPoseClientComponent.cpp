#include "FayArdyPoseClientComponent.h"

#include "Dom/JsonObject.h"
#include "FayBodyMotionComponent.h"
#include "FayCore27Skeleton.h"
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
constexpr int32 ExpectedProtocolVersion = 2;
constexpr int32 TargetBufferFrames = 8;
constexpr int32 MaximumBufferFrames = 32;
constexpr int32 ExpectedJointCount = 27;
constexpr int32 MaximumResponseBytes = 512 * 1024;
constexpr double HealthRetrySeconds = 2.0;
constexpr double HealthPollSeconds = 5.0;
constexpr double ExpectedFrameStepSeconds = 1.0 / ExpectedFramesPerSecond;
constexpr double MaximumRootTranslationMetres = 10.0;
constexpr double MaximumRootFrameStepMetres = 0.25;
constexpr double MaximumActionTransitionGapSeconds = 0.5;
constexpr double MaximumActionTransitionRootStepMetres = 1.0;
constexpr double ExclusiveInt64UpperBound = 9223372036854775808.0;
constexpr double RootPositionConsistencyToleranceMetres = 1.0e-5;
constexpr float RootRotationConsistencyDotThreshold = 1.0f - 1.0e-5f;
constexpr int32 NeckJointIndex = 5;
constexpr int32 HeadJointIndex = 6;
constexpr double MaximumJointPositionMetres = 10.0;
constexpr TCHAR ExpectedCoordinateSystem[] =
    TEXT("ardy-rh-x-left-y-up-z-forward-meters");

const TArray<FString>& ExpectedContactOrder()
{
    static const TArray<FString> Contacts = {
        TEXT("left_heel"), TEXT("left_toe"), TEXT("right_heel"), TEXT("right_toe")};
    return Contacts;
}

const TArray<FName>& ExpectedMotionCatalog()
{
    static const TArray<FName> Catalog = {
        TEXT("idle"), TEXT("listen"), TEXT("explain"), TEXT("wave"),
        TEXT("jog_in_place"), TEXT("run_in_place"), TEXT("jumping_jacks"),
        TEXT("stretch"), TEXT("dance_relaxed")};
    return Catalog;
}

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
    if (!FMath::IsFinite(SizeSquared) || SizeSquared < 0.98f || SizeSquared > 1.02f)
    {
        return false;
    }
    Out.Normalize();
    return true;
}

void StabilizeQuaternionHemisphere(
    const FQuat4f& Reference,
    FQuat4f& Rotation)
{
    const float Dot = Reference.X * Rotation.X + Reference.Y * Rotation.Y +
        Reference.Z * Rotation.Z + Reference.W * Rotation.W;
    if (Dot < 0.0f)
    {
        Rotation.X = -Rotation.X;
        Rotation.Y = -Rotation.Y;
        Rotation.Z = -Rotation.Z;
        Rotation.W = -Rotation.W;
    }
}

bool ReadExactStringArray(
    const TArray<TSharedPtr<FJsonValue>>& Values,
    const TArray<FString>& Expected)
{
    if (Values.Num() != Expected.Num())
    {
        return false;
    }
    for (int32 Index = 0; Index < Expected.Num(); ++Index)
    {
        FString Value;
        if (!Values[Index].IsValid() || !Values[Index]->TryGetString(Value) ||
            Value != Expected[Index])
        {
            return false;
        }
    }
    return true;
}

bool ValidateSourceDescriptor(const TSharedPtr<FJsonObject>& Source)
{
    if (!Source.IsValid() || Source->Values.Num() != 8)
    {
        return false;
    }

    FString System;
    FString Revision;
    FString Skeleton;
    FString RotationSpace;
    FString QuaternionOrder;
    FString PositionSpace;
    const TArray<TSharedPtr<FJsonValue>>* JointOrder = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* ContactOrder = nullptr;
    if (!Source->TryGetStringField(TEXT("system"), System) ||
        System != TEXT("nv-tlabs/ardy") ||
        !Source->TryGetStringField(TEXT("revision"), Revision) ||
        Revision != TEXT("693f74d13b3d04a0a22ce127ee79c929dd89756b") ||
        !Source->TryGetStringField(TEXT("skeleton"), Skeleton) ||
        Skeleton != TEXT("Core27") ||
        !Source->TryGetStringField(TEXT("rotationSpace"), RotationSpace) ||
        RotationSpace != TEXT("local") ||
        !Source->TryGetStringField(TEXT("quaternionOrder"), QuaternionOrder) ||
        QuaternionOrder != TEXT("xyzw") ||
        !Source->TryGetStringField(TEXT("positionSpace"), PositionSpace) ||
        PositionSpace != TEXT("global") ||
        !Source->TryGetArrayField(TEXT("jointOrder"), JointOrder) ||
        JointOrder == nullptr ||
        !Source->TryGetArrayField(TEXT("contactOrder"), ContactOrder) ||
        ContactOrder == nullptr)
    {
        return false;
    }

    const TArray<FFayCore27Bone>& Hierarchy = FayGetCore27Hierarchy();
    if (JointOrder->Num() != Hierarchy.Num())
    {
        return false;
    }
    for (int32 Index = 0; Index < Hierarchy.Num(); ++Index)
    {
        FString Joint;
        if (!(*JointOrder)[Index].IsValid() ||
            !(*JointOrder)[Index]->TryGetString(Joint) ||
            Joint != Hierarchy[Index].Name.ToString())
        {
            return false;
        }
    }
    return ReadExactStringArray(*ContactOrder, ExpectedContactOrder());
}

bool ValidateMotionCatalog(
    const TArray<TSharedPtr<FJsonValue>>& Values,
    TSet<FName>& OutCatalog)
{
    OutCatalog.Reset();
    const TArray<FName>& Expected = ExpectedMotionCatalog();
    if (Values.Num() != Expected.Num())
    {
        return false;
    }
    for (int32 Index = 0; Index < Expected.Num(); ++Index)
    {
        FString Value;
        if (!Values[Index].IsValid() || !Values[Index]->TryGetString(Value) ||
            FName(*Value) != Expected[Index])
        {
            OutCatalog.Reset();
            return false;
        }
        OutCatalog.Add(Expected[Index]);
    }
    return true;
}

void StabilizePoseHemisphere(
    const FFayArdyPoseFrame& Reference,
    FFayArdyPoseFrame& Pose)
{
    StabilizeQuaternionHemisphere(Reference.RootRotation, Pose.RootRotation);
    if (Reference.JointRotations.Num() != Pose.JointRotations.Num())
    {
        return;
    }
    for (int32 Index = 0; Index < Pose.JointRotations.Num(); ++Index)
    {
        StabilizeQuaternionHemisphere(
            Reference.JointRotations[Index],
            Pose.JointRotations[Index]);
    }
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
    int32 AllowDiagnosticProviderOverride = 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayAllowDiagnosticArdy="),
            AllowDiagnosticProviderOverride) &&
        AllowDiagnosticProviderOverride != 0)
    {
        bAllowDiagnosticProvider = true;
        UE_LOG(LogFayArdyPoseClient, Display,
            TEXT("ARDY diagnostic-provider health compatibility is enabled."));
    }
    ProbeHealth();
}

void UFayArdyPoseClientComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    bClientEnabled = false;
    ActiveBehavior = NAME_None;
    ActivePrompt.Reset();
    RetireHealthRequest();
    RetirePoseRequest();
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
    HealthRetryElapsedSeconds += FMath::Max(0.0f, DeltaTime);
    const double HealthProbeIntervalSeconds =
        bServiceReady ? HealthPollSeconds : HealthRetrySeconds;
    if (HealthRetryElapsedSeconds >= HealthProbeIntervalSeconds &&
        !HealthRequest.IsValid())
    {
        HealthRetryElapsedSeconds = 0.0;
        ProbeHealth();
    }
    if (!bServiceReady)
    {
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
    const float DurationSeconds,
    const FString& Prompt)
{
    if (!bClientEnabled || !bServiceReady ||
        !UFayBodyMotionComponent::IsBehaviorAllowed(Behavior) ||
        !SupportsBehavior(Behavior))
    {
        return false;
    }
    const FString NormalizedPrompt = Prompt.TrimStartAndEnd();
    if (NormalizedPrompt.Len() > 512)
    {
        return false;
    }
    RetirePoseRequest();
    ActiveBehavior = FName(*Behavior.ToString().TrimStartAndEnd().ToLower());
    ActivePrompt = NormalizedPrompt;
    ActiveIntensity = FMath::Clamp(FMath::IsFinite(Intensity) ? Intensity : 0.5f, 0.0f, 1.0f);
    ActiveDurationSeconds = FMath::Clamp(
        FMath::IsFinite(DurationSeconds) ? DurationSeconds : 1.0f,
        0.2f,
        10.0f);
    PoseBuffer.Reset();
    bAllowActionTransitionGap = true;
    bPlaybackStarted = false;
    RequestPoseBatch();
    return true;
}

bool UFayArdyPoseClientComponent::SupportsBehavior(const FName Behavior) const
{
    const FName Normalized(*Behavior.ToString().TrimStartAndEnd().ToLower());
    return bServiceReady && SupportedBehaviors.Contains(Normalized);
}

void UFayArdyPoseClientComponent::StopBehavior()
{
    ActiveBehavior = NAME_None;
    ActivePrompt.Reset();
    RetirePoseRequest();
    PoseBuffer.Reset();
    bPlaybackStarted = false;
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
    OutPose.JointPositionsMetres.SetNum(ExpectedJointCount);
    for (int32 Index = 0; Index < ExpectedJointCount; ++Index)
    {
        OutPose.JointRotations[Index] = FQuat4f::Slerp(
            A.JointRotations[Index],
            B.JointRotations[Index],
            Alpha);
        OutPose.JointPositionsMetres[Index] = FMath::Lerp(
            A.JointPositionsMetres[Index],
            B.JointPositionsMetres[Index],
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
        RetireHealthRequest();
        SetReady(false);
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
    if (!ActivePrompt.IsEmpty())
    {
        Payload->SetStringField(TEXT("prompt"), ActivePrompt);
    }
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
    PoseRequest->SetURL(BaseUrl + TEXT("/v2/poses"));
    PoseRequest->SetVerb(TEXT("POST"));
    PoseRequest->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    PoseRequest->SetContentAsString(Body);
    PoseRequest->SetTimeout(2.0f);
    PoseRequest->OnProcessRequestComplete().BindUObject(
        this,
        &UFayArdyPoseClientComponent::HandlePoseResponse);
    if (!PoseRequest->ProcessRequest())
    {
        RetirePoseRequest();
        SetReady(false);
    }
}

void UFayArdyPoseClientComponent::RetireHealthRequest()
{
    if (HealthRequest.IsValid())
    {
        HealthRequest->OnProcessRequestComplete().Unbind();
        HealthRequest->CancelRequest();
        HealthRequest.Reset();
    }
}

void UFayArdyPoseClientComponent::RetirePoseRequest()
{
    if (PoseRequest.IsValid())
    {
        PoseRequest->OnProcessRequestComplete().Unbind();
        PoseRequest->CancelRequest();
        PoseRequest.Reset();
    }
}

void UFayArdyPoseClientComponent::HandleHealthResponse(
    FHttpRequestPtr Request,
    FHttpResponsePtr Response,
    const bool bSucceeded)
{
    if (!bClientEnabled || Request != HealthRequest)
    {
        return;
    }
    HealthRequest.Reset();
    bool bReady = false;
    TSet<FName> QualifiedCatalog;
    if (bSucceeded && Response.IsValid() && Response->GetResponseCode() == 200 &&
        Request->GetEffectiveURL() == BaseUrl + TEXT("/healthz") &&
        Response->GetContent().Num() <= MaximumResponseBytes &&
        Response->GetContentType().Equals(
            TEXT("application/json"),
            ESearchCase::IgnoreCase))
    {
        TSharedPtr<FJsonObject> Object;
        const TSharedRef<TJsonReader<>> Reader =
            TJsonReaderFactory<>::Create(Response->GetContentAsString());
        FString Status;
        double Version = 0.0;
        double FramesPerSecond = 0.0;
        double BufferFrames = 0.0;
        double EmbeddingCount = 0.0;
        double P95GenerationMilliseconds = 0.0;
        bool bDynamicTextReady = false;
        FString Provider;
        FString FacialControl;
        FString CoordinateSystem;
        FString Checkpoint;
        const TSharedPtr<FJsonObject>* Source = nullptr;
        const TArray<TSharedPtr<FJsonValue>>* MotionCatalog = nullptr;
        const bool bBaseHealthReady =
            FJsonSerializer::Deserialize(Reader, Object) && Object.IsValid() &&
            Object->Values.Num() == 13 &&
            Object->TryGetStringField(TEXT("status"), Status) && Status == TEXT("ready") &&
            Object->TryGetStringField(TEXT("provider"), Provider) &&
            Object->TryGetNumberField(TEXT("protocolVersion"), Version) &&
            Version == static_cast<double>(ExpectedProtocolVersion) &&
            Object->TryGetNumberField(TEXT("fps"), FramesPerSecond) &&
            FramesPerSecond == static_cast<double>(ExpectedFramesPerSecond) &&
            Object->TryGetNumberField(TEXT("bufferFrames"), BufferFrames) &&
            BufferFrames == static_cast<double>(TargetBufferFrames) &&
            Object->TryGetStringField(TEXT("facialControl"), FacialControl) &&
            FacialControl == TEXT("excluded") &&
            Object->TryGetStringField(TEXT("coordinateSystem"), CoordinateSystem) &&
            CoordinateSystem == ExpectedCoordinateSystem &&
            Object->TryGetObjectField(TEXT("source"), Source) && Source != nullptr &&
            ValidateSourceDescriptor(*Source) &&
            Object->TryGetArrayField(TEXT("motionCatalog"), MotionCatalog) &&
            MotionCatalog != nullptr &&
            ValidateMotionCatalog(*MotionCatalog, QualifiedCatalog) &&
            Object->TryGetNumberField(TEXT("embeddingCount"), EmbeddingCount) &&
            FMath::IsFinite(EmbeddingCount) &&
            Object->TryGetNumberField(
                TEXT("p95GenerationMs"), P95GenerationMilliseconds) &&
            FMath::IsFinite(P95GenerationMilliseconds) &&
            Object->TryGetBoolField(TEXT("dynamicTextReady"), bDynamicTextReady);
        if (bBaseHealthReady && bAllowDiagnosticProvider)
        {
            bReady = true;
        }
        else if (bBaseHealthReady)
        {
            bReady = Provider == TEXT("ardy") &&
                Object->TryGetStringField(TEXT("checkpoint"), Checkpoint) &&
                Checkpoint == TEXT("ARDY-Core-RP-20FPS-Horizon8") &&
                EmbeddingCount == static_cast<double>(ExpectedMotionCatalog().Num()) &&
                bDynamicTextReady &&
                P95GenerationMilliseconds > 0.0 &&
                P95GenerationMilliseconds < 400.0;
        }
    }
    if (bReady)
    {
        SupportedBehaviors = MoveTemp(QualifiedCatalog);
    }
    SetReady(bReady);
}

void UFayArdyPoseClientComponent::HandlePoseResponse(
    FHttpRequestPtr Request,
    FHttpResponsePtr Response,
    const bool bSucceeded)
{
    if (!bClientEnabled || !bServiceReady || ActiveBehavior.IsNone() ||
        Request != PoseRequest)
    {
        return;
    }
    PoseRequest.Reset();
    if (!bSucceeded || !Response.IsValid() || Response->GetResponseCode() != 200 ||
        Request->GetEffectiveURL() != BaseUrl + TEXT("/v2/poses") ||
        Response->GetContent().Num() > MaximumResponseBytes ||
        !Response->GetContentType().Equals(
            TEXT("application/json"),
            ESearchCase::IgnoreCase))
    {
        SetReady(false);
        return;
    }
    FFayBodyPoseBatch Batch;
    FString Error;
    bool bRejected = !ParsePoseBatch(Response->GetContentAsString(), Batch, Error);
    if (!bRejected && Batch.Sequence <= LastSequence)
    {
        Error = TEXT("sequence is not increasing");
        bRejected = true;
    }
    if (!bRejected && LastFrameTimeSeconds >= 0.0)
    {
        const double FrameGapSeconds =
            Batch.Frames[0].TimeSeconds - LastFrameTimeSeconds;
        if (bAllowActionTransitionGap)
        {
            const double RoundedGapSeconds = FMath::FloorToDouble(
                FrameGapSeconds / ExpectedFrameStepSeconds + 0.5) *
                ExpectedFrameStepSeconds;
            if (FrameGapSeconds < ExpectedFrameStepSeconds - 0.0001 ||
                FrameGapSeconds > MaximumActionTransitionGapSeconds + 0.0001 ||
                !FMath::IsNearlyEqual(FrameGapSeconds, RoundedGapSeconds, 0.0001))
            {
                Error = TEXT("action-transition frame gap is invalid");
                bRejected = true;
            }
        }
        else if (!FMath::IsNearlyEqual(
            FrameGapSeconds,
            ExpectedFrameStepSeconds,
            0.0001))
        {
            Error = TEXT("cross-batch frame time is discontinuous");
            bRejected = true;
        }
        if (!bRejected && bHasLastRootTranslation)
        {
            const double GapFrames = FMath::Max(
                1.0,
                FMath::FloorToDouble(
                    FrameGapSeconds / ExpectedFrameStepSeconds + 0.5));
            const double MaximumRootStepMetres = bAllowActionTransitionGap
                ? FMath::Min(
                    MaximumActionTransitionRootStepMetres,
                    MaximumRootFrameStepMetres * GapFrames)
                : MaximumRootFrameStepMetres;
            if ((Batch.Frames[0].RootTranslationMetres - LastRootTranslationMetres).Size() >
                MaximumRootStepMetres)
            {
                Error = TEXT("cross-batch root motion is discontinuous");
                bRejected = true;
            }
        }
    }
    if (bRejected)
    {
        UE_LOG(LogFayArdyPoseClient, Warning,
            TEXT("Rejected ARDY pose batch: %s."),
            Error.IsEmpty() ? TEXT("unknown validation failure") : *Error);
        SetReady(false);
        return;
    }
    LastSequence = Batch.Sequence;
    LastFrameTimeSeconds = Batch.Frames.Last().TimeSeconds;
    LastRootTranslationMetres = Batch.Frames.Last().RootTranslationMetres;
    bHasLastRootTranslation = true;
    bAllowActionTransitionGap = false;
    for (FFayArdyPoseFrame& Frame : Batch.Frames)
    {
        if (PoseBuffer.Num() >= MaximumBufferFrames)
        {
            break;
        }
        if (PoseBuffer.IsEmpty() || Frame.TimeSeconds > PoseBuffer.Last().TimeSeconds)
        {
            if (!PoseBuffer.IsEmpty())
            {
                StabilizePoseHemisphere(PoseBuffer.Last(), Frame);
            }
            PoseBuffer.Add(MoveTemp(Frame));
        }
    }
}

void UFayArdyPoseClientComponent::SetReady(const bool bReady)
{
    const bool bChanged = bServiceReady != bReady;
    if (!bReady)
    {
        RetireHealthRequest();
        RetirePoseRequest();
        PoseBuffer.Reset();
        LastFrameTimeSeconds = -1.0;
        bHasLastRootTranslation = false;
        bAllowActionTransitionGap = false;
        PlaybackTimeSeconds = 0.0;
        bPlaybackStarted = false;
        SupportedBehaviors.Reset();
    }
    if (!bChanged)
    {
        return;
    }
    bServiceReady = bReady;
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
    OutBatch = FFayBodyPoseBatch();
    OutError.Reset();
    TSharedPtr<FJsonObject> Object;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Object) || !Object.IsValid())
    {
        OutError = TEXT("invalid JSON");
        return false;
    }
    double Version = 0.0;
    double FramesPerSecond = 0.0;
    double SequenceNumber = 0.0;
    FString CoordinateSystem;
    const TSharedPtr<FJsonObject>* Source = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Frames = nullptr;
    if (Object->Values.Num() != 6 ||
        !Object->TryGetNumberField(TEXT("version"), Version) ||
        Version != static_cast<double>(ExpectedProtocolVersion) ||
        !Object->TryGetNumberField(TEXT("sequence"), SequenceNumber) ||
        !FMath::IsFinite(SequenceNumber) || SequenceNumber < 1.0 ||
        SequenceNumber >= ExclusiveInt64UpperBound ||
        SequenceNumber != FMath::FloorToDouble(SequenceNumber) ||
        !Object->TryGetNumberField(TEXT("fps"), FramesPerSecond) ||
        FramesPerSecond != static_cast<double>(ExpectedFramesPerSecond) ||
        !Object->TryGetStringField(TEXT("coordinateSystem"), CoordinateSystem) ||
        CoordinateSystem != ExpectedCoordinateSystem ||
        !Object->TryGetObjectField(TEXT("source"), Source) || Source == nullptr ||
        !ValidateSourceDescriptor(*Source) ||
        !Object->TryGetArrayField(TEXT("frames"), Frames) || Frames == nullptr ||
        Frames->Num() != TargetBufferFrames)
    {
        OutError = TEXT("invalid batch envelope");
        return false;
    }
    OutBatch.Version = static_cast<int32>(Version);
    OutBatch.Sequence = static_cast<int64>(SequenceNumber);
    OutBatch.FramesPerSecond = static_cast<int32>(FramesPerSecond);
    OutBatch.CoordinateSystem = CoordinateSystem;
    double PreviousTime = -1.0;
    FVector3f PreviousRootTranslationMetres = FVector3f::ZeroVector;
    bool bHasPreviousRootTranslation = false;
    FQuat4f PreviousRootRotation = FQuat4f::Identity;
    TArray<FQuat4f> PreviousJointRotations;
    bool bHasPreviousRotations = false;
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
        const TArray<TSharedPtr<FJsonValue>>* Positions = nullptr;
        const TArray<TSharedPtr<FJsonValue>>* Contacts = nullptr;
        if ((*FrameObject)->Values.Num() != 5 ||
            !(*FrameObject)->TryGetNumberField(TEXT("time"), Frame.TimeSeconds) ||
            !FMath::IsFinite(Frame.TimeSeconds) || Frame.TimeSeconds < 0.0 ||
            (PreviousTime >= 0.0 &&
                !FMath::IsNearlyEqual(
                    Frame.TimeSeconds - PreviousTime,
                    ExpectedFrameStepSeconds,
                    0.0001)) ||
            !(*FrameObject)->TryGetArrayField(TEXT("root"), Root) || Root == nullptr ||
            Root->Num() != 7 ||
            !(*FrameObject)->TryGetArrayField(TEXT("joints"), Joints) || Joints == nullptr ||
            Joints->Num() != ExpectedJointCount ||
            !(*FrameObject)->TryGetArrayField(TEXT("positions"), Positions) ||
            Positions == nullptr || Positions->Num() != ExpectedJointCount ||
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
        if (bHasPreviousRotations)
        {
            StabilizeQuaternionHemisphere(PreviousRootRotation, Frame.RootRotation);
        }
        Frame.RootTranslationMetres = FVector3f(
            static_cast<float>(X), static_cast<float>(Y), static_cast<float>(Z));
        if (Frame.RootTranslationMetres.Size() > MaximumRootTranslationMetres)
        {
            OutError = TEXT("root translation exceeds the sealed bound");
            return false;
        }
        if (bHasPreviousRootTranslation &&
            (Frame.RootTranslationMetres - PreviousRootTranslationMetres).Size() >
                MaximumRootFrameStepMetres)
        {
            OutError = TEXT("root translation changes too far between frames");
            return false;
        }
        PreviousRootTranslationMetres = Frame.RootTranslationMetres;
        bHasPreviousRootTranslation = true;
        for (int32 JointIndex = 0; JointIndex < Joints->Num(); ++JointIndex)
        {
            const TSharedPtr<FJsonValue>& JointValue = (*Joints)[JointIndex];
            const TArray<TSharedPtr<FJsonValue>>* Rotation = nullptr;
            FQuat4f Quaternion;
            if (!JointValue.IsValid() || !JointValue->TryGetArray(Rotation) ||
                Rotation == nullptr || !ReadQuaternion(*Rotation, Quaternion))
            {
                OutError = TEXT("invalid joint quaternion");
                return false;
            }
            if (bHasPreviousRotations)
            {
                StabilizeQuaternionHemisphere(
                    PreviousJointRotations[JointIndex],
                    Quaternion);
            }
            Frame.JointRotations.Add(Quaternion);
        }
        for (const TSharedPtr<FJsonValue>& PositionValue : *Positions)
        {
            const TArray<TSharedPtr<FJsonValue>>* Position = nullptr;
            double PositionX = 0.0;
            double PositionY = 0.0;
            double PositionZ = 0.0;
            if (!PositionValue.IsValid() || !PositionValue->TryGetArray(Position) ||
                Position == nullptr || Position->Num() != 3 ||
                !ReadFiniteNumber(*Position, 0, PositionX) ||
                !ReadFiniteNumber(*Position, 1, PositionY) ||
                !ReadFiniteNumber(*Position, 2, PositionZ))
            {
                OutError = TEXT("invalid global joint position");
                return false;
            }
            const FVector3f JointPosition(
                static_cast<float>(PositionX),
                static_cast<float>(PositionY),
                static_cast<float>(PositionZ));
            if (JointPosition.Size() > MaximumJointPositionMetres)
            {
                OutError = TEXT("global joint position exceeds the sealed bound");
                return false;
            }
            Frame.JointPositionsMetres.Add(JointPosition);
        }
        const FVector3f& HipsPosition = Frame.JointPositionsMetres[0];
        if (FMath::Abs(Frame.RootTranslationMetres.X - HipsPosition.X) >
                RootPositionConsistencyToleranceMetres ||
            FMath::Abs(Frame.RootTranslationMetres.Y - HipsPosition.Y) >
                RootPositionConsistencyToleranceMetres ||
            FMath::Abs(Frame.RootTranslationMetres.Z - HipsPosition.Z) >
                RootPositionConsistencyToleranceMetres)
        {
            OutError = TEXT("root translation does not match global Hips position");
            return false;
        }
        const FQuat4f& HipsRotation = Frame.JointRotations[0];
        const float RootHipsRotationDot = FMath::Abs(
            Frame.RootRotation.X * HipsRotation.X +
            Frame.RootRotation.Y * HipsRotation.Y +
            Frame.RootRotation.Z * HipsRotation.Z +
            Frame.RootRotation.W * HipsRotation.W);
        if (!FMath::IsFinite(RootHipsRotationDot) ||
            RootHipsRotationDot < RootRotationConsistencyDotThreshold)
        {
            OutError = TEXT("root rotation does not match local Hips rotation");
            return false;
        }
        for (int32 Index = 0; Index < 4; ++Index)
        {
            double Contact = 0.0;
            if (!ReadFiniteNumber(*Contacts, Index, Contact) ||
                Contact < 0.0 || Contact > 1.0)
            {
                OutError = TEXT("invalid contact value");
                return false;
            }
            Frame.Contacts.Add(static_cast<float>(Contact));
        }
        PreviousRootRotation = Frame.RootRotation;
        PreviousJointRotations = Frame.JointRotations;
        bHasPreviousRotations = true;
        OutBatch.Frames.Add(MoveTemp(Frame));
    }
    const auto IsIdentityRotation = [](const FQuat4f& Rotation)
    {
        return FMath::Abs(Rotation.X) <= 0.0001f &&
            FMath::Abs(Rotation.Y) <= 0.0001f &&
            FMath::Abs(Rotation.Z) <= 0.0001f &&
            FMath::Abs(FMath::Abs(Rotation.W) - 1.0f) <= 0.0001f;
    };
    for (const FFayArdyPoseFrame& Frame : OutBatch.Frames)
    {
        if (!IsIdentityRotation(Frame.JointRotations[NeckJointIndex]) ||
            !IsIdentityRotation(Frame.JointRotations[HeadJointIndex]))
        {
            OutError = TEXT("generated neck or head rotation is not excluded");
            return false;
        }
    }
    return true;
}

bool UFayArdyPoseClientComponent::IsEndpointSealed() const
{
    return BaseUrl == TEXT("http://127.0.0.1:8777");
}

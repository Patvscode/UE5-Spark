#include "FayArkitSpeechDriverComponent.h"

#include "Animation/MorphTarget.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/Actor.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayArkitRuntime, Log, All);

namespace
{
const FName JawOpenMorph(TEXT("jawOpen"));
const FName MouthCloseMorph(TEXT("mouthClose"));
const FName MouthFunnelMorph(TEXT("mouthFunnel"));
const FName MouthPuckerMorph(TEXT("mouthPucker"));
const FName MouthSmileLeftMorph(TEXT("mouthSmileLeft"));
const FName MouthSmileLeftUnrealMorph(TEXT("mouthSmile_L"));
const FName MouthSmileRightMorph(TEXT("mouthSmileRight"));
const FName MouthSmileRightUnrealMorph(TEXT("mouthSmile_R"));
const FName EyeBlinkLeftMorph(TEXT("eyeBlinkLeft"));
const FName EyeBlinkLeftUnrealMorph(TEXT("eyeBlink_L"));
const FName EyeBlinkRightMorph(TEXT("eyeBlinkRight"));
const FName EyeBlinkRightUnrealMorph(TEXT("eyeBlink_R"));
constexpr int32 ReviewedArkitMorphCount = 8;

struct FResolvedArkitMorphContract
{
    FName JawOpen = NAME_None;
    FName MouthClose = NAME_None;
    FName MouthFunnel = NAME_None;
    FName MouthPucker = NAME_None;
    FName MouthSmileLeft = NAME_None;
    FName MouthSmileRight = NAME_None;
    FName EyeBlinkLeft = NAME_None;
    FName EyeBlinkRight = NAME_None;
};

FString GetStableComponentName(const USkeletalMeshComponent* Component)
{
    FString StableName = Component != nullptr ? Component->GetName() : FString();
    StableName.RemoveFromEnd(TEXT("_GEN_VARIABLE"));
    return StableName;
}

bool ResolveReviewedMorph(
    const USkeletalMesh* Mesh,
    const FName Primary,
    const FName ReviewedAlternate,
    FName& OutResolved)
{
    if (!IsValid(Mesh))
    {
        return false;
    }
    if (const UMorphTarget* Morph = Mesh->FindMorphTarget(Primary))
    {
        OutResolved = Morph->GetFName();
        return true;
    }
    if (!ReviewedAlternate.IsNone())
    {
        if (const UMorphTarget* Morph = Mesh->FindMorphTarget(ReviewedAlternate))
        {
            OutResolved = Morph->GetFName();
            return true;
        }
    }
    return false;
}

bool ResolveCompleteReviewedMorphContract(
    const USkeletalMesh* Mesh,
    FResolvedArkitMorphContract& OutContract,
    FString& OutMissingMorphs)
{
    OutContract = FResolvedArkitMorphContract();
    OutMissingMorphs.Reset();
    if (!IsValid(Mesh))
    {
        OutMissingMorphs = TEXT("<skeletal-mesh-unavailable>");
        return false;
    }

    TArray<FString, TInlineAllocator<8>> Missing;
    const auto Resolve = [Mesh, &Missing](
        const TCHAR* Label,
        const FName Primary,
        const FName ReviewedAlternate,
        FName& OutResolved)
    {
        if (!ResolveReviewedMorph(Mesh, Primary, ReviewedAlternate, OutResolved))
        {
            Missing.Add(Label);
        }
    };
    Resolve(TEXT("jawOpen"), JawOpenMorph, NAME_None, OutContract.JawOpen);
    Resolve(TEXT("mouthClose"), MouthCloseMorph, NAME_None, OutContract.MouthClose);
    Resolve(TEXT("mouthFunnel"), MouthFunnelMorph, NAME_None, OutContract.MouthFunnel);
    Resolve(TEXT("mouthPucker"), MouthPuckerMorph, NAME_None, OutContract.MouthPucker);
    Resolve(
        TEXT("mouthSmileLeft|mouthSmile_L"),
        MouthSmileLeftMorph,
        MouthSmileLeftUnrealMorph,
        OutContract.MouthSmileLeft);
    Resolve(
        TEXT("mouthSmileRight|mouthSmile_R"),
        MouthSmileRightMorph,
        MouthSmileRightUnrealMorph,
        OutContract.MouthSmileRight);
    Resolve(
        TEXT("eyeBlinkLeft|eyeBlink_L"),
        EyeBlinkLeftMorph,
        EyeBlinkLeftUnrealMorph,
        OutContract.EyeBlinkLeft);
    Resolve(
        TEXT("eyeBlinkRight|eyeBlink_R"),
        EyeBlinkRightMorph,
        EyeBlinkRightUnrealMorph,
        OutContract.EyeBlinkRight);
    OutMissingMorphs = FString::Join(Missing, TEXT(", "));
    return Missing.IsEmpty();
}

bool IsPositiveExpressionMessage(const FFayAvatarMessage& Message)
{
    FString Meaning = Message.Action.Affect.ToLower();
    Meaning.AppendChar(TEXT(' '));
    Meaning.Append(Message.Action.Behavior.ToLower());
    return Meaning.Contains(TEXT("happy")) || Meaning.Contains(TEXT("joy")) ||
        Meaning.Contains(TEXT("smile")) || Meaning.Contains(TEXT("friendly")) ||
        Meaning.Contains(TEXT("playful")) || Meaning.Contains(TEXT("excit"));
}
}

UFayArkitSpeechDriverComponent::UFayArkitSpeechDriverComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
    PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UFayArkitSpeechDriverComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    AttachBridge(nullptr);
    ClearAvatar();
    Super::EndPlay(EndPlayReason);
}

void UFayArkitSpeechDriverComponent::AttachBridge(UFayAvatarBridgeComponent* InBridge)
{
    if (Bridge == InBridge)
    {
        return;
    }

    if (Bridge != nullptr)
    {
        Bridge->OnMessageReceived.RemoveDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleAvatarMessage);
        Bridge->OnSpeechStarted.RemoveDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleSpeechStarted);
        Bridge->OnSpeechFinished.RemoveDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleSpeechFinished);
        Bridge->OnMouthAmplitude.RemoveDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleMouthAmplitude);
    }

    Bridge = InBridge;
    bSpeechActive = false;
    TargetMouthAmplitude = 0.0f;
    TargetSmile = 0.0f;
    SmileHoldRemainingSeconds = 0.0f;

    if (Bridge != nullptr)
    {
        Bridge->OnMessageReceived.AddUniqueDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleAvatarMessage);
        Bridge->OnSpeechStarted.AddUniqueDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleSpeechStarted);
        Bridge->OnSpeechFinished.AddUniqueDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleSpeechFinished);
        Bridge->OnMouthAmplitude.AddUniqueDynamic(
            this,
            &UFayArkitSpeechDriverComponent::HandleMouthAmplitude);
    }
}

bool UFayArkitSpeechDriverComponent::ConfigureAvatar(
    AActor* InAvatar,
    const FName FaceComponentName)
{
    if (!IsValid(InAvatar) || FaceComponentName.IsNone())
    {
        UE_LOG(LogFayArkitRuntime, Error,
            TEXT("Rejected ARKit avatar configuration without an exact actor and face-component name."));
        return false;
    }

    USkeletalMeshComponent* CandidateFaceMesh = nullptr;
    TInlineComponentArray<USkeletalMeshComponent*> SkeletalMeshes(InAvatar);
    for (USkeletalMeshComponent* Candidate : SkeletalMeshes)
    {
        if (!IsValid(Candidate) || Candidate->GetOwner() != InAvatar ||
            GetStableComponentName(Candidate) != FaceComponentName.ToString())
        {
            continue;
        }
        if (CandidateFaceMesh != nullptr)
        {
            UE_LOG(LogFayArkitRuntime, Error,
                TEXT("Rejected ARKit avatar '%s': face component name '%s' is ambiguous."),
                *InAvatar->GetName(),
                *FaceComponentName.ToString());
            return false;
        }
        CandidateFaceMesh = Candidate;
    }

    if (!IsValid(CandidateFaceMesh))
    {
        UE_LOG(LogFayArkitRuntime, Error,
            TEXT("Rejected ARKit avatar '%s': exact skeletal face component '%s' was not found."),
            *InAvatar->GetName(),
            *FaceComponentName.ToString());
        return false;
    }

    USkeletalMesh* CandidateAsset = CandidateFaceMesh->GetSkeletalMeshAsset();
    FResolvedArkitMorphContract ResolvedContract;
    FString MissingMorphs;
    if (!ResolveCompleteReviewedMorphContract(
            CandidateAsset,
            ResolvedContract,
            MissingMorphs))
    {
        UE_LOG(LogFayArkitRuntime, Error,
            TEXT("Rejected ARKit avatar '%s': face '%s' is missing reviewed morphs: %s."),
            *InAvatar->GetName(),
            *FaceComponentName.ToString(),
            *MissingMorphs);
        return false;
    }

    if (IsConfigured() && Avatar == InAvatar && FaceMesh == CandidateFaceMesh &&
        ReviewedSkeletalMeshAsset == CandidateAsset &&
        ReviewedFaceComponentName == FaceComponentName)
    {
        return true;
    }

    // The complete candidate is reviewed before the currently configured face
    // is touched, so an invalid reconfiguration request cannot disturb it.
    ClearAvatar();
    Avatar = InAvatar;
    FaceMesh = CandidateFaceMesh;
    ReviewedSkeletalMeshAsset = CandidateAsset;
    ReviewedFaceComponentName = FaceComponentName;
    ResolvedJawOpenMorph = ResolvedContract.JawOpen;
    ResolvedMouthCloseMorph = ResolvedContract.MouthClose;
    ResolvedMouthFunnelMorph = ResolvedContract.MouthFunnel;
    ResolvedMouthPuckerMorph = ResolvedContract.MouthPucker;
    ResolvedMouthSmileLeftMorph = ResolvedContract.MouthSmileLeft;
    ResolvedMouthSmileRightMorph = ResolvedContract.MouthSmileRight;
    ResolvedEyeBlinkLeftMorph = ResolvedContract.EyeBlinkLeft;
    ResolvedEyeBlinkRightMorph = ResolvedContract.EyeBlinkRight;
    BlinkRandomStream.Initialize(static_cast<int32>(GetTypeHash(InAvatar->GetPathName())));
    ResetRuntimeState();
    ResetDrivenMorphs(FaceMesh);
    ScheduleNextBlink();

    UE_LOG(LogFayArkitRuntime, Display,
        TEXT("Configured reviewed ARKit face '%s.%s' with %d fixed morph targets."),
        *InAvatar->GetName(),
        *FaceComponentName.ToString(),
        ReviewedArkitMorphCount);
    return true;
}

void UFayArkitSpeechDriverComponent::ClearAvatar()
{
    if (IsValid(FaceMesh) && IsValid(ReviewedSkeletalMeshAsset) &&
        FaceMesh->GetSkeletalMeshAsset() == ReviewedSkeletalMeshAsset)
    {
        ResetDrivenMorphs(FaceMesh);
    }

    Avatar = nullptr;
    FaceMesh = nullptr;
    ReviewedSkeletalMeshAsset = nullptr;
    ReviewedFaceComponentName = NAME_None;
    ResolvedJawOpenMorph = NAME_None;
    ResolvedMouthCloseMorph = NAME_None;
    ResolvedMouthFunnelMorph = NAME_None;
    ResolvedMouthPuckerMorph = NAME_None;
    ResolvedMouthSmileLeftMorph = NAME_None;
    ResolvedMouthSmileRightMorph = NAME_None;
    ResolvedEyeBlinkLeftMorph = NAME_None;
    ResolvedEyeBlinkRightMorph = NAME_None;
    ResetRuntimeState();
}

bool UFayArkitSpeechDriverComponent::IsConfigured() const
{
    return IsValid(Avatar) && IsValid(FaceMesh) &&
        IsValid(ReviewedSkeletalMeshAsset) && FaceMesh->GetOwner() == Avatar &&
        FaceMesh->GetSkeletalMeshAsset() == ReviewedSkeletalMeshAsset &&
        !ReviewedFaceComponentName.IsNone() &&
        !ResolvedJawOpenMorph.IsNone() && !ResolvedMouthCloseMorph.IsNone() &&
        !ResolvedMouthFunnelMorph.IsNone() && !ResolvedMouthPuckerMorph.IsNone() &&
        !ResolvedMouthSmileLeftMorph.IsNone() &&
        !ResolvedMouthSmileRightMorph.IsNone() &&
        !ResolvedEyeBlinkLeftMorph.IsNone() &&
        !ResolvedEyeBlinkRightMorph.IsNone() &&
        GetStableComponentName(FaceMesh) == ReviewedFaceComponentName.ToString();
}

void UFayArkitSpeechDriverComponent::HandleAvatarMessage(
    const FFayAvatarMessage& Message)
{
    if (!IsConfigured())
    {
        return;
    }

    const float Sentiment = FMath::IsFinite(Message.Sentiment)
        ? FMath::Clamp(Message.Sentiment, -1.0f, 1.0f)
        : 0.0f;
    const float SentimentSmile = FMath::Max(0.0f, Sentiment) * PositiveSmileScale;
    const float SemanticSmile = IsPositiveExpressionMessage(Message)
        ? PositiveSmileScale * 0.75f
        : 0.0f;
    TargetSmile = FMath::Clamp(
        FMath::Max(SentimentSmile, SemanticSmile),
        0.0f,
        PositiveSmileScale);
    SmileHoldRemainingSeconds = TargetSmile > KINDA_SMALL_NUMBER ? 1.4f : 0.0f;
}

void UFayArkitSpeechDriverComponent::HandleSpeechStarted(
    const FFayAvatarMessage& Message,
    const float DurationSeconds)
{
    (void)Message;
    (void)DurationSeconds;
    if (!IsConfigured())
    {
        return;
    }
    bSpeechActive = true;
    TargetMouthAmplitude = Bridge != nullptr
        ? FMath::Clamp(Bridge->GetMouthAmplitude(), 0.0f, 1.0f)
        : 0.0f;
    SpeechArticulationPhase = 0.0f;
}

void UFayArkitSpeechDriverComponent::HandleSpeechFinished(
    const FFayAvatarMessage& Message)
{
    (void)Message;
    bSpeechActive = false;
    TargetMouthAmplitude = 0.0f;
}

void UFayArkitSpeechDriverComponent::HandleMouthAmplitude(const float Amplitude)
{
    if (!IsConfigured() || !bSpeechActive)
    {
        TargetMouthAmplitude = 0.0f;
        return;
    }
    TargetMouthAmplitude = FMath::IsFinite(Amplitude)
        ? FMath::Clamp(Amplitude, 0.0f, 1.0f)
        : 0.0f;
}

void UFayArkitSpeechDriverComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    if (Avatar == nullptr && FaceMesh == nullptr)
    {
        return;
    }
    if (!IsConfigured())
    {
        InvalidateConfiguration(TEXT("the reviewed actor, component, or skeletal mesh changed at runtime"));
        return;
    }

    const float SafeDeltaTime = FMath::IsFinite(DeltaTime)
        ? FMath::Max(0.0f, DeltaTime)
        : 0.0f;
    if (SafeDeltaTime <= 0.0f)
    {
        return;
    }

    if (SmileHoldRemainingSeconds > 0.0f)
    {
        SmileHoldRemainingSeconds = FMath::Max(
            0.0f,
            SmileHoldRemainingSeconds - SafeDeltaTime);
    }
    else
    {
        TargetSmile = SmoothCurve(TargetSmile, 0.0f, 1.4f, SafeDeltaTime);
    }

    SpeechArticulationPhase = FMath::Fmod(
        SpeechArticulationPhase + SafeDeltaTime * 13.0f,
        2.0f * PI);
    const float MouthAmplitude = bSpeechActive
        ? FMath::Clamp(TargetMouthAmplitude, 0.0f, 1.0f)
        : 0.0f;
    const float ArticulationWave = 0.5f + 0.5f * FMath::Sin(SpeechArticulationPhase);
    const float RootAmplitude = FMath::Sqrt(MouthAmplitude);
    const float LowEnergyClosure = bSpeechActive
        ? FMath::Clamp(1.0f - MouthAmplitude * 6.0f, 0.0f, 1.0f)
        : 0.0f;

    const float JawTarget = MouthAmplitude * FMath::Clamp(JawOpenScale, 0.0f, 1.0f);
    const float CloseTarget = LowEnergyClosure * FMath::Clamp(MouthCloseScale, 0.0f, 0.25f);
    const float FunnelTarget = RootAmplitude * (0.45f + 0.55f * ArticulationWave) *
        FMath::Clamp(MouthFunnelScale, 0.0f, 0.25f);
    const float PuckerTarget = RootAmplitude * (1.0f - 0.45f * ArticulationWave) *
        FMath::Clamp(MouthPuckerScale, 0.0f, 0.25f);
    const float SmileTarget = FMath::Clamp(TargetSmile, 0.0f, 0.35f) *
        (1.0f - 0.45f * MouthAmplitude);
    const float BlinkTarget = UpdateBlink(SafeDeltaTime);

    const float SafeSmoothingSpeed = FMath::Clamp(MorphSmoothingSpeed, 1.0f, 60.0f);
    CurrentJawOpen = SmoothCurve(CurrentJawOpen, JawTarget, SafeSmoothingSpeed, SafeDeltaTime);
    CurrentMouthClose = SmoothCurve(CurrentMouthClose, CloseTarget, SafeSmoothingSpeed, SafeDeltaTime);
    CurrentMouthFunnel = SmoothCurve(CurrentMouthFunnel, FunnelTarget, SafeSmoothingSpeed, SafeDeltaTime);
    CurrentMouthPucker = SmoothCurve(CurrentMouthPucker, PuckerTarget, SafeSmoothingSpeed, SafeDeltaTime);
    CurrentMouthSmile = SmoothCurve(CurrentMouthSmile, SmileTarget, SafeSmoothingSpeed * 0.45f, SafeDeltaTime);
    CurrentBlink = SmoothCurve(CurrentBlink, BlinkTarget, 52.0f, SafeDeltaTime);
    ApplyDrivenMorphs();
}

void UFayArkitSpeechDriverComponent::ResetRuntimeState()
{
    TargetMouthAmplitude = 0.0f;
    TargetSmile = 0.0f;
    SmileHoldRemainingSeconds = 0.0f;
    SpeechArticulationPhase = 0.0f;
    SecondsUntilNextBlink = 0.0f;
    BlinkElapsedSeconds = -1.0f;
    CurrentJawOpen = 0.0f;
    CurrentMouthClose = 0.0f;
    CurrentMouthFunnel = 0.0f;
    CurrentMouthPucker = 0.0f;
    CurrentMouthSmile = 0.0f;
    CurrentBlink = 0.0f;
    bSpeechActive = false;
}

void UFayArkitSpeechDriverComponent::ResetDrivenMorphs(
    USkeletalMeshComponent* InFaceMesh) const
{
    if (!IsValid(InFaceMesh))
    {
        return;
    }
    for (const FName MorphTarget : {
             ResolvedJawOpenMorph,
             ResolvedMouthCloseMorph,
             ResolvedMouthFunnelMorph,
             ResolvedMouthPuckerMorph,
             ResolvedMouthSmileLeftMorph,
             ResolvedMouthSmileRightMorph,
             ResolvedEyeBlinkLeftMorph,
             ResolvedEyeBlinkRightMorph})
    {
        // Keep zero-weight entries installed so no unrelated system is asked
        // to clear its own active morph set.
        if (!MorphTarget.IsNone())
        {
            InFaceMesh->SetMorphTarget(MorphTarget, 0.0f, false);
        }
    }
}

void UFayArkitSpeechDriverComponent::ApplyDrivenMorphs()
{
    if (!IsConfigured())
    {
        return;
    }

    FaceMesh->SetMorphTarget(ResolvedJawOpenMorph, FMath::Clamp(CurrentJawOpen, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedMouthCloseMorph, FMath::Clamp(CurrentMouthClose, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedMouthFunnelMorph, FMath::Clamp(CurrentMouthFunnel, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedMouthPuckerMorph, FMath::Clamp(CurrentMouthPucker, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedMouthSmileLeftMorph, FMath::Clamp(CurrentMouthSmile, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedMouthSmileRightMorph, FMath::Clamp(CurrentMouthSmile, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedEyeBlinkLeftMorph, FMath::Clamp(CurrentBlink, 0.0f, 1.0f), false);
    FaceMesh->SetMorphTarget(ResolvedEyeBlinkRightMorph, FMath::Clamp(CurrentBlink, 0.0f, 1.0f), false);
}

void UFayArkitSpeechDriverComponent::InvalidateConfiguration(const TCHAR* Reason)
{
    UE_LOG(LogFayArkitRuntime, Error,
        TEXT("Stopped ARKit face output because %s. Neutral was not written to an unreviewed mesh."),
        Reason != nullptr ? Reason : TEXT("the runtime contract failed"));
    Avatar = nullptr;
    FaceMesh = nullptr;
    ReviewedSkeletalMeshAsset = nullptr;
    ReviewedFaceComponentName = NAME_None;
    ResolvedJawOpenMorph = NAME_None;
    ResolvedMouthCloseMorph = NAME_None;
    ResolvedMouthFunnelMorph = NAME_None;
    ResolvedMouthPuckerMorph = NAME_None;
    ResolvedMouthSmileLeftMorph = NAME_None;
    ResolvedMouthSmileRightMorph = NAME_None;
    ResolvedEyeBlinkLeftMorph = NAME_None;
    ResolvedEyeBlinkRightMorph = NAME_None;
    ResetRuntimeState();
}

void UFayArkitSpeechDriverComponent::ScheduleNextBlink()
{
    const float MinimumInterval = FMath::Clamp(MinimumBlinkIntervalSeconds, 1.0f, 30.0f);
    const float MaximumInterval = FMath::Clamp(
        MaximumBlinkIntervalSeconds,
        MinimumInterval,
        30.0f);
    SecondsUntilNextBlink = BlinkRandomStream.FRandRange(MinimumInterval, MaximumInterval);
    BlinkElapsedSeconds = -1.0f;
}

float UFayArkitSpeechDriverComponent::UpdateBlink(const float DeltaTime)
{
    if (!bEnableProceduralBlink)
    {
        return 0.0f;
    }

    if (BlinkElapsedSeconds < 0.0f)
    {
        SecondsUntilNextBlink -= DeltaTime;
        if (SecondsUntilNextBlink <= 0.0f)
        {
            BlinkElapsedSeconds = 0.0f;
        }
        return 0.0f;
    }

    const float SafeBlinkDuration = FMath::Clamp(BlinkDurationSeconds, 0.08f, 0.5f);
    BlinkElapsedSeconds += DeltaTime;
    const float Progress = FMath::Clamp(BlinkElapsedSeconds / SafeBlinkDuration, 0.0f, 1.0f);
    if (Progress >= 1.0f)
    {
        ScheduleNextBlink();
        return 0.0f;
    }

    // Fast close and slower reopen approximate an ordinary bilateral blink.
    const float Shape = Progress < 0.35f
        ? Progress / 0.35f
        : 1.0f - ((Progress - 0.35f) / 0.65f);
    return FMath::Clamp(Shape, 0.0f, 1.0f) * FMath::Clamp(BlinkStrength, 0.0f, 1.0f);
}

float UFayArkitSpeechDriverComponent::SmoothCurve(
    const float Current,
    const float Target,
    const float Speed,
    const float DeltaTime)
{
    if (DeltaTime <= 0.0f)
    {
        return Current;
    }
    const float Alpha = 1.0f - FMath::Exp(-FMath::Max(0.0f, Speed) * DeltaTime);
    return FMath::Lerp(Current, Target, FMath::Clamp(Alpha, 0.0f, 1.0f));
}

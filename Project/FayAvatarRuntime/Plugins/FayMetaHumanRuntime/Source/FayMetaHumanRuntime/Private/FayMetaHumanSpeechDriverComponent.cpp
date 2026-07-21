#include "FayMetaHumanSpeechDriverComponent.h"

#include "Animation/AnimInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/World.h"
#include "Features/IModularFeatures.h"
#include "GameFramework/Actor.h"
#include "GuiToRawControlsUtils.h"
#include "HAL/UnrealMemory.h"
#include "ILiveLinkClient.h"
#include "ILiveLinkSource.h"
#include "LiveLinkInstance.h"
#include "LiveLinkTypes.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "NNEModelData.h"
#include "Roles/LiveLinkBasicRole.h"
#include "Roles/LiveLinkBasicTypes.h"
#include "SpeechAnimationSolverTypes.h"
#include "SpeechAnimationSolverV4.h"
#include "UObject/Class.h"
#include "UObject/Package.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayMetaHumanRuntime, Log, All);

namespace
{
constexpr int32 SolverFramesPerSecond = 50;
constexpr int32 SolverSampleRate = 16000;
constexpr int32 TailSolveSteps = 10;
constexpr int32 ExtraLiveLinkProperties = 9;
constexpr int32 ExpectedSolverCurveCount = 81;
constexpr int32 ExpectedRawControlCount = 251;
constexpr float LiveLinkHeartbeatSeconds = 0.10f;
constexpr float LiveLinkPendingGraceSeconds = 2.0f;
constexpr float MinimumHeadGestureDegrees = 4.0f;
constexpr float HardMaximumHeadGestureDegrees = 12.0f;

const FName HeadControlSwitchName(TEXT("HeadControlSwitch"));
const FName HeadRollName(TEXT("HeadRoll"));
const FName HeadPitchName(TEXT("HeadPitch"));
const FName HeadYawName(TEXT("HeadYaw"));
const FName HeadTranslationXName(TEXT("HeadTranslationX"));
const FName HeadTranslationYName(TEXT("HeadTranslationY"));
const FName HeadTranslationZName(TEXT("HeadTranslationZ"));
const FName DataVersionName(TEXT("MHFDSVersion"));
const FName DisableFaceOverrideName(TEXT("DisableFaceOverride"));

enum class EFaySemanticHeadGesture : uint8
{
    None,
    Nod,
    Shake,
    Think,
    Warn,
    BodyOwnedWave,
    BodyOwnedInvite
};

enum class EFayLiveLinkSubjectReadiness : uint8
{
    Pending,
    Ready,
    Collision,
    Invalid
};

struct FFayHeadPose
{
    float RollDegrees = 0.0f;
    float PitchDegrees = 0.0f;
    float YawDegrees = 0.0f;
    bool bDriveOrientation = false;
};

class FFaySpeechLiveLinkSource final : public ILiveLinkSource
{
public:
    explicit FFaySpeechLiveLinkSource(const FName InSubjectName)
        : SubjectName(InSubjectName)
    {
    }

    virtual void ReceiveClient(ILiveLinkClient* InClient, const FGuid InSourceGuid) override
    {
        Client = InClient;
        SourceGuid = InSourceGuid;
        PushStaticData();
    }

    virtual bool IsSourceStillValid() const override
    {
        return !bShutdownRequested && Client != nullptr && SourceGuid.IsValid();
    }

    virtual bool RequestSourceShutdown() override
    {
        bShutdownRequested = true;
        bStaticDataQueued = false;
        Client = nullptr;
        SourceGuid.Invalidate();
        return true;
    }

    virtual FText GetSourceType() const override
    {
        return FText::FromString(TEXT("Fay local speech animation"));
    }

    virtual FText GetSourceMachineName() const override
    {
        return FText::FromString(TEXT("localhost"));
    }

    virtual FText GetSourceStatus() const override
    {
        return FText::FromString(IsSourceStillValid() ? TEXT("Active") : TEXT("Stopped"));
    }

    void SetPropertyNames(const TArray<FName>& InPropertyNames)
    {
        PropertyNames = InPropertyNames;
        bStaticDataQueued = false;
        PushStaticData();
    }

    bool CanPublish() const
    {
        return IsSourceStillValid() && bStaticDataQueued;
    }

    FName GetSubjectName() const
    {
        return SubjectName;
    }

    EFayLiveLinkSubjectReadiness GetExactSubjectReadiness(FString& OutReason) const
    {
        OutReason.Reset();
        if (!CanPublish())
        {
            OutReason = TEXT("the source has not queued its static data");
            return EFayLiveLinkSubjectReadiness::Pending;
        }

        const FLiveLinkSubjectKey SubjectKey(SourceGuid, SubjectName);
        bool bFoundExactSubject = false;
        for (const FLiveLinkSubjectKey& ExistingSubject : Client->GetSubjects(true, true))
        {
            if (!(ExistingSubject.SubjectName == SubjectKey.SubjectName))
            {
                continue;
            }
            if (ExistingSubject != SubjectKey)
            {
                OutReason = FString::Printf(
                    TEXT("another Live Link source already owns subject '%s'"),
                    *SubjectName.ToString());
                return EFayLiveLinkSubjectReadiness::Collision;
            }
            bFoundExactSubject = true;
        }

        if (!bFoundExactSubject)
        {
            OutReason = TEXT("the exact subject has not been processed by Live Link yet");
            return EFayLiveLinkSubjectReadiness::Pending;
        }
        if (Client->GetSubjectRole_AnyThread(SubjectKey) != ULiveLinkBasicRole::StaticClass())
        {
            OutReason = TEXT("the exact subject does not have the Live Link Basic role");
            return EFayLiveLinkSubjectReadiness::Invalid;
        }

        const FLiveLinkStaticDataStruct* StaticDataStruct =
            Client->GetSubjectStaticData_AnyThread(SubjectKey, false);
        const FLiveLinkBaseStaticData* StaticData = StaticDataStruct != nullptr
            ? StaticDataStruct->Cast<FLiveLinkBaseStaticData>()
            : nullptr;
        if (StaticData == nullptr || StaticData->PropertyNames != PropertyNames)
        {
            OutReason = TEXT("the exact subject has not accepted the required static schema");
            return EFayLiveLinkSubjectReadiness::Pending;
        }
        if (!Client->IsSubjectEnabled(SubjectKey, false))
        {
            OutReason = TEXT("the exact subject is disabled");
            return EFayLiveLinkSubjectReadiness::Invalid;
        }
        if (!Client->IsSubjectEnabled(SubjectKey, true) || !Client->IsSubjectValid(SubjectKey))
        {
            OutReason = TEXT("the exact subject has not entered the current Live Link snapshot");
            return EFayLiveLinkSubjectReadiness::Pending;
        }

        FLiveLinkSubjectFrameData EvaluatedFrame;
        if (!Client->EvaluateFrameFromSource_AnyThread(
                SubjectKey,
                ULiveLinkBasicRole::StaticClass(),
                EvaluatedFrame))
        {
            OutReason = TEXT("the exact subject does not yet have an evaluable frame");
            return EFayLiveLinkSubjectReadiness::Pending;
        }
        const FLiveLinkBaseFrameData* FrameData =
            EvaluatedFrame.FrameData.Cast<FLiveLinkBaseFrameData>();
        if (FrameData == nullptr || FrameData->PropertyValues.Num() != PropertyNames.Num())
        {
            OutReason = TEXT("the exact subject's evaluated frame does not match its static schema");
            return EFayLiveLinkSubjectReadiness::Invalid;
        }
        return EFayLiveLinkSubjectReadiness::Ready;
    }

    bool PushValues(
        const TArray<float>& Values,
        const bool bIsNeutralFrame = false,
        const bool bHasHeadOrientation = false)
    {
        if (!CanPublish() || PropertyNames.Num() == 0 ||
            Values.Num() != PropertyNames.Num())
        {
            return false;
        }

        FLiveLinkFrameDataStruct FrameDataStruct(FLiveLinkBaseFrameData::StaticStruct());
        FLiveLinkBaseFrameData* FrameData = FrameDataStruct.Cast<FLiveLinkBaseFrameData>();
        if (FrameData == nullptr)
        {
            return false;
        }

        FrameData->PropertyValues = Values;
        FrameData->MetaData.StringMetaData.Add(
            TEXT("IsNeutralFrame"),
            bIsNeutralFrame ? TEXT("true") : TEXT("false"));
        // UE 5.8's EMetaHumanLiveLinkHeadPoseMode::Orientation is 1 << 1.
        FrameData->MetaData.StringMetaData.Add(
            TEXT("HeadPoseMode"),
            bHasHeadOrientation ? TEXT("2") : TEXT("0"));
        Client->PushSubjectFrameData_AnyThread(
            FLiveLinkSubjectKey(SourceGuid, SubjectName),
            MoveTemp(FrameDataStruct));
        return true;
    }

private:
    void PushStaticData()
    {
        if (!IsSourceStillValid() || PropertyNames.Num() == 0)
        {
            return;
        }

        FLiveLinkStaticDataStruct StaticDataStruct(FLiveLinkBaseStaticData::StaticStruct());
        FLiveLinkBaseStaticData* StaticData = StaticDataStruct.Cast<FLiveLinkBaseStaticData>();
        if (StaticData == nullptr)
        {
            return;
        }

        StaticData->PropertyNames = PropertyNames;
        Client->PushSubjectStaticData_AnyThread(
            FLiveLinkSubjectKey(SourceGuid, SubjectName),
            ULiveLinkBasicRole::StaticClass(),
            MoveTemp(StaticDataStruct));
        bStaticDataQueued = true;
    }

    ILiveLinkClient* Client = nullptr;
    FGuid SourceGuid;
    FName SubjectName;
    TArray<FName> PropertyNames;
    bool bShutdownRequested = false;
    bool bStaticDataQueued = false;
};

EAudioDrivenAnimationMood ResolveMood(const FFayAvatarMessage& Message)
{
    FString Affect = Message.Action.Affect.ToLower();
    Affect.AppendChar(TEXT(' '));
    Affect.Append(Message.Action.Behavior.ToLower());

    if (Affect.Contains(TEXT("confiden")))
    {
        return EAudioDrivenAnimationMood::Confidence;
    }
    if (Affect.Contains(TEXT("excit")))
    {
        return EAudioDrivenAnimationMood::Excitement;
    }
    if (Affect.Contains(TEXT("play")))
    {
        return EAudioDrivenAnimationMood::Playfulness;
    }
    if (Affect.Contains(TEXT("happy")) || Affect.Contains(TEXT("joy")) ||
        Affect.Contains(TEXT("smile")))
    {
        return EAudioDrivenAnimationMood::Happiness;
    }
    if (Affect.Contains(TEXT("bored")))
    {
        return EAudioDrivenAnimationMood::Boredom;
    }
    if (Affect.Contains(TEXT("sad")))
    {
        return EAudioDrivenAnimationMood::Sadness;
    }
    if (Affect.Contains(TEXT("fear")) || Affect.Contains(TEXT("afraid")))
    {
        return EAudioDrivenAnimationMood::Fear;
    }
    if (Affect.Contains(TEXT("confus")) || Affect.Contains(TEXT("think")))
    {
        return EAudioDrivenAnimationMood::Confusion;
    }
    if (Affect.Contains(TEXT("disgust")))
    {
        return EAudioDrivenAnimationMood::Disgust;
    }
    if (Affect.Contains(TEXT("anger")) || Affect.Contains(TEXT("angry")) ||
        Affect.Contains(TEXT("warn")))
    {
        return EAudioDrivenAnimationMood::Anger;
    }
    if (Affect.Contains(TEXT("surpris")))
    {
        return EAudioDrivenAnimationMood::Surprise;
    }
    if (Message.Sentiment >= 0.45f)
    {
        return EAudioDrivenAnimationMood::Happiness;
    }
    if (Message.Sentiment <= -0.45f)
    {
        return EAudioDrivenAnimationMood::Sadness;
    }
    return EAudioDrivenAnimationMood::AutoDetect;
}

float ResolveMoodIntensity(const FFayAvatarMessage& Message)
{
    const float Requested = Message.Action.bIsValid
        ? Message.Action.Intensity
        : FMath::Abs(Message.Sentiment);
    return FMath::Clamp(Requested > KINDA_SMALL_NUMBER ? Requested : 0.7f, 0.0f, 1.0f);
}

EFaySemanticHeadGesture ResolveSemanticHeadGesture(const FFayAvatarMessage& Message)
{
    if (!Message.Action.bIsValid)
    {
        return EFaySemanticHeadGesture::None;
    }

    const FString Behavior = Message.Action.Behavior.TrimStartAndEnd().ToLower();
    const FString Code = Message.Action.Code.TrimStartAndEnd().ToLower();

    if (Behavior == TEXT("nod") || Code == TEXT("dialogue.confirm") ||
        Code == TEXT("greeting.hello"))
    {
        return EFaySemanticHeadGesture::Nod;
    }
    if (Behavior == TEXT("shake") || Behavior == TEXT("reject") ||
        Code == TEXT("dialogue.reject"))
    {
        return EFaySemanticHeadGesture::Shake;
    }
    if (Behavior == TEXT("think") || Code == TEXT("dialogue.think"))
    {
        return EFaySemanticHeadGesture::Think;
    }
    if (Behavior == TEXT("warn") || Code == TEXT("guidance.warn"))
    {
        return EFaySemanticHeadGesture::Warn;
    }
    if (Behavior == TEXT("wave") || Code == TEXT("farewell.goodbye"))
    {
        return EFaySemanticHeadGesture::BodyOwnedWave;
    }
    if (Behavior == TEXT("invite") || Code == TEXT("guidance.invite") ||
        Code == TEXT("greeting.welcome"))
    {
        return EFaySemanticHeadGesture::BodyOwnedInvite;
    }
    return EFaySemanticHeadGesture::None;
}

float GetGestureBaseDurationSeconds(const EFaySemanticHeadGesture Gesture)
{
    switch (Gesture)
    {
    case EFaySemanticHeadGesture::Nod:
        return 0.55f;
    case EFaySemanticHeadGesture::Shake:
        return 0.75f;
    case EFaySemanticHeadGesture::Think:
        return 1.15f;
    case EFaySemanticHeadGesture::Warn:
        return 0.75f;
    default:
        return 0.0f;
    }
}

float SmoothStep01(const float Value)
{
    const float Alpha = FMath::Clamp(Value, 0.0f, 1.0f);
    return Alpha * Alpha * (3.0f - 2.0f * Alpha);
}

float AttackHoldReleaseEnvelope(const float NormalizedTime)
{
    constexpr float AttackFraction = 0.20f;
    constexpr float ReleaseFraction = 0.25f;

    if (NormalizedTime < AttackFraction)
    {
        return SmoothStep01(NormalizedTime / AttackFraction);
    }
    if (NormalizedTime > 1.0f - ReleaseFraction)
    {
        return 1.0f - SmoothStep01(
            (NormalizedTime - (1.0f - ReleaseFraction)) / ReleaseFraction);
    }
    return 1.0f;
}

FFayHeadPose EvaluateHeadGesture(
    const EFaySemanticHeadGesture Gesture,
    const float ElapsedSeconds,
    const float DurationSeconds,
    const float Strength,
    const float RequestedMaximumDegrees)
{
    FFayHeadPose Pose;
    if (Gesture == EFaySemanticHeadGesture::None ||
        Gesture == EFaySemanticHeadGesture::BodyOwnedWave ||
        Gesture == EFaySemanticHeadGesture::BodyOwnedInvite ||
        DurationSeconds <= KINDA_SMALL_NUMBER)
    {
        return Pose;
    }

    if (ElapsedSeconds >= DurationSeconds)
    {
        return Pose;
    }
    Pose.bDriveOrientation = true;
    const float NormalizedTime = FMath::Clamp(
        ElapsedSeconds / DurationSeconds,
        0.0f,
        1.0f);
    const float MaximumDegrees = FMath::Clamp(
        FMath::IsFinite(RequestedMaximumDegrees)
            ? RequestedMaximumDegrees
            : MinimumHeadGestureDegrees,
        MinimumHeadGestureDegrees,
        HardMaximumHeadGestureDegrees);
    const float AmplitudeDegrees = MaximumDegrees * FMath::Clamp(Strength, 0.0f, 1.0f);
    const float SineWindow = FMath::Sin(PI * NormalizedTime);

    switch (Gesture)
    {
    case EFaySemanticHeadGesture::Nod:
        Pose.PitchDegrees = AmplitudeDegrees * SineWindow * SineWindow;
        break;
    case EFaySemanticHeadGesture::Shake:
        Pose.YawDegrees = AmplitudeDegrees *
            FMath::Sin(2.0f * PI * NormalizedTime) * SineWindow;
        break;
    case EFaySemanticHeadGesture::Think:
    {
        const float Envelope = AttackHoldReleaseEnvelope(NormalizedTime);
        Pose.RollDegrees = 0.65f * AmplitudeDegrees * Envelope;
        Pose.PitchDegrees = -0.15f * AmplitudeDegrees * Envelope;
        Pose.YawDegrees = 0.20f * AmplitudeDegrees * Envelope;
        break;
    }
    case EFaySemanticHeadGesture::Warn:
        Pose.PitchDegrees =
            0.80f * AmplitudeDegrees * AttackHoldReleaseEnvelope(NormalizedTime);
        break;
    default:
        break;
    }

    Pose.RollDegrees = FMath::Clamp(
        Pose.RollDegrees,
        -HardMaximumHeadGestureDegrees,
        HardMaximumHeadGestureDegrees);
    Pose.PitchDegrees = FMath::Clamp(
        Pose.PitchDegrees,
        -HardMaximumHeadGestureDegrees,
        HardMaximumHeadGestureDegrees);
    Pose.YawDegrees = FMath::Clamp(
        Pose.YawDegrees,
        -HardMaximumHeadGestureDegrees,
        HardMaximumHeadGestureDegrees);
    return Pose;
}

bool SetLiveLinkSubjectProperty(UObject* Object, const FName PropertyName, const FName SubjectName)
{
    if (Object == nullptr)
    {
        return false;
    }

    FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (StructProperty->Struct == FLiveLinkSubjectName::StaticStruct())
        {
            FLiveLinkSubjectName* Value =
                StructProperty->ContainerPtrToValuePtr<FLiveLinkSubjectName>(Object);
            Value->Name = SubjectName;
            return true;
        }
    }
    if (FNameProperty* NameProperty = CastField<FNameProperty>(Property))
    {
        NameProperty->SetPropertyValue_InContainer(Object, SubjectName);
        return true;
    }
    return false;
}

bool GetLiveLinkSubjectProperty(UObject* Object, const FName PropertyName, FName& OutSubjectName)
{
    if (Object == nullptr)
    {
        return false;
    }

    FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (StructProperty->Struct == FLiveLinkSubjectName::StaticStruct())
        {
            const FLiveLinkSubjectName* Value =
                StructProperty->ContainerPtrToValuePtr<FLiveLinkSubjectName>(Object);
            OutSubjectName = Value->Name;
            return true;
        }
    }
    if (FNameProperty* NameProperty = CastField<FNameProperty>(Property))
    {
        OutSubjectName = NameProperty->GetPropertyValue_InContainer(Object);
        return true;
    }
    return false;
}

bool SetBooleanProperty(UObject* Object, const FName PropertyName, const bool Value)
{
    if (Object == nullptr)
    {
        return false;
    }
    if (FBoolProperty* Property =
            CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(PropertyName)))
    {
        Property->SetPropertyValue_InContainer(Object, Value);
        return true;
    }
    return false;
}

bool GetBooleanProperty(UObject* Object, const FName PropertyName, bool& OutValue)
{
    if (Object == nullptr)
    {
        return false;
    }
    if (FBoolProperty* Property =
            CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(PropertyName)))
    {
        OutValue = Property->GetPropertyValue_InContainer(Object);
        return true;
    }
    return false;
}

FString StableComponentName(const UActorComponent* Component)
{
    FString Name = Component != nullptr ? Component->GetName() : FString();
    Name.RemoveFromEnd(TEXT("_GEN_VARIABLE"));
    return Name;
}

USkeletalMeshComponent* FindSkeletalMeshComponent(
    AActor* InAvatar,
    const FStringView StableName)
{
    if (!IsValid(InAvatar))
    {
        return nullptr;
    }

    TInlineComponentArray<USkeletalMeshComponent*> SkeletalMeshes(InAvatar);
    for (USkeletalMeshComponent* Mesh : SkeletalMeshes)
    {
        if (StableComponentName(Mesh) == StableName)
        {
            return Mesh;
        }
    }
    return nullptr;
}

USkeletalMeshComponent* FindFaceMeshComponent(AActor* InAvatar)
{
    return FindSkeletalMeshComponent(InAvatar, TEXTVIEW("Face"));
}

USkeletalMeshComponent* FindBodyMeshComponent(AActor* InAvatar)
{
    return FindSkeletalMeshComponent(InAvatar, TEXTVIEW("Body"));
}

bool HasMetaHumanLiveLinkSetupSignature(const UFunction* SetupFunction)
{
    if (SetupFunction == nullptr || SetupFunction->NumParms != 4 ||
        SetupFunction->ParmsSize == 0)
    {
        return false;
    }

    bool bHasSkeletalMesh = false;
    bool bHasSubjectName = false;
    bool bHasRetargetAsset = false;
    bool bHasUseLiveLink = false;
    int32 InputParameterCount = 0;
    for (TFieldIterator<FProperty> Iterator(SetupFunction); Iterator; ++Iterator)
    {
        FProperty* Property = *Iterator;
        if (!Property->HasAnyPropertyFlags(CPF_Parm))
        {
            continue;
        }
        if (Property->HasAnyPropertyFlags(CPF_ReturnParm | CPF_OutParm))
        {
            return false;
        }
        ++InputParameterCount;

        const FName PropertyName = Property->GetFName();
        if (PropertyName == TEXT("SkeletalMesh"))
        {
            const FObjectPropertyBase* ObjectProperty =
                CastField<FObjectPropertyBase>(Property);
            bHasSkeletalMesh = ObjectProperty != nullptr &&
                ObjectProperty->PropertyClass->IsChildOf(
                    USkeletalMeshComponent::StaticClass());
        }
        else if (PropertyName == TEXT("SubjectName"))
        {
            const FStructProperty* StructProperty = CastField<FStructProperty>(Property);
            bHasSubjectName = StructProperty != nullptr &&
                StructProperty->Struct == FLiveLinkSubjectName::StaticStruct();
        }
        else if (PropertyName == TEXT("RetargetAsset"))
        {
            bHasRetargetAsset = CastField<FObjectPropertyBase>(Property) != nullptr;
        }
        else if (PropertyName == TEXT("UseLiveLink"))
        {
            bHasUseLiveLink = CastField<FBoolProperty>(Property) != nullptr;
        }
        else
        {
            return false;
        }
    }

    return InputParameterCount == 4 && bHasSkeletalMesh && bHasSubjectName &&
        bHasRetargetAsset && bHasUseLiveLink;
}

bool InvokeMetaHumanLiveLinkSetup(
    AActor* InAvatar,
    UFunction* SetupFunction,
    USkeletalMeshComponent* SkeletalMesh,
    const FName SubjectName,
    const bool bUseLiveLink)
{
    if (!IsValid(InAvatar) || !IsValid(SkeletalMesh) ||
        !HasMetaHumanLiveLinkSetupSignature(SetupFunction))
    {
        return false;
    }

    TArray<uint8, TInlineAllocator<128>> Parameters;
    Parameters.SetNumZeroed(SetupFunction->ParmsSize);
    for (TFieldIterator<FProperty> Iterator(SetupFunction); Iterator; ++Iterator)
    {
        FProperty* Property = *Iterator;
        if (!Property->HasAnyPropertyFlags(CPF_Parm))
        {
            continue;
        }

        const FName PropertyName = Property->GetFName();
        if (PropertyName == TEXT("SkeletalMesh"))
        {
            CastFieldChecked<FObjectPropertyBase>(Property)
                ->SetObjectPropertyValue_InContainer(Parameters.GetData(), SkeletalMesh);
        }
        else if (PropertyName == TEXT("SubjectName"))
        {
            FLiveLinkSubjectName* Value = CastFieldChecked<FStructProperty>(Property)
                ->ContainerPtrToValuePtr<FLiveLinkSubjectName>(Parameters.GetData());
            Value->Name = SubjectName;
        }
        else if (PropertyName == TEXT("UseLiveLink"))
        {
            CastFieldChecked<FBoolProperty>(Property)
                ->SetPropertyValue_InContainer(Parameters.GetData(), bUseLiveLink);
        }
        // RetargetAsset deliberately remains null. The Fay source already
        // publishes the MetaHuman raw-control schema consumed by this assembly.
    }

    InAvatar->ProcessEvent(SetupFunction, Parameters.GetData());
    return true;
}

bool ApplyMetaHumanLiveLinkSetup(
    AActor* InAvatar,
    UFunction* SetupFunction,
    const FName SubjectName,
    const bool bUseLiveLink)
{
    USkeletalMeshComponent* BodyMesh = FindBodyMeshComponent(InAvatar);
    USkeletalMeshComponent* FaceMesh = FindFaceMeshComponent(InAvatar);
    if (!InvokeMetaHumanLiveLinkSetup(
            InAvatar,
            SetupFunction,
            BodyMesh,
            SubjectName,
            bUseLiveLink))
    {
        return false;
    }

    // LiveLinkSetup can replace animation instances. Resolve the Face again
    // before mirroring the Blueprint's second OnAnimInitialized call.
    FaceMesh = FindFaceMeshComponent(InAvatar);
    return InvokeMetaHumanLiveLinkSetup(
        InAvatar,
        SetupFunction,
        FaceMesh,
        SubjectName,
        bUseLiveLink);
}

bool RestoreBodyAnimationState(
    AActor* InAvatar,
    UClass* OriginalAnimClass,
    const EAnimationMode::Type OriginalAnimationMode)
{
    USkeletalMeshComponent* BodyMesh = FindBodyMeshComponent(InAvatar);
    if (BodyMesh == nullptr)
    {
        return false;
    }

    BodyMesh->SetAnimInstanceClass(OriginalAnimClass);
    BodyMesh->SetAnimationMode(OriginalAnimationMode);
    return BodyMesh->GetAnimClass() == OriginalAnimClass &&
        BodyMesh->GetAnimationMode() == OriginalAnimationMode;
}

bool HasVerifiedLiveLinkConsumer(
    AActor* InAvatar,
    const FName SubjectName,
    FString* OutReason = nullptr)
{
    if (OutReason != nullptr)
    {
        OutReason->Reset();
    }
    const auto Fail = [OutReason](FString Reason)
    {
        if (OutReason != nullptr)
        {
            *OutReason = MoveTemp(Reason);
        }
        return false;
    };

    if (SubjectName.IsNone())
    {
        return Fail(TEXT("the requested consumer subject is empty"));
    }

    bool bUseLiveLink = false;
    FName ActorSubject = NAME_None;
    USkeletalMeshComponent* BodyMesh = FindBodyMeshComponent(InAvatar);
    if (BodyMesh == nullptr)
    {
        return Fail(TEXT("Ada's Body component is missing"));
    }

    ULiveLinkInstance* BodyAnimation = BodyMesh != nullptr
        ? Cast<ULiveLinkInstance>(BodyMesh->GetAnimInstance())
        : nullptr;
    if (BodyAnimation == nullptr)
    {
        const UAnimInstance* ActualAnimation = BodyMesh->GetAnimInstance();
        return Fail(FString::Printf(
            TEXT("Ada's Body animation instance is %s instead of ULiveLinkInstance"),
            ActualAnimation != nullptr
                ? *ActualAnimation->GetClass()->GetPathName()
                : TEXT("null")));
    }
    if (!GetBooleanProperty(InAvatar, TEXT("UseLiveLink"), bUseLiveLink) ||
        !bUseLiveLink)
    {
        return Fail(TEXT("Ada's UseLiveLink actor property is unavailable or false"));
    }
    if (!GetLiveLinkSubjectProperty(
            InAvatar,
            TEXT("LiveLinkSubject"),
            ActorSubject) ||
        ActorSubject != SubjectName)
    {
        return Fail(FString::Printf(
            TEXT("Ada's actor subject is '%s' instead of '%s'"),
            *ActorSubject.ToString(),
            *SubjectName.ToString()));
    }
    if (!BodyAnimation->GetEnableLiveLinkEvaluation())
    {
        return Fail(TEXT("Ada's native Body Live Link evaluation is disabled"));
    }
    return true;
}

void DecodeAndResamplePcm16(
    const TArray<uint8>& Pcm16,
    const int32 SourceSampleRate,
    const int32 SourceNumChannels,
    TArray<float>& OutMono16Khz)
{
    const int32 SourceFrameCount =
        Pcm16.Num() / (static_cast<int32>(sizeof(int16)) * SourceNumChannels);
    TArray<float> SourceMono;
    SourceMono.SetNumUninitialized(SourceFrameCount);

    for (int32 FrameIndex = 0; FrameIndex < SourceFrameCount; ++FrameIndex)
    {
        float MixedSample = 0.0f;
        for (int32 ChannelIndex = 0; ChannelIndex < SourceNumChannels; ++ChannelIndex)
        {
            const int32 SampleIndex = FrameIndex * SourceNumChannels + ChannelIndex;
            const int32 ByteIndex = SampleIndex * static_cast<int32>(sizeof(int16));
            const uint16 UnsignedSample = static_cast<uint16>(Pcm16[ByteIndex]) |
                (static_cast<uint16>(Pcm16[ByteIndex + 1]) << 8);
            MixedSample +=
                static_cast<float>(static_cast<int16>(UnsignedSample)) / 32768.0f;
        }
        SourceMono[FrameIndex] = MixedSample / static_cast<float>(SourceNumChannels);
    }

    if (SourceSampleRate == SolverSampleRate)
    {
        OutMono16Khz = MoveTemp(SourceMono);
        return;
    }

    const int32 OutputFrameCount = FMath::Max(
        1,
        FMath::RoundToInt32(
            static_cast<double>(SourceFrameCount) *
            static_cast<double>(SolverSampleRate) /
            static_cast<double>(SourceSampleRate)));
    OutMono16Khz.SetNumUninitialized(OutputFrameCount);

    const double SourceFramesPerOutputFrame =
        static_cast<double>(SourceSampleRate) / static_cast<double>(SolverSampleRate);
    for (int32 OutputIndex = 0; OutputIndex < OutputFrameCount; ++OutputIndex)
    {
        const double SourcePosition =
            FMath::Min(
                static_cast<double>(OutputIndex) * SourceFramesPerOutputFrame,
                static_cast<double>(SourceFrameCount - 1));
        const int32 LowerIndex = FMath::FloorToInt32(SourcePosition);
        const int32 UpperIndex = FMath::Min(LowerIndex + 1, SourceFrameCount - 1);
        const float Alpha = static_cast<float>(SourcePosition - LowerIndex);
        OutMono16Khz[OutputIndex] = FMath::Lerp(
            SourceMono[LowerIndex],
            SourceMono[UpperIndex],
            Alpha);
    }
}
}

struct FFayMetaHumanSpeechRuntimeState
{
    TSharedPtr<FSpeechAnimationSolverV4> Solver;
    TSharedPtr<FFaySpeechLiveLinkSource> Source;
    TArray<FString> RawControlNames;
    TArray<float> NeutralPropertyValues;

    bool TryMakePropertyValues(
        const TMap<FString, float>& RawControls,
        TArray<float>& OutValues,
        const FFayHeadPose& HeadPose = FFayHeadPose()) const
    {
        OutValues.Reset();
        if (RawControls.Num() != RawControlNames.Num() ||
            !FMath::IsFinite(HeadPose.RollDegrees) ||
            !FMath::IsFinite(HeadPose.PitchDegrees) ||
            !FMath::IsFinite(HeadPose.YawDegrees))
        {
            return false;
        }
        OutValues.Reserve(RawControlNames.Num() + ExtraLiveLinkProperties);
        for (const FString& Name : RawControlNames)
        {
            const float* Value = RawControls.Find(Name);
            if (Value == nullptr || !FMath::IsFinite(*Value))
            {
                OutValues.Reset();
                return false;
            }
            OutValues.Add(*Value);
        }
        // Keep Epic's UE 5.8 MetaHuman Live Link order and degree units.
        OutValues.Add(HeadPose.bDriveOrientation ? 1.0f : 0.0f);
        OutValues.Add(HeadPose.RollDegrees);
        OutValues.Add(HeadPose.PitchDegrees);
        OutValues.Add(HeadPose.YawDegrees);
        OutValues.AddZeroed(3);
        OutValues.Add(1.0f);
        OutValues.Add(1.0f);
        return OutValues.Num() == RawControlNames.Num() + ExtraLiveLinkProperties;
    }

    bool PushNeutral() const
    {
        if (Source.IsValid() && NeutralPropertyValues.Num() > 0)
        {
            return Source->PushValues(NeutralPropertyValues, true, false);
        }
        return false;
    }
};

UFayMetaHumanSpeechDriverComponent::UFayMetaHumanSpeechDriverComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
    PrimaryComponentTick.TickGroup = TG_PostUpdateWork;
}

void UFayMetaHumanSpeechDriverComponent::BeginPlay()
{
    Super::BeginPlay();
    int32 ResetCacheOverride = bResetSolverCacheBetweenUtterances ? 1 : 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayResetSpeechCache="),
            ResetCacheOverride))
    {
        bResetSolverCacheBetweenUtterances = ResetCacheOverride != 0;
    }
    int32 RecreateSolverOverride = bRecreateSolverBetweenUtterances ? 1 : 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayRecreateSpeechSolver="),
            RecreateSolverOverride))
    {
        bRecreateSolverBetweenUtterances = RecreateSolverOverride != 0;
    }
    if (bRecreateSolverBetweenUtterances)
    {
        bResetSolverCacheBetweenUtterances = false;
    }
    int32 TrimMemoryOverride = bTrimMemoryAfterUtterance ? 1 : 0;
    if (FParse::Value(
            FCommandLine::Get(),
            TEXT("FayTrimSpeechMemory="),
            TrimMemoryOverride))
    {
        bTrimMemoryAfterUtterance = TrimMemoryOverride != 0;
    }
    UE_LOG(LogFayMetaHumanRuntime, Display,
        TEXT("StreamingADA utterance reset mode: %s (post-solve trim=%s)."),
        bRecreateSolverBetweenUtterances
            ? TEXT("recreate-solver")
            : (bResetSolverCacheBetweenUtterances ? TEXT("clear-cache") : TEXT("contiguous-flag")),
        bTrimMemoryAfterUtterance ? TEXT("enabled") : TEXT("disabled"));
    InitializeSolverAndSource();
}

void UFayMetaHumanSpeechDriverComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    AttachBridge(nullptr);
    if (RuntimeState.IsValid())
    {
        RuntimeState->PushNeutral();
    }
    RestoreConfiguredAvatar();
    PendingAvatar = nullptr;
    ShutdownSource();
    ResetSpeechState();
    SpeechModel = nullptr;
    RuntimeState.Reset();
    Super::EndPlay(EndPlayReason);
}

void UFayMetaHumanSpeechDriverComponent::AttachBridge(UFayAvatarBridgeComponent* InBridge)
{
    if (Bridge == InBridge)
    {
        return;
    }
    if (Bridge != nullptr)
    {
        Bridge->OnDecodedPcm.RemoveAll(this);
        Bridge->OnSpeechStarted.RemoveDynamic(this, &UFayMetaHumanSpeechDriverComponent::HandleSpeechStarted);
        Bridge->OnSpeechFinished.RemoveDynamic(this, &UFayMetaHumanSpeechDriverComponent::HandleSpeechFinished);
    }

    Bridge = InBridge;
    if (Bridge != nullptr)
    {
        Bridge->OnDecodedPcm.AddUObject(this, &UFayMetaHumanSpeechDriverComponent::HandleDecodedPcm);
        Bridge->OnSpeechStarted.AddDynamic(this, &UFayMetaHumanSpeechDriverComponent::HandleSpeechStarted);
        Bridge->OnSpeechFinished.AddDynamic(this, &UFayMetaHumanSpeechDriverComponent::HandleSpeechFinished);
    }
}

bool UFayMetaHumanSpeechDriverComponent::IsSolverReady() const
{
    return RuntimeState.IsValid() && RuntimeState->Solver.IsValid() &&
        RuntimeState->Source.IsValid() && RuntimeState->Source->CanPublish() &&
        RuntimeState->Source->GetSubjectName() == LiveLinkSubjectName;
}

bool UFayMetaHumanSpeechDriverComponent::IsAvatarConfigured() const
{
    if (!IsSolverReady() || !IsValid(Avatar) ||
        !HasVerifiedLiveLinkConsumer(Avatar, LiveLinkSubjectName))
    {
        return false;
    }
    FString ReadinessReason;
    return RuntimeState->Source->GetExactSubjectReadiness(ReadinessReason) ==
        EFayLiveLinkSubjectReadiness::Ready;
}

bool UFayMetaHumanSpeechDriverComponent::IsAvatarConfigurationPending() const
{
    return IsValid(PendingAvatar);
}

void UFayMetaHumanSpeechDriverComponent::InitializeSolverAndSource()
{
    if (IsSolverReady())
    {
        return;
    }

    if (LiveLinkSubjectName.IsNone())
    {
        UE_LOG(LogFayMetaHumanRuntime, Error, TEXT("The Fay Live Link subject name is empty."));
        return;
    }

    FModuleManager::Get().LoadModule(TEXT("LiveLink"));
    FModuleManager::Get().LoadModule(TEXT("NNERuntimeORT"));

    IModularFeatures& Features = IModularFeatures::Get();
    if (!Features.IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
    {
        UE_LOG(LogFayMetaHumanRuntime, Error, TEXT("The Live Link client is unavailable."));
        return;
    }

    const FString ModelPath = ISpeechAnimationSolver::GetLatestModelAssetPath();
    SpeechModel = LoadObject<UNNEModelData>(GetTransientPackage(), *ModelPath);
    if (SpeechModel == nullptr)
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The UE 5.8 StreamingADA model could not be loaded. Ensure /StreamingADA is cooked."));
        return;
    }

    RuntimeState = MakeShared<FFayMetaHumanSpeechRuntimeState>();
    RuntimeState->Solver = MakeShared<FSpeechAnimationSolverV4>(
        SpeechModel,
        TEXT("NNERuntimeORTCpu"));
    if (!RuntimeState->Solver->Initialize())
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The UE 5.8 speech-animation solver failed to initialize with NNERuntimeORTCpu."));
        RuntimeState.Reset();
        return;
    }
    if (RuntimeState->Solver->GetNumCurves() != ExpectedSolverCurveCount ||
        RuntimeState->Solver->GetCurveNames().Num() != ExpectedSolverCurveCount)
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The UE 5.8 speech-animation solver exposed an unexpected curve schema."));
        RuntimeState.Reset();
        return;
    }

    const TMap<FString, float> NeutralControls =
        GuiToRawControlsUtils::ConvertGuiToRawControls(TMap<FString, float>());
    NeutralControls.GenerateKeyArray(RuntimeState->RawControlNames);
    RuntimeState->RawControlNames.Sort();
    if (RuntimeState->RawControlNames.Num() != ExpectedRawControlCount)
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The MetaHuman GUI-to-raw conversion exposed %d controls instead of %d."),
            RuntimeState->RawControlNames.Num(),
            ExpectedRawControlCount);
        RuntimeState.Reset();
        return;
    }

    TArray<FName> PropertyNames;
    PropertyNames.Reserve(RuntimeState->RawControlNames.Num() + ExtraLiveLinkProperties);
    for (const FString& Name : RuntimeState->RawControlNames)
    {
        PropertyNames.Add(FName(Name));
    }
    PropertyNames.Add(HeadControlSwitchName);
    PropertyNames.Add(HeadRollName);
    PropertyNames.Add(HeadPitchName);
    PropertyNames.Add(HeadYawName);
    PropertyNames.Add(HeadTranslationXName);
    PropertyNames.Add(HeadTranslationYName);
    PropertyNames.Add(HeadTranslationZName);
    PropertyNames.Add(DataVersionName);
    PropertyNames.Add(DisableFaceOverrideName);

    if (!RuntimeState->TryMakePropertyValues(
            NeutralControls,
            RuntimeState->NeutralPropertyValues))
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The MetaHuman neutral raw-control frame did not match the UE 5.8 schema."));
        RuntimeState.Reset();
        return;
    }
    RuntimeState->Source = MakeShared<FFaySpeechLiveLinkSource>(LiveLinkSubjectName);
    RuntimeState->Source->SetPropertyNames(PropertyNames);

    ILiveLinkClient& LiveLinkClient =
        Features.GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName);
    const FGuid SourceGuid = LiveLinkClient.AddSource(RuntimeState->Source);
    if (!SourceGuid.IsValid())
    {
        UE_LOG(LogFayMetaHumanRuntime, Error, TEXT("Live Link refused the Fay speech source."));
        RuntimeState.Reset();
        return;
    }

    if (!RuntimeState->Source->CanPublish() || !RuntimeState->PushNeutral())
    {
        LiveLinkClient.RemoveSource(RuntimeState->Source);
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The Fay Live Link source could not queue its static data and neutral frame."));
        RuntimeState.Reset();
        return;
    }
    UE_LOG(LogFayMetaHumanRuntime, Display,
        TEXT("Initialized local UE 5.8 speech animation and queued its Live Link bootstrap "
             "(solver_curves=%d, raw_controls=%d, subject=%s)."),
        RuntimeState->Solver->GetNumCurves(),
        RuntimeState->RawControlNames.Num(),
        *LiveLinkSubjectName.ToString());
}

void UFayMetaHumanSpeechDriverComponent::ShutdownSource()
{
    if (!RuntimeState.IsValid() || !RuntimeState->Source.IsValid())
    {
        return;
    }

    IModularFeatures& Features = IModularFeatures::Get();
    if (Features.IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
    {
        ILiveLinkClient& Client =
            Features.GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName);
        Client.RemoveSource(RuntimeState->Source);
    }
    RuntimeState->Source.Reset();
}

bool UFayMetaHumanSpeechDriverComponent::ConfigureAvatar(AActor* InAvatar)
{
    if (!IsSolverReady() || !IsValid(InAvatar) || LiveLinkSubjectName.IsNone())
    {
        return false;
    }

    if (Avatar == InAvatar && IsAvatarConfigured())
    {
        PendingAvatar = nullptr;
        return true;
    }
    if (Avatar == InAvatar && IsValid(Avatar))
    {
        if (RuntimeState.IsValid())
        {
            RuntimeState->PushNeutral();
        }
        if (!RestoreConfiguredAvatar())
        {
            return false;
        }
    }
    if (IsValid(Avatar) && Avatar != InAvatar)
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("Fay rejected a second avatar while another MetaHuman is configured; "
                 "the existing configuration was preserved."));
        return false;
    }

    if (PendingAvatar != InAvatar)
    {
        PendingAvatar = InAvatar;
        bPendingSubjectWaitLogged = false;
        bTerminalSubjectFailureLogged = false;
    }
    return TryConfigurePendingAvatar();
}

bool UFayMetaHumanSpeechDriverComponent::TryConfigurePendingAvatar()
{
    if (!IsValid(PendingAvatar))
    {
        PendingAvatar = nullptr;
        return false;
    }
    if (!IsSolverReady())
    {
        if (!bTerminalSubjectFailureLogged)
        {
            UE_LOG(LogFayMetaHumanRuntime, Error,
                TEXT("Fay cancelled the pending MetaHuman configuration because its solver "
                     "or Live Link source became unavailable."));
            bTerminalSubjectFailureLogged = true;
        }
        PendingAvatar = nullptr;
        return false;
    }

    FString ReadinessReason;
    const EFayLiveLinkSubjectReadiness Readiness =
        RuntimeState->Source->GetExactSubjectReadiness(ReadinessReason);
    if (Readiness == EFayLiveLinkSubjectReadiness::Pending)
    {
        if (!bPendingSubjectWaitLogged)
        {
            UE_LOG(LogFayMetaHumanRuntime, Display,
                TEXT("Deferring MetaHuman configuration until Live Link processes the exact "
                     "Fay source (%s)."),
                *ReadinessReason);
            bPendingSubjectWaitLogged = true;
        }
        return false;
    }
    if (Readiness == EFayLiveLinkSubjectReadiness::Collision ||
        Readiness == EFayLiveLinkSubjectReadiness::Invalid)
    {
        if (!bTerminalSubjectFailureLogged)
        {
            UE_LOG(LogFayMetaHumanRuntime, Error,
                TEXT("Fay refused to configure the MetaHuman Live Link consumer: %s."),
                *ReadinessReason);
            bTerminalSubjectFailureLogged = true;
        }
        PendingAvatar = nullptr;
        // Remove only this adapter's source. The pre-existing subject owner is
        // deliberately left untouched, and IsSolverReady becomes false.
        ShutdownSource();
        return false;
    }

    bPendingSubjectWaitLogged = false;
    bTerminalSubjectFailureLogged = false;
    AActor* CandidateAvatar = PendingAvatar;
    if (!ApplyAvatarConfiguration(CandidateAvatar))
    {
        PendingAvatar = nullptr;
        return false;
    }
    PendingAvatar = nullptr;
    return true;
}

bool UFayMetaHumanSpeechDriverComponent::ApplyAvatarConfiguration(AActor* InAvatar)
{
    if (!IsValid(InAvatar) || IsValid(Avatar))
    {
        return false;
    }

    UFunction* SetupFunction = InAvatar->FindFunction(TEXT("LiveLinkSetup"));
    USkeletalMeshComponent* BodyMesh = FindBodyMeshComponent(InAvatar);
    USkeletalMeshComponent* FaceMesh = FindFaceMeshComponent(InAvatar);
    UClass* PreviousBodyAnimClass = BodyMesh != nullptr
        ? BodyMesh->GetAnimClass()
        : nullptr;
    const EAnimationMode::Type PreviousBodyAnimationMode = BodyMesh != nullptr
        ? BodyMesh->GetAnimationMode()
        : EAnimationMode::AnimationBlueprint;
    bool OriginalUseLiveLink = false;
    FName OriginalActorSubject = NAME_None;
    if (!HasMetaHumanLiveLinkSetupSignature(SetupFunction) || BodyMesh == nullptr ||
        FaceMesh == nullptr ||
        !GetBooleanProperty(InAvatar, TEXT("UseLiveLink"), OriginalUseLiveLink) ||
        !GetLiveLinkSubjectProperty(
            InAvatar,
            TEXT("LiveLinkSubject"),
            OriginalActorSubject))
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("The assembled avatar lacks the complete UE 5.8 Live Link actor contract; "
                 "Fay facial animation remains unconfigured."));
        return false;
    }

    if (OriginalUseLiveLink || Cast<ULiveLinkInstance>(BodyMesh->GetAnimInstance()) != nullptr)
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("Fay will not replace an avatar that already has a Live Link consumer."));
        return false;
    }

    const auto RollBackCandidate = [&]()
    {
        const bool bActorSubjectRestored = SetLiveLinkSubjectProperty(
            InAvatar,
            TEXT("LiveLinkSubject"),
            OriginalActorSubject);
        const bool bUseLiveLinkRestored =
            SetBooleanProperty(InAvatar, TEXT("UseLiveLink"), OriginalUseLiveLink);
        const bool bLiveLinkSetupRestored = ApplyMetaHumanLiveLinkSetup(
            InAvatar,
            SetupFunction,
            OriginalActorSubject,
            OriginalUseLiveLink);
        const bool bBodyAnimationRestored = RestoreBodyAnimationState(
            InAvatar,
            PreviousBodyAnimClass,
            PreviousBodyAnimationMode);
        bool bRollbackSucceeded = bActorSubjectRestored && bUseLiveLinkRestored &&
            bLiveLinkSetupRestored && bBodyAnimationRestored;

        bool RestoredUseLiveLink = !OriginalUseLiveLink;
        FName RestoredActorSubject = NAME_None;
        bRollbackSucceeded =
            GetBooleanProperty(InAvatar, TEXT("UseLiveLink"), RestoredUseLiveLink) &&
            RestoredUseLiveLink == OriginalUseLiveLink &&
            GetLiveLinkSubjectProperty(
                InAvatar,
                TEXT("LiveLinkSubject"),
                RestoredActorSubject) &&
            RestoredActorSubject == OriginalActorSubject && bRollbackSucceeded;
        if (!bRollbackSucceeded)
        {
            UE_LOG(LogFayMetaHumanRuntime, Error,
                TEXT("Fay could not completely roll back a rejected MetaHuman Live Link setup."));
        }
    };

    const bool bActorSubjectSet = SetLiveLinkSubjectProperty(
        InAvatar,
        TEXT("LiveLinkSubject"),
        LiveLinkSubjectName);
    const bool bUseLiveLinkSet =
        SetBooleanProperty(InAvatar, TEXT("UseLiveLink"), true);
    if (!bActorSubjectSet || !bUseLiveLinkSet)
    {
        RollBackCandidate();
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("The assembled avatar rejected the Fay Live Link actor configuration."));
        return false;
    }

    // In the Editor, changing UseLiveLink reruns Ada's construction logic and
    // installs this class before LiveLinkSetup. Runtime property reflection
    // deliberately does not rerun construction scripts, so mirror that one
    // public-engine operation explicitly in a packaged build.
    BodyMesh->SetAnimInstanceClass(ULiveLinkInstance::StaticClass());
    if (Cast<ULiveLinkInstance>(BodyMesh->GetAnimInstance()) == nullptr)
    {
        RollBackCandidate();
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("Ada's Body rejected UE 5.8's native LiveLinkInstance class."));
        return false;
    }

    if (!ApplyMetaHumanLiveLinkSetup(
            InAvatar,
            SetupFunction,
            LiveLinkSubjectName,
            true))
    {
        RollBackCandidate();
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("The assembled avatar rejected the UE 5.8 LiveLinkSetup contract."));
        return false;
    }

    // UE 5.8 does not expose a public getter for ULiveLinkInstance's subject.
    // Assign it once more through the native public API, then verify the actor
    // contract and the consumer's public evaluation state below. The exact
    // source key/schema/frame are independently verified by IsAvatarConfigured.
    BodyMesh = FindBodyMeshComponent(InAvatar);
    ULiveLinkInstance* BodyAnimation = BodyMesh != nullptr
        ? Cast<ULiveLinkInstance>(BodyMesh->GetAnimInstance())
        : nullptr;
    if (BodyAnimation == nullptr)
    {
        RollBackCandidate();
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("The assembled avatar did not install UE 5.8's native Body LiveLinkInstance."));
        return false;
    }
    FLiveLinkSubjectName NativeSubject;
    NativeSubject.Name = LiveLinkSubjectName;
    BodyAnimation->SetSubject(NativeSubject);
    BodyAnimation->EnableLiveLinkEvaluation(true);

    const bool bConfigurationReadBack =
        HasVerifiedLiveLinkConsumer(InAvatar, LiveLinkSubjectName);

    if (!bConfigurationReadBack || !IsSolverReady() ||
        !RuntimeState->PushNeutral())
    {
        RollBackCandidate();
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("The assembled avatar did not expose a verified Body LiveLinkInstance consumer "
                 "for the Fay Live Link subject; facial animation remains unconfigured."));
        return false;
    }

    OriginalActorLiveLinkSubject = OriginalActorSubject;
    OriginalBodyAnimClass = PreviousBodyAnimClass;
    OriginalBodyAnimationModeValue = static_cast<int32>(PreviousBodyAnimationMode);
    bOriginalUseLiveLink = OriginalUseLiveLink;
    bHasOriginalAvatarConfiguration = true;
    LiveLinkHeartbeatElapsedSeconds = 0.0;
    LiveLinkPendingElapsedSeconds = 0.0;
    bLiveLinkPendingGraceLogged = false;
    Avatar = InAvatar;
    UE_LOG(LogFayMetaHumanRuntime, Display,
        TEXT("Configured assembled MetaHuman Body LiveLinkInstance to consume the local Fay "
             "Live Link speech subject."));
    return true;
}

bool UFayMetaHumanSpeechDriverComponent::RestoreConfiguredAvatar()
{
    if (!bHasOriginalAvatarConfiguration)
    {
        Avatar = nullptr;
        return true;
    }

    AActor* ConfiguredAvatar = Avatar;
    bool bRestored = !IsValid(ConfiguredAvatar);
    if (IsValid(ConfiguredAvatar))
    {
        UFunction* SetupFunction = ConfiguredAvatar->FindFunction(TEXT("LiveLinkSetup"));
        const bool bSetupSignatureValid =
            HasMetaHumanLiveLinkSetupSignature(SetupFunction);
        const bool bActorSubjectRestored = SetLiveLinkSubjectProperty(
            ConfiguredAvatar,
            TEXT("LiveLinkSubject"),
            OriginalActorLiveLinkSubject);
        const bool bUseLiveLinkRestored = SetBooleanProperty(
            ConfiguredAvatar,
            TEXT("UseLiveLink"),
            bOriginalUseLiveLink);
        const bool bLiveLinkSetupRestored = bSetupSignatureValid &&
            ApplyMetaHumanLiveLinkSetup(
                ConfiguredAvatar,
                SetupFunction,
                OriginalActorLiveLinkSubject,
                bOriginalUseLiveLink);
        const bool bBodyAnimationRestored = RestoreBodyAnimationState(
            ConfiguredAvatar,
            OriginalBodyAnimClass,
            static_cast<EAnimationMode::Type>(OriginalBodyAnimationModeValue));

        USkeletalMeshComponent* RestoredBodyMesh =
            FindBodyMeshComponent(ConfiguredAvatar);
        const bool bBodyReadBack = RestoredBodyMesh != nullptr &&
            RestoredBodyMesh->GetAnimClass() == OriginalBodyAnimClass &&
            RestoredBodyMesh->GetAnimationMode() ==
                static_cast<EAnimationMode::Type>(OriginalBodyAnimationModeValue);
        bool RestoredUseLiveLink = !bOriginalUseLiveLink;
        FName RestoredActorSubject = NAME_None;
        const bool bUseLiveLinkReadBack = GetBooleanProperty(
                ConfiguredAvatar,
                TEXT("UseLiveLink"),
                RestoredUseLiveLink) &&
            RestoredUseLiveLink == bOriginalUseLiveLink;
        const bool bActorSubjectReadBack = GetLiveLinkSubjectProperty(
                ConfiguredAvatar,
                TEXT("LiveLinkSubject"),
                RestoredActorSubject) &&
            RestoredActorSubject == OriginalActorLiveLinkSubject;
        bRestored = bSetupSignatureValid && bActorSubjectRestored &&
            bUseLiveLinkRestored && bLiveLinkSetupRestored &&
            bBodyAnimationRestored && bBodyReadBack &&
            bUseLiveLinkReadBack && bActorSubjectReadBack;
    }

    if (!bRestored)
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("Fay could not completely restore the MetaHuman's original Live Link configuration."));
    }

    if (bRestored)
    {
        Avatar = nullptr;
        OriginalActorLiveLinkSubject = NAME_None;
        OriginalBodyAnimClass = nullptr;
        OriginalBodyAnimationModeValue = 0;
        bOriginalUseLiveLink = false;
        bHasOriginalAvatarConfiguration = false;
    }
    LiveLinkHeartbeatElapsedSeconds = 0.0;
    LiveLinkPendingElapsedSeconds = 0.0;
    bLiveLinkPendingGraceLogged = false;
    return bRestored;
}

void UFayMetaHumanSpeechDriverComponent::HandleDecodedPcm(
    const FFayAvatarMessage& Message,
    const TArray<uint8>& Pcm16,
    const int32 SampleRate,
    const int32 NumChannels)
{
    ResetSpeechState();
    if (!IsAvatarConfigured())
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("Skipping speech animation because no verified MetaHuman Live Link consumer is configured."));
        return;
    }
    if (SampleRate < 8000 || SampleRate > 192000 ||
        (NumChannels != 1 && NumChannels != 2) || Pcm16.IsEmpty() ||
        (Pcm16.Num() % (static_cast<int32>(sizeof(int16)) * NumChannels)) != 0)
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning,
            TEXT("Skipping speech animation for an unsupported or empty PCM16 payload."));
        return;
    }

    DecodeAndResamplePcm16(
        Pcm16,
        SampleRate,
        NumChannels,
        SpeechSamples);
    SpeechSampleRate = SolverSampleRate;
    SpeechNumChannels = 1;
    SpeechFramesPerStep = SolverSampleRate / SolverFramesPerSecond;
    RemainingTailSteps = TailSolveSteps;
    MoodValue = static_cast<uint8>(ResolveMood(Message));
    MoodIntensity = ResolveMoodIntensity(Message);
    if (bRecreateSolverBetweenUtterances)
    {
        RuntimeState->Solver.Reset();
        FMemory::Trim(true);
        RuntimeState->Solver = MakeShared<FSpeechAnimationSolverV4>(
            SpeechModel,
            TEXT("NNERuntimeORTCpu"));
        if (!RuntimeState->Solver->Initialize() ||
            RuntimeState->Solver->GetNumCurves() != ExpectedSolverCurveCount ||
            RuntimeState->Solver->GetCurveNames().Num() != ExpectedSolverCurveCount)
        {
            UE_LOG(LogFayMetaHumanRuntime, Error,
                TEXT("Could not recreate the StreamingADA solver for the next utterance."));
            RuntimeState->Solver.Reset();
            return;
        }
    }
    else if (bResetSolverCacheBetweenUtterances)
    {
        RuntimeState->Solver->ClearCache();
    }
    bSpeechPrepared = true;
}

void UFayMetaHumanSpeechDriverComponent::HandleSpeechStarted(
    const FFayAvatarMessage& Message,
    const float DurationSeconds)
{
    if (!bSpeechPrepared)
    {
        return;
    }
    ExpectedSpeechDurationSeconds = FMath::Max(DurationSeconds, 0.0f);
    HeadGestureValue = static_cast<uint8>(EFaySemanticHeadGesture::None);
    HeadGestureStrength = 0.0f;
    HeadGestureDurationSeconds = 0.0f;

    const EFaySemanticHeadGesture Gesture = ResolveSemanticHeadGesture(Message);
    switch (Gesture)
    {
    case EFaySemanticHeadGesture::BodyOwnedWave:
        UE_LOG(LogFayMetaHumanRuntime, Display,
            TEXT("Fay wave action was delegated to the character-neutral body-motion provider."));
        break;
    case EFaySemanticHeadGesture::BodyOwnedInvite:
        UE_LOG(LogFayMetaHumanRuntime, Display,
            TEXT("Fay invitation action was delegated to the character-neutral body-motion provider."));
        break;
    case EFaySemanticHeadGesture::Nod:
    case EFaySemanticHeadGesture::Shake:
    case EFaySemanticHeadGesture::Think:
    case EFaySemanticHeadGesture::Warn:
        if (bEnableSemanticHeadGestures)
        {
            const float RequestedIntensity = FMath::IsFinite(Message.Action.Intensity)
                ? FMath::Clamp(Message.Action.Intensity, 0.0f, 1.0f)
                : 0.0f;
            HeadGestureValue = static_cast<uint8>(Gesture);
            HeadGestureStrength = FMath::Lerp(0.45f, 1.0f, RequestedIntensity);
            const int32 SpeechSolveSteps = SpeechFramesPerStep > 0
                ? (SpeechSamples.Num() + SpeechFramesPerStep - 1) / SpeechFramesPerStep
                : 0;
            const float AvailableDuration = FMath::Max(
                1.0f / static_cast<float>(SolverFramesPerSecond),
                static_cast<float>(SpeechSolveSteps + TailSolveSteps - 1) /
                    static_cast<float>(SolverFramesPerSecond));
            HeadGestureDurationSeconds = FMath::Min(
                GetGestureBaseDurationSeconds(Gesture),
                AvailableDuration);
        }
        break;
    default:
        break;
    }
    AnimationElapsedSeconds = 0.0;
    bSpeechStarted = true;
    bSpeechFinished = false;
}

void UFayMetaHumanSpeechDriverComponent::HandleSpeechFinished(const FFayAvatarMessage& Message)
{
    (void)Message;
    bSpeechFinished = true;
}

void UFayMetaHumanSpeechDriverComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    if (IsValid(PendingAvatar))
    {
        // A source registered during the first game frame can remain pending
        // if its one bootstrap frame is processed before Live Link has fully
        // attached the subject. Keep publishing the same bounded neutral frame
        // until the exact source becomes evaluable; this also makes a cold
        // launch independent of scheduler timing.
        LiveLinkHeartbeatElapsedSeconds += FMath::Max(DeltaTime, 0.0f);
        if (IsSolverReady() &&
            LiveLinkHeartbeatElapsedSeconds >= LiveLinkHeartbeatSeconds)
        {
            RuntimeState->PushNeutral();
            LiveLinkHeartbeatElapsedSeconds = 0.0;
        }
        TryConfigurePendingAvatar();
    }

    if (IsValid(Avatar) && IsSolverReady())
    {
        const bool bSpeechDriving = bSpeechPrepared && bSpeechStarted;
        if (bSpeechDriving)
        {
            LiveLinkHeartbeatElapsedSeconds = 0.0;
        }
        else
        {
            LiveLinkHeartbeatElapsedSeconds += FMath::Max(DeltaTime, 0.0f);
            if (LiveLinkHeartbeatElapsedSeconds >= LiveLinkHeartbeatSeconds)
            {
                RuntimeState->PushNeutral();
                LiveLinkHeartbeatElapsedSeconds = 0.0;
            }
        }
    }

    if (IsValid(Avatar))
    {
        FString ConsumerReason;
        const bool bConsumerReady = HasVerifiedLiveLinkConsumer(
            Avatar,
            LiveLinkSubjectName,
            &ConsumerReason);
        FString ReadinessReason;
        const bool bSolverReady = IsSolverReady();
        const EFayLiveLinkSubjectReadiness SubjectReadiness =
            bSolverReady
            ? RuntimeState->Source->GetExactSubjectReadiness(ReadinessReason)
            : EFayLiveLinkSubjectReadiness::Invalid;
        if (!bSolverReady)
        {
            ReadinessReason = TEXT("the local solver or Live Link source is unavailable");
        }
        const bool bRuntimeHealthy = bConsumerReady &&
            SubjectReadiness == EFayLiveLinkSubjectReadiness::Ready;
        if (bConsumerReady &&
            SubjectReadiness == EFayLiveLinkSubjectReadiness::Pending)
        {
            LiveLinkPendingElapsedSeconds += FMath::Max(DeltaTime, 0.0f);
            if (!bLiveLinkPendingGraceLogged)
            {
                UE_LOG(LogFayMetaHumanRuntime, Display,
                    TEXT("Keeping Ada configured while the exact Fay Live Link subject is "
                         "temporarily pending (%s)."),
                    *ReadinessReason);
                bLiveLinkPendingGraceLogged = true;
            }
            if (LiveLinkPendingElapsedSeconds < LiveLinkPendingGraceSeconds)
            {
                return;
            }
            ReadinessReason = FString::Printf(
                TEXT("the subject remained pending beyond %.1f seconds: %s"),
                LiveLinkPendingGraceSeconds,
                *ReadinessReason);
        }
        if (bRuntimeHealthy)
        {
            if (bLiveLinkPendingGraceLogged)
            {
                UE_LOG(LogFayMetaHumanRuntime, Display,
                    TEXT("The exact Fay Live Link subject is evaluable again."));
            }
            LiveLinkPendingElapsedSeconds = 0.0;
            bLiveLinkPendingGraceLogged = false;
            bTerminalSubjectFailureLogged = false;
        }
        else
        {
            if (!bTerminalSubjectFailureLogged)
            {
                UE_LOG(LogFayMetaHumanRuntime, Error,
                    TEXT("The Fay MetaHuman runtime contract failed; restoring Ada "
                         "(consumer=%s; source=%s)."),
                    bConsumerReady ? TEXT("ready") : *ConsumerReason,
                    SubjectReadiness == EFayLiveLinkSubjectReadiness::Ready
                        ? TEXT("ready")
                        : *ReadinessReason);
                bTerminalSubjectFailureLogged = true;
            }
            if (RuntimeState.IsValid())
            {
                RuntimeState->PushNeutral();
            }
            RestoreConfiguredAvatar();
            ResetSpeechState();
            if (SubjectReadiness == EFayLiveLinkSubjectReadiness::Collision ||
                SubjectReadiness == EFayLiveLinkSubjectReadiness::Invalid)
            {
                ShutdownSource();
            }
            return;
        }
    }

    if (!bSpeechPrepared || !bSpeechStarted || !IsSolverReady())
    {
        return;
    }
    if (!HasVerifiedLiveLinkConsumer(Avatar, LiveLinkSubjectName))
    {
        RuntimeState->PushNeutral();
        ResetSpeechState();
        return;
    }

    AnimationElapsedSeconds += FMath::Max(DeltaTime, 0.0f);
    if (!bSpeechFinished && Bridge != nullptr && !Bridge->IsSpeechPlaying() &&
        AnimationElapsedSeconds > 0.1)
    {
        RuntimeState->PushNeutral();
        ResetSpeechState();
        return;
    }

    const int32 DesiredSteps = FMath::FloorToInt32(
        AnimationElapsedSeconds * static_cast<double>(SolverFramesPerSecond)) + 1;
    const int32 StepsBehind = FMath::Max(0, DesiredSteps - SolvedStepCount);
    const int32 NormalStepLimit = FMath::Clamp(MaximumSolveStepsPerTick, 1, 4);
    const int32 CatchUpStepLimit = FMath::Clamp(
        MaximumCatchUpSolveStepsPerTick,
        NormalStepLimit,
        8);
    // Pay the larger synchronous cost only when elapsed playback time proves
    // that the 50 Hz solver has accumulated a backlog.
    const int32 StepLimit = FMath::Min(
        CatchUpStepLimit,
        FMath::Max(NormalStepLimit, StepsBehind));
    int32 StepsThisTick = 0;
    while (SolvedStepCount < DesiredSteps && StepsThisTick < StepLimit)
    {
        if (!SolveNextFrame())
        {
            RuntimeState->PushNeutral();
            ResetSpeechState();
            break;
        }
        ++StepsThisTick;
    }
}

bool UFayMetaHumanSpeechDriverComponent::SolveNextFrame()
{
    if (!IsSolverReady() || SpeechFramesPerStep <= 0 || SpeechNumChannels <= 0)
    {
        return false;
    }

    const int32 TotalSpeechFrames = SpeechSamples.Num() / SpeechNumChannels;
    const int32 AvailableFrames = FMath::Max(0, TotalSpeechFrames - SpeechFrameCursor);
    const int32 FramesToCopy = FMath::Min(SpeechFramesPerStep, AvailableFrames);
    if (FramesToCopy == 0 && RemainingTailSteps <= 0)
    {
        return false;
    }

    FSpeechAnimationAudioFrame Input;
    Input.AudioSamples.SetNumZeroed(SpeechFramesPerStep * SpeechNumChannels);
    if (FramesToCopy > 0)
    {
        const int32 SourceSampleOffset = SpeechFrameCursor * SpeechNumChannels;
        const int32 SamplesToCopy = FramesToCopy * SpeechNumChannels;
        FMemory::Memcpy(
            Input.AudioSamples.GetData(),
            SpeechSamples.GetData() + SourceSampleOffset,
            SamplesToCopy * static_cast<int32>(sizeof(float)));
        SpeechFrameCursor += FramesToCopy;
    }
    else
    {
        --RemainingTailSteps;
    }

    Input.SamplesCount = SpeechFramesPerStep;
    Input.SampleRate = SpeechSampleRate;
    Input.NumChannels = SpeechNumChannels;
    Input.bContiguous = !bFirstSolverFrame;
    Input.Mood = static_cast<EAudioDrivenAnimationMood>(MoodValue);
    Input.MoodIntensity = MoodIntensity;
    Input.Lookahead = FMath::Clamp(LookaheadMilliseconds, 80, 240);
    Input.ArrivalTime = FPlatformTime::Seconds();
    Input.FrameId = FGuid::NewGuid();

    const double SolveStarted = FPlatformTime::Seconds();
    FSpeechAnimationFrameData Output;
    if (!RuntimeState->Solver->SolveAudioFrame(Input, Output) ||
        Output.CurveNames.Num() != Output.CurveValues.Num() ||
        Output.CurveNames.IsEmpty())
    {
        UE_LOG(LogFayMetaHumanRuntime, Error, TEXT("The speech-animation model failed to solve a PCM frame."));
        return false;
    }
    bFirstSolverFrame = false;
    ++SolvedStepCount;

    TMap<FString, float> GuiControls;
    GuiControls.Reserve(Output.CurveNames.Num());
    for (int32 Index = 0; Index < Output.CurveNames.Num(); ++Index)
    {
        GuiControls.Add(Output.CurveNames[Index].ToString(), Output.CurveValues[Index]);
    }
    const TMap<FString, float> RawControls =
        GuiToRawControlsUtils::ConvertGuiToRawControls(GuiControls);
    const float GestureElapsedSeconds = static_cast<float>(SolvedStepCount - 1) /
        static_cast<float>(SolverFramesPerSecond);
    const FFayHeadPose HeadPose = EvaluateHeadGesture(
        static_cast<EFaySemanticHeadGesture>(HeadGestureValue),
        GestureElapsedSeconds,
        HeadGestureDurationSeconds,
        HeadGestureStrength,
        MaximumHeadGestureDegrees);
    TArray<float> PropertyValues;
    if (!RuntimeState->TryMakePropertyValues(RawControls, PropertyValues, HeadPose))
    {
        UE_LOG(LogFayMetaHumanRuntime, Error,
            TEXT("The speech-animation output did not match the exact MetaHuman raw-control schema."));
        return false;
    }
    if (!RuntimeState->Source->PushValues(
            PropertyValues,
            false,
            HeadPose.bDriveOrientation))
    {
        UE_LOG(LogFayMetaHumanRuntime, Warning, TEXT("Live Link rejected a Fay facial-animation frame."));
        return false;
    }

    const double SolveMilliseconds = (FPlatformTime::Seconds() - SolveStarted) * 1000.0;
    SolveDurationsMilliseconds.Add(static_cast<float>(SolveMilliseconds));
    if (SolvedStepCount == 1)
    {
        UE_LOG(LogFayMetaHumanRuntime, Display,
            TEXT("Fay facial solve step completed in %.2f ms (step=%d)."),
            SolveMilliseconds,
            SolvedStepCount);
    }
    return true;
}

void UFayMetaHumanSpeechDriverComponent::ResetSpeechState()
{
    const bool bHadSolveResults = !SolveDurationsMilliseconds.IsEmpty();
    if (bHadSolveResults)
    {
        TArray<float> SortedDurations = SolveDurationsMilliseconds;
        SortedDurations.Sort();
        float TotalMilliseconds = 0.0f;
        for (const float DurationMilliseconds : SortedDurations)
        {
            TotalMilliseconds += DurationMilliseconds;
        }
        const int32 P95Index = FMath::Clamp(
            FMath::CeilToInt32(static_cast<float>(SortedDurations.Num()) * 0.95f) - 1,
            0,
            SortedDurations.Num() - 1);
        UE_LOG(LogFayMetaHumanRuntime, Display,
            TEXT("Fay facial solve summary (frames=%d, speech_seconds=%.3f, average_ms=%.2f, p95_ms=%.2f, maximum_ms=%.2f)."),
            SortedDurations.Num(),
            ExpectedSpeechDurationSeconds,
            TotalMilliseconds / static_cast<float>(SortedDurations.Num()),
            SortedDurations[P95Index],
            SortedDurations.Last());
    }

    SpeechSamples.Reset();
    SpeechSampleRate = 0;
    SpeechNumChannels = 0;
    SpeechFrameCursor = 0;
    SpeechFramesPerStep = 0;
    RemainingTailSteps = 0;
    SolvedStepCount = 0;
    AnimationElapsedSeconds = 0.0;
    SolveDurationsMilliseconds.Reset();
    ExpectedSpeechDurationSeconds = 0.0f;
    MoodIntensity = 1.0f;
    HeadGestureStrength = 0.0f;
    HeadGestureDurationSeconds = 0.0f;
    MoodValue = static_cast<uint8>(EAudioDrivenAnimationMood::Neutral);
    HeadGestureValue = static_cast<uint8>(EFaySemanticHeadGesture::None);
    bFirstSolverFrame = true;
    bSpeechPrepared = false;
    bSpeechStarted = false;
    bSpeechFinished = false;
    if (bHadSolveResults && bTrimMemoryAfterUtterance)
    {
        const double TrimStarted = FPlatformTime::Seconds();
        FMemory::Trim(true);
        UE_LOG(LogFayMetaHumanRuntime, Display,
            TEXT("Released completed-utterance allocator pools in %.2f ms."),
            (FPlatformTime::Seconds() - TrimStarted) * 1000.0);
    }
}

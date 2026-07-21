#include "FayBodyMotionComponent.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimMontage.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "FayArdyPoseClientComponent.h"
#include "FayBodyMotionProvider.h"
#include "GameFramework/Actor.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayBodyMotion, Log, All);

namespace
{
const TSet<FName>& AllowedBehaviors()
{
    static const TSet<FName> Behaviors = {
        TEXT("idle"), TEXT("listen"), TEXT("wave"), TEXT("invite"),
        TEXT("think"), TEXT("warn"), TEXT("nod"), TEXT("shake"),
        TEXT("explain")};
    return Behaviors;
}

FName NormalizeBehavior(const FName Behavior)
{
    return FName(*Behavior.ToString().TrimStartAndEnd().ToLower());
}

bool IsDeterministicBehavior(const FName Behavior)
{
    return Behavior == TEXT("wave") || Behavior == TEXT("invite") ||
        Behavior == TEXT("think") || Behavior == TEXT("warn") ||
        Behavior == TEXT("nod") || Behavior == TEXT("shake");
}

bool HasProceduralFallback(const FName Behavior)
{
    return Behavior == TEXT("wave") || Behavior == TEXT("invite") ||
        Behavior == TEXT("think") || Behavior == TEXT("warn") ||
        Behavior == TEXT("nod") || Behavior == TEXT("shake") ||
        Behavior == TEXT("explain");
}

constexpr int32 Core27JointCount = 27;
constexpr float GeneratedBlendInSeconds = 0.25f;
constexpr float MaximumRootOffsetCentimetres = 20.0f;

const TArray<FName>& Core27TargetBones()
{
    // Neck/head and the sparse Core27 hand endpoints remain intentionally
    // unmapped. StreamingADA and reviewed hand poses retain those controls.
    static const TArray<FName> Bones = {
        TEXT("pelvis"),
        TEXT("spine_01"), TEXT("spine_02"), TEXT("spine_03"), TEXT("spine_05"),
        NAME_None, NAME_None,
        TEXT("clavicle_r"), TEXT("upperarm_r"), TEXT("lowerarm_r"), TEXT("hand_r"),
        NAME_None, NAME_None,
        TEXT("clavicle_l"), TEXT("upperarm_l"), TEXT("lowerarm_l"), TEXT("hand_l"),
        NAME_None, NAME_None,
        TEXT("thigh_r"), TEXT("calf_r"), TEXT("foot_r"), TEXT("ball_r"),
        TEXT("thigh_l"), TEXT("calf_l"), TEXT("foot_l"), TEXT("ball_l")};
    return Bones;
}

FQuat ConvertArdyRotationToUnreal(const FQuat4f& Rotation)
{
    // ARDY X-right/Y-up/Z-forward -> Unreal X-forward/Y-right/Z-up.
    FQuat Converted(Rotation.Z, Rotation.X, Rotation.Y, Rotation.W);
    Converted.Normalize();
    return Converted;
}

FVector ConvertArdyTranslationToUnrealCentimetres(const FVector3f& Translation)
{
    return FVector(Translation.Z, Translation.X, Translation.Y) * 100.0;
}

USkeletalMeshComponent* FindNamedBodyMesh(AActor* Avatar, const FName ComponentName)
{
    if (!IsValid(Avatar) || ComponentName.IsNone())
    {
        return nullptr;
    }
    TInlineComponentArray<USkeletalMeshComponent*> Meshes(Avatar);
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        FString StableName = IsValid(Mesh) ? Mesh->GetName() : FString();
        StableName.RemoveFromEnd(TEXT("_GEN_VARIABLE"));
        if (StableName == ComponentName.ToString())
        {
            return Mesh;
        }
    }
    return nullptr;
}

class FBakedMotionProvider final : public IFayBodyMotionProvider
{
public:
    FBakedMotionProvider(
        USkeletalMeshComponent* InBodyMesh,
        TMap<FName, TSoftObjectPtr<UAnimMontage>>* InMontages,
        TFunction<void(const FFayBodyMotionRequest&)> InBeginProcedural,
        TFunction<void()> InStopProcedural)
        : BodyMesh(InBodyMesh), Montages(InMontages),
          BeginProcedural(MoveTemp(InBeginProcedural)),
          StopProcedural(MoveTemp(InStopProcedural))
    {
    }

    virtual EFayBodyMotionProvider GetKind() const override
    {
        return EFayBodyMotionProvider::Baked;
    }

    virtual bool IsReady() const override
    {
        return BodyMesh.IsValid() && Montages != nullptr;
    }

    virtual bool Perform(const FFayBodyMotionRequest& Request) override
    {
        if (!IsReady())
        {
            return false;
        }
        if (Request.Behavior == TEXT("idle") || Request.Behavior == TEXT("listen"))
        {
            Stop(0.2f);
            return true;
        }
        const TSoftObjectPtr<UAnimMontage>* MontageReference = Montages->Find(Request.Behavior);
        UAnimMontage* Montage = MontageReference != nullptr
            ? MontageReference->LoadSynchronous()
            : nullptr;
        UAnimInstance* Animation = BodyMesh->GetAnimInstance();
        if (IsValid(Montage) && IsValid(Animation))
        {
            StopProcedural();
            const float NaturalDuration = Montage->GetPlayLength();
            const float PlayRate = Request.DurationSeconds > 0.0f && NaturalDuration > 0.0f
                ? FMath::Clamp(NaturalDuration / Request.DurationSeconds, 0.5f, 2.0f)
                : 1.0f;
            return Animation->Montage_Play(Montage, PlayRate) > 0.0f;
        }
        if (!HasProceduralFallback(Request.Behavior))
        {
            return false;
        }
        BeginProcedural(Request);
        return true;
    }

    virtual void Stop(const float BlendOutSeconds) override
    {
        if (BodyMesh.IsValid() && IsValid(BodyMesh->GetAnimInstance()))
        {
            BodyMesh->GetAnimInstance()->Montage_Stop(FMath::Max(0.0f, BlendOutSeconds));
        }
        StopProcedural();
    }

    virtual void Tick(const float DeltaSeconds) override
    {
        (void)DeltaSeconds;
    }

private:
    TWeakObjectPtr<USkeletalMeshComponent> BodyMesh;
    TMap<FName, TSoftObjectPtr<UAnimMontage>>* Montages = nullptr;
    TFunction<void(const FFayBodyMotionRequest&)> BeginProcedural;
    TFunction<void()> StopProcedural;
};

/** Disabled until the validated loopback client owns a complete pose buffer. */
class FArdyMotionProvider final : public IFayBodyMotionProvider
{
public:
    FArdyMotionProvider(
        UFayArdyPoseClientComponent* InClient,
        const bool* InRetargetReady)
        : Client(InClient), RetargetReady(InRetargetReady)
    {
    }

    virtual EFayBodyMotionProvider GetKind() const override
    {
        return EFayBodyMotionProvider::Ardy;
    }
    virtual bool IsReady() const override
    {
        return Client.IsValid() && Client->IsReady() && RetargetReady != nullptr &&
            *RetargetReady;
    }
    virtual bool Perform(const FFayBodyMotionRequest& Request) override
    {
        return IsReady() && Client->StartBehavior(
            Request.Behavior,
            Request.Intensity,
            Request.DurationSeconds);
    }
    virtual void Stop(const float BlendOutSeconds) override
    {
        (void)BlendOutSeconds;
        if (Client.IsValid())
        {
            Client->StopBehavior();
        }
    }
    virtual void Tick(const float DeltaSeconds) override { (void)DeltaSeconds; }

private:
    TWeakObjectPtr<UFayArdyPoseClientComponent> Client;
    const bool* RetargetReady = nullptr;
};
}

UFayBodyMotionComponent::UFayBodyMotionComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UFayBodyMotionComponent::BeginPlay()
{
    Super::BeginPlay();
    if (Bridge != nullptr)
    {
        Bridge->OnMessageReceived.AddUniqueDynamic(
            this,
            &UFayBodyMotionComponent::HandleAvatarMessage);
    }
}

void UFayBodyMotionComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (Bridge != nullptr)
    {
        Bridge->OnMessageReceived.RemoveDynamic(
            this,
            &UFayBodyMotionComponent::HandleAvatarMessage);
    }
    ResetProviders();
    Super::EndPlay(EndPlayReason);
}

void UFayBodyMotionComponent::TickComponent(
    const float DeltaTime,
    const ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (BakedProvider != nullptr)
    {
        BakedProvider->Tick(DeltaTime);
    }
    if (ArdyProvider != nullptr)
    {
        ArdyProvider->Tick(DeltaTime);
    }
    if (!ProceduralBehavior.IsNone())
    {
        ProceduralGestureElapsedSeconds += FMath::Max(0.0f, DeltaTime);
        if (ProceduralGestureElapsedSeconds >= ProceduralGestureDurationSeconds)
        {
            StopProceduralGesture();
            if (ActiveProvider == EFayBodyMotionProvider::Baked)
            {
                SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
            }
        }
    }
}

void UFayBodyMotionComponent::AttachBridge(UFayAvatarBridgeComponent* InBridge)
{
    if (Bridge == InBridge)
    {
        return;
    }
    if (HasBegunPlay() && Bridge != nullptr)
    {
        Bridge->OnMessageReceived.RemoveDynamic(
            this,
            &UFayBodyMotionComponent::HandleAvatarMessage);
    }
    Bridge = InBridge;
    if (HasBegunPlay() && Bridge != nullptr)
    {
        Bridge->OnMessageReceived.AddUniqueDynamic(
            this,
            &UFayBodyMotionComponent::HandleAvatarMessage);
    }
}

void UFayBodyMotionComponent::AttachArdyClient(UFayArdyPoseClientComponent* InClient)
{
    ArdyClient = InClient;
}

bool UFayBodyMotionComponent::ConfigureAvatar(
    AActor* InAvatar,
    const FName BodyComponentName)
{
    ResetProviders();
    Avatar = InAvatar;
    BodyMesh = FindNamedBodyMesh(InAvatar, BodyComponentName);
    if (!IsValid(BodyMesh))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("The selected avatar has no reviewed '%s' body component; body motion remains disabled."),
            *BodyComponentName.ToString());
        SetState(EFayBodyMotionState::Error, EFayBodyMotionProvider::Baked);
        return false;
    }

    BakedProvider = MakeUnique<FBakedMotionProvider>(
        BodyMesh,
        &BakedMontages,
        [this](const FFayBodyMotionRequest& Request)
        {
            BeginProceduralGesture(Request);
        },
        [this]()
        {
            StopProceduralGesture();
        });
    bGeneratedRetargetReady = ConfigureGeneratedRetarget();
    ArdyProvider = MakeUnique<FArdyMotionProvider>(ArdyClient, &bGeneratedRetargetReady);
    SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Configured character-neutral body-motion routing (face/head excluded, generated retarget=%s)."),
        bGeneratedRetargetReady ? TEXT("ready") : TEXT("disabled"));
    return true;
}

bool UFayBodyMotionComponent::ConfigureGeneratedRetarget()
{
    if (!IsValid(BodyMesh) || !IsValid(BodyMesh->GetSkeletalMeshAsset()))
    {
        return false;
    }
    const TArray<FName>& TargetBones = Core27TargetBones();
    if (TargetBones.Num() != Core27JointCount)
    {
        return false;
    }
    Core27TargetBoneIndices.SetNum(Core27JointCount);
    int32 MappedBodyBones = 0;
    for (int32 Index = 0; Index < TargetBones.Num(); ++Index)
    {
        Core27TargetBoneIndices[Index] = TargetBones[Index].IsNone()
            ? INDEX_NONE
            : BodyMesh->GetBoneIndex(TargetBones[Index]);
        if (!TargetBones[Index].IsNone() && Core27TargetBoneIndices[Index] == INDEX_NONE)
        {
            UE_LOG(LogFayBodyMotion, Warning,
                TEXT("Generated retarget disabled: reviewed target bone '%s' is absent."),
                *TargetBones[Index].ToString());
            Core27TargetBoneIndices.Reset();
            return false;
        }
        MappedBodyBones += Core27TargetBoneIndices[Index] != INDEX_NONE ? 1 : 0;
    }
    if (MappedBodyBones < 19)
    {
        Core27TargetBoneIndices.Reset();
        return false;
    }

    ResetRetargetCalibration();
    BodyTransformsFinalizedHandle = BodyMesh->RegisterOnBoneTransformsFinalizedDelegate(
        FOnBoneTransformsFinalizedMultiCast::FDelegate::CreateUObject(
            this,
            &UFayBodyMotionComponent::HandleBodyTransformsFinalized));
    return BodyTransformsFinalizedHandle.IsValid();
}

void UFayBodyMotionComponent::HandleBodyTransformsFinalized()
{
    if (!bGeneratedRetargetReady || !IsValid(BodyMesh))
    {
        return;
    }
    if (ActiveProvider == EFayBodyMotionProvider::Baked &&
        !ProceduralBehavior.IsNone())
    {
        ApplyProceduralGesture();
        GeneratedBlendWeight = 0.0f;
        return;
    }
    if (!IsValid(ArdyClient) || ActiveProvider != EFayBodyMotionProvider::Ardy)
    {
        GeneratedBlendWeight = 0.0f;
        return;
    }

    const UWorld* World = GetWorld();
    const double Now = World != nullptr ? World->GetTimeSeconds() : 0.0;
    const float DeltaSeconds = LastRetargetSampleSeconds > 0.0
        ? static_cast<float>(FMath::Clamp(Now - LastRetargetSampleSeconds, 0.0, 0.1))
        : 1.0f / 60.0f;
    LastRetargetSampleSeconds = Now;

    FFayArdyPoseFrame Pose;
    const bool bHasFreshPose = ArdyClient->SamplePose(DeltaSeconds, Pose) &&
        Pose.JointRotations.Num() == Core27JointCount;
    if (!bHasFreshPose)
    {
        GeneratedBlendWeight = FMath::Max(
            0.0f,
            GeneratedBlendWeight - DeltaSeconds / GeneratedBlendInSeconds);
        if (!bHasLastGeneratedPose || GeneratedBlendWeight <= 0.0f)
        {
            return;
        }
        Pose = LastGeneratedPose;
    }
    else
    {
        LastGeneratedPose = Pose;
        bHasLastGeneratedPose = true;
    }

    if (ArdyBaselineLocalRotations.Num() != Core27JointCount)
    {
        ArdyBaselineLocalRotations = Pose.JointRotations;
        ArdyBaselineRootTranslation = Pose.RootTranslationMetres;
        GeneratedBlendWeight = 0.0f;
        return;
    }

    if (bHasFreshPose)
    {
        GeneratedBlendWeight = FMath::Min(
            1.0f,
            GeneratedBlendWeight + DeltaSeconds / GeneratedBlendInSeconds);
    }

    // FinalizeBoneTransform has just flipped the evaluated pose into the read
    // buffer. This callback still precedes attachment, bounds, and render-data
    // updates. The compatibility write is limited to the pinned UE 5.8 build
    // and the validated skeleton mapping above.
    const TArray<FTransform>& EvaluatedTransforms = BodyMesh->GetComponentSpaceTransforms();
    if (EvaluatedTransforms.Num() != BodyMesh->GetNumBones())
    {
        return;
    }
    TArray<FTransform> OriginalTransforms = EvaluatedTransforms;
    TArray<FTransform>& OutputTransforms =
        const_cast<TArray<FTransform>&>(BodyMesh->GetComponentSpaceTransforms());
    const FReferenceSkeleton& ReferenceSkeleton =
        BodyMesh->GetSkeletalMeshAsset()->GetRefSkeleton();

    TMap<int32, FQuat> BoneDeltas;
    for (int32 JointIndex = 0; JointIndex < Core27JointCount; ++JointIndex)
    {
        const int32 BoneIndex = Core27TargetBoneIndices[JointIndex];
        if (BoneIndex == INDEX_NONE || BoneIndex >= OutputTransforms.Num())
        {
            continue;
        }
        FQuat4f Delta = Pose.JointRotations[JointIndex] *
            ArdyBaselineLocalRotations[JointIndex].Inverse();
        Delta.Normalize();
        FQuat ConvertedDelta = ConvertArdyRotationToUnreal(Delta);
        ConvertedDelta = FQuat::Slerp(FQuat::Identity, ConvertedDelta, GeneratedBlendWeight);
        BoneDeltas.Add(BoneIndex, ConvertedDelta);
    }

    FVector RootOffset = ConvertArdyTranslationToUnrealCentimetres(
        Pose.RootTranslationMetres - ArdyBaselineRootTranslation);
    RootOffset = RootOffset.GetClampedToMaxSize(MaximumRootOffsetCentimetres) *
        GeneratedBlendWeight;
    const int32 PelvisIndex = Core27TargetBoneIndices[0];

    for (int32 BoneIndex = 0; BoneIndex < OutputTransforms.Num(); ++BoneIndex)
    {
        const int32 ParentIndex = ReferenceSkeleton.GetParentIndex(BoneIndex);
        FTransform LocalTransform = ParentIndex == INDEX_NONE
            ? OriginalTransforms[BoneIndex]
            : OriginalTransforms[BoneIndex].GetRelativeTransform(
                OriginalTransforms[ParentIndex]);
        if (const FQuat* Delta = BoneDeltas.Find(BoneIndex))
        {
            LocalTransform.SetRotation((*Delta * LocalTransform.GetRotation()).GetNormalized());
        }
        if (BoneIndex == PelvisIndex)
        {
            LocalTransform.AddToTranslation(RootOffset);
        }
        OutputTransforms[BoneIndex] = ParentIndex == INDEX_NONE
            ? LocalTransform
            : LocalTransform * OutputTransforms[ParentIndex];
    }
}

void UFayBodyMotionComponent::BeginProceduralGesture(
    const FFayBodyMotionRequest& Request)
{
    ProceduralBehavior = Request.Behavior;
    ProceduralGestureElapsedSeconds = 0.0f;
    ProceduralGestureDurationSeconds = FMath::Max(0.2f, Request.DurationSeconds);
    ProceduralGestureIntensity = FMath::Clamp(Request.Intensity, 0.0f, 1.0f);
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Using character-neutral procedural fallback for '%s'."),
        *ProceduralBehavior.ToString());
}

void UFayBodyMotionComponent::StopProceduralGesture()
{
    ProceduralBehavior = NAME_None;
    ProceduralGestureElapsedSeconds = 0.0f;
    ProceduralGestureDurationSeconds = 0.0f;
    ProceduralGestureIntensity = 0.0f;
}

void UFayBodyMotionComponent::ApplyProceduralGesture()
{
    const TArray<FTransform>& EvaluatedTransforms = BodyMesh->GetComponentSpaceTransforms();
    if (EvaluatedTransforms.Num() != BodyMesh->GetNumBones() ||
        Core27TargetBoneIndices.Num() != Core27JointCount)
    {
        return;
    }

    const float Duration = FMath::Max(0.2f, ProceduralGestureDurationSeconds);
    const float Progress = FMath::Clamp(
        ProceduralGestureElapsedSeconds / Duration,
        0.0f,
        1.0f);
    const float BlendWindow = FMath::Min(0.2f, Duration * 0.25f);
    const float BlendIn = FMath::Clamp(
        ProceduralGestureElapsedSeconds / BlendWindow,
        0.0f,
        1.0f);
    const float BlendOut = FMath::Clamp(
        (Duration - ProceduralGestureElapsedSeconds) / BlendWindow,
        0.0f,
        1.0f);
    const float Weight = FMath::SmoothStep(
        0.0f,
        1.0f,
        FMath::Min(BlendIn, BlendOut)) *
        FMath::Lerp(0.45f, 1.0f, ProceduralGestureIntensity);

    TMap<int32, FQuat> BoneDeltas;
    const auto AddDelta = [&BoneDeltas, Weight](
        const int32 BoneIndex,
        const FVector Axis,
        const float Degrees)
    {
        if (BoneIndex != INDEX_NONE)
        {
            const FQuat Delta(Axis.GetSafeNormal(), FMath::DegreesToRadians(Degrees * Weight));
            if (FQuat* Existing = BoneDeltas.Find(BoneIndex))
            {
                *Existing = (Delta * *Existing).GetNormalized();
            }
            else
            {
                BoneDeltas.Add(BoneIndex, Delta);
            }
        }
    };

    // Core27 indices 8-10 and 14-16 are the reviewed right/left arm chains.
    if (ProceduralBehavior == TEXT("wave"))
    {
        AddDelta(Core27TargetBoneIndices[8], FVector::YAxisVector, -62.0f);
        AddDelta(Core27TargetBoneIndices[8], FVector::ZAxisVector, -24.0f);
        AddDelta(Core27TargetBoneIndices[9], FVector::YAxisVector, -78.0f);
        AddDelta(
            Core27TargetBoneIndices[10],
            FVector::XAxisVector,
            FMath::Sin(Progress * 6.0f * PI) * 28.0f);
    }
    else if (ProceduralBehavior == TEXT("invite") ||
        ProceduralBehavior == TEXT("explain"))
    {
        const float ConversationalSweep = ProceduralBehavior == TEXT("explain")
            ? FMath::Sin(Progress * 2.0f * PI) * 10.0f
            : 0.0f;
        AddDelta(Core27TargetBoneIndices[8], FVector::YAxisVector, -30.0f);
        AddDelta(Core27TargetBoneIndices[8], FVector::ZAxisVector, -20.0f - ConversationalSweep);
        AddDelta(Core27TargetBoneIndices[9], FVector::YAxisVector, -42.0f);
        AddDelta(Core27TargetBoneIndices[10], FVector::XAxisVector, 35.0f);
        AddDelta(Core27TargetBoneIndices[14], FVector::YAxisVector, 30.0f);
        AddDelta(Core27TargetBoneIndices[14], FVector::ZAxisVector, 20.0f - ConversationalSweep);
        AddDelta(Core27TargetBoneIndices[15], FVector::YAxisVector, 42.0f);
        AddDelta(Core27TargetBoneIndices[16], FVector::XAxisVector, -35.0f);
    }
    else if (ProceduralBehavior == TEXT("think"))
    {
        AddDelta(Core27TargetBoneIndices[8], FVector::YAxisVector, -38.0f);
        AddDelta(Core27TargetBoneIndices[8], FVector::ZAxisVector, -18.0f);
        AddDelta(Core27TargetBoneIndices[9], FVector::YAxisVector, -92.0f);
        AddDelta(Core27TargetBoneIndices[10], FVector::XAxisVector, 18.0f);
    }
    else if (ProceduralBehavior == TEXT("warn"))
    {
        AddDelta(Core27TargetBoneIndices[8], FVector::YAxisVector, -54.0f);
        AddDelta(Core27TargetBoneIndices[8], FVector::ZAxisVector, -12.0f);
        AddDelta(Core27TargetBoneIndices[9], FVector::YAxisVector, -64.0f);
        AddDelta(Core27TargetBoneIndices[10], FVector::XAxisVector, 70.0f);
    }
    // nod/shake intentionally leave the body unchanged; the face driver owns
    // their deterministic head curve so body motion cannot fight it.

    if (BoneDeltas.IsEmpty())
    {
        return;
    }
    TArray<FTransform> OriginalTransforms = EvaluatedTransforms;
    TArray<FTransform>& OutputTransforms =
        const_cast<TArray<FTransform>&>(BodyMesh->GetComponentSpaceTransforms());
    const FReferenceSkeleton& ReferenceSkeleton =
        BodyMesh->GetSkeletalMeshAsset()->GetRefSkeleton();
    for (int32 BoneIndex = 0; BoneIndex < OutputTransforms.Num(); ++BoneIndex)
    {
        const int32 ParentIndex = ReferenceSkeleton.GetParentIndex(BoneIndex);
        FTransform LocalTransform = ParentIndex == INDEX_NONE
            ? OriginalTransforms[BoneIndex]
            : OriginalTransforms[BoneIndex].GetRelativeTransform(
                OriginalTransforms[ParentIndex]);
        if (const FQuat* Delta = BoneDeltas.Find(BoneIndex))
        {
            LocalTransform.SetRotation((*Delta * LocalTransform.GetRotation()).GetNormalized());
        }
        OutputTransforms[BoneIndex] = ParentIndex == INDEX_NONE
            ? LocalTransform
            : LocalTransform * OutputTransforms[ParentIndex];
    }
}

void UFayBodyMotionComponent::ResetRetargetCalibration()
{
    ArdyBaselineLocalRotations.Reset();
    ArdyBaselineRootTranslation = FVector3f::ZeroVector;
    LastGeneratedPose = FFayArdyPoseFrame();
    GeneratedBlendWeight = 0.0f;
    LastRetargetSampleSeconds = 0.0;
    bHasLastGeneratedPose = false;
}

bool UFayBodyMotionComponent::PerformAction(
    const FName Behavior,
    const float Intensity,
    const float DurationSeconds)
{
    FFayBodyMotionRequest Request;
    Request.Behavior = NormalizeBehavior(Behavior);
    Request.Intensity = FMath::IsFinite(Intensity)
        ? FMath::Clamp(Intensity, 0.0f, 1.0f)
        : 0.5f;
    Request.DurationSeconds = FMath::IsFinite(DurationSeconds)
        ? FMath::Clamp(DurationSeconds, 0.2f, 10.0f)
        : 1.0f;
    return Dispatch(Request);
}

bool UFayBodyMotionComponent::IsBehaviorAllowed(const FName Behavior)
{
    return AllowedBehaviors().Contains(NormalizeBehavior(Behavior));
}

void UFayBodyMotionComponent::HandleAvatarMessage(const FFayAvatarMessage& Message)
{
    if (!Message.Action.bIsValid)
    {
        return;
    }
    FFayBodyMotionRequest Request;
    Request.Behavior = NormalizeBehavior(FName(*Message.Action.Behavior));
    Request.Intensity = FMath::IsFinite(Message.Action.Intensity)
        ? FMath::Clamp(Message.Action.Intensity, 0.0f, 1.0f)
        : 0.5f;
    Request.DurationSeconds = Message.DurationHintSeconds > 0.0f
        ? FMath::Clamp(Message.DurationHintSeconds, 0.2f, 10.0f)
        : 1.0f;
    Request.Priority = FMath::Clamp(Message.Action.Priority, -100, 100);
    Dispatch(Request);
}

bool UFayBodyMotionComponent::Dispatch(const FFayBodyMotionRequest& Request)
{
    if (!IsBehaviorAllowed(Request.Behavior))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Rejected non-allowlisted avatar behavior '%s'."),
            *Request.Behavior.ToString());
        return false;
    }
    if (BakedProvider == nullptr || !BakedProvider->IsReady())
    {
        EnterBakedIdle(Request.Behavior, TEXT("body motion is not configured"));
        return false;
    }

    IFayBodyMotionProvider* Preferred = BakedProvider.Get();
    if (!IsDeterministicBehavior(Request.Behavior) &&
        ArdyProvider != nullptr && ArdyProvider->IsReady())
    {
        Preferred = ArdyProvider.Get();
    }
    if (Preferred->Perform(Request))
    {
        if (Preferred == ArdyProvider.Get())
        {
            UE_LOG(LogFayBodyMotion, Display,
                TEXT("Using ARDY generated motion provider for '%s'."),
                *Request.Behavior.ToString());
        }
        SetState(
            Request.Behavior == TEXT("idle")
                ? EFayBodyMotionState::Idle
                : EFayBodyMotionState::Performing,
            Preferred->GetKind());
        return true;
    }

    if (Preferred != BakedProvider.Get() && BakedProvider->Perform(Request))
    {
        SetState(EFayBodyMotionState::FallingBack, EFayBodyMotionProvider::Baked);
        OnMotionFallback.Broadcast(Request.Behavior, TEXT("generated provider unavailable"));
        return true;
    }

    EnterBakedIdle(Request.Behavior, TEXT("no compatible reviewed baked clip"));
    return false;
}

void UFayBodyMotionComponent::EnterBakedIdle(
    const FName FailedBehavior,
    const FString& Reason)
{
    if (BakedProvider != nullptr)
    {
        BakedProvider->Stop(0.2f);
    }
    SetState(EFayBodyMotionState::FallingBack, EFayBodyMotionProvider::Baked);
    OnMotionFallback.Broadcast(FailedBehavior, Reason);
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Body action '%s' fell back safely to idle: %s."),
        *FailedBehavior.ToString(),
        *Reason);
}

void UFayBodyMotionComponent::SetState(
    const EFayBodyMotionState NewState,
    const EFayBodyMotionProvider Provider)
{
    if (MotionState == NewState && ActiveProvider == Provider)
    {
        return;
    }
    MotionState = NewState;
    ActiveProvider = Provider;
    OnMotionStateChanged.Broadcast(MotionState, ActiveProvider);
}

void UFayBodyMotionComponent::ResetProviders()
{
    if (BakedProvider != nullptr)
    {
        BakedProvider->Stop(0.1f);
    }
    if (ArdyProvider != nullptr)
    {
        ArdyProvider->Stop(0.1f);
    }
    BakedProvider.Reset();
    ArdyProvider.Reset();
    if (IsValid(BodyMesh) && BodyTransformsFinalizedHandle.IsValid())
    {
        BodyMesh->UnregisterOnBoneTransformsFinalizedDelegate(BodyTransformsFinalizedHandle);
        BodyTransformsFinalizedHandle.Reset();
    }
    ResetRetargetCalibration();
    StopProceduralGesture();
    Core27TargetBoneIndices.Reset();
    bGeneratedRetargetReady = false;
    BodyMesh = nullptr;
    Avatar = nullptr;
    SetState(EFayBodyMotionState::Unconfigured, EFayBodyMotionProvider::Baked);
}

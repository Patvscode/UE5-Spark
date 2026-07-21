#include "FayBodyMotionComponent.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimMontage.h"
#include "Components/SkeletalMeshComponent.h"
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
        TMap<FName, TSoftObjectPtr<UAnimMontage>>* InMontages)
        : BodyMesh(InBodyMesh), Montages(InMontages)
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
        if (!IsValid(Montage) || !IsValid(Animation))
        {
            return false;
        }
        const float NaturalDuration = Montage->GetPlayLength();
        const float PlayRate = Request.DurationSeconds > 0.0f && NaturalDuration > 0.0f
            ? FMath::Clamp(NaturalDuration / Request.DurationSeconds, 0.5f, 2.0f)
            : 1.0f;
        return Animation->Montage_Play(Montage, PlayRate) > 0.0f;
    }

    virtual void Stop(const float BlendOutSeconds) override
    {
        if (BodyMesh.IsValid() && IsValid(BodyMesh->GetAnimInstance()))
        {
            BodyMesh->GetAnimInstance()->Montage_Stop(FMath::Max(0.0f, BlendOutSeconds));
        }
    }

    virtual void Tick(const float DeltaSeconds) override
    {
        (void)DeltaSeconds;
    }

private:
    TWeakObjectPtr<USkeletalMeshComponent> BodyMesh;
    TMap<FName, TSoftObjectPtr<UAnimMontage>>* Montages = nullptr;
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

    BakedProvider = MakeUnique<FBakedMotionProvider>(BodyMesh, &BakedMontages);
    ArdyProvider = MakeUnique<FArdyMotionProvider>(ArdyClient, &bGeneratedRetargetReady);
    SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Configured character-neutral body-motion routing (face/head excluded, ARDY disabled until buffered validation)."));
    return true;
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
    BodyMesh = nullptr;
    Avatar = nullptr;
    SetState(EFayBodyMotionState::Unconfigured, EFayBodyMotionProvider::Baked);
}

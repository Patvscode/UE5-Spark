#include "FayBodyMotionComponent.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimMontage.h"
#include "Components/SceneComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "FayArdyCoordinateConversion.h"
#include "FayArdyPoseClientComponent.h"
#include "FayCore27Skeleton.h"
#include "FayCore27SourceAnimInstance.h"
#include "FayBodyMotionProvider.h"
#include "GameFramework/Actor.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayBodyMotion, Log, All);

namespace
{
const TSet<FName>& AllowedBehaviors()
{
    static const TSet<FName> Behaviors = {
        TEXT("idle"), TEXT("listen"), TEXT("wave"), TEXT("invite"),
        TEXT("think"), TEXT("warn"), TEXT("nod"), TEXT("shake"),
        TEXT("explain"), TEXT("jog_in_place"), TEXT("run_in_place"),
        TEXT("jumping_jacks"), TEXT("stretch"), TEXT("dance_relaxed")};
    return Behaviors;
}

FName NormalizeBehavior(const FName Behavior)
{
    return FName(*Behavior.ToString().TrimStartAndEnd().ToLower());
}

const TSet<FName>& ReviewedGeneratedBehaviors()
{
    static const TSet<FName> Behaviors = {
        TEXT("idle"), TEXT("listen"), TEXT("explain"), TEXT("wave"),
        TEXT("jog_in_place"), TEXT("run_in_place"),
        TEXT("jumping_jacks"), TEXT("stretch"), TEXT("dance_relaxed")};
    return Behaviors;
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
constexpr float GeneratedBlendOutMaximumSeconds = 0.50f;
constexpr int32 RetargetContractVersion = 2;
const FName ArdySourceInputProperty(TEXT("FayArdySourceMeshComponent"));
const FName ArdyBlendWeightProperty(TEXT("FayArdyBlendWeight"));
const FName ProceduralBehaviorProperty(TEXT("FayProceduralBehavior"));
const FName ProceduralProgressProperty(TEXT("FayProceduralProgress"));
const FName ProceduralIntensityProperty(TEXT("FayProceduralIntensity"));
const FName ContractVersionProperty(TEXT("FayArdyContractVersion"));
const FName ExcludesNeckHeadProperty(TEXT("FayArdyExcludesNeckAndHead"));
const FName PreservesFingersProperty(TEXT("FayArdyPreservesFingerPose"));
const FName UsesFootContactOffsetsProperty(TEXT("FayArdyUsesFootContactOffsets"));
const FName ArdyLeftHeelOffsetProperty(TEXT("FayArdyLeftHeelOffset"));
const FName ArdyLeftToeOffsetProperty(TEXT("FayArdyLeftToeOffset"));
const FName ArdyRightHeelOffsetProperty(TEXT("FayArdyRightHeelOffset"));
const FName ArdyRightToeOffsetProperty(TEXT("FayArdyRightToeOffset"));
const FName ArdyLeftHeelContactProperty(TEXT("FayArdyLeftHeelContact"));
const FName ArdyLeftToeContactProperty(TEXT("FayArdyLeftToeContact"));
const FName ArdyRightHeelContactProperty(TEXT("FayArdyRightHeelContact"));
const FName ArdyRightToeContactProperty(TEXT("FayArdyRightToeContact"));
const FName ArdyFootOffsetProperties[FFayArdyFootContactOutput::ContactCount] = {
    ArdyLeftHeelOffsetProperty,
    ArdyLeftToeOffsetProperty,
    ArdyRightHeelOffsetProperty,
    ArdyRightToeOffsetProperty};
const FName ArdyFootContactProperties[FFayArdyFootContactOutput::ContactCount] = {
    ArdyLeftHeelContactProperty,
    ArdyLeftToeContactProperty,
    ArdyRightHeelContactProperty,
    ArdyRightToeContactProperty};

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
        const bool* InSafeProceduralReady,
        TFunction<void(const FFayBodyMotionRequest&)> InBeginProcedural,
        TFunction<void()> InStopProcedural)
        : BodyMesh(InBodyMesh), Montages(InMontages),
          SafeProceduralReady(InSafeProceduralReady),
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

    virtual bool CanPerform(const FFayBodyMotionRequest& Request) const override
    {
        if (!IsReady())
        {
            return false;
        }
        if (Request.Behavior == TEXT("idle") || Request.Behavior == TEXT("listen"))
        {
            return true;
        }
        const TSoftObjectPtr<UAnimMontage>* MontageReference =
            Montages->Find(Request.Behavior);
        const bool bHasMontage = MontageReference != nullptr &&
            !MontageReference->IsNull();
        const bool bHasSafeProcedural = SafeProceduralReady != nullptr &&
            *SafeProceduralReady && HasProceduralFallback(Request.Behavior);
        return bHasMontage || bHasSafeProcedural;
    }

    virtual bool Perform(const FFayBodyMotionRequest& Request) override
    {
        if (!CanPerform(Request))
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
        if (SafeProceduralReady == nullptr || !*SafeProceduralReady ||
            !HasProceduralFallback(Request.Behavior))
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
    const bool* SafeProceduralReady = nullptr;
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
    virtual bool CanPerform(const FFayBodyMotionRequest& Request) const override
    {
        return IsReady() && Client->SupportsBehavior(Request.Behavior);
    }
    virtual bool Perform(const FFayBodyMotionRequest& Request) override
    {
        return CanPerform(Request) && Client->StartBehavior(
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
    const float SafeDeltaSeconds = FMath::Max(0.0f, DeltaTime);
    if (BakedProvider != nullptr)
    {
        BakedProvider->Tick(DeltaTime);
    }
    if (ArdyProvider != nullptr)
    {
        ArdyProvider->Tick(DeltaTime);
    }
    if (bGeneratedActionActive)
    {
        UpdateGeneratedRetarget(SafeDeltaSeconds);
    }
    if (!ProceduralBehavior.IsNone())
    {
        ProceduralGestureElapsedSeconds += SafeDeltaSeconds;
        UpdateProceduralGestureBinding();
        if (ProceduralGestureElapsedSeconds >= ProceduralGestureDurationSeconds)
        {
            StopProceduralGesture();
            if (ActiveProvider == EFayBodyMotionProvider::Baked)
            {
                SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
            }
        }
    }
    if (bGeneratedActionActive)
    {
        GeneratedActionElapsedSeconds += SafeDeltaSeconds;
        if (!bGeneratedBlendOutActive)
        {
            if (ArdyProvider == nullptr || !ArdyProvider->IsReady())
            {
                BeginGeneratedActionBlendOut(
                    true,
                    TEXT("generated provider became unavailable during the action"));
            }
            else if (GeneratedActionElapsedSeconds >= GeneratedActionDurationSeconds)
            {
                BeginGeneratedActionBlendOut(false, FString());
            }
        }
        if (bGeneratedBlendOutActive)
        {
            GeneratedBlendOutElapsedSeconds += SafeDeltaSeconds;
            const bool bPoseHasBlendedOut =
                GeneratedBlendOutElapsedSeconds >= GeneratedBlendInSeconds &&
                GeneratedBlendWeight <= KINDA_SMALL_NUMBER;
            if (bPoseHasBlendedOut ||
                GeneratedBlendOutElapsedSeconds >= GeneratedBlendOutMaximumSeconds)
            {
                CompleteGeneratedActionBlendOut();
            }
        }
    }
    if ((MotionState == EFayBodyMotionState::Performing ||
            MotionState == EFayBodyMotionState::FallingBack) &&
        ActiveProvider == EFayBodyMotionProvider::Baked &&
        ProceduralBehavior.IsNone())
    {
        const UAnimInstance* Animation = IsValid(BodyMesh)
            ? BodyMesh->GetAnimInstance()
            : nullptr;
        if (Animation == nullptr || !Animation->IsAnyMontagePlaying())
        {
            SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
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
        &bSafeProceduralReady,
        [this](const FFayBodyMotionRequest& Request)
        {
            BeginProceduralGesture(Request);
        },
        [this]()
        {
            StopProceduralGesture();
        });
    bGeneratedRetargetReady = ConfigureGeneratedRetarget();
    bSafeProceduralReady = bGeneratedRetargetReady;
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

    TInlineComponentArray<UFayArdyRetargetBindingComponent*> Bindings(Avatar);
    if (Bindings.Num() != 1 || !IsValid(Bindings[0]))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: the character must contain exactly one reviewed FayArdyRetargetBinding component."));
        return false;
    }
    RetargetBinding = Bindings[0];
    RetargetProfile = RetargetBinding->Profile.LoadSynchronous();
    FString FailureReason;
    if (!IsValid(RetargetProfile) ||
        !RetargetProfile->ValidateAssetReferences(FailureReason))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: %s."),
            FailureReason.IsEmpty() ? TEXT("the reviewed profile could not be loaded") : *FailureReason);
        TearDownGeneratedRetarget();
        return false;
    }

    USkeletalMesh* SourceAsset = RetargetProfile->Core27SourceMesh.LoadSynchronous();
    if (!FayValidateExactCore27Mesh(SourceAsset, FailureReason))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: %s."), *FailureReason);
        TearDownGeneratedRetarget();
        return false;
    }

    UClass* ExpectedPostProcessClass =
        RetargetProfile->TargetPostProcessAnimClass.LoadSynchronous();
    UObject* IKRetargeter = RetargetProfile->IKRetargeterAsset.LoadSynchronous();
    UObject* BlendMask = RetargetProfile->TargetBodyBlendMask.LoadSynchronous();
    if (!IsValid(ExpectedPostProcessClass) || !IsValid(IKRetargeter) ||
        IKRetargeter->GetClass()->GetPathName() != TEXT("/Script/IKRig.IKRetargeter") ||
        !IsValid(BlendMask) ||
        BlendMask->GetClass()->GetPathName() != TEXT("/Script/Engine.BlendProfile"))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: the profile does not resolve to the exact IKRetargeter and BlendProfile asset classes."));
        TearDownGeneratedRetarget();
        return false;
    }

    TargetPostProcessAnimation = BodyMesh->GetPostProcessInstance();
    if (!IsValid(TargetPostProcessAnimation) ||
        TargetPostProcessAnimation->GetClass() != ExpectedPostProcessClass)
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: Body does not run the exact reviewed post-process AnimBP '%s'."),
            *GetNameSafe(ExpectedPostProcessClass));
        TearDownGeneratedRetarget();
        return false;
    }

    const FIntProperty* VersionProperty = FindFProperty<FIntProperty>(
        TargetPostProcessAnimation->GetClass(), ContractVersionProperty);
    const FBoolProperty* ExclusionProperty = FindFProperty<FBoolProperty>(
        TargetPostProcessAnimation->GetClass(), ExcludesNeckHeadProperty);
    const FBoolProperty* FingersProperty = FindFProperty<FBoolProperty>(
        TargetPostProcessAnimation->GetClass(), PreservesFingersProperty);
    const FBoolProperty* ContactUsageProperty = FindFProperty<FBoolProperty>(
        TargetPostProcessAnimation->GetClass(), UsesFootContactOffsetsProperty);
    const FObjectPropertyBase* SourceInput = FindFProperty<FObjectPropertyBase>(
        TargetPostProcessAnimation->GetClass(), ArdySourceInputProperty);
    const FFloatProperty* WeightInput = FindFProperty<FFloatProperty>(
        TargetPostProcessAnimation->GetClass(), ArdyBlendWeightProperty);
    const FNameProperty* ProceduralNameInput = FindFProperty<FNameProperty>(
        TargetPostProcessAnimation->GetClass(), ProceduralBehaviorProperty);
    const FFloatProperty* ProceduralProgressInput = FindFProperty<FFloatProperty>(
        TargetPostProcessAnimation->GetClass(), ProceduralProgressProperty);
    const FFloatProperty* ProceduralIntensityInput = FindFProperty<FFloatProperty>(
        TargetPostProcessAnimation->GetClass(), ProceduralIntensityProperty);
    bool bContactContractValid = true;
    for (int32 ContactIndex = 0;
         ContactIndex < FFayArdyFootContactOutput::ContactCount;
         ++ContactIndex)
    {
        const FStructProperty* OffsetInput = FindFProperty<FStructProperty>(
            TargetPostProcessAnimation->GetClass(),
            ArdyFootOffsetProperties[ContactIndex]);
        const FFloatProperty* ContactInput = FindFProperty<FFloatProperty>(
            TargetPostProcessAnimation->GetClass(),
            ArdyFootContactProperties[ContactIndex]);
        bContactContractValid = bContactContractValid &&
            OffsetInput != nullptr &&
            OffsetInput->Struct == TBaseStructure<FVector>::Get() &&
            ContactInput != nullptr;
    }
    if (VersionProperty == nullptr ||
        VersionProperty->GetPropertyValue_InContainer(TargetPostProcessAnimation) !=
            RetargetContractVersion ||
        ExclusionProperty == nullptr ||
        !ExclusionProperty->GetPropertyValue_InContainer(TargetPostProcessAnimation) ||
        FingersProperty == nullptr ||
        !FingersProperty->GetPropertyValue_InContainer(TargetPostProcessAnimation) ||
        ContactUsageProperty == nullptr ||
        !ContactUsageProperty->GetPropertyValue_InContainer(
            TargetPostProcessAnimation) ||
        SourceInput == nullptr ||
        !SourceInput->PropertyClass->IsChildOf(USkeletalMeshComponent::StaticClass()) ||
        WeightInput == nullptr || ProceduralNameInput == nullptr ||
        ProceduralProgressInput == nullptr || ProceduralIntensityInput == nullptr ||
        !bContactContractValid)
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: the target AnimBP failed the sealed v%d inputs/head-exclusion/finger-preservation/contact-offset contract."),
            RetargetContractVersion);
        TearDownGeneratedRetarget();
        return false;
    }

    OriginalBodyAnimClass = BodyMesh->GetAnimClass();
    if (!IsValid(OriginalBodyAnimClass) || !IsValid(BodyMesh->GetAnimInstance()))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: Body has no ordinary animation instance to preserve."));
        TearDownGeneratedRetarget();
        return false;
    }

    ArdySourceMesh = NewObject<USkeletalMeshComponent>(
        Avatar,
        USkeletalMeshComponent::StaticClass(),
        TEXT("FayArdyCore27Source"));
    if (!IsValid(ArdySourceMesh))
    {
        TearDownGeneratedRetarget();
        return false;
    }
    Avatar->AddInstanceComponent(ArdySourceMesh);
    ArdySourceMesh->SetupAttachment(Avatar->GetRootComponent());
    ArdySourceMesh->SetSkeletalMesh(SourceAsset);
    ArdySourceMesh->SetAnimInstanceClass(UFayCore27SourceAnimInstance::StaticClass());
    ArdySourceMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    ArdySourceMesh->SetGenerateOverlapEvents(false);
    ArdySourceMesh->SetHiddenInGame(true, true);
    ArdySourceMesh->SetVisibility(false, true);
    ArdySourceMesh->VisibilityBasedAnimTickOption =
        EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
    ArdySourceMesh->RegisterComponent();
    ArdySourceAnimation = Cast<UFayCore27SourceAnimInstance>(
        ArdySourceMesh->GetAnimInstance());
    if (!IsValid(ArdySourceAnimation))
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: the hidden Core27 mesh rejected its native source AnimInstance."));
        TearDownGeneratedRetarget();
        return false;
    }

    // BodyMotion samples first, the hidden source evaluates second, and the
    // visible body/post-process retarget consumes that completed source third.
    ArdySourceMesh->AddTickPrerequisiteComponent(this);
    BodyMesh->AddTickPrerequisiteComponent(ArdySourceMesh);
    if (!SetTargetObjectInput(ArdySourceInputProperty, ArdySourceMesh) ||
        !SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f) ||
        !SetTargetNameInput(ProceduralBehaviorProperty, NAME_None) ||
        !SetTargetFloatInput(ProceduralProgressProperty, 0.0f) ||
        !SetTargetFloatInput(ProceduralIntensityProperty, 0.0f) ||
        !ApplyFootContactOutput(FFayArdyFootContactOutput()) ||
        BodyMesh->GetAnimClass() != OriginalBodyAnimClass)
    {
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("Generated retarget disabled: the target inputs could not be sealed without changing Body's main animation class."));
        TearDownGeneratedRetarget();
        return false;
    }

    ResetGeneratedRetargetState();
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Validated hidden Core27 -> IK Retargeter contract '%s'; Body main animation and face/head ownership remain unchanged."),
        *RetargetProfile->ProfileId.ToString());
    return true;
}

void UFayBodyMotionComponent::TearDownGeneratedRetarget()
{
    if (IsValid(TargetPostProcessAnimation))
    {
        SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
        SetTargetNameInput(ProceduralBehaviorProperty, NAME_None);
        ClearFootContactOutput();
        SetTargetObjectInput(ArdySourceInputProperty, nullptr);
    }
    if (IsValid(BodyMesh) && IsValid(ArdySourceMesh))
    {
        BodyMesh->RemoveTickPrerequisiteComponent(ArdySourceMesh);
    }
    if (IsValid(ArdySourceAnimation))
    {
        ArdySourceAnimation->ResetPose();
    }
    if (IsValid(ArdySourceMesh))
    {
        if (IsValid(Avatar))
        {
            Avatar->RemoveInstanceComponent(ArdySourceMesh);
        }
        ArdySourceMesh->DestroyComponent();
    }
    ArdySourceAnimation = nullptr;
    ArdySourceMesh = nullptr;
    TargetPostProcessAnimation = nullptr;
    OriginalBodyAnimClass = nullptr;
    RetargetProfile = nullptr;
    RetargetBinding = nullptr;
    ContactStabilizer.Reset();
    bGeneratedRetargetReady = false;
    bSafeProceduralReady = false;
}

bool UFayBodyMotionComponent::IsGeneratedRetargetBindingIntact() const
{
    return IsValid(BodyMesh) && IsValid(RetargetBinding) &&
        IsValid(RetargetProfile) && IsValid(ArdySourceMesh) &&
        IsValid(ArdySourceAnimation) && IsValid(TargetPostProcessAnimation) &&
        IsValid(OriginalBodyAnimClass) &&
        BodyMesh->GetAnimClass() == OriginalBodyAnimClass &&
        BodyMesh->GetPostProcessInstance() == TargetPostProcessAnimation &&
        TargetPostProcessAnimation->GetClass() ==
            RetargetProfile->TargetPostProcessAnimClass.Get();
}

void UFayBodyMotionComponent::UpdateGeneratedRetarget(const float DeltaSeconds)
{
    if (!bGeneratedRetargetReady || !IsGeneratedRetargetBindingIntact())
    {
        if (bGeneratedRetargetReady)
        {
            UE_LOG(LogFayBodyMotion, Error,
                TEXT("Generated retarget contract changed at runtime; disabling it without touching the evaluated Body pose."));
        }
        bGeneratedRetargetReady = false;
        bSafeProceduralReady = false;
        GeneratedBlendWeight = 0.0f;
        SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
        ContactStabilizer.Reset();
        ClearFootContactOutput();
        return;
    }
    if (!IsValid(ArdyClient) || ActiveProvider != EFayBodyMotionProvider::Ardy)
    {
        return;
    }

    FFayArdyPoseFrame Pose;
    const bool bHasFreshPose = ArdyClient->SamplePose(DeltaSeconds, Pose) &&
        Pose.JointRotations.Num() == Core27JointCount &&
        Pose.JointPositionsMetres.Num() == Core27JointCount &&
        Pose.Contacts.Num() == FFayArdyFootContactOutput::ContactCount;
    FFayArdyFootContactOutput ContactOutput;
    if (!bHasFreshPose)
    {
        ContactStabilizer.FadeOut(DeltaSeconds, ContactOutput);
        if (!ApplyFootContactOutput(ContactOutput))
        {
            bGeneratedRetargetReady = false;
            bSafeProceduralReady = false;
            GeneratedBlendWeight = 0.0f;
            SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
            return;
        }
        GeneratedBlendWeight = FMath::Max(
            0.0f,
            GeneratedBlendWeight - DeltaSeconds / GeneratedBlendInSeconds);
        if (!bHasLastGeneratedPose || GeneratedBlendWeight <= 0.0f)
        {
            SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
            return;
        }
        Pose = LastGeneratedPose;
    }
    else
    {
        if (!ContactStabilizer.Update(Pose, DeltaSeconds, ContactOutput) ||
            !ApplyFootContactOutput(ContactOutput))
        {
            bGeneratedRetargetReady = false;
            bSafeProceduralReady = false;
            GeneratedBlendWeight = 0.0f;
            SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
            ClearFootContactOutput();
            UE_LOG(LogFayBodyMotion, Error,
                TEXT("Generated contact stabilizer rejected a pose; ARDY retarget failed closed."));
            return;
        }
        LastGeneratedPose = Pose;
        bHasLastGeneratedPose = true;
        GeneratedBlendWeight = FMath::Min(
            1.0f,
            GeneratedBlendWeight + DeltaSeconds / GeneratedBlendInSeconds);
    }

    ArdySourceAnimation->SubmitPose(Pose, ComputeBoundedRootOffset(Pose));
    if (!SetTargetFloatInput(ArdyBlendWeightProperty, GeneratedBlendWeight))
    {
        bGeneratedRetargetReady = false;
        bSafeProceduralReady = false;
        GeneratedBlendWeight = 0.0f;
        ContactStabilizer.Reset();
        ClearFootContactOutput();
    }
}

FVector UFayBodyMotionComponent::ComputeBoundedRootOffset(
    const FFayArdyPoseFrame& Pose)
{
    if (!IsValid(RetargetProfile) ||
        RetargetProfile->RootMotionPolicy == EFayArdyRootMotionPolicy::LockedInPlace)
    {
        return FVector::ZeroVector;
    }
    if (!bHasGeneratedRootOrigin)
    {
        GeneratedRootOriginMetres = Pose.RootTranslationMetres;
        bHasGeneratedRootOrigin = true;
        return FVector::ZeroVector;
    }
    const FVector Offset = FayConvertArdyPositionToUnrealCentimetres(
        Pose.RootTranslationMetres - GeneratedRootOriginMetres);
    return Offset.GetClampedToMaxSize(
        RetargetProfile->MaximumRootOffsetCentimetres);
}

bool UFayBodyMotionComponent::SetTargetObjectInput(
    const FName PropertyName,
    UObject* Value)
{
    if (!IsValid(TargetPostProcessAnimation))
    {
        return false;
    }
    FObjectPropertyBase* Property = FindFProperty<FObjectPropertyBase>(
        TargetPostProcessAnimation->GetClass(), PropertyName);
    if (Property == nullptr ||
        (Value != nullptr && !Value->IsA(Property->PropertyClass)))
    {
        return false;
    }
    Property->SetObjectPropertyValue_InContainer(TargetPostProcessAnimation, Value);
    return Property->GetObjectPropertyValue_InContainer(TargetPostProcessAnimation) == Value;
}

bool UFayBodyMotionComponent::SetTargetFloatInput(
    const FName PropertyName,
    const float Value)
{
    if (!IsValid(TargetPostProcessAnimation) || !FMath::IsFinite(Value))
    {
        return false;
    }
    FFloatProperty* Property = FindFProperty<FFloatProperty>(
        TargetPostProcessAnimation->GetClass(), PropertyName);
    if (Property == nullptr)
    {
        return false;
    }
    Property->SetPropertyValue_InContainer(TargetPostProcessAnimation, Value);
    return FMath::IsNearlyEqual(
        Property->GetPropertyValue_InContainer(TargetPostProcessAnimation),
        Value,
        KINDA_SMALL_NUMBER);
}

bool UFayBodyMotionComponent::SetTargetNameInput(
    const FName PropertyName,
    const FName Value)
{
    if (!IsValid(TargetPostProcessAnimation))
    {
        return false;
    }
    FNameProperty* Property = FindFProperty<FNameProperty>(
        TargetPostProcessAnimation->GetClass(), PropertyName);
    if (Property == nullptr)
    {
        return false;
    }
    Property->SetPropertyValue_InContainer(TargetPostProcessAnimation, Value);
    return Property->GetPropertyValue_InContainer(TargetPostProcessAnimation) == Value;
}

bool UFayBodyMotionComponent::SetTargetVectorInput(
    const FName PropertyName,
    const FVector& Value)
{
    if (!IsValid(TargetPostProcessAnimation) || Value.ContainsNaN())
    {
        return false;
    }
    FStructProperty* Property = FindFProperty<FStructProperty>(
        TargetPostProcessAnimation->GetClass(), PropertyName);
    if (Property == nullptr ||
        Property->Struct != TBaseStructure<FVector>::Get())
    {
        return false;
    }
    FVector* Destination = Property->ContainerPtrToValuePtr<FVector>(
        TargetPostProcessAnimation);
    if (Destination == nullptr)
    {
        return false;
    }
    *Destination = Value;
    return Destination->Equals(Value, KINDA_SMALL_NUMBER);
}

bool UFayBodyMotionComponent::ApplyFootContactOutput(
    const FFayArdyFootContactOutput& Output)
{
    bool bAppliedAll = true;
    for (int32 ContactIndex = 0;
         ContactIndex < FFayArdyFootContactOutput::ContactCount;
         ++ContactIndex)
    {
        const FVector& Offset = Output.OffsetsCentimetres[ContactIndex];
        const float Weight = Output.Weights[ContactIndex];
        if (Offset.ContainsNaN() || Offset.Size() > 6.001f ||
            !FMath::IsFinite(Weight) || Weight < 0.0f || Weight > 1.0f ||
            !SetTargetVectorInput(
                ArdyFootOffsetProperties[ContactIndex], Offset) ||
            !SetTargetFloatInput(
                ArdyFootContactProperties[ContactIndex], Weight))
        {
            bAppliedAll = false;
        }
    }
    if (!bAppliedAll)
    {
        ClearFootContactOutput();
    }
    return bAppliedAll;
}

void UFayBodyMotionComponent::ClearFootContactOutput()
{
    for (int32 ContactIndex = 0;
         ContactIndex < FFayArdyFootContactOutput::ContactCount;
         ++ContactIndex)
    {
        SetTargetVectorInput(
            ArdyFootOffsetProperties[ContactIndex],
            FVector::ZeroVector);
        SetTargetFloatInput(
            ArdyFootContactProperties[ContactIndex],
            0.0f);
    }
}

void UFayBodyMotionComponent::BeginProceduralGesture(
    const FFayBodyMotionRequest& Request)
{
    ProceduralBehavior = Request.Behavior;
    ProceduralGestureElapsedSeconds = 0.0f;
    ProceduralGestureDurationSeconds = FMath::Max(0.2f, Request.DurationSeconds);
    ProceduralGestureIntensity = FMath::Clamp(Request.Intensity, 0.0f, 1.0f);
    UpdateProceduralGestureBinding();
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Using reviewed post-process procedural fallback for '%s'."),
        *ProceduralBehavior.ToString());
}

void UFayBodyMotionComponent::StopProceduralGesture()
{
    SetTargetNameInput(ProceduralBehaviorProperty, NAME_None);
    SetTargetFloatInput(ProceduralProgressProperty, 0.0f);
    SetTargetFloatInput(ProceduralIntensityProperty, 0.0f);
    ProceduralBehavior = NAME_None;
    ProceduralGestureElapsedSeconds = 0.0f;
    ProceduralGestureDurationSeconds = 0.0f;
    ProceduralGestureIntensity = 0.0f;
}

void UFayBodyMotionComponent::UpdateProceduralGestureBinding()
{
    if (!bSafeProceduralReady || !IsGeneratedRetargetBindingIntact() ||
        ProceduralBehavior.IsNone())
    {
        return;
    }
    const float Duration = FMath::Max(0.2f, ProceduralGestureDurationSeconds);
    const float Progress = FMath::Clamp(
        ProceduralGestureElapsedSeconds / Duration,
        0.0f,
        1.0f);
    if (!SetTargetNameInput(ProceduralBehaviorProperty, ProceduralBehavior) ||
        !SetTargetFloatInput(ProceduralProgressProperty, Progress) ||
        !SetTargetFloatInput(
            ProceduralIntensityProperty,
            FMath::Clamp(ProceduralGestureIntensity, 0.0f, 1.0f)))
    {
        bSafeProceduralReady = false;
    }
}

void UFayBodyMotionComponent::ResetGeneratedRetargetState()
{
    bHasGeneratedRootOrigin = false;
    GeneratedRootOriginMetres = FVector3f::ZeroVector;
    LastGeneratedPose = FFayArdyPoseFrame();
    GeneratedBlendWeight = 0.0f;
    bHasLastGeneratedPose = false;
    ContactStabilizer.Reset();
    if (IsValid(ArdySourceAnimation))
    {
        ArdySourceAnimation->ResetPose();
    }
    SetTargetFloatInput(ArdyBlendWeightProperty, 0.0f);
    ClearFootContactOutput();
}

void UFayBodyMotionComponent::StartGeneratedAction(
    const FFayBodyMotionRequest& Request)
{
    // Root displacement and cached pose are action-scoped. Rotations are the
    // absolute Core27 source pose; no first-frame local-delta calibration exists.
    ResetGeneratedRetargetState();
    GeneratedBehavior = Request.Behavior;
    GeneratedActionElapsedSeconds = 0.0f;
    GeneratedActionDurationSeconds = FMath::IsFinite(Request.DurationSeconds)
        ? FMath::Clamp(Request.DurationSeconds, 0.2f, 10.0f)
        : 1.0f;
    GeneratedBlendOutElapsedSeconds = 0.0f;
    bGeneratedActionActive = true;
    bGeneratedBlendOutActive = false;
}

void UFayBodyMotionComponent::BeginGeneratedActionBlendOut(
    const bool bProviderFailure,
    const FString& Reason)
{
    if (!bGeneratedActionActive || bGeneratedBlendOutActive)
    {
        return;
    }

    bGeneratedBlendOutActive = true;
    GeneratedBlendOutElapsedSeconds = 0.0f;
    if (ArdyProvider != nullptr)
    {
        // Stop new pose batches but leave this provider selected while the
        // target AnimBP's reviewed blend weight fades its last pose to zero.
        ArdyProvider->Stop(GeneratedBlendInSeconds);
    }

    if (bProviderFailure)
    {
        SetState(EFayBodyMotionState::FallingBack, EFayBodyMotionProvider::Ardy);
        OnMotionFallback.Broadcast(GeneratedBehavior, Reason);
        UE_LOG(LogFayBodyMotion, Warning,
            TEXT("ARDY action '%s' began a bounded fallback to baked idle: %s."),
            *GeneratedBehavior.ToString(),
            *Reason);
    }
    else
    {
        UE_LOG(LogFayBodyMotion, Display,
            TEXT("ARDY action '%s' reached its bounded duration; blending to baked idle."),
            *GeneratedBehavior.ToString());
    }
}

void UFayBodyMotionComponent::CompleteGeneratedActionBlendOut()
{
    if (!bGeneratedActionActive)
    {
        return;
    }

    const FName CompletedBehavior = GeneratedBehavior;
    GeneratedBlendWeight = 0.0f;
    GeneratedBehavior = NAME_None;
    GeneratedActionElapsedSeconds = 0.0f;
    GeneratedActionDurationSeconds = 0.0f;
    GeneratedBlendOutElapsedSeconds = 0.0f;
    bGeneratedActionActive = false;
    bGeneratedBlendOutActive = false;
    ResetGeneratedRetargetState();

    if (BakedProvider == nullptr || !BakedProvider->IsReady())
    {
        SetState(EFayBodyMotionState::Error, EFayBodyMotionProvider::Baked);
        OnMotionFallback.Broadcast(
            CompletedBehavior,
            TEXT("baked idle was unavailable after generated motion"));
        UE_LOG(LogFayBodyMotion, Error,
            TEXT("ARDY action '%s' stopped, but its reviewed baked-idle fallback was unavailable."),
            *CompletedBehavior.ToString());
        return;
    }

    BakedProvider->Stop(GeneratedBlendInSeconds);
    SetState(EFayBodyMotionState::Idle, EFayBodyMotionProvider::Baked);
    UE_LOG(LogFayBodyMotion, Display,
        TEXT("Completed bounded ARDY action '%s' and returned to baked idle."),
        *CompletedBehavior.ToString());
}

void UFayBodyMotionComponent::StopGeneratedActionImmediately()
{
    if (ArdyProvider != nullptr)
    {
        ArdyProvider->Stop(0.0f);
    }
    GeneratedBlendWeight = 0.0f;
    GeneratedBehavior = NAME_None;
    GeneratedActionElapsedSeconds = 0.0f;
    GeneratedActionDurationSeconds = 0.0f;
    GeneratedBlendOutElapsedSeconds = 0.0f;
    bGeneratedActionActive = false;
    bGeneratedBlendOutActive = false;
    ResetGeneratedRetargetState();
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

bool UFayBodyMotionComponent::CanEnterDormancy() const
{
    if (MotionState != EFayBodyMotionState::Idle || !IsValid(Avatar) ||
        !IsValid(BodyMesh) || BakedProvider == nullptr ||
        !BakedProvider->IsReady() || !ProceduralBehavior.IsNone() ||
        bGeneratedActionActive)
    {
        return false;
    }

    const UAnimInstance* Animation = BodyMesh->GetAnimInstance();
    return Animation == nullptr || !Animation->IsAnyMontagePlaying();
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

    const bool bReviewedGeneratedAction =
        ReviewedGeneratedBehaviors().Contains(Request.Behavior);
    IFayBodyMotionProvider* Preferred = BakedProvider.Get();
    if (bReviewedGeneratedAction && ArdyProvider != nullptr &&
        ArdyProvider->CanPerform(Request))
    {
        Preferred = ArdyProvider.Get();
    }
    if (Preferred->Perform(Request))
    {
        if (Preferred == ArdyProvider.Get())
        {
            StartGeneratedAction(Request);
            UE_LOG(LogFayBodyMotion, Display,
                TEXT("Using ARDY generated motion provider for '%s' (bounded_seconds=%.2f)."),
                *Request.Behavior.ToString(),
                GeneratedActionDurationSeconds);
        }
        else
        {
            if (bGeneratedActionActive)
            {
                StopGeneratedActionImmediately();
            }
        }
        const bool bUsedBakedFailureFallback =
            bReviewedGeneratedAction && Preferred == BakedProvider.Get();
        SetState(
            bUsedBakedFailureFallback
                ? EFayBodyMotionState::FallingBack
                : (Request.Behavior == TEXT("idle")
                    ? EFayBodyMotionState::Idle
                    : EFayBodyMotionState::Performing),
            Preferred->GetKind());
        if (bUsedBakedFailureFallback)
        {
            OnMotionFallback.Broadcast(
                Request.Behavior,
                TEXT("strict ARDY v2 or the reviewed retarget was unavailable"));
            UE_LOG(LogFayBodyMotion, Warning,
                TEXT("ARDY-first action '%s' used its reviewed baked/procedural failure fallback."),
                *Request.Behavior.ToString());
        }
        return true;
    }

    if (Preferred == BakedProvider.Get() && ArdyProvider != nullptr &&
        ArdyProvider->CanPerform(Request) && ArdyProvider->Perform(Request))
    {
        StartGeneratedAction(Request);
        SetState(
            Request.Behavior == TEXT("idle")
                ? EFayBodyMotionState::Idle
                : EFayBodyMotionState::Performing,
            EFayBodyMotionProvider::Ardy);
        return true;
    }

    if (Preferred != BakedProvider.Get() &&
        BakedProvider->CanPerform(Request) && BakedProvider->Perform(Request))
    {
        StopGeneratedActionImmediately();
        SetState(EFayBodyMotionState::FallingBack, EFayBodyMotionProvider::Baked);
        OnMotionFallback.Broadcast(Request.Behavior, TEXT("generated provider unavailable"));
        return true;
    }

    EnterBakedIdle(
        Request.Behavior,
        TEXT("no compatible generated, reviewed montage, or safe procedural motion"));
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
    StopGeneratedActionImmediately();
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
    StopGeneratedActionImmediately();
    BakedProvider.Reset();
    ArdyProvider.Reset();
    StopProceduralGesture();
    ResetGeneratedRetargetState();
    TearDownGeneratedRetarget();
    BodyMesh = nullptr;
    Avatar = nullptr;
    SetState(EFayBodyMotionState::Unconfigured, EFayBodyMotionProvider::Baked);
}

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FayWardrobeTypes.h"

#include "FayWardrobeComponent.generated.h"

class AActor;
class UMeshComponent;

/** Opts one reviewed character Blueprint into one sealed wardrobe profile. */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYWARDROBE_API UFayWardrobeBindingComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayWardrobeBindingComponent();

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    TSoftObjectPtr<UFayWardrobeProfileAsset> Profile;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName DefaultPresetId = NAME_None;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FFayWardrobeChangedEvent,
    FName,
    SlotId,
    FName,
    ItemId);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(
    FFayWardrobePresetEvent,
    FName,
    PresetId);

/**
 * Applies sealed logical wardrobe selections to components on one avatar.
 *
 * Profiles are packaged application data. User input may select an existing ID
 * but can never provide an Unreal object path or component name.
 */
UCLASS(ClassGroup = (Fay), meta = (BlueprintSpawnableComponent))
class FAYWARDROBE_API UFayWardrobeComponent final : public UActorComponent
{
    GENERATED_BODY()

public:
    UFayWardrobeComponent();

    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

    /** Validate the complete profile and actor before changing any visibility. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    bool ConfigureAvatar(AActor* InAvatar, const FFayWardrobeProfile& InProfile);

    /** Resolve exactly one private binding and apply its complete default preset. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    bool ConfigureFromReviewedBinding(AActor* InAvatar);

    /** Apply one complete reviewed preset atomically. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    bool ApplyPreset(FName PresetId);

    /** Change one slot to one reviewed item while retaining all other slots. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    bool SetSlotItem(FName SlotId, FName ItemId);

    /** Apply one complete reviewed slot selection atomically. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    bool ApplyCompleteSelection(const TMap<FName, FName>& Selection);

    /** Restore the actor's original visibility and discard all mappings. */
    UFUNCTION(BlueprintCallable, Category = "Fay|Wardrobe")
    void ResetWardrobe();

    UFUNCTION(BlueprintPure, Category = "Fay|Wardrobe")
    bool IsReady() const { return bReady; }

    UFUNCTION(BlueprintPure, Category = "Fay|Wardrobe")
    FName GetProfileId() const { return ActiveProfile.ProfileId; }

    UFUNCTION(BlueprintPure, Category = "Fay|Wardrobe")
    FName GetActiveItem(FName SlotId) const;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Wardrobe")
    FFayWardrobeChangedEvent OnSlotChanged;

    UPROPERTY(BlueprintAssignable, Category = "Fay|Wardrobe")
    FFayWardrobePresetEvent OnPresetApplied;

private:
    struct FOriginalVisibility
    {
        bool bVisible = true;
        bool bHiddenInGame = false;
        bool bTickEnabled = false;
    };

    bool ValidateAndResolveProfile(
        AActor* InAvatar,
        const FFayWardrobeProfile& InProfile,
        TMap<FName, TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>>& OutComponents,
        TMap<TWeakObjectPtr<UMeshComponent>, FOriginalVisibility>& OutVisibility,
        FString& OutError) const;
    bool ApplySelection(const TMap<FName, FName>& Selection, FString& OutError);
    static bool SelectionIsFullyUnclothed(
        const TMap<FName, FName>& Selection,
        const FFayWardrobeProfile& Profile);
    static bool IsReviewedId(FName Value);

    UPROPERTY(Transient)
    TObjectPtr<AActor> Avatar;

    FFayWardrobeProfile ActiveProfile;
    TMap<FName, TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>> ComponentsBySlot;
    TMap<TWeakObjectPtr<UMeshComponent>, FOriginalVisibility> OriginalVisibility;
    TMap<FName, FName> ActiveSelection;
    bool bReady = false;
};

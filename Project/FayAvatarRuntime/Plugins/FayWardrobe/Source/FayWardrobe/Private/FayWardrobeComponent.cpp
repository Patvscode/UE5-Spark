#include "FayWardrobeComponent.h"

#include "Components/MeshComponent.h"
#include "GameFramework/Actor.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayWardrobe, Log, All);

namespace
{
FString StableComponentName(const UActorComponent* Component)
{
    FString Name = IsValid(Component) ? Component->GetName() : FString();
    Name.RemoveFromEnd(TEXT("_GEN_VARIABLE"));
    return Name;
}
}

UFayWardrobeComponent::UFayWardrobeComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

UFayWardrobeBindingComponent::UFayWardrobeBindingComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UFayWardrobeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    ResetWardrobe();
    Super::EndPlay(EndPlayReason);
}

bool UFayWardrobeComponent::ConfigureAvatar(
    AActor* InAvatar,
    const FFayWardrobeProfile& InProfile)
{
    TMap<FName, TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>> ResolvedComponents;
    TMap<TWeakObjectPtr<UMeshComponent>, FOriginalVisibility> ResolvedVisibility;
    FString Error;
    if (!ValidateAndResolveProfile(
            InAvatar,
            InProfile,
            ResolvedComponents,
            ResolvedVisibility,
            Error))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Wardrobe profile was rejected without changing the avatar: %s"),
            *Error);
        return false;
    }

    ResetWardrobe();
    Avatar = InAvatar;
    ActiveProfile = InProfile;
    ComponentsBySlot = MoveTemp(ResolvedComponents);
    OriginalVisibility = MoveTemp(ResolvedVisibility);
    ActiveSelection.Reset();
    bReady = true;

    UE_LOG(LogFayWardrobe, Display,
        TEXT("Configured sealed wardrobe profile '%s' (slots=%d, presets=%d, fully_unclothed=%s)."),
        *ActiveProfile.ProfileId.ToString(),
        ActiveProfile.Slots.Num(),
        ActiveProfile.Presets.Num(),
        ActiveProfile.bAllowFullyUnclothed ? TEXT("reviewed") : TEXT("blocked"));
    return true;
}

bool UFayWardrobeComponent::ConfigureFromReviewedBinding(AActor* InAvatar)
{
    if (!IsValid(InAvatar))
    {
        return false;
    }
    TInlineComponentArray<UFayWardrobeBindingComponent*> Bindings(InAvatar);
    if (Bindings.Num() == 0)
    {
        UE_LOG(LogFayWardrobe, Verbose,
            TEXT("Avatar has no reviewed wardrobe binding; wardrobe remains disabled."));
        return false;
    }
    if (Bindings.Num() != 1 || !IsValid(Bindings[0]) ||
        Bindings[0]->Profile.IsNull() ||
        !IsReviewedId(Bindings[0]->DefaultPresetId))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Avatar wardrobe failed closed: expected exactly one complete reviewed binding."));
        return false;
    }

    UFayWardrobeProfileAsset* ProfileAsset =
        Bindings[0]->Profile.LoadSynchronous();
    if (!IsValid(ProfileAsset) ||
        !ConfigureAvatar(InAvatar, ProfileAsset->Profile) ||
        !ApplyPreset(Bindings[0]->DefaultPresetId))
    {
        ResetWardrobe();
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Avatar wardrobe binding or default preset was rejected and reset."));
        return false;
    }
    return true;
}

bool UFayWardrobeComponent::ApplyPreset(const FName PresetId)
{
    if (!bReady || !IsReviewedId(PresetId))
    {
        return false;
    }
    const FFayWardrobePreset* Preset = ActiveProfile.Presets.FindByPredicate(
        [PresetId](const FFayWardrobePreset& Candidate)
        {
            return Candidate.PresetId == PresetId;
        });
    if (Preset == nullptr ||
        (Preset->bFullyUnclothed && !ActiveProfile.bAllowFullyUnclothed))
    {
        UE_LOG(LogFayWardrobe, Warning,
            TEXT("Rejected unavailable or unreviewed wardrobe preset '%s'."),
            *PresetId.ToString());
        return false;
    }

    FString Error;
    if (!ApplySelection(Preset->SlotItems, Error))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Wardrobe preset '%s' failed closed: %s"),
            *PresetId.ToString(),
            *Error);
        return false;
    }
    OnPresetApplied.Broadcast(PresetId);
    return true;
}

bool UFayWardrobeComponent::SetSlotItem(const FName SlotId, const FName ItemId)
{
    if (!bReady || !IsReviewedId(SlotId) || !IsReviewedId(ItemId) ||
        !ComponentsBySlot.Contains(SlotId) ||
        !ComponentsBySlot.FindChecked(SlotId).Contains(ItemId))
    {
        return false;
    }
    TMap<FName, FName> Selection = ActiveSelection;
    if (Selection.Num() != ComponentsBySlot.Num())
    {
        UE_LOG(LogFayWardrobe, Warning,
            TEXT("A complete preset must be applied before individual wardrobe changes."));
        return false;
    }
    Selection.Add(SlotId, ItemId);
    if (SelectionIsFullyUnclothed(Selection, ActiveProfile) &&
        !ActiveProfile.bAllowFullyUnclothed)
    {
        UE_LOG(LogFayWardrobe, Warning,
            TEXT("Wardrobe slot change rejected by the independent complete-body approval gate."));
        return false;
    }
    FString Error;
    if (!ApplySelection(Selection, Error))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Wardrobe slot change failed closed: %s"), *Error);
        return false;
    }
    return true;
}

bool UFayWardrobeComponent::ApplyCompleteSelection(
    const TMap<FName, FName>& Selection)
{
    if (!bReady || Selection.Num() != ComponentsBySlot.Num())
    {
        return false;
    }
    for (const TPair<FName, FName>& Entry : Selection)
    {
        const TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>* Items =
            ComponentsBySlot.Find(Entry.Key);
        if (!IsReviewedId(Entry.Key) || !IsReviewedId(Entry.Value) ||
            Items == nullptr || !Items->Contains(Entry.Value))
        {
            return false;
        }
    }

    FString Error;
    if (!ApplySelection(Selection, Error))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Complete wardrobe selection failed closed: %s"), *Error);
        return false;
    }
    return true;
}

void UFayWardrobeComponent::ResetWardrobe()
{
    for (const TPair<TWeakObjectPtr<UMeshComponent>, FOriginalVisibility>& Entry :
        OriginalVisibility)
    {
        if (UMeshComponent* Component = Entry.Key.Get())
        {
            Component->SetVisibility(Entry.Value.bVisible, false);
            Component->SetHiddenInGame(Entry.Value.bHiddenInGame, false);
            Component->SetComponentTickEnabled(Entry.Value.bTickEnabled);
        }
    }
    Avatar = nullptr;
    ActiveProfile = FFayWardrobeProfile();
    ComponentsBySlot.Reset();
    OriginalVisibility.Reset();
    ActiveSelection.Reset();
    bReady = false;
}

FName UFayWardrobeComponent::GetActiveItem(const FName SlotId) const
{
    const FName* Value = ActiveSelection.Find(SlotId);
    return Value != nullptr ? *Value : NAME_None;
}

bool UFayWardrobeComponent::ValidateAndResolveProfile(
    AActor* InAvatar,
    const FFayWardrobeProfile& InProfile,
    TMap<FName, TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>>& OutComponents,
    TMap<TWeakObjectPtr<UMeshComponent>, FOriginalVisibility>& OutVisibility,
    FString& OutError) const
{
    OutComponents.Reset();
    OutVisibility.Reset();
    if (!IsValid(InAvatar) || !IsReviewedId(InProfile.ProfileId) ||
        InProfile.Slots.IsEmpty() || InProfile.Presets.IsEmpty())
    {
        OutError = TEXT("avatar or profile envelope is invalid");
        return false;
    }

    TMap<FString, UMeshComponent*> NamedComponents;
    TInlineComponentArray<UMeshComponent*> AvatarMeshes(InAvatar);
    for (UMeshComponent* Component : AvatarMeshes)
    {
        if (!IsValid(Component))
        {
            continue;
        }
        const FString StableName = StableComponentName(Component);
        if (StableName.IsEmpty() || NamedComponents.Contains(StableName))
        {
            OutError = TEXT("avatar component names are empty or ambiguous");
            return false;
        }
        NamedComponents.Add(StableName, Component);
    }

    TSet<FName> SeenSlots;
    TSet<FName> SeenComponents;
    bool bHasBodyCoverageItem = false;
    for (const FFayWardrobeSlot& Slot : InProfile.Slots)
    {
        if (!IsReviewedId(Slot.SlotId) || SeenSlots.Contains(Slot.SlotId) ||
            Slot.Items.IsEmpty())
        {
            OutError = TEXT("wardrobe slot is invalid or duplicated");
            return false;
        }
        SeenSlots.Add(Slot.SlotId);
        TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>> ResolvedItems;
        for (const FFayWardrobeItem& Item : Slot.Items)
        {
            if (!IsReviewedId(Item.ItemId) || ResolvedItems.Contains(Item.ItemId))
            {
                OutError = TEXT("wardrobe item is invalid or duplicated");
                return false;
            }
            if (Item.ItemId == TEXT("none"))
            {
                if (!Item.ComponentNames.IsEmpty() || Item.bProvidesBodyCoverage)
                {
                    OutError = TEXT("the logical none item must be empty and cannot provide coverage");
                    return false;
                }
                ResolvedItems.Add(
                    Item.ItemId,
                    TArray<TWeakObjectPtr<UMeshComponent>>());
                continue;
            }
            if (Item.ComponentNames.IsEmpty() || Item.ComponentNames.Num() > 8)
            {
                OutError = TEXT("a visible wardrobe item must contain one through eight reviewed components");
                return false;
            }
            TArray<TWeakObjectPtr<UMeshComponent>> ResolvedItemComponents;
            TSet<FName> ItemComponentNames;
            for (const FName ComponentName : Item.ComponentNames)
            {
                UMeshComponent* const* Component =
                    NamedComponents.Find(ComponentName.ToString());
                if (ComponentName.IsNone() ||
                    ItemComponentNames.Contains(ComponentName) ||
                    Component == nullptr || !IsValid(*Component) ||
                    SeenComponents.Contains(ComponentName))
                {
                    OutError = TEXT("a reviewed wardrobe component is missing, duplicated, or reused");
                    return false;
                }
                ItemComponentNames.Add(ComponentName);
                SeenComponents.Add(ComponentName);
                ResolvedItemComponents.Add(*Component);
                FOriginalVisibility Visibility;
                Visibility.bVisible = (*Component)->IsVisible();
                Visibility.bHiddenInGame = (*Component)->bHiddenInGame;
                Visibility.bTickEnabled = (*Component)->IsComponentTickEnabled();
                OutVisibility.Add(*Component, Visibility);
            }
            bHasBodyCoverageItem |= Item.bProvidesBodyCoverage;
            ResolvedItems.Add(Item.ItemId, MoveTemp(ResolvedItemComponents));
        }
        OutComponents.Add(Slot.SlotId, MoveTemp(ResolvedItems));
    }
    if (!bHasBodyCoverageItem)
    {
        OutError = TEXT("wardrobe profile has no reviewed body-coverage item");
        return false;
    }

    TSet<FName> SeenPresets;
    for (const FFayWardrobePreset& Preset : InProfile.Presets)
    {
        if (!IsReviewedId(Preset.PresetId) || SeenPresets.Contains(Preset.PresetId) ||
            Preset.SlotItems.Num() != OutComponents.Num() ||
            Preset.bFullyUnclothed !=
                SelectionIsFullyUnclothed(Preset.SlotItems, InProfile) ||
            (Preset.bFullyUnclothed && !InProfile.bAllowFullyUnclothed))
        {
            OutError = TEXT("wardrobe preset is incomplete, duplicated, or unapproved");
            return false;
        }
        SeenPresets.Add(Preset.PresetId);
        for (const TPair<FName, FName>& Selection : Preset.SlotItems)
        {
            const TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>* Items =
                OutComponents.Find(Selection.Key);
            if (Items == nullptr || !Items->Contains(Selection.Value))
            {
                OutError = TEXT("wardrobe preset selects an unknown slot or item");
                return false;
            }
        }
    }
    return true;
}

bool UFayWardrobeComponent::ApplySelection(
    const TMap<FName, FName>& Selection,
    FString& OutError)
{
    if (!bReady || !IsValid(Avatar) || Selection.Num() != ComponentsBySlot.Num())
    {
        OutError = TEXT("wardrobe is not ready or selection is incomplete");
        return false;
    }
    if (SelectionIsFullyUnclothed(Selection, ActiveProfile) &&
        !ActiveProfile.bAllowFullyUnclothed)
    {
        OutError = TEXT("selection requires independent complete-body approval");
        return false;
    }

    TArray<TPair<UMeshComponent*, bool>> VisibilityPlan;
    for (const TPair<FName, TMap<FName, TArray<TWeakObjectPtr<UMeshComponent>>>>& Slot :
        ComponentsBySlot)
    {
        const FName* SelectedItem = Selection.Find(Slot.Key);
        if (SelectedItem == nullptr || !Slot.Value.Contains(*SelectedItem))
        {
            OutError = TEXT("selection contains an unknown slot or item");
            return false;
        }
        for (const TPair<FName, TArray<TWeakObjectPtr<UMeshComponent>>>& Item : Slot.Value)
        {
            if (Item.Key == TEXT("none"))
            {
                continue;
            }
            for (const TWeakObjectPtr<UMeshComponent>& WeakComponent : Item.Value)
            {
                UMeshComponent* Component = WeakComponent.Get();
                if (!IsValid(Component))
                {
                    OutError = TEXT("a reviewed wardrobe component became unavailable");
                    return false;
                }
                VisibilityPlan.Emplace(Component, Item.Key == *SelectedItem);
            }
        }
    }

    for (const TPair<UMeshComponent*, bool>& Change : VisibilityPlan)
    {
        Change.Key->SetVisibility(Change.Value, false);
        Change.Key->SetHiddenInGame(!Change.Value, false);
        const FOriginalVisibility* Original = OriginalVisibility.Find(Change.Key);
        Change.Key->SetComponentTickEnabled(
            Change.Value && Original != nullptr && Original->bTickEnabled);
    }
    const TMap<FName, FName> PreviousSelection = ActiveSelection;
    ActiveSelection = Selection;
    for (const TPair<FName, FName>& Item : ActiveSelection)
    {
        const FName* Previous = PreviousSelection.Find(Item.Key);
        if (Previous == nullptr || *Previous != Item.Value)
        {
            OnSlotChanged.Broadcast(Item.Key, Item.Value);
        }
    }
    return true;
}

bool UFayWardrobeComponent::SelectionIsFullyUnclothed(
    const TMap<FName, FName>& Selection,
    const FFayWardrobeProfile& Profile)
{
    bool bProfileContainsCoverage = false;
    bool bSelectionProvidesCoverage = false;
    for (const FFayWardrobeSlot& Slot : Profile.Slots)
    {
        const FName* SelectedId = Selection.Find(Slot.SlotId);
        for (const FFayWardrobeItem& Item : Slot.Items)
        {
            bProfileContainsCoverage |= Item.bProvidesBodyCoverage;
            if (SelectedId != nullptr && Item.ItemId == *SelectedId &&
                Item.bProvidesBodyCoverage)
            {
                bSelectionProvidesCoverage = true;
            }
        }
    }
    return bProfileContainsCoverage && !bSelectionProvidesCoverage;
}

bool UFayWardrobeComponent::IsReviewedId(const FName Value)
{
    if (Value.IsNone())
    {
        return false;
    }
    const FString Text = Value.ToString();
    if (Text.IsEmpty() || Text.Len() > 32 || !FChar::IsLower(Text[0]) ||
        !FChar::IsAlpha(Text[0]))
    {
        return false;
    }
    for (const TCHAR Character : Text)
    {
        if ((!FChar::IsLower(Character) || !FChar::IsAlpha(Character)) &&
            !FChar::IsDigit(Character) && Character != TEXT('_') &&
            Character != TEXT('-'))
        {
            return false;
        }
    }
    return true;
}

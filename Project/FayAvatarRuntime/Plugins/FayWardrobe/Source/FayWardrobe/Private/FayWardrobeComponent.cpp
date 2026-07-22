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

void UFayWardrobeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    ResetWardrobe();
    Super::EndPlay(EndPlayReason);
}

bool UFayWardrobeComponent::ConfigureAvatar(
    AActor* InAvatar,
    const FFayWardrobeProfile& InProfile)
{
    TMap<FName, TMap<FName, TWeakObjectPtr<UMeshComponent>>> ResolvedComponents;
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
    FString Error;
    if (!ApplySelection(Selection, Error))
    {
        UE_LOG(LogFayWardrobe, Error,
            TEXT("Wardrobe slot change failed closed: %s"), *Error);
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
    TMap<FName, TMap<FName, TWeakObjectPtr<UMeshComponent>>>& OutComponents,
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
    for (const FFayWardrobeSlot& Slot : InProfile.Slots)
    {
        if (!IsReviewedId(Slot.SlotId) || SeenSlots.Contains(Slot.SlotId) ||
            Slot.Items.IsEmpty())
        {
            OutError = TEXT("wardrobe slot is invalid or duplicated");
            return false;
        }
        SeenSlots.Add(Slot.SlotId);
        TMap<FName, TWeakObjectPtr<UMeshComponent>> ResolvedItems;
        for (const FFayWardrobeItem& Item : Slot.Items)
        {
            if (!IsReviewedId(Item.ItemId) || ResolvedItems.Contains(Item.ItemId))
            {
                OutError = TEXT("wardrobe item is invalid or duplicated");
                return false;
            }
            if (Item.ItemId == TEXT("none"))
            {
                if (!Item.ComponentName.IsNone())
                {
                    OutError = TEXT("the logical none item must not name a component");
                    return false;
                }
                ResolvedItems.Add(Item.ItemId, nullptr);
                continue;
            }
            if (Item.ComponentName.IsNone())
            {
                OutError = TEXT("a visible wardrobe item has no reviewed component");
                return false;
            }
            UMeshComponent* const* Component =
                NamedComponents.Find(Item.ComponentName.ToString());
            if (Component == nullptr || !IsValid(*Component) ||
                SeenComponents.Contains(Item.ComponentName))
            {
                OutError = TEXT("a reviewed wardrobe component is missing or reused");
                return false;
            }
            SeenComponents.Add(Item.ComponentName);
            ResolvedItems.Add(Item.ItemId, *Component);
            FOriginalVisibility Visibility;
            Visibility.bVisible = (*Component)->IsVisible();
            Visibility.bHiddenInGame = (*Component)->bHiddenInGame;
            OutVisibility.Add(*Component, Visibility);
        }
        OutComponents.Add(Slot.SlotId, MoveTemp(ResolvedItems));
    }

    TSet<FName> SeenPresets;
    for (const FFayWardrobePreset& Preset : InProfile.Presets)
    {
        if (!IsReviewedId(Preset.PresetId) || SeenPresets.Contains(Preset.PresetId) ||
            Preset.SlotItems.Num() != OutComponents.Num() ||
            (Preset.bFullyUnclothed && !InProfile.bAllowFullyUnclothed))
        {
            OutError = TEXT("wardrobe preset is incomplete, duplicated, or unapproved");
            return false;
        }
        SeenPresets.Add(Preset.PresetId);
        for (const TPair<FName, FName>& Selection : Preset.SlotItems)
        {
            const TMap<FName, TWeakObjectPtr<UMeshComponent>>* Items =
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

    TArray<TPair<UMeshComponent*, bool>> VisibilityPlan;
    for (const TPair<FName, TMap<FName, TWeakObjectPtr<UMeshComponent>>>& Slot :
        ComponentsBySlot)
    {
        const FName* SelectedItem = Selection.Find(Slot.Key);
        if (SelectedItem == nullptr || !Slot.Value.Contains(*SelectedItem))
        {
            OutError = TEXT("selection contains an unknown slot or item");
            return false;
        }
        for (const TPair<FName, TWeakObjectPtr<UMeshComponent>>& Item : Slot.Value)
        {
            if (Item.Key == TEXT("none"))
            {
                continue;
            }
            UMeshComponent* Component = Item.Value.Get();
            if (!IsValid(Component))
            {
                OutError = TEXT("a reviewed wardrobe component became unavailable");
                return false;
            }
            VisibilityPlan.Emplace(Component, Item.Key == *SelectedItem);
        }
    }

    for (const TPair<UMeshComponent*, bool>& Change : VisibilityPlan)
    {
        Change.Key->SetVisibility(Change.Value, false);
        Change.Key->SetHiddenInGame(!Change.Value, false);
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

#pragma once

#include "CoreMinimal.h"

#include "FayWardrobeTypes.generated.h"

/** One reviewed logical choice backed by a component already inside the avatar. */
USTRUCT(BlueprintType)
struct FAYWARDROBE_API FFayWardrobeItem
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName ItemId = NAME_None;

    /** Empty only for the explicit logical `none` item. Never supplied by a client. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName ComponentName = NAME_None;
};

/** A mutually exclusive group such as top, bottom, feet, or hair. */
USTRUCT(BlueprintType)
struct FAYWARDROBE_API FFayWardrobeSlot
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName SlotId = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    TArray<FFayWardrobeItem> Items;
};

/** One complete, reviewed selection. Partial presets are intentionally rejected. */
USTRUCT(BlueprintType)
struct FAYWARDROBE_API FFayWardrobePreset
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName PresetId = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    TMap<FName, FName> SlotItems;

    /** Requires the profile's independent body-completeness approval. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    bool bFullyUnclothed = false;
};

/** Packaged, character-specific mapping selected by a reviewed character ID. */
USTRUCT(BlueprintType)
struct FAYWARDROBE_API FFayWardrobeProfile
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    FName ProfileId = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    TArray<FFayWardrobeSlot> Slots;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    TArray<FFayWardrobePreset> Presets;

    /** False until a manual complete-body, material, and every-LOD audit passes. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Fay|Wardrobe")
    bool bAllowFullyUnclothed = false;
};

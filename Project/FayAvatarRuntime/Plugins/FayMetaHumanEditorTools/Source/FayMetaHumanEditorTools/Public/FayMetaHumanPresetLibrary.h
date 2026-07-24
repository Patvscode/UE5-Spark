#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"

#include "FayMetaHumanPresetLibrary.generated.h"

class UMetaHumanCharacter;

/**
 * Minimal adapter for the UE 5.8 MetaHuman Character editor API that is not
 * otherwise reflected to Blueprint or Python.
 */
UCLASS()
class FAYMETAHUMANEDITORTOOLS_API UFayMetaHumanPresetLibrary final : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * Initializes a fresh, registered MetaHuman Character from a preset.
     *
     * The target must have been created with UMetaHumanCharacterFactoryNew and
     * registered through UMetaHumanCharacterEditorSubsystem::TryAddObjectToEdit.
     * The function deliberately refuses already-rigged or high-resolution
     * targets so automation cannot silently replace an existing character.
     */
    UFUNCTION(BlueprintCallable, Category = "Fay|MetaHuman")
    static bool InitializeFromPreset(
        UMetaHumanCharacter* TargetCharacter,
        UMetaHumanCharacter* PresetCharacter);

    /** Returns true when the character contains face DNA of any rig type. */
    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    static bool HasFaceDNA(UMetaHumanCharacter* Character);

    /** Returns true only when the character contains face-DNA blend shapes. */
    UFUNCTION(BlueprintPure, Category = "Fay|MetaHuman")
    static bool HasFaceDNABlendShapes(UMetaHumanCharacter* Character);
};

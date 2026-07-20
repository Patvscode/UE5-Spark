#include "FayMetaHumanPresetLibrary.h"

#include "MetaHumanCharacter.h"
#include "MetaHumanCharacterEditorSubsystem.h"

DEFINE_LOG_CATEGORY_STATIC(LogFayMetaHumanEditorTools, Log, All);

bool UFayMetaHumanPresetLibrary::InitializeFromPreset(
    UMetaHumanCharacter* TargetCharacter,
    UMetaHumanCharacter* PresetCharacter)
{
    if (!IsValid(TargetCharacter) || !IsValid(PresetCharacter))
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("InitializeFromPreset requires valid target and preset characters."));
        return false;
    }

    if (TargetCharacter == PresetCharacter)
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("InitializeFromPreset refuses to use the target as its own preset."));
        return false;
    }

    if (!TargetCharacter->IsCharacterValid() || !PresetCharacter->IsCharacterValid())
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("InitializeFromPreset requires initialized MetaHuman Character assets."));
        return false;
    }

    if (TargetCharacter->HasFaceDNA() || TargetCharacter->HasHighResolutionTextures())
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("InitializeFromPreset refuses a target that already has rig or high-resolution texture data."));
        return false;
    }

    UMetaHumanCharacterEditorSubsystem* Subsystem = UMetaHumanCharacterEditorSubsystem::Get();
    if (!IsValid(Subsystem))
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("The MetaHuman Character editor subsystem is unavailable."));
        return false;
    }

    if (!Subsystem->IsObjectAddedForEditing(TargetCharacter))
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("The target must be registered with TryAddObjectToEdit before applying a preset."));
        return false;
    }

    Subsystem->InitializeFromPreset(TargetCharacter, PresetCharacter);

    const bool bMatchesPreset =
        TargetCharacter->FaceEvaluationSettings.GlobalDelta ==
            PresetCharacter->FaceEvaluationSettings.GlobalDelta &&
        TargetCharacter->FaceEvaluationSettings.HighFrequencyDelta ==
            PresetCharacter->FaceEvaluationSettings.HighFrequencyDelta &&
        TargetCharacter->FaceEvaluationSettings.HeadScale ==
            PresetCharacter->FaceEvaluationSettings.HeadScale &&
        TargetCharacter->SkinSettings.Skin.FaceTextureIndex ==
            PresetCharacter->SkinSettings.Skin.FaceTextureIndex &&
        TargetCharacter->HighResBodyTexturesInfo.Num() ==
            PresetCharacter->HighResBodyTexturesInfo.Num() &&
        TargetCharacter->PreviewMaterialType == PresetCharacter->PreviewMaterialType;

    if (!bMatchesPreset)
    {
        UE_LOG(
            LogFayMetaHumanEditorTools,
            Error,
            TEXT("InitializeFromPreset returned without copying Ada's key preset state."));
        return false;
    }

    return true;
}

bool UFayMetaHumanPresetLibrary::HasFaceDNA(UMetaHumanCharacter* Character)
{
    return IsValid(Character) && Character->HasFaceDNA();
}

bool UFayMetaHumanPresetLibrary::HasFaceDNABlendShapes(
    UMetaHumanCharacter* Character)
{
    return IsValid(Character) && Character->HasFaceDNABlendshapes();
}

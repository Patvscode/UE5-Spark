from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "Project/FayAvatarRuntime/Plugins/FayWardrobe"
SOURCE = (
    PLUGIN_ROOT / "Source/FayWardrobe/Private/FayWardrobeComponent.cpp"
).read_text(encoding="utf-8")
HEADER = (
    PLUGIN_ROOT / "Source/FayWardrobe/Public/FayWardrobeComponent.h"
).read_text(encoding="utf-8")
TYPES = (
    PLUGIN_ROOT / "Source/FayWardrobe/Public/FayWardrobeTypes.h"
).read_text(encoding="utf-8")


class WardrobeUnrealContractTests(unittest.TestCase):
    def test_plugin_is_runtime_and_contentless(self) -> None:
        plugin = json.loads((PLUGIN_ROOT / "FayWardrobe.uplugin").read_text())
        self.assertIs(plugin["CanContainContent"], False)
        self.assertEqual(plugin["Modules"], [{
            "Name": "FayWardrobe",
            "Type": "Runtime",
            "LoadingPhase": "Default",
        }])

    def test_client_surface_uses_ids_not_paths_or_components(self) -> None:
        for marker in (
            "bool ApplyPreset(FName PresetId);",
            "bool SetSlotItem(FName SlotId, FName ItemId);",
            "bool bAllowFullyUnclothed = false;",
            "A complete preset must be applied before individual wardrobe changes.",
        ):
            self.assertIn(marker, HEADER + TYPES + SOURCE)
        for forbidden in (
            "LoadObject<",
            "StaticLoadObject",
            "FSoftObjectPath",
            "FPackageName",
            "SetSkeletalMesh",
        ):
            self.assertNotIn(forbidden, SOURCE)

    def test_configuration_is_transactional_and_reset_restores_visibility(self) -> None:
        configure = SOURCE[
            SOURCE.index("bool UFayWardrobeComponent::ConfigureAvatar") :
            SOURCE.index("bool UFayWardrobeComponent::ApplyPreset")
        ]
        self.assertLess(configure.index("ValidateAndResolveProfile("), configure.index("ResetWardrobe();"))
        for marker in (
            "ResolvedComponents",
            "ResolvedVisibility",
            "OriginalVisibility",
            "Component->SetVisibility(Entry.Value.bVisible, false);",
            "Component->SetHiddenInGame(Entry.Value.bHiddenInGame, false);",
            "without changing the avatar",
        ):
            self.assertIn(marker, SOURCE)

    def test_fully_unclothed_requires_independent_profile_approval(self) -> None:
        self.assertIn(
            "Preset->bFullyUnclothed && !ActiveProfile.bAllowFullyUnclothed",
            SOURCE,
        )
        self.assertIn(
            "Preset.bFullyUnclothed && !InProfile.bAllowFullyUnclothed",
            SOURCE,
        )

    def test_game_runtime_owns_the_content_free_adapter(self) -> None:
        game_header = (
            REPO_ROOT
            / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
            "FayAvatarBootstrapGameMode.h"
        ).read_text(encoding="utf-8")
        game_source = (
            REPO_ROOT
            / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
            "FayAvatarBootstrapGameMode.cpp"
        ).read_text(encoding="utf-8")
        game_build = (
            REPO_ROOT
            / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/"
            "FayAvatarRuntime.Build.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("TObjectPtr<UFayWardrobeComponent> Wardrobe;", game_header)
        self.assertIn(
            'CreateDefaultSubobject<UFayWardrobeComponent>(TEXT("FayWardrobe"))',
            game_source,
        )
        self.assertIn('"FayWardrobe"', game_build)


if __name__ == "__main__":
    unittest.main()

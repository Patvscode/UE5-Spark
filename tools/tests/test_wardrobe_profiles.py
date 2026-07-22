from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wardrobe-profiles.py"
PROFILE = REPO_ROOT / "config/wardrobe-profiles/CasualGirl.pending.json"
SPEC = importlib.util.spec_from_file_location("wardrobe_profiles", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WARDROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WARDROBE)


class WardrobeProfileTests(unittest.TestCase):
    def test_pending_casual_girl_profile_is_sealed_and_not_nude(self) -> None:
        profile = WARDROBE.load_profile(PROFILE)
        self.assertEqual(profile["id"], "casual-girl")
        self.assertEqual(profile["status"], "pending_asset_audit")
        self.assertFalse(profile["allowFullyUnclothed"])
        self.assertEqual(
            tuple(profile["slots"]),
            ("top", "bottom", "feet", "hair"),
        )
        self.assertEqual(set(profile["presets"]), {"underwear", "casual", "hoodie"})

    def test_unknown_fields_and_arbitrary_paths_fail_closed(self) -> None:
        original = json.loads(PROFILE.read_text(encoding="utf-8"))
        variants = []
        extra = deepcopy(original)
        extra["assetPath"] = "/Game/Anything"
        variants.append(extra)
        escaped = deepcopy(original)
        escaped["reviewedAssetRoot"] = "/Game/Other/CasualGirl"
        variants.append(escaped)
        arbitrary_item = deepcopy(original)
        arbitrary_item["slots"]["top"].append("../../OtherAsset")
        variants.append(arbitrary_item)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(
                WARDROBE.WardrobeProfileError
            ):
                WARDROBE.validate_profile(value)

    def test_pending_profile_cannot_enable_fully_unclothed(self) -> None:
        value = json.loads(PROFILE.read_text(encoding="utf-8"))
        value["allowFullyUnclothed"] = True
        with self.assertRaisesRegex(
            WARDROBE.WardrobeProfileError,
            "pending profile cannot expose",
        ):
            WARDROBE.validate_profile(value)

    def test_every_preset_selects_reviewed_items(self) -> None:
        value = json.loads(PROFILE.read_text(encoding="utf-8"))
        value["presets"]["casual"]["top"] = "downloaded_asset_path"
        with self.assertRaisesRegex(
            WARDROBE.WardrobeProfileError,
            "unknown top choice",
        ):
            WARDROBE.validate_profile(value)

    def test_symlink_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "profile.json"
            target.write_text(PROFILE.read_text(encoding="utf-8"), encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target.name)
            with self.assertRaises(WARDROBE.WardrobeProfileError):
                WARDROBE.load_profile(link)

    def test_editor_audit_is_read_only_and_scoped(self) -> None:
        source = (REPO_ROOT / "scripts/audit-fab-casual-girl.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('REVIEWED_ROOT = "/Game/FayFab/CasualGirl"', source)
        self.assertIn('emit("BODY_COMPLETENESS", "manual_review_required")', source)
        self.assertIn('emit("UNDERWEAR_IMPLEMENTATION", "manual_review_required")', source)
        for forbidden in ("save_asset(", "save_loaded_asset(", "delete_asset(", "rename_asset("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Validate sealed, asset-path-free wardrobe profiles.

Fab assets remain private and are never represented here by downloadable files
or arbitrary Unreal object paths.  A pending profile describes only reviewed
logical choices.  It cannot be promoted to a runtime-ready profile until the
locally acquired asset has passed the Editor audit documented in
``docs/fab-casual-girl.md``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SCHEMA = 1
PROFILE_KEYS = {
    "schema",
    "status",
    "id",
    "sourceListing",
    "adapter",
    "reviewedAssetRoot",
    "allowFullyUnclothed",
    "slots",
    "presets",
}
STATUS_VALUES = {"pending_asset_audit", "installed"}
ADAPTER_VALUES = {"UE5EpicArkit"}
SLOT_IDS = ("top", "bottom", "feet", "hair")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
ITEM_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
LISTING_PATTERN = re.compile(
    r"^https://www\.fab\.com/listings/[0-9a-f]{8}-[0-9a-f-]{27}$"
)
ASSET_ROOT_PATTERN = re.compile(r"^/Game/FayFab/[A-Za-z][A-Za-z0-9_-]{0,31}$")


class WardrobeProfileError(RuntimeError):
    """A wardrobe profile violated its sealed public contract."""


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WardrobeProfileError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise WardrobeProfileError(f"{label} contains a non-string key")
    return value


def _identifier(value: object, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise WardrobeProfileError(f"{label} is not a reviewed identifier")
    return value


def validate_profile(value: object) -> dict[str, object]:
    """Return the validated profile without accepting unknown fields."""

    profile = _object(value, "profile")
    if set(profile) != PROFILE_KEYS:
        raise WardrobeProfileError("profile fields do not match schema 1")
    if type(profile["schema"]) is not int or profile["schema"] != SCHEMA:
        raise WardrobeProfileError("profile schema is unsupported")

    status = profile["status"]
    if status not in STATUS_VALUES:
        raise WardrobeProfileError("profile status is unsupported")
    profile_id = _identifier(profile["id"], "profile id", ID_PATTERN)
    listing = profile["sourceListing"]
    if not isinstance(listing, str) or not LISTING_PATTERN.fullmatch(listing):
        raise WardrobeProfileError("sourceListing must be one canonical Fab listing")
    if profile["adapter"] not in ADAPTER_VALUES:
        raise WardrobeProfileError("profile adapter is unsupported")
    asset_root = profile["reviewedAssetRoot"]
    if not isinstance(asset_root, str) or not ASSET_ROOT_PATTERN.fullmatch(asset_root):
        raise WardrobeProfileError("reviewedAssetRoot is outside /Game/FayFab")
    if type(profile["allowFullyUnclothed"]) is not bool:
        raise WardrobeProfileError("allowFullyUnclothed must be boolean")
    if status == "pending_asset_audit" and profile["allowFullyUnclothed"]:
        raise WardrobeProfileError(
            "a pending profile cannot expose a fully unclothed state"
        )

    slots = _object(profile["slots"], "slots")
    if tuple(slots) != SLOT_IDS:
        raise WardrobeProfileError("slots must use the reviewed order and exact names")
    reviewed_items: dict[str, set[str]] = {}
    for slot_id in SLOT_IDS:
        choices = slots[slot_id]
        if not isinstance(choices, list) or not choices:
            raise WardrobeProfileError(f"slot {slot_id} must contain choices")
        if not all(
            isinstance(choice, str) and ITEM_PATTERN.fullmatch(choice)
            for choice in choices
        ):
            raise WardrobeProfileError(f"slot {slot_id} has an invalid choice")
        if len(choices) != len(set(choices)):
            raise WardrobeProfileError(f"slot {slot_id} has a duplicate choice")
        reviewed_items[slot_id] = set(choices)

    presets = _object(profile["presets"], "presets")
    if not presets:
        raise WardrobeProfileError("presets must not be empty")
    for preset_id, raw_preset in presets.items():
        _identifier(preset_id, "preset id", ITEM_PATTERN)
        preset = _object(raw_preset, f"preset {preset_id}")
        if tuple(preset) != SLOT_IDS:
            raise WardrobeProfileError(
                f"preset {preset_id} must select every reviewed slot"
            )
        for slot_id in SLOT_IDS:
            if preset[slot_id] not in reviewed_items[slot_id]:
                raise WardrobeProfileError(
                    f"preset {preset_id} selects an unknown {slot_id} choice"
                )

    return profile


def load_profile(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise WardrobeProfileError("profile must be a regular non-symlink file")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise WardrobeProfileError("profile must be a regular non-symlink file")
    if resolved.stat().st_size > 64 * 1024:
        raise WardrobeProfileError("profile is unexpectedly large")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WardrobeProfileError("profile is not valid UTF-8 JSON") from error
    return validate_profile(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("command", choices=("validate", "json"))
    args = parser.parse_args()
    profile = load_profile(args.profile)
    if args.command == "validate":
        print(
            f"validated wardrobe profile {profile['id']} "
            f"(status={profile['status']}, presets={len(profile['presets'])})"
        )
    else:
        print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

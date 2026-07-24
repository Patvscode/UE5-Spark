"""Strict loader for the shared, reviewed UE5-Spark motion catalog."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re


CATALOG_SCHEMA_VERSION = 1
CATALOG_ID = "ue5-spark-reviewed-motion-v1"
MAX_CATALOG_BYTES = 64 * 1024
_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ITEM_FIELDS = {
    "label",
    "aliases",
    "prompt",
    "duration",
    "intensity",
    "rootMode",
    "routeBehavior",
    "rendererPackaged",
}


class MotionCatalogError(RuntimeError):
    """The committed motion catalog violated its sealed source contract."""


def _catalog_path() -> Path:
    packaged = Path(__file__).resolve().parent / "motion-catalog.json"
    if packaged.is_file():
        return packaged
    repository = Path(__file__).resolve().parents[3] / "config" / "motion-catalog.json"
    return repository


def load_motion_catalog(path: Path | None = None) -> dict[str, dict[str, object]]:
    """Load and strictly validate the reviewed catalog without accepting overrides."""

    selected = _catalog_path() if path is None else path
    if not selected.is_file() or selected.is_symlink():
        raise MotionCatalogError("reviewed motion catalog is missing or is a symlink")
    if selected.stat().st_size > MAX_CATALOG_BYTES:
        raise MotionCatalogError("reviewed motion catalog is too large")
    try:
        document = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MotionCatalogError("reviewed motion catalog is invalid JSON") from error
    if not isinstance(document, dict) or set(document) != {
        "schemaVersion",
        "catalogId",
        "items",
    }:
        raise MotionCatalogError("reviewed motion catalog has an invalid envelope")
    if (
        document["schemaVersion"] != CATALOG_SCHEMA_VERSION
        or type(document["schemaVersion"]) is not int
        or document["catalogId"] != CATALOG_ID
    ):
        raise MotionCatalogError("reviewed motion catalog identity is unsupported")
    items = document["items"]
    if not isinstance(items, dict) or not items:
        raise MotionCatalogError("reviewed motion catalog has no items")

    result: dict[str, dict[str, object]] = {}
    for behavior, item in items.items():
        if not isinstance(behavior, str) or not _ID_PATTERN.fullmatch(behavior):
            raise MotionCatalogError("motion catalog contains an invalid behavior ID")
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise MotionCatalogError(f"motion catalog item {behavior} has an invalid envelope")
        _validate_item(behavior, item)
        result[behavior] = dict(item)
    return result


def _validate_item(behavior: str, item: dict[str, object]) -> None:
    label = item["label"]
    aliases = item["aliases"]
    prompt = item["prompt"]
    if not isinstance(label, str) or not 1 <= len(label) <= 64 or label.strip() != label:
        raise MotionCatalogError(f"motion catalog item {behavior} has an invalid label")
    if (
        not isinstance(aliases, list)
        or not aliases
        or len(aliases) > 16
        or any(
            not isinstance(alias, str)
            or not 1 <= len(alias) <= 80
            or alias.strip() != alias
            for alias in aliases
        )
        or len(set(aliases)) != len(aliases)
    ):
        raise MotionCatalogError(f"motion catalog item {behavior} has invalid aliases")
    if (
        not isinstance(prompt, str)
        or not 1 <= len(prompt) <= 512
        or prompt.strip() != prompt
        or "\n" in prompt
    ):
        raise MotionCatalogError(f"motion catalog item {behavior} has an invalid prompt")
    duration = item["duration"]
    intensity = item["intensity"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or not 0.2 <= float(duration) <= 10.0
    ):
        raise MotionCatalogError(f"motion catalog item {behavior} has invalid duration")
    if (
        isinstance(intensity, bool)
        or not isinstance(intensity, (int, float))
        or not math.isfinite(float(intensity))
        or not 0.0 <= float(intensity) <= 1.0
    ):
        raise MotionCatalogError(f"motion catalog item {behavior} has invalid intensity")
    if item["rootMode"] != "locked":
        raise MotionCatalogError(f"motion catalog item {behavior} has unsupported root mode")
    if item["routeBehavior"] != behavior:
        raise MotionCatalogError(f"motion catalog item {behavior} has invalid route behavior")
    if type(item["rendererPackaged"]) is not bool:
        raise MotionCatalogError(f"motion catalog item {behavior} has invalid package status")


MOTION_CATALOG = load_motion_catalog()
GENERATED_BEHAVIORS = tuple(MOTION_CATALOG)
REVIEWED_PROMPTS = {
    behavior: str(item["prompt"]) for behavior, item in MOTION_CATALOG.items()
}

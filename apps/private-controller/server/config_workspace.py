#!/usr/bin/env python3
"""Safe, persistent configuration workspace for the private controller.

The controller release tree is immutable on the Spark.  This module therefore
copies a small, explicit set of text configuration templates into a separate
workspace selected by the controller launcher.  Every operation addresses a
logical file ID; callers never provide a filesystem path.

This module intentionally does not edit or inspect Unreal ``.uasset`` files.
Changing a character or wardrobe JSON document describes a future package but
cannot add an uncooked mesh, material, animation, or garment to the running
application.
"""

from __future__ import annotations

import configparser
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Callable


WORKSPACE_SCHEMA = 1
MAX_JSON_BYTES = 64 * 1024
MAX_INI_BYTES = 128 * 1024
MAX_WARDROBE_FILES = 64
WARDROBE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}\.json$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MOTION_IDS = frozenset({
    "idle",
    "listen",
    "explain",
    "wave",
    "jog_in_place",
    "run_in_place",
    "jumping_jacks",
    "stretch",
    "dance_relaxed",
})
MOTION_FIELDS = frozenset({
    "label",
    "aliases",
    "prompt",
    "duration",
    "intensity",
    "rootMode",
    "routeBehavior",
    "rendererPackaged",
})
AI_MODES = ("deterministic", "ai_motion", "asset_aware_ai")
AI_MODE_FIELDS = frozenset({
    "id",
    "label",
    "description",
    "usesGenerativeMotion",
    "acceptsCharacterAssetContext",
    "requiresExplicitLocalOptIn",
})
AI_MODE_SEMANTICS = {
    "deterministic": (False, False, False),
    "ai_motion": (True, False, False),
    "asset_aware_ai": (True, True, True),
}


class ConfigWorkspaceError(RuntimeError):
    """Base error returned to the controller's narrow HTTP adapter."""


class ConfigWorkspaceSecurityError(ConfigWorkspaceError):
    """A path, symlink, or file-type boundary was violated."""


class ConfigWorkspaceConflict(ConfigWorkspaceError):
    """The caller edited an out-of-date revision."""


class ConfigWorkspaceValidationError(ConfigWorkspaceError):
    """The proposed text does not satisfy its configuration contract."""


class ConfigWorkspaceNotFound(ConfigWorkspaceError):
    """A logical file ID is unknown."""


@dataclass(frozen=True)
class BuiltinFile:
    name: str
    directory_id: str
    source_relative_path: str
    workspace_relative_path: str
    kind: str
    apply_mode: str
    apply_target: str
    validator: str


@dataclass(frozen=True)
class ManagedFile:
    id: str
    name: str
    directory_id: str
    path: Path
    kind: str
    apply_mode: str
    apply_target: str
    built_in: bool


BUILTINS = (
    BuiltinFile(
        name="motion-catalog.json",
        directory_id="controller-config",
        source_relative_path="config/motion-catalog.json",
        workspace_relative_path="controller/motion-catalog.json",
        kind="json",
        apply_mode="live",
        apply_target="private controller",
        validator="motion_catalog",
    ),
    BuiltinFile(
        name="character-ai-control.json",
        directory_id="controller-config",
        source_relative_path="config/character-ai-control.json",
        workspace_relative_path="controller/character-ai-control.json",
        kind="json",
        apply_mode="live",
        apply_target="private controller",
        validator="ai_control",
    ),
    BuiltinFile(
        name="DefaultGame.ini",
        directory_id="unreal-config",
        source_relative_path="Project/FayAvatarRuntime/Config/DefaultGame.ini",
        workspace_relative_path="unreal/DefaultGame.ini",
        kind="ini",
        apply_mode="rebuild",
        apply_target="Unreal Linux ARM64 package",
        validator="character_profiles",
    ),
)


def _strict_json(text: str, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ConfigWorkspaceValidationError(
                    f"{label} contains duplicate key {key!r}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise ConfigWorkspaceValidationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ConfigWorkspaceValidationError(f"{label} must contain one JSON object")
    return value


def _validate_motion_catalog(text: str) -> dict[str, object]:
    value = _strict_json(text, "motion catalog")
    if (
        set(value) != {"schemaVersion", "catalogId", "items"}
        or value.get("schemaVersion") != 1
        or value.get("catalogId") != "ue5-spark-reviewed-motion-v1"
        or not isinstance(value.get("items"), dict)
        or set(value["items"]) != MOTION_IDS
    ):
        raise ConfigWorkspaceValidationError(
            "motion catalog must keep the schema-1 packaged fallback set"
        )
    for motion_id, item in value["items"].items():
        if not isinstance(item, dict) or set(item) != MOTION_FIELDS:
            raise ConfigWorkspaceValidationError(
                f"motion {motion_id!r} has unsupported fields"
            )
        aliases = item["aliases"]
        if (
            not isinstance(item["label"], str)
            or not 1 <= len(item["label"]) <= 48
            or not isinstance(aliases, list)
            or not 1 <= len(aliases) <= 8
            or any(
                not isinstance(alias, str) or not 1 <= len(alias) <= 64
                for alias in aliases
            )
            or len(aliases) != len(set(aliases))
            or not isinstance(item["prompt"], str)
            or not 1 <= len(item["prompt"]) <= 300
            or type(item["duration"]) not in (int, float)
            or not 0.2 <= float(item["duration"]) <= 10.0
            or type(item["intensity"]) not in (int, float)
            or not 0.0 <= float(item["intensity"]) <= 1.0
            or item["rootMode"] != "locked"
            or item["routeBehavior"] != motion_id
            or type(item["rendererPackaged"]) is not bool
        ):
            raise ConfigWorkspaceValidationError(
                f"motion {motion_id!r} violates the packaged fallback contract"
            )
    return value


def _validate_ai_control(text: str) -> dict[str, object]:
    value = _strict_json(text, "character AI-control config")
    if (
        set(value)
        != {
            "$schema",
            "schemaVersion",
            "controlConfigId",
            "defaultMode",
            "assetAwareNotice",
            "modes",
        }
        or value.get("$schema") != "./character-ai-control.schema.json"
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("controlConfigId") != "ue5-spark-local-ai-control-v1"
        or value.get("defaultMode") != "ai_motion"
        or not isinstance(value.get("assetAwareNotice"), str)
        or not 1 <= len(value["assetAwareNotice"]) <= 240
        or not isinstance(value.get("modes"), list)
        or len(value["modes"]) != len(AI_MODES)
    ):
        raise ConfigWorkspaceValidationError(
            "character AI-control config violates schema 1"
        )
    for expected_id, mode in zip(AI_MODES, value["modes"]):
        semantics = (
            mode.get("usesGenerativeMotion") if isinstance(mode, dict) else None,
            mode.get("acceptsCharacterAssetContext") if isinstance(mode, dict) else None,
            mode.get("requiresExplicitLocalOptIn") if isinstance(mode, dict) else None,
        )
        if (
            not isinstance(mode, dict)
            or set(mode) != AI_MODE_FIELDS
            or mode.get("id") != expected_id
            or not isinstance(mode.get("label"), str)
            or not 1 <= len(mode["label"]) <= 32
            or not isinstance(mode.get("description"), str)
            or not 1 <= len(mode["description"]) <= 180
            or any(type(item) is not bool for item in semantics)
            or semantics != AI_MODE_SEMANTICS[expected_id]
        ):
            raise ConfigWorkspaceValidationError(
                f"AI-control mode {expected_id!r} violates schema 1"
            )
    return value


def _load_module(name: str, path: Path) -> ModuleType:
    if path.is_symlink() or not path.is_file():
        raise ConfigWorkspaceSecurityError(f"validator {path.name} is unavailable")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ConfigWorkspaceError(f"could not load validator {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


class ConfigWorkspace:
    """Persistent, text-only workspace rooted at an explicit private path."""

    def __init__(
        self,
        template_root: Path,
        workspace_root: Path,
        *,
        project_root: Path | None = None,
    ):
        self.template_root = self._existing_directory(template_root, "template root")
        self.project_root = self._existing_directory(
            project_root or template_root, "project root"
        )
        self.workspace_root = self._prepare_workspace_root(workspace_root)
        self.backup_root = self.workspace_root / "backups"
        self._lock = threading.RLock()
        self._wardrobe_validator = _load_module(
            "ue5_spark_wardrobe_profiles",
            self.template_root / "scripts" / "wardrobe-profiles.py",
        )
        self._character_validator = _load_module(
            "ue5_spark_character_profiles",
            self.template_root / "scripts" / "character-profiles.py",
        )
        self._validators: dict[str, Callable[[str], object]] = {
            "motion_catalog": _validate_motion_catalog,
            "ai_control": _validate_ai_control,
            "character_profiles": self._validate_character_profiles,
            "wardrobe_profile": self._validate_wardrobe_profile,
        }
        self._baseline_wardrobe_names = self._source_wardrobe_names()
        self._initialize()

    @staticmethod
    def _existing_directory(path: Path, label: str) -> Path:
        lexical = Path(os.path.abspath(path))
        if lexical.is_symlink():
            raise ConfigWorkspaceSecurityError(f"{label} must not be a symlink")
        try:
            resolved = lexical.resolve(strict=True)
        except OSError as exc:
            raise ConfigWorkspaceError(f"{label} is unavailable") from exc
        if not resolved.is_dir():
            raise ConfigWorkspaceError(f"{label} must be a directory")
        return resolved

    @staticmethod
    def _prepare_workspace_root(path: Path) -> Path:
        lexical = Path(os.path.abspath(path))
        if lexical.is_symlink():
            raise ConfigWorkspaceSecurityError("workspace root must not be a symlink")
        try:
            lexical.mkdir(mode=0o700, parents=True, exist_ok=True)
            lexical.chmod(0o700)
            resolved = lexical.resolve(strict=True)
        except OSError as exc:
            raise ConfigWorkspaceError("workspace root could not be prepared") from exc
        if not resolved.is_dir() or resolved.is_symlink():
            raise ConfigWorkspaceSecurityError(
                "workspace root must be a regular directory"
            )
        return resolved

    def _source_wardrobe_names(self) -> frozenset[str]:
        directory = self.template_root / "config" / "wardrobe-profiles"
        self._require_directory(directory, self.template_root)
        names: set[str] = set()
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                raise ConfigWorkspaceSecurityError(
                    "template wardrobe directory contains a symlink"
                )
            if entry.is_file() and entry.suffix == ".json":
                if not WARDROBE_NAME_PATTERN.fullmatch(entry.name):
                    raise ConfigWorkspaceSecurityError(
                        "template wardrobe filename is unsupported"
                    )
                names.add(entry.name)
        if not names:
            raise ConfigWorkspaceError("no baseline wardrobe profiles are available")
        return frozenset(names)

    def _initialize(self) -> None:
        for relative in ("controller", "unreal", "wardrobe", "backups", ".validation"):
            directory = self.workspace_root / relative
            self._require_inside(directory, self.workspace_root)
            if directory.exists() and directory.is_symlink():
                raise ConfigWorkspaceSecurityError(
                    f"workspace directory {relative!r} must not be a symlink"
                )
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)

        for builtin in BUILTINS:
            self._seed_file(
                self.template_root / builtin.source_relative_path,
                self.workspace_root / builtin.workspace_relative_path,
                builtin.validator,
                MAX_JSON_BYTES if builtin.kind == "json" else MAX_INI_BYTES,
            )
        for name in self._baseline_wardrobe_names:
            self._seed_file(
                self.template_root / "config" / "wardrobe-profiles" / name,
                self.workspace_root / "wardrobe" / name,
                "wardrobe_profile",
                MAX_JSON_BYTES,
            )

    def _seed_file(
        self,
        source: Path,
        destination: Path,
        validator: str,
        max_bytes: int,
    ) -> None:
        self._require_regular_file(source, self.template_root, max_bytes)
        if destination.exists() or destination.is_symlink():
            self._require_regular_file(destination, self.workspace_root, max_bytes)
            return
        text = source.read_text(encoding="utf-8")
        self._validators[validator](text)
        self._atomic_create(destination, text.encode("utf-8"))

    @staticmethod
    def _require_inside(path: Path, root: Path) -> Path:
        lexical = Path(os.path.abspath(path))
        if not lexical.is_relative_to(root):
            raise ConfigWorkspaceSecurityError("managed path escaped its workspace")
        current = root
        for part in lexical.relative_to(root).parts:
            current /= part
            if current.exists() and current.is_symlink():
                raise ConfigWorkspaceSecurityError(
                    "managed path contains a symlink"
                )
        return lexical

    def _require_directory(self, path: Path, root: Path) -> Path:
        lexical = self._require_inside(path, root)
        try:
            metadata = lexical.lstat()
        except OSError as exc:
            raise ConfigWorkspaceError(f"directory {lexical.name!r} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ConfigWorkspaceSecurityError(
                f"{lexical.name!r} must be a non-symlink directory"
            )
        return lexical

    def _require_regular_file(
        self, path: Path, root: Path, max_bytes: int
    ) -> tuple[Path, os.stat_result]:
        lexical = self._require_inside(path, root)
        try:
            metadata = lexical.lstat()
        except OSError as exc:
            raise ConfigWorkspaceNotFound(f"file {lexical.name!r} is unavailable") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or not 1 <= metadata.st_size <= max_bytes
        ):
            raise ConfigWorkspaceSecurityError(
                f"{lexical.name!r} must be one bounded regular file"
            )
        return lexical, metadata

    def _validate_character_profiles(self, text: str) -> object:
        encoded = self._bounded_text(text, MAX_INI_BYTES, "character profiles")
        validation_root = self.workspace_root / ".validation"
        self._require_directory(validation_root, self.workspace_root)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="DefaultGame.", suffix=".ini", dir=validation_root
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                return self._character_validator.load_profiles(Path(temporary_name))
            except (OSError, configparser.Error, RuntimeError) as exc:
                raise ConfigWorkspaceValidationError(
                    f"character profiles are invalid: {exc}"
                ) from exc
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def _validate_wardrobe_profile(self, text: str) -> object:
        value = _strict_json(text, "wardrobe profile")
        try:
            return self._wardrobe_validator.validate_profile(value)
        except RuntimeError as exc:
            raise ConfigWorkspaceValidationError(
                f"wardrobe profile is invalid: {exc}"
            ) from exc

    @staticmethod
    def _bounded_text(text: object, max_bytes: int, label: str) -> bytes:
        if not isinstance(text, str) or "\x00" in text:
            raise ConfigWorkspaceValidationError(
                f"{label} must be plain UTF-8 text"
            )
        try:
            encoded = text.encode("utf-8")
        except UnicodeError as exc:
            raise ConfigWorkspaceValidationError(
                f"{label} must be valid UTF-8"
            ) from exc
        if not 1 <= len(encoded) <= max_bytes:
            raise ConfigWorkspaceValidationError(
                f"{label} must be between 1 and {max_bytes} UTF-8 bytes"
            )
        return encoded

    @staticmethod
    def _opaque_id(directory_id: str, name: str) -> str:
        digest = hashlib.sha256(
            f"ue5-spark-config-v1\0{directory_id}\0{name}".encode("utf-8")
        ).hexdigest()
        return f"cfg_{digest[:24]}"

    def _managed_files(self) -> dict[str, ManagedFile]:
        files: dict[str, ManagedFile] = {}
        for builtin in BUILTINS:
            file_id = self._opaque_id(builtin.directory_id, builtin.name)
            files[file_id] = ManagedFile(
                id=file_id,
                name=builtin.name,
                directory_id=builtin.directory_id,
                path=self.workspace_root / builtin.workspace_relative_path,
                kind=builtin.kind,
                apply_mode=builtin.apply_mode,
                apply_target=builtin.apply_target,
                built_in=True,
            )

        wardrobe_root = self.workspace_root / "wardrobe"
        self._require_directory(wardrobe_root, self.workspace_root)
        wardrobe_entries = sorted(wardrobe_root.iterdir(), key=lambda item: item.name)
        if len(wardrobe_entries) > MAX_WARDROBE_FILES:
            raise ConfigWorkspaceSecurityError("too many wardrobe profile files")
        for entry in wardrobe_entries:
            if entry.is_symlink():
                raise ConfigWorkspaceSecurityError(
                    "wardrobe workspace contains a symlink"
                )
            if not entry.is_file() or not WARDROBE_NAME_PATTERN.fullmatch(entry.name):
                raise ConfigWorkspaceSecurityError(
                    "wardrobe workspace contains an unsupported entry"
                )
            file_id = self._opaque_id("wardrobe-profiles", entry.name)
            files[file_id] = ManagedFile(
                id=file_id,
                name=entry.name,
                directory_id="wardrobe-profiles",
                path=entry,
                kind="json",
                apply_mode="rebuild",
                apply_target="Unreal Linux ARM64 package",
                built_in=entry.name in self._baseline_wardrobe_names,
            )
        return files

    def _validator_for(self, managed: ManagedFile) -> Callable[[str], object]:
        if managed.directory_id == "wardrobe-profiles":
            return self._validators["wardrobe_profile"]
        for builtin in BUILTINS:
            if builtin.directory_id == managed.directory_id and builtin.name == managed.name:
                return self._validators[builtin.validator]
        raise ConfigWorkspaceNotFound("file validator is unavailable")

    def _read(self, managed: ManagedFile) -> tuple[bytes, os.stat_result]:
        maximum = MAX_JSON_BYTES if managed.kind == "json" else MAX_INI_BYTES
        path, metadata = self._require_regular_file(
            managed.path, self.workspace_root, maximum
        )
        try:
            data = path.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ConfigWorkspaceSecurityError(
                f"{managed.name!r} is not readable UTF-8 text"
            ) from exc
        return data, metadata

    def _validation(self, managed: ManagedFile, text: str) -> dict[str, object]:
        try:
            self._validator_for(managed)(text)
        except ConfigWorkspaceValidationError as exc:
            return {"valid": False, "message": str(exc)}
        return {"valid": True, "message": "Configuration contract is valid."}

    def _file_payload(
        self, managed: ManagedFile, *, include_content: bool
    ) -> dict[str, object]:
        data, metadata = self._read(managed)
        text = data.decode("utf-8")
        payload: dict[str, object] = {
            "id": managed.id,
            "directoryId": managed.directory_id,
            "name": managed.name,
            "path": str(managed.path),
            "kind": managed.kind,
            "editable": True,
            "removable": not managed.built_in,
            "builtIn": managed.built_in,
            "applyMode": managed.apply_mode,
            "applyTarget": managed.apply_target,
            "applyNote": (
                "Validated controller settings apply immediately and persist after reboot."
                if managed.apply_mode == "live"
                else "Saved as a rebuild draft; review it into source before the next Unreal cook."
            ),
            "modifiedAt": datetime.fromtimestamp(
                metadata.st_mtime, timezone.utc
            ).isoformat(),
            "revision": _revision(data),
            "size": len(data),
            "validation": self._validation(managed, text),
        }
        if include_content:
            payload["content"] = text
        return payload

    def _options(self, files: dict[str, ManagedFile]) -> dict[str, object]:
        motion = next(
            item
            for item in files.values()
            if item.directory_id == "controller-config"
            and item.name == "motion-catalog.json"
        )
        ai = next(
            item
            for item in files.values()
            if item.directory_id == "controller-config"
            and item.name == "character-ai-control.json"
        )
        characters = next(
            item
            for item in files.values()
            if item.directory_id == "unreal-config"
        )
        motion_value = _strict_json(self._read(motion)[0].decode(), "motion catalog")
        ai_value = _strict_json(self._read(ai)[0].decode(), "AI-control config")
        try:
            _default, profiles, _digest = self._character_validator.load_profiles(
                characters.path
            )
            character_ids = list(profiles)
        except (OSError, configparser.Error, RuntimeError):
            character_ids = []

        wardrobe_options: list[dict[str, object]] = []
        for managed in files.values():
            if managed.directory_id != "wardrobe-profiles":
                continue
            try:
                value = _strict_json(
                    self._read(managed)[0].decode(), "wardrobe profile"
                )
                wardrobe_options.append({
                    "fileId": managed.id,
                    "profileId": value.get("id"),
                    "status": value.get("status"),
                    "slots": value.get("slots", {}),
                    "presets": sorted(value.get("presets", {})),
                })
            except ConfigWorkspaceError:
                continue
        return {
            "characters": character_ids,
            "motionPresets": sorted(motion_value.get("items", {})),
            "aiControlModes": [
                mode.get("id")
                for mode in ai_value.get("modes", [])
                if isinstance(mode, dict)
            ],
            "wardrobeProfiles": wardrobe_options,
        }

    def snapshot(self, file_id: str | None = None) -> dict[str, object]:
        """Return the API-ready workspace manifest, optionally with one file body."""

        with self._lock:
            files = self._managed_files()
            selected: ManagedFile | None = None
            if file_id is not None:
                if not isinstance(file_id, str) or file_id not in files:
                    raise ConfigWorkspaceNotFound("configuration file ID is unknown")
                selected = files[file_id]
            directories = [
                {
                    "id": "controller-config",
                    "label": "Controller configuration",
                    "path": str(self.workspace_root / "controller"),
                    "description": (
                        "Validated text settings apply live and are loaded again after reboot."
                    ),
                    "addable": False,
                },
                {
                    "id": "unreal-config",
                    "label": "Character profiles",
                    "path": str(self.workspace_root / "unreal"),
                    "description": (
                        "Reviewed Unreal character, camera, cook, and adapter profiles. "
                        "Changes require a new cooked package."
                    ),
                    "addable": False,
                },
                {
                    "id": "wardrobe-profiles",
                    "label": "Wardrobe profiles",
                    "path": str(self.workspace_root / "wardrobe"),
                    "description": (
                        "Logical garment and preset IDs. New JSON files are supported, "
                        "but they do not install or cook the referenced Unreal assets."
                    ),
                    "addable": True,
                    "acceptedKind": "wardrobe-profile-json",
                },
                {
                    "id": "project-assets",
                    "label": "Private Unreal assets",
                    "path": str(
                        self.project_root / "Project" / "FayAvatarRuntime" / "Content"
                    ),
                    "description": (
                        "Meshes, materials, morphs, animations, and cooked garments. "
                        "Binary Unreal assets are managed through Unreal, not this editor."
                    ),
                    "addable": False,
                },
                {
                    "id": "wardrobe-runtime",
                    "label": "Wardrobe runtime adapter",
                    "path": str(
                        self.project_root
                        / "Project"
                        / "FayAvatarRuntime"
                        / "Plugins"
                        / "FayWardrobe"
                    ),
                    "description": (
                        "Source adapter that resolves logical wardrobe IDs to reviewed "
                        "components during a package build."
                    ),
                    "addable": False,
                },
                {
                    "id": "workspace-backups",
                    "label": "Configuration backups",
                    "path": str(self.backup_root),
                    "description": (
                        "Automatic timestamped copies created before every save or delete."
                    ),
                    "addable": False,
                },
            ]
            payload: dict[str, object] = {
                "schemaVersion": WORKSPACE_SCHEMA,
                "workspaceId": "ue5-spark-private-config-v1",
                "workspacePath": str(self.workspace_root),
                "backupPath": str(self.backup_root),
                "directories": directories,
                "files": [
                    self._file_payload(
                        managed,
                        include_content=selected is not None and managed.id == selected.id,
                    )
                    for managed in sorted(
                        files.values(), key=lambda item: (item.directory_id, item.name)
                    )
                ],
                "options": self._options(files),
                "guidance": [
                    (
                        "Save validates first, writes atomically, and preserves the "
                        "previous revision under Configuration backups."
                    ),
                    (
                        "Controller configuration is reloaded after a validated save and "
                        "remains available after reboot."
                    ),
                    (
                        "Rebuild-mode changes require a reviewed Unreal cook/package. "
                        "Editing JSON or INI cannot add an uncooked model or garment."
                    ),
                    (
                        "Add or remove is limited to user-created wardrobe JSON. Built-in "
                        "baseline files can be edited but cannot be deleted."
                    ),
                ],
            }
            if selected is not None:
                payload["file"] = next(
                    item for item in payload["files"] if item["id"] == selected.id
                )
            return payload

    def read_file(self, file_id: str) -> dict[str, object]:
        """Return the direct file object expected by ``GET ?file=<opaque-id>``."""

        return self.snapshot(file_id)["file"]

    def apply_action(self, payload: object) -> dict[str, object]:
        """Validate and dispatch the exact POST ``/api/workspace`` contract."""

        if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
            raise ConfigWorkspaceValidationError(
                "workspace request must contain one supported action"
            )
        action = payload["action"]
        if action == "save":
            if set(payload) != {"action", "fileId", "revision", "content"}:
                raise ConfigWorkspaceValidationError(
                    "save accepts only fileId, revision, and content"
                )
            result = self.save_file(
                payload["fileId"], payload["revision"], payload["content"]
            )
        elif action == "create":
            if set(payload) != {"action", "directoryId", "name", "content"}:
                raise ConfigWorkspaceValidationError(
                    "create accepts only directoryId, name, and content"
                )
            result = self.create_file(
                payload["directoryId"], payload["name"], payload["content"]
            )
        elif action == "delete":
            if set(payload) != {"action", "fileId", "revision"}:
                raise ConfigWorkspaceValidationError(
                    "delete accepts only fileId and revision"
                )
            result = self.delete_file(payload["fileId"], payload["revision"])
        else:
            raise ConfigWorkspaceValidationError(
                "workspace action must be save, create, or delete"
            )
        result["workspace"] = self.snapshot()
        return result

    def save_file(
        self, file_id: str, revision: str, content: object
    ) -> dict[str, object]:
        with self._lock:
            files = self._managed_files()
            if not isinstance(file_id, str) or file_id not in files:
                raise ConfigWorkspaceNotFound("configuration file ID is unknown")
            managed = files[file_id]
            current, _metadata = self._read(managed)
            self._require_revision(revision, current)
            maximum = MAX_JSON_BYTES if managed.kind == "json" else MAX_INI_BYTES
            candidate = self._bounded_text(content, maximum, managed.name)
            candidate_text = candidate.decode("utf-8")
            self._validator_for(managed)(candidate_text)
            if managed.directory_id == "wardrobe-profiles":
                self._require_unique_wardrobe_id(
                    candidate_text, files, exclude_file_id=managed.id
                )
            backup = self._backup_copy(managed, current, "save")
            self._atomic_replace(managed.path, candidate)
            file_payload = self._file_payload(managed, include_content=True)
            return {
                "message": self._apply_message(managed, "saved"),
                "file": file_payload,
                "validation": file_payload["validation"],
                "backup": backup,
            }

    def create_file(
        self, directory_id: str, name: object, content: object
    ) -> dict[str, object]:
        with self._lock:
            if directory_id != "wardrobe-profiles":
                raise ConfigWorkspaceSecurityError(
                    "new files are supported only in Wardrobe profiles"
                )
            if not isinstance(name, str) or not WARDROBE_NAME_PATTERN.fullmatch(name):
                raise ConfigWorkspaceSecurityError(
                    "wardrobe filename must be a simple .json name"
                )
            files = self._managed_files()
            wardrobe_files = [
                item for item in files.values()
                if item.directory_id == "wardrobe-profiles"
            ]
            if len(wardrobe_files) >= MAX_WARDROBE_FILES:
                raise ConfigWorkspaceSecurityError("wardrobe profile limit reached")
            if any(item.name.casefold() == name.casefold() for item in wardrobe_files):
                raise ConfigWorkspaceConflict("wardrobe filename already exists")
            candidate = self._bounded_text(content, MAX_JSON_BYTES, name)
            candidate_text = candidate.decode("utf-8")
            self._validators["wardrobe_profile"](candidate_text)
            self._require_unique_wardrobe_id(candidate_text, files)
            destination = self.workspace_root / "wardrobe" / name
            self._require_inside(destination, self.workspace_root)
            self._atomic_create(destination, candidate)
            managed = ManagedFile(
                id=self._opaque_id(directory_id, name),
                name=name,
                directory_id=directory_id,
                path=destination,
                kind="json",
                apply_mode="rebuild",
                apply_target="Unreal Linux ARM64 package",
                built_in=False,
            )
            file_payload = self._file_payload(managed, include_content=True)
            return {
                "message": self._apply_message(managed, "created"),
                "file": file_payload,
                "validation": file_payload["validation"],
                "backup": {"created": False, "path": None},
            }

    def delete_file(self, file_id: str, revision: str) -> dict[str, object]:
        with self._lock:
            files = self._managed_files()
            if not isinstance(file_id, str) or file_id not in files:
                raise ConfigWorkspaceNotFound("configuration file ID is unknown")
            managed = files[file_id]
            if managed.built_in or managed.directory_id != "wardrobe-profiles":
                raise ConfigWorkspaceSecurityError(
                    "built-in configuration files cannot be deleted"
                )
            current, _metadata = self._read(managed)
            self._require_revision(revision, current)
            backup_path = self._backup_path(managed, current, "delete")
            try:
                os.replace(managed.path, backup_path)
                self._fsync_directory(managed.path.parent)
                self._fsync_directory(backup_path.parent)
            except OSError as exc:
                raise ConfigWorkspaceError("configuration delete could not be archived") from exc
            return {
                "message": self._apply_message(managed, "removed"),
                "file": {
                    "id": managed.id,
                    "directoryId": managed.directory_id,
                    "name": managed.name,
                    "path": str(managed.path),
                    "revision": _revision(current),
                    "removable": True,
                    "builtIn": False,
                    "applyMode": managed.apply_mode,
                },
                "validation": {"valid": True, "message": "Archived before removal."},
                "backup": {"created": True, "path": str(backup_path)},
            }

    @staticmethod
    def _apply_message(managed: ManagedFile, verb: str) -> str:
        if managed.apply_mode == "live":
            return f"{managed.name} {verb} and ready to apply live."
        if managed.apply_mode == "restart":
            return (
                f"{managed.name} {verb}. Restart {managed.apply_target} to apply it."
            )
        return (
            f"{managed.name} {verb}. Rebuild {managed.apply_target}; this text "
            "change does not install or cook Unreal assets."
        )

    @staticmethod
    def _require_revision(revision: object, current: bytes) -> None:
        if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
            raise ConfigWorkspaceConflict("a valid current revision is required")
        if revision != _revision(current):
            raise ConfigWorkspaceConflict(
                "configuration changed since it was opened; reload before saving"
            )

    def _require_unique_wardrobe_id(
        self,
        candidate_text: str,
        files: dict[str, ManagedFile],
        *,
        exclude_file_id: str | None = None,
    ) -> None:
        candidate_id = _strict_json(candidate_text, "wardrobe profile").get("id")
        for managed in files.values():
            if (
                managed.directory_id != "wardrobe-profiles"
                or managed.id == exclude_file_id
            ):
                continue
            value = _strict_json(
                self._read(managed)[0].decode("utf-8"), "wardrobe profile"
            )
            if value.get("id") == candidate_id:
                raise ConfigWorkspaceConflict(
                    f"wardrobe profile ID {candidate_id!r} already exists"
                )

    def _backup_path(
        self, managed: ManagedFile, data: bytes, operation: str
    ) -> Path:
        directory = self.backup_root / managed.directory_id
        self._require_inside(directory, self.workspace_root)
        if directory.exists() and directory.is_symlink():
            raise ConfigWorkspaceSecurityError("backup directory must not be a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        basename = (
            f"{_utc_timestamp()}-{operation}-{managed.name}-"
            f"{_revision(data)[:12]}.bak"
        )
        destination = directory / basename
        self._require_inside(destination, self.workspace_root)
        if destination.exists() or destination.is_symlink():
            raise ConfigWorkspaceSecurityError("backup destination already exists")
        return destination

    def _backup_copy(
        self, managed: ManagedFile, data: bytes, operation: str
    ) -> dict[str, object]:
        destination = self._backup_path(managed, data, operation)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory(destination.parent)
        except OSError as exc:
            raise ConfigWorkspaceError("configuration backup could not be written") from exc
        return {"created": True, "path": str(destination)}

    def _atomic_create(self, destination: Path, data: bytes) -> None:
        self._require_inside(destination, self.workspace_root)
        parent = destination.parent
        self._require_directory(parent, self.workspace_root)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory(parent)
        except OSError as exc:
            raise ConfigWorkspaceError(
                f"could not create configuration {destination.name!r}"
            ) from exc

    def _atomic_replace(self, destination: Path, data: bytes) -> None:
        self._require_regular_file(
            destination,
            self.workspace_root,
            MAX_JSON_BYTES if destination.suffix == ".json" else MAX_INI_BYTES,
        )
        parent = destination.parent
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
            self._fsync_directory(parent)
        except OSError as exc:
            raise ConfigWorkspaceError(
                f"could not replace configuration {destination.name!r}"
            ) from exc
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

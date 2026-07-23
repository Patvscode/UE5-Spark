#!/usr/bin/env python3
"""Private same-origin controller and narrow Fay proxy for UE5-Spark."""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import math
import mimetypes
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any


TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
MAX_REQUEST_BYTES = 8 * 1024
MAX_WORKSPACE_REQUEST_BYTES = 192 * 1024
MAX_MESSAGE_CHARS = 2_000
MAX_MOTION_COMMAND_CHARS = 512
MAX_LIVE_FRAME_BYTES = 2 * 1024 * 1024
MAX_LIVE_FRAME_AGE_SECONDS = 2.0
MAX_RENDERER_CONTROL_BYTES = 16 * 1024
MAX_RENDERER_STATE_AGE_SECONDS = 6.0
SERVER_VERSION = "prototype-9-managed-stack-workspace"
PROJECT_STACK_UNIT = "ue5-spark-digital-human.target"
PROJECT_SERVICE_UNITS = {
    "ardy": "ue5-spark-ardy.service",
    "ardy-ready": "ue5-spark-ardy-ready.service",
    "avatar": "ue5-spark-avatar.service",
}
SERVICE_CONTROL_ACTIONS = ("start", "stop", "restart", "status")
SYSTEMCTL_PATH = Path("/usr/bin/systemctl")
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL)
LLM_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CHAT_SYSTEM_PROMPT = (
    "Reply in concise, natural English. Never expose hidden reasoning, analysis, "
    "or <think> tags. Do not claim the avatar performed an action unless the user "
    "used an available movement control."
)
ALLOWED_BEHAVIORS = frozenset({
    "idle", "listen", "wave", "invite", "think", "warn", "nod", "shake", "explain",
    "jog_in_place", "run_in_place", "jumping_jacks", "stretch", "dance_relaxed",
})
MOTION_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "motion-catalog.json"
CHARACTER_AI_CONTROL_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "character-ai-control.json"
)
AI_CONTROL_MODES = ("deterministic", "ai_motion", "asset_aware_ai")
MOTION_PROVIDER_HINTS = frozenset({"baked", "hybrid"})
MOTION_CONTEXT_FIELDS = frozenset({
    "schemaVersion", "characterProfile", "wardrobePreset",
    "cameraFraming", "stageZoom", "rendererState",
})
MOTION_CONTEXT_CHARACTER_PROFILES = frozenset({"ada", "aoi", "casual-girl"})
MOTION_CONTEXT_CAMERA_FRAMINGS = frozenset({"fit", "portrait", "custom"})
MOTION_CONTEXT_RENDERER_STATES = frozenset({
    "live-preview", "renderer-unstreamed", "verified-replay",
})
RENDERER_CHARACTER_PROFILES = {
    "ada": "Ada",
    "aoi": "Aoi",
    "casual-girl": "CasualGirl",
}
RENDERER_SWITCH_STATES = frozenset({
    "starting", "switching", "ready", "failed", "rollback",
})
RENDERER_STATE_FILE = "renderer-state.json"
RENDERER_REQUEST_FILE = "renderer-request.json"
WARDROBE_REQUEST_FILE = "wardrobe-request.json"
WARDROBE_APPLIED_FILE = "wardrobe-applied.json"
WARDROBE_REJECTED_FILE = "wardrobe-rejected.json"
AI_CONTROL_CONFIG_FIELDS = frozenset({
    "$schema", "schemaVersion", "controlConfigId", "defaultMode", "assetAwareNotice", "modes",
})
AI_CONTROL_MODE_FIELDS = frozenset({
    "id", "label", "description", "usesGenerativeMotion",
    "acceptsCharacterAssetContext", "requiresExplicitLocalOptIn",
})
AI_CONTROL_SEMANTICS = {
    "deterministic": (False, False, False),
    "ai_motion": (True, False, False),
    "asset_aware_ai": (True, True, True),
}
AI_CONTROL_MOTION_PROVIDERS = {
    "deterministic": "baked",
    "ai_motion": "hybrid",
    "asset_aware_ai": "hybrid",
}
MOTION_CATALOG_IDS = frozenset({
    "idle", "listen", "explain", "wave", "jog_in_place", "run_in_place",
    "jumping_jacks", "stretch", "dance_relaxed",
})
MOTION_ITEM_FIELDS = frozenset({
    "label", "aliases", "prompt", "duration", "intensity", "rootMode",
    "routeBehavior", "rendererPackaged",
})


class AssetAwareOptInRequired(ValueError):
    """Raised when the controller-wide asset-aware mode was not explicitly enabled."""


class ProjectServiceControlError(RuntimeError):
    """The fixed project-owned systemd target could not be controlled."""


def _load_config_workspace_module() -> object:
    """Load the sibling module when this file is run or imported by path."""

    module_name = "ue5_spark_config_workspace"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    path = Path(__file__).with_name("config_workspace.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("configuration workspace module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_CONFIG_WORKSPACE_MODULE = _load_config_workspace_module()
ConfigWorkspace = _CONFIG_WORKSPACE_MODULE.ConfigWorkspace
ConfigWorkspaceError = _CONFIG_WORKSPACE_MODULE.ConfigWorkspaceError
ConfigWorkspaceConflict = _CONFIG_WORKSPACE_MODULE.ConfigWorkspaceConflict
ConfigWorkspaceNotFound = _CONFIG_WORKSPACE_MODULE.ConfigWorkspaceNotFound
ConfigWorkspaceSecurityError = _CONFIG_WORKSPACE_MODULE.ConfigWorkspaceSecurityError
ConfigWorkspaceValidationError = _CONFIG_WORKSPACE_MODULE.ConfigWorkspaceValidationError


def normalize_service_control_request(payload: object) -> str:
    """Accept one operation for the fixed companion target, never a unit name."""

    if not isinstance(payload, dict) or set(payload) != {"action"}:
        raise ValueError("service request must contain exactly one action")
    action = payload.get("action")
    if not isinstance(action, str) or action not in SERVICE_CONTROL_ACTIONS:
        raise ValueError("service action must be start, stop, restart, or status")
    return action


def _service_status_label(active_state: str) -> str:
    return {
        "active": "running",
        "activating": "starting",
        "deactivating": "stopping",
        "inactive": "stopped",
        "failed": "failed",
    }.get(active_state, "unavailable")


class ProjectServiceManager:
    """Narrow systemd adapter for the project-owned heavy companion stack.

    HTTP callers never provide a unit name. All subprocess calls use fixed
    argv, never a shell, and Fay is intentionally absent from the managed unit
    table because its lifecycle belongs to the existing external deployment.
    """

    _STATUS_PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result")
    _SAFE_STATE = re.compile(r"[a-z][a-z0-9-]{0,31}")

    def __init__(
        self,
        *,
        enabled: bool,
        systemctl_path: Path = SYSTEMCTL_PATH,
        runner: object = subprocess.run,
    ) -> None:
        self.enabled = enabled
        self.systemctl_path = systemctl_path
        self._runner = runner

    def _unit_status(self, unit: str) -> dict[str, object]:
        if unit not in {PROJECT_STACK_UNIT, *PROJECT_SERVICE_UNITS.values()}:
            raise ProjectServiceControlError("unit is not project-owned")
        if not self.enabled:
            return {
                "unit": unit,
                "loadState": "unavailable",
                "activeState": "unknown",
                "subState": "unknown",
                "result": "unknown",
                "status": "unavailable",
            }
        command = [
            str(self.systemctl_path),
            "--user",
            "show",
            "--no-pager",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--property=Result",
            unit,
        ]
        try:
            completed = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        values: dict[str, str] = {}
        if completed is not None and completed.returncode == 0:
            for line in completed.stdout[:4096].splitlines():
                key, separator, value = line.partition("=")
                if separator and key in self._STATUS_PROPERTIES:
                    values[key] = (
                        value if self._SAFE_STATE.fullmatch(value) else "unknown"
                    )
        load_state = values.get("LoadState", "unknown")
        active_state = values.get("ActiveState", "unknown")
        sub_state = values.get("SubState", "unknown")
        result = values.get("Result", "unknown")
        status = (
            _service_status_label(active_state)
            if load_state == "loaded"
            else "unavailable"
        )
        return {
            "unit": unit,
            "loadState": load_state,
            "activeState": active_state,
            "subState": sub_state,
            "result": result,
            "status": status,
        }

    def snapshot(self, *, fay_online: bool | None) -> dict[str, object]:
        target = self._unit_status(PROJECT_STACK_UNIT)
        components = {
            component_id: self._unit_status(unit)
            for component_id, unit in PROJECT_SERVICE_UNITS.items()
        }
        component_states = [item["status"] for item in components.values()]
        if not self.enabled:
            companion_status = "unavailable"
        elif target["status"] == "unavailable" or "unavailable" in component_states:
            companion_status = "unavailable"
        elif "failed" in component_states or target["status"] == "failed":
            companion_status = "failed"
        elif target["status"] == "starting" or "starting" in component_states:
            companion_status = "starting"
        elif target["status"] == "stopping" or "stopping" in component_states:
            companion_status = "stopping"
        elif target["status"] == "running" and all(
            state == "running" for state in component_states
        ):
            companion_status = "running"
        elif target["status"] == "stopped" and all(
            state == "stopped" for state in component_states
        ):
            companion_status = "stopped"
        else:
            companion_status = "failed"

        def service_entry(
            service_id: str,
            label: str,
            status: str,
            detail: str,
            *,
            required: bool,
            managed: bool,
        ) -> dict[str, object]:
            return {
                "id": service_id,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
                "managed": managed,
            }

        ardy = components["ardy"]
        ready = components["ardy-ready"]
        avatar = components["avatar"]
        can_start = self.enabled and companion_status in {"stopped", "failed"}
        can_stop = self.enabled and companion_status not in {
            "stopped", "unavailable",
        }
        can_restart = self.enabled and companion_status not in {
            "starting", "stopping", "unavailable",
        }
        action_flags = {
            "start": can_start,
            "stop": can_stop,
            "restart": can_restart,
            "status": self.enabled,
        }
        services = [
            service_entry(
                "controller",
                "Web controller",
                "running",
                "Lightweight controller is available and configured to start after login.",
                required=True,
                managed=False,
            ),
            service_entry(
                "fay",
                "Fay",
                "running" if fay_online is True else "stopped" if fay_online is False else "unknown",
                "Externally managed; this app will never start, stop, or reconfigure Fay.",
                required=True,
                managed=False,
            ),
            service_entry(
                "ardy",
                "ARDY motion",
                str(ardy["status"]),
                (
                    "Generative motion service is ready."
                    if ardy["status"] == "running"
                    else "Project-owned ARDY service; startup requires at least 20 GiB available memory."
                ),
                required=True,
                managed=True,
            ),
            service_entry(
                "ardy-ready",
                "ARDY warm-up",
                str(ready["status"]),
                "Requires dynamic text and a measured 0–400 ms cached pose batch before Unreal starts.",
                required=True,
                managed=True,
            ),
            service_entry(
                "avatar",
                "Unreal avatar",
                str(avatar["status"]),
                "Project-owned packaged Unreal renderer and private frame supervisor.",
                required=True,
                managed=True,
            ),
        ]
        return {
            "schemaVersion": 1,
            "enabled": self.enabled,
            "targetState": companion_status,
            "components": services,
            "services": services,
            "companion": {
                "status": companion_status,
                "canStart": can_start,
                "canStop": can_stop,
                "canRestart": can_restart,
            },
            "allowedActions": [
                action for action in SERVICE_CONTROL_ACTIONS if action_flags[action]
            ],
        }

    def request(self, action: str) -> None:
        if action not in SERVICE_CONTROL_ACTIONS:
            raise ProjectServiceControlError("service action is not supported")
        if not self.enabled:
            raise ProjectServiceControlError("project service control is not enabled")
        if action == "status":
            return
        if action in {"start", "restart"}:
            reset_command = [
                str(self.systemctl_path),
                "--user",
                "reset-failed",
                *PROJECT_SERVICE_UNITS.values(),
            ]
            try:
                reset = self._runner(
                    reset_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ProjectServiceControlError(
                    "project service failure state could not be cleared"
                ) from exc
            if reset.returncode != 0:
                raise ProjectServiceControlError(
                    "project service failure state could not be cleared"
                )
        command = [
            str(self.systemctl_path),
            "--user",
            "--no-block",
            action,
            PROJECT_STACK_UNIT,
        ]
        try:
            completed = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProjectServiceControlError(
                "project service manager is unavailable"
            ) from exc
        if completed.returncode != 0:
            raise ProjectServiceControlError(
                "project service manager rejected the request"
            )


def _strict_json_object(text: str, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise RuntimeError(f"{label} contains a duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain one JSON object")
    return payload


def load_character_ai_control(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise RuntimeError("character AI-control config must not be a symlink")
    try:
        metadata = path.stat()
        if not path.is_file() or not 1 <= metadata.st_size <= 64 * 1024:
            raise RuntimeError("character AI-control config must be one bounded file")
        payload = _strict_json_object(
            path.read_text(encoding="utf-8"), "character AI-control config"
        )
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("character AI-control config is unavailable") from exc
    if (
        set(payload) != AI_CONTROL_CONFIG_FIELDS
        or payload.get("$schema") != "./character-ai-control.schema.json"
        or type(payload.get("schemaVersion")) is not int
        or payload.get("schemaVersion") != 1
        or payload.get("controlConfigId") != "ue5-spark-local-ai-control-v1"
        or payload.get("defaultMode") != "ai_motion"
        or not isinstance(payload.get("assetAwareNotice"), str)
        or not 1 <= len(payload["assetAwareNotice"]) <= 240
        or not isinstance(payload.get("modes"), list)
        or len(payload["modes"]) != len(AI_CONTROL_MODES)
    ):
        raise RuntimeError("character AI-control config contract is invalid")

    normalized_modes: list[dict[str, object]] = []
    for expected_id, mode in zip(AI_CONTROL_MODES, payload["modes"]):
        if not isinstance(mode, dict) or set(mode) != AI_CONTROL_MODE_FIELDS:
            raise RuntimeError(f"character AI-control mode {expected_id} is invalid")
        if mode.get("id") != expected_id:
            raise RuntimeError("character AI-control modes are not in their sealed order")
        if (
            not isinstance(mode.get("label"), str)
            or not 1 <= len(mode["label"]) <= 32
            or not isinstance(mode.get("description"), str)
            or not 1 <= len(mode["description"]) <= 180
        ):
            raise RuntimeError(f"character AI-control mode {expected_id} text is invalid")
        semantic_values = (
            mode.get("usesGenerativeMotion"),
            mode.get("acceptsCharacterAssetContext"),
            mode.get("requiresExplicitLocalOptIn"),
        )
        if (
            any(type(value) is not bool for value in semantic_values)
            or semantic_values != AI_CONTROL_SEMANTICS[expected_id]
        ):
            raise RuntimeError(f"character AI-control mode {expected_id} boundary is invalid")
        normalized_modes.append(dict(mode))
    return {
        "$schema": payload["$schema"],
        "schemaVersion": payload["schemaVersion"],
        "controlConfigId": payload["controlConfigId"],
        "defaultMode": payload["defaultMode"],
        "assetAwareNotice": payload["assetAwareNotice"],
        "modes": normalized_modes,
    }


def normalize_ai_control_request(
    payload: object, allowed_modes: frozenset[str] = frozenset(AI_CONTROL_MODES)
) -> tuple[str, bool]:
    if not isinstance(payload, dict) or "mode" not in payload:
        raise ValueError("AI-control request must contain one mode")
    mode = payload.get("mode")
    if not isinstance(mode, str) or mode not in allowed_modes:
        raise ValueError("AI-control mode is not supported")
    if mode == "asset_aware_ai":
        if set(payload) != {"mode", "acknowledgeAssetContext"}:
            raise AssetAwareOptInRequired(
                "asset-aware AI requires explicit controller-wide context acknowledgement"
            )
        acknowledgement = payload.get("acknowledgeAssetContext")
        if type(acknowledgement) is not bool or acknowledgement is not True:
            raise AssetAwareOptInRequired(
                "asset-aware AI requires explicit controller-wide context acknowledgement"
            )
        return mode, True
    if set(payload) != {"mode"}:
        raise ValueError("non-asset AI-control requests must contain only mode")
    return mode, False


class LocalAiControlState:
    """Thread-safe, process-local control mode; restart returns to ai_motion."""

    def __init__(self, config: dict[str, object]):
        self._config = config
        self._allowed_modes = frozenset(
            str(mode["id"]) for mode in config["modes"]
        )
        self._selected_mode = str(config["defaultMode"])
        self._lock = threading.Lock()

    def selected_mode(self) -> str:
        with self._lock:
            return self._selected_mode

    def motion_planner_enabled(self) -> bool:
        return self.selected_mode() != "deterministic"

    def select(self, payload: object) -> dict[str, object]:
        mode, _acknowledged = normalize_ai_control_request(payload, self._allowed_modes)
        with self._lock:
            self._selected_mode = mode
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        selected = self.selected_mode()
        return {
            "schemaVersion": self._config["schemaVersion"],
            "controlConfigId": self._config["controlConfigId"],
            "defaultMode": self._config["defaultMode"],
            "selectedMode": selected,
            "assetAwareEnabled": selected == "asset_aware_ai",
            "assetAwareNotice": self._config["assetAwareNotice"],
            "modes": [dict(mode) for mode in self._config["modes"]],
        }


def load_motion_catalog(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("reviewed motion catalog is unavailable") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "catalogId", "items"}
        or payload.get("schemaVersion") != 1
        or payload.get("catalogId") != "ue5-spark-reviewed-motion-v1"
        or not isinstance(payload.get("items"), dict)
        or set(payload["items"]) != MOTION_CATALOG_IDS
    ):
        raise RuntimeError("reviewed motion catalog contract is invalid")

    catalog: dict[str, dict[str, object]] = {}
    for catalog_id, item in payload["items"].items():
        if not isinstance(item, dict) or set(item) != MOTION_ITEM_FIELDS:
            raise RuntimeError(f"reviewed motion item {catalog_id} is invalid")
        label = item["label"]
        aliases = item["aliases"]
        prompt = item["prompt"]
        duration = item["duration"]
        intensity = item["intensity"]
        root_mode = item["rootMode"]
        route_behavior = item["routeBehavior"]
        renderer_packaged = item["rendererPackaged"]
        if not isinstance(label, str) or not 1 <= len(label) <= 48:
            raise RuntimeError(f"reviewed motion label {catalog_id} is invalid")
        if (
            not isinstance(aliases, list) or not 1 <= len(aliases) <= 8
            or any(not isinstance(alias, str) or not 1 <= len(alias) <= 64 for alias in aliases)
            or len(set(aliases)) != len(aliases)
        ):
            raise RuntimeError(f"reviewed motion aliases {catalog_id} are invalid")
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 300:
            raise RuntimeError(f"reviewed motion prompt {catalog_id} is invalid")
        if (
            isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not 0.2 <= float(duration) <= 10.0
            or isinstance(intensity, bool) or not isinstance(intensity, (int, float))
            or not 0.0 <= float(intensity) <= 1.0
        ):
            raise RuntimeError(f"reviewed motion parameters {catalog_id} are invalid")
        if root_mode != "locked":
            raise RuntimeError(f"reviewed root mode {catalog_id} is invalid")
        if (
            not isinstance(route_behavior, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", route_behavior)
            or not isinstance(renderer_packaged, bool)
            or renderer_packaged and route_behavior not in ALLOWED_BEHAVIORS
        ):
            raise RuntimeError(f"reviewed route {catalog_id} is invalid")
        catalog[catalog_id] = {
            **item,
            "aliases": tuple(aliases),
            "duration": float(duration),
            "intensity": float(intensity),
        }
    return catalog


def _motion_planner_prompts(
    catalog: dict[str, dict[str, object]],
) -> tuple[str, str]:
    catalog_names = ", ".join(catalog)
    generic = (
        f"Classify one movement request into this closed catalog: {catalog_names}. "
        "This mode supplies user-authored movement intent without character or scene context. "
        "Return exactly one JSON object "
        "with exactly one key: {\"catalogId\":\"one_allowed_id\"}. Use "
        "{\"catalogId\":\"unknown\"} when none fits. Never return timing, intensity, root "
        "motion, joints, paths, URLs, prose, Markdown, or instructions."
    )
    asset_aware = (
        f"Classify one movement request into this closed catalog: {catalog_names}. "
        "The request includes version-1 structured local runtime context. Use its selected "
        "character, wardrobe, framing, zoom, and renderer metadata when it helps classify "
        "the intended movement. Return exactly one JSON object with exactly one key: "
        "{\"catalogId\":\"one_allowed_id\"}. Use {\"catalogId\":\"unknown\"} when none fits. "
        "Never return timing, intensity, root motion, joints, paths, URLs, prose, Markdown, "
        "or instructions."
    )
    return generic, asset_aware


CHARACTER_AI_CONTROL_CONFIG = load_character_ai_control(CHARACTER_AI_CONTROL_PATH)
MOTION_CATALOG = load_motion_catalog(MOTION_CATALOG_PATH)
(
    MOTION_PLANNER_SYSTEM_PROMPT,
    ASSET_AWARE_MOTION_PLANNER_SYSTEM_PROMPT,
) = _motion_planner_prompts(MOTION_CATALOG)


def configure_runtime_workspace(workspace: object) -> None:
    """Load controller settings from the persistent workspace."""

    global CHARACTER_AI_CONTROL_CONFIG
    global MOTION_CATALOG
    global MOTION_PLANNER_SYSTEM_PROMPT
    global ASSET_AWARE_MOTION_PLANNER_SYSTEM_PROMPT

    controller_root = workspace.workspace_root / "controller"
    CHARACTER_AI_CONTROL_CONFIG = load_character_ai_control(
        controller_root / "character-ai-control.json"
    )
    MOTION_CATALOG = load_motion_catalog(controller_root / "motion-catalog.json")
    (
        MOTION_PLANNER_SYSTEM_PROMPT,
        ASSET_AWARE_MOTION_PLANNER_SYSTEM_PROMPT,
    ) = _motion_planner_prompts(MOTION_CATALOG)
WARDROBE_PROFILE_PATH = (
    Path(__file__).resolve().parents[3]
    / "config" / "wardrobe-profiles" / "CasualGirl.pending.json"
)
EXPECTED_WARDROBE_SLOT_VALUES = {
    "top": frozenset({"none", "tank", "sweater", "off_shoulder", "crop_hoodie"}),
    "bottom": frozenset({"shorts", "pants"}),
    "feet": frozenset({"barefoot", "shoes_socks"}),
    "hair": frozenset({"style_1", "style_2"}),
}
EXPECTED_WARDROBE_PRESETS = frozenset({"underwear", "casual", "hoodie"})
CURRENT_WARDROBE_PRESET = "casual"
CURRENT_WARDROBE_SELECTION = {
    "top": "tank",
    "bottom": "pants",
    "feet": "shoes_socks",
    "hair": "style_1",
}


def load_wardrobe_profile(path: Path) -> tuple[dict[str, object], dict[str, frozenset[str]], frozenset[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("reviewed wardrobe profile is unavailable") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {
            "schema", "status", "id", "sourceListing", "adapter", "reviewedAssetRoot",
            "allowFullyUnclothed", "slots", "presets",
        }
        or payload.get("schema") != 1
        or payload.get("id") != "casual-girl"
        or payload.get("sourceListing") != "https://www.fab.com/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300"
        or payload.get("adapter") != "UE5EpicArkit"
        or payload.get("reviewedAssetRoot") != "/Game/FayFab/CasualGirl"
        or payload.get("status") not in {"pending_asset_audit", "installed"}
        or not isinstance(payload.get("allowFullyUnclothed"), bool)
        or not isinstance(payload.get("slots"), dict)
        or not isinstance(payload.get("presets"), dict)
    ):
        raise RuntimeError("reviewed wardrobe profile contract is invalid")

    slots = payload["slots"]
    if set(slots) != set(EXPECTED_WARDROBE_SLOT_VALUES):
        raise RuntimeError("reviewed wardrobe slots are invalid")
    normalized_slots: dict[str, frozenset[str]] = {}
    for slot, values in slots.items():
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or frozenset(values) != EXPECTED_WARDROBE_SLOT_VALUES[slot]
            or len(values) != len(set(values))
        ):
            raise RuntimeError(f"reviewed wardrobe slot {slot} is invalid")
        normalized_slots[slot] = frozenset(values)

    presets = payload["presets"]
    if set(presets) != EXPECTED_WARDROBE_PRESETS:
        raise RuntimeError("reviewed wardrobe presets are invalid")
    for preset_id, selection in presets.items():
        if not isinstance(selection, dict) or set(selection) != set(normalized_slots):
            raise RuntimeError(f"reviewed wardrobe preset {preset_id} is invalid")
        if any(selection[slot] not in normalized_slots[slot] for slot in normalized_slots):
            raise RuntimeError(f"reviewed wardrobe preset {preset_id} is invalid")
    if payload["status"] != "installed" and payload["allowFullyUnclothed"]:
        raise RuntimeError("pending wardrobe profile cannot allow full undress")

    # The native v30 actor currently carries only this inspected default
    # outfit. The broader seller catalog remains pending and is deliberately
    # not exposed as a working runtime choice.
    installed = True
    current_preset = dict(presets[CURRENT_WARDROBE_PRESET])
    if current_preset != CURRENT_WARDROBE_SELECTION:
        raise RuntimeError("current runtime wardrobe preset drifted from its sealed mapping")
    public_profile = {
        "profileId": payload["id"],
        "displayName": "Casual Girl",
        "installed": installed,
        "state": "installed_default_only",
        "scope": "default_outfit_only",
        "presets": [{
            "id": CURRENT_WARDROBE_PRESET,
            "label": "Casual",
            "slots": current_preset,
        }],
        "slots": {
            slot: [{
                "id": current_preset[slot],
                "label": current_preset[slot].replace("_", " ").title(),
            }]
            for slot in slots
        },
        "fullyUnclothed": {
            "enabled": installed and payload["allowFullyUnclothed"],
            "reason": (
                "Complete base-body audit approved."
                if installed and payload["allowFullyUnclothed"] else
                "Complete base-body geometry has not been audited; only the fixed casual outfit is installed."
            ),
        },
    }
    return public_profile, normalized_slots, frozenset(presets)


WARDROBE_PROFILE, WARDROBE_SLOT_VALUES, WARDROBE_PRESETS = load_wardrobe_profile(
    WARDROBE_PROFILE_PATH
)
MEDIA_MAP = {
    "ada-idle.mp4": "v21/ada-v21-idle-isolation-8s-20260721T131806Z.mp4",
    "ada-wave.mp4": "v28/ada-20260721T212709Z/ada-v28-speaking-wave-front-8s.mp4",
    "ada-explain.mp4": "v28/ada-real-ardy-20260721T231312Z/ada-v28-real-ardy-explain-8s.mp4",
    "ada-listen.mp4": "v12/ada-v12-face-body.mp4",
    "ada-poster.png": "v28/ada-real-ardy-20260721T231312Z/ada-v28-real-ardy-explain.png",
    "aoi-motion.mp4": "v13/aoi-v13-speech-motion.mp4",
    "aoi-explain.mp4": "v13/aoi-v13-explain.mp4",
    "aoi-poster.png": "v13/aoi-v13-launch.png",
}


def checked_bind_host(value: str) -> str:
    address = ipaddress.ip_address(value)
    if not (address.is_loopback or address in TAILSCALE_NET):
        raise argparse.ArgumentTypeError("host must be loopback or a concrete Tailscale IPv4 address")
    return str(address)


def checked_upstream(value: str, *, loopback_only: bool = False) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("upstream must be an unauthenticated HTTP origin")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("upstream host must be a concrete IP address") from exc
    if loopback_only and not address.is_loopback:
        raise argparse.ArgumentTypeError("upstream must be loopback")
    if not loopback_only and not (address.is_loopback or address in TAILSCALE_NET):
        raise argparse.ArgumentTypeError("upstream must be loopback or Tailscale")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("upstream must not include a path, query, or fragment")
    return value.rstrip("/")


def motion_provider_for_ai_control_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode not in AI_CONTROL_MOTION_PROVIDERS:
        raise ValueError("AI-control mode has no reviewed motion provider")
    provider = AI_CONTROL_MOTION_PROVIDERS[mode]
    if provider not in MOTION_PROVIDER_HINTS:
        raise RuntimeError("AI-control motion-provider mapping is invalid")
    return provider


def normalize_action(
    payload: object, *, provider_hint: str | None = None
) -> dict[str, object]:
    if not isinstance(payload, dict) or not set(payload).issubset(
        {"behavior", "intensity", "duration", "prompt"}
    ):
        raise ValueError("action must be a small JSON object")
    behavior = str(payload.get("behavior", "")).strip().lower()
    if behavior not in ALLOWED_BEHAVIORS:
        raise ValueError("behavior is not allowlisted")
    try:
        intensity = float(payload.get("intensity", 0.5))
        duration = float(payload.get("duration", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("intensity and duration must be numbers") from exc
    if not 0 <= intensity <= 1 or not 0.2 <= duration <= 10:
        raise ValueError("action values are outside the reviewed bounds")
    action: dict[str, object] = {
        "behavior": behavior,
        "intensity": intensity,
        "duration": duration,
        "user": "User",
    }
    if "prompt" in payload:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("motion prompt must be text")
        prompt = prompt.strip()
        if not prompt or len(prompt) > MAX_MOTION_COMMAND_CHARS:
            raise ValueError("motion prompt must contain 1 to 512 characters")
        action["prompt"] = prompt
    if provider_hint is not None:
        if not isinstance(provider_hint, str) or provider_hint not in MOTION_PROVIDER_HINTS:
            raise ValueError("motion provider hint is not supported")
        action["provider"] = provider_hint
    return action


def normalize_motion_command(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"command"}:
        raise ValueError("movement request must contain only command")
    command = payload.get("command")
    if not isinstance(command, str):
        raise ValueError("movement command must be text")
    command = re.sub(r"[ \t]+", " ", command).strip()
    if not command or len(command) > MAX_MOTION_COMMAND_CHARS:
        raise ValueError("movement command must contain 1 to 512 characters")
    if any(ord(character) < 32 for character in command):
        raise ValueError("movement command must be one line")
    return command


def normalize_motion_context(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != MOTION_CONTEXT_FIELDS:
        raise ValueError("runtime context does not match the bounded context adapter")
    if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1:
        raise ValueError("runtime context schema version is not supported")
    if payload.get("characterProfile") not in MOTION_CONTEXT_CHARACTER_PROFILES:
        raise ValueError("runtime context character profile is not supported")
    if payload.get("wardrobePreset") not in WARDROBE_PRESETS | {"not-applicable"}:
        raise ValueError("runtime context wardrobe preset is not supported")
    if (
        payload.get("characterProfile") != "casual-girl"
        and payload.get("wardrobePreset") != "not-applicable"
    ):
        raise ValueError("runtime context wardrobe preset does not match the character")
    if payload.get("cameraFraming") not in MOTION_CONTEXT_CAMERA_FRAMINGS:
        raise ValueError("runtime context camera framing is not supported")
    if payload.get("rendererState") not in MOTION_CONTEXT_RENDERER_STATES:
        raise ValueError("runtime context renderer state is not supported")
    zoom = payload.get("stageZoom")
    if (
        isinstance(zoom, bool)
        or not isinstance(zoom, (int, float))
        or not math.isfinite(float(zoom))
        or not 0.75 <= float(zoom) <= 3.0
    ):
        raise ValueError("runtime context stage zoom is outside the reviewed bounds")
    return {
        "schemaVersion": 1,
        "characterProfile": payload["characterProfile"],
        "wardrobePreset": payload["wardrobePreset"],
        "cameraFraming": payload["cameraFraming"],
        "stageZoom": round(float(zoom), 2),
        "rendererState": payload["rendererState"],
    }


def normalize_motion_request(
    payload: object,
) -> tuple[str, dict[str, object] | None]:
    if not isinstance(payload, dict) or not set(payload).issubset({"command", "context"}):
        raise ValueError("movement request contains unsupported fields")
    command = normalize_motion_command({"command": payload.get("command")})
    context = (
        normalize_motion_context(payload["context"])
        if "context" in payload
        else None
    )
    return command, context


def direct_motion_catalog_id(command: str) -> str | None:
    lowered = command.casefold()
    matches: list[tuple[int, str]] = []
    for catalog_id, item in MOTION_CATALOG.items():
        for alias in item["aliases"]:
            if re.search(rf"(?<!\w){re.escape(str(alias).casefold())}(?!\w)", lowered):
                matches.append((len(str(alias)), catalog_id))
    return max(matches)[1] if matches else None


def parse_planner_catalog_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or set(payload) != {"catalogId"}:
        return None
    catalog_id = payload.get("catalogId")
    if catalog_id == "unknown":
        return None
    return catalog_id if isinstance(catalog_id, str) and catalog_id in MOTION_CATALOG else None


def resolve_motion_command(command: str, planner_catalog_id: str | None = None) -> dict[str, object] | None:
    catalog_id = direct_motion_catalog_id(command)
    if catalog_id is None and planner_catalog_id in MOTION_CATALOG:
        catalog_id = planner_catalog_id
    if catalog_id is None:
        return None
    item = MOTION_CATALOG[catalog_id]
    return {
        "catalogId": catalog_id,
        "label": item["label"],
        "duration": item["duration"],
        "intensity": item["intensity"],
        "rootMode": item["rootMode"],
        "rendererPackaged": item["rendererPackaged"],
        "routeBehavior": item["routeBehavior"],
    }


def normalize_wardrobe(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("wardrobe request must be a small JSON object")
    if not {"profileId"} <= set(payload) <= {"profileId", "preset", "slots"}:
        raise ValueError("wardrobe request contains unsupported fields")
    if payload.get("profileId") != WARDROBE_PROFILE["profileId"]:
        raise ValueError("wardrobe profile is not reviewed")
    if "preset" not in payload:
        raise ValueError("wardrobe request needs the installed casual preset")

    normalized: dict[str, object] = {"profileId": WARDROBE_PROFILE["profileId"]}
    preset = payload.get("preset")
    if preset != CURRENT_WARDROBE_PRESET:
        raise ValueError("wardrobe preset is not installed in this renderer")
    normalized["preset"] = CURRENT_WARDROBE_PRESET
    if "slots" in payload:
        slots = payload.get("slots")
        if not isinstance(slots, dict) or slots != CURRENT_WARDROBE_SELECTION:
            raise ValueError("only the complete installed casual outfit is available")
    normalized["slots"] = dict(CURRENT_WARDROBE_SELECTION)
    return normalized


def normalize_message(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"message"}:
        raise ValueError("chat request must contain only message")
    message = payload.get("message")
    if not isinstance(message, str):
        raise ValueError("message must be text")
    message = message.strip()
    if not message or len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("message must contain 1 to 2000 characters")
    return message


def normalize_reply(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid reply")
    reply = THINK_BLOCK_PATTERN.sub("", value)
    reply = re.sub(r"</?think>", "", reply, flags=re.IGNORECASE)
    reply = re.sub(r"[ \t]+", " ", reply)
    reply = re.sub(r"\n{3,}", "\n\n", reply).strip()
    return reply or "I’m ready—please try that again."


def checked_model_name(value: str) -> str:
    if not LLM_MODEL_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("LLM model must be one reviewed simple name")
    return value


def safe_root(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def safe_private_root(path: Path, label: str) -> Path:
    resolved = safe_root(path, label)
    metadata = resolved.stat()
    if metadata.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"{label} must not be accessible by group or other users")
    return resolved


def read_live_frame(live_root: Path, *, now_ns: int | None = None) -> bytes | None:
    """Read one fresh, private JPEG without following a replaceable symlink."""
    frame_path = live_root / "frame.jpg"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(frame_path, flags)
    except (FileNotFoundError, OSError):
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            return None
        if not 4 <= metadata.st_size <= MAX_LIVE_FRAME_BYTES:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        age_ns = current_ns - metadata.st_mtime_ns
        if age_ns < 0 or age_ns > int(MAX_LIVE_FRAME_AGE_SECONDS * 1_000_000_000):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(MAX_LIVE_FRAME_BYTES + 1)
        if len(payload) != metadata.st_size:
            return None
        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            return None
        return payload
    finally:
        os.close(descriptor)


def live_stream_ready(renderer: bool, live_root: Path) -> bool:
    return renderer and read_live_frame(live_root) is not None


def normalize_renderer_character_request(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"character"}:
        raise ValueError("character request must contain exactly one character")
    character = payload.get("character")
    if not isinstance(character, str) or character not in RENDERER_CHARACTER_PROFILES:
        raise ValueError("character is not a reviewed renderer profile")
    return character


def _read_private_control_json(path: Path) -> dict[str, object] | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError):
        return None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 2 <= metadata.st_size <= MAX_RENDERER_CONTROL_BYTES
        ):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(MAX_RENDERER_CONTROL_BYTES + 1)
        if len(body) != metadata.st_size:
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        os.close(descriptor)


def read_renderer_state(
    live_root: Path, *, now_unix_ms: int | None = None
) -> dict[str, object] | None:
    payload = _read_private_control_json(live_root / RENDERER_STATE_FILE)
    if payload is None or set(payload) != {
        "schemaVersion", "state", "activeCharacter", "requestedCharacter",
        "availableCharacters", "packageGeneration", "updatedAtUnixMs",
    }:
        return None
    now_ms = int(time.time() * 1000) if now_unix_ms is None else now_unix_ms
    updated_ms = payload.get("updatedAtUnixMs")
    available = payload.get("availableCharacters")
    active = payload.get("activeCharacter")
    requested = payload.get("requestedCharacter")
    generation = payload.get("packageGeneration")
    if (
        payload.get("schemaVersion") != 1
        or payload.get("state") not in RENDERER_SWITCH_STATES
        or type(updated_ms) is not int
        or updated_ms > now_ms + 2_000
        or now_ms - updated_ms > int(MAX_RENDERER_STATE_AGE_SECONDS * 1000)
        or not isinstance(available, list)
        or not 1 <= len(available) <= len(RENDERER_CHARACTER_PROFILES)
        or len(available) != len(set(available))
        or any(item not in RENDERER_CHARACTER_PROFILES for item in available)
        or active is not None and active not in available
        or requested is not None and requested not in available
        or not isinstance(generation, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", generation) is None
    ):
        return None
    if payload["state"] == "ready" and active is None:
        return None
    return {
        "state": payload["state"],
        "activeCharacter": active,
        "requestedCharacter": requested,
        "availableCharacters": list(available),
        "packageGeneration": generation,
    }


def write_renderer_request(live_root: Path, character: str) -> dict[str, object]:
    if character not in RENDERER_CHARACTER_PROFILES:
        raise ValueError("character is not a reviewed renderer profile")
    request = {
        "schemaVersion": 1,
        "character": character,
        "requestId": secrets.token_hex(12),
        "requestedAtUnixMs": int(time.time() * 1000),
    }
    _atomic_private_control_json(
        live_root, RENDERER_REQUEST_FILE, request, str(request["requestId"])
    )
    return request


def _atomic_private_control_json(
    live_root: Path,
    filename: str,
    payload: dict[str, object],
    nonce: str,
) -> None:
    destination = live_root / filename
    temporary = live_root / f".{filename}.{nonce}.tmp"
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if not 2 <= len(body) <= MAX_RENDERER_CONTROL_BYTES:
        raise ValueError("private control request is outside the allowed size")
    flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory_descriptor = os.open(live_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_wardrobe_request(
    live_root: Path, selection: dict[str, object]
) -> dict[str, object]:
    normalized = normalize_wardrobe(selection)
    request = {
        "schemaVersion": 1,
        "requestId": secrets.token_hex(12),
        "profileId": normalized["profileId"],
        "preset": normalized["preset"],
        "slots": normalized["slots"],
        "requestedAtUnixMs": int(time.time() * 1000),
    }
    _atomic_private_control_json(
        live_root, WARDROBE_REQUEST_FILE, request, str(request["requestId"])
    )
    return request


def read_wardrobe_receipt(live_root: Path, filename: str) -> dict[str, object] | None:
    if filename not in {WARDROBE_APPLIED_FILE, WARDROBE_REJECTED_FILE}:
        raise ValueError("wardrobe receipt filename is not supported")
    payload = _read_private_control_json(live_root / filename)
    if payload is None or set(payload) != {
        "schemaVersion", "requestId", "profileId", "preset", "slots",
        "requestedAtUnixMs",
    }:
        return None
    request_id = payload.get("requestId")
    requested_ms = payload.get("requestedAtUnixMs")
    if (
        payload.get("schemaVersion") != 1
        or not isinstance(request_id, str)
        or re.fullmatch(r"[0-9a-f]{24}", request_id) is None
        or type(requested_ms) is not int
        or requested_ms <= 0
    ):
        return None
    try:
        normalized = normalize_wardrobe({
            "profileId": payload.get("profileId"),
            "preset": payload.get("preset"),
            "slots": payload.get("slots"),
        })
    except ValueError:
        return None
    return {
        "requestId": request_id,
        "profileId": normalized["profileId"],
        "preset": normalized["preset"],
        "slots": normalized["slots"],
        "status": "applied" if filename == WARDROBE_APPLIED_FILE else "rejected",
    }


class ControllerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], dist: Path, media_root: Path,
                 live_root: Path, fay_base: str, ardy_base: str,
                 llm_base: str | None, llm_model: str | None,
                 motion_planner_model: str | None,
                 service_manager: ProjectServiceManager | None = None,
                 config_workspace: object | None = None):
        super().__init__(address, ControllerHandler)
        self.dist = dist
        self.media_root = media_root
        self.live_root = live_root
        self.fay_base = fay_base
        self.ardy_base = ardy_base
        self.llm_base = llm_base
        self.llm_model = llm_model
        self.motion_planner_model = motion_planner_model
        self.ai_control = LocalAiControlState(CHARACTER_AI_CONTROL_CONFIG)
        self.service_manager = service_manager or ProjectServiceManager(enabled=False)
        self.config_workspace = config_workspace


class ControllerHandler(BaseHTTPRequestHandler):
    server: ControllerServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            self._status()
        elif path == "/api/services":
            self._service_status()
        elif path == "/api/workspace":
            self._workspace_get(parsed.query)
        elif path == "/api/character":
            self._renderer_character_status()
        elif path == "/api/ai-control":
            self._json(HTTPStatus.OK, self.server.ai_control.snapshot())
        elif path == "/api/wardrobe":
            self._json(HTTPStatus.OK, WARDROBE_PROFILE)
        elif path == "/live/frame.jpg":
            self._live_frame()
        elif path.startswith("/media/"):
            self._media(path.removeprefix("/media/"))
        elif path.startswith("/api/") or path.startswith("/live/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        else:
            self._static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/live/frame.jpg":
            self._live_frame(head_only=True)
        elif path.startswith("/media/"):
            self._media(path.removeprefix("/media/"), head_only=True)
        elif not path.startswith("/api/") and not path.startswith("/live/"):
            self._static(path, head_only=True)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self._request_json(
                maximum=(
                    MAX_WORKSPACE_REQUEST_BYTES
                    if path == "/api/workspace"
                    else MAX_REQUEST_BYTES
                )
            )
            if path == "/api/chat":
                self._chat(payload)
            elif path == "/api/action":
                self._action(payload)
            elif path == "/api/motion-command":
                self._motion_command(payload)
            elif path == "/api/ai-control":
                self._ai_control(payload)
            elif path == "/api/character":
                self._renderer_character(payload)
            elif path == "/api/wardrobe":
                self._wardrobe(payload)
            elif path in {"/api/services", "/api/services/companion"}:
                self._service_control(payload)
            elif path == "/api/workspace":
                self._workspace_mutate(payload)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "same_origin_only"})

    def _request_json(self, *, maximum: int = MAX_REQUEST_BYTES) -> object:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if not 1 <= length <= maximum:
            raise ValueError("request body is outside the allowed size")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc

    def _status(self) -> None:
        fay = False
        renderer = False
        ardy = False
        try:
            status = self._upstream_json(
                f"{self.server.fay_base}/api/get-system-status?username=User", timeout=3,
            )
            fay = status.get("server") is True
            renderer = status.get("digital_human") is True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        try:
            status = self._upstream_json(f"{self.server.ardy_base}/healthz", timeout=3)
            ardy = status.get("status") == "ready"
        except (OSError, ValueError, urllib.error.URLError):
            pass
        stream = live_stream_ready(renderer, self.server.live_root)
        renderer_control = read_renderer_state(self.server.live_root)
        if renderer_control is None:
            active_character = "ada" if renderer and stream else None
            requested_character = active_character
            available_characters = ["ada", "aoi"]
            switch_state = "unmanaged"
            package_generation = "legacy"
            switch_supported = False
        else:
            active_character = renderer_control["activeCharacter"]
            requested_character = renderer_control["requestedCharacter"]
            available_characters = renderer_control["availableCharacters"]
            switch_state = renderer_control["state"]
            package_generation = renderer_control["packageGeneration"]
            switch_supported = True
        self._json(HTTPStatus.OK, {
            "fay": fay, "ardy": ardy, "renderer": renderer, "stream": stream,
            "mode": (
                "live-preview" if stream else
                "renderer-unstreamed" if renderer else
                "verified-replay"
            ),
            "activeCharacter": active_character,
            "requestedCharacter": requested_character,
            "availableCharacters": available_characters,
            "rendererSwitchState": switch_state,
            "rendererSwitchSupported": switch_supported,
            "packageGeneration": package_generation,
            "version": SERVER_VERSION,
        })

    def _fay_service_online(self) -> bool | None:
        try:
            status = self._upstream_json(
                f"{self.server.fay_base}/api/get-system-status?username=User",
                timeout=1,
            )
            return status.get("server") is True
        except (OSError, ValueError, urllib.error.URLError, socket.timeout):
            return None

    def _service_status(self) -> None:
        self._json(
            HTTPStatus.OK,
            self.server.service_manager.snapshot(
                fay_online=self._fay_service_online()
            ),
        )

    def _service_control(self, payload: object) -> None:
        action = normalize_service_control_request(payload)
        if action == "status":
            self._service_status()
            return
        try:
            self.server.service_manager.request(action)
        except ProjectServiceControlError:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "project_service_control_unavailable",
                "detail": (
                    "The fixed DGX Spark companion services could not accept "
                    "that request. Fay was not changed."
                ),
            })
            return
        snapshot = self.server.service_manager.snapshot(
            fay_online=self._fay_service_online()
        )
        snapshot["acceptedAction"] = action
        snapshot["message"] = {
            "start": "Companion startup requested.",
            "stop": "Companion shutdown requested.",
            "restart": "Companion restart requested.",
        }[action]
        self._json(HTTPStatus.ACCEPTED, snapshot)

    def _workspace_get(self, query: str) -> None:
        if self.server.config_workspace is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "configuration_workspace_unavailable",
                "detail": "The persistent configuration workspace is not configured.",
            })
            return
        try:
            fields = urllib.parse.parse_qsl(
                query, keep_blank_values=True, strict_parsing=True, max_num_fields=1
            ) if query else []
            if not fields:
                payload = self.server.config_workspace.snapshot()
            elif len(fields) == 1 and fields[0][0] == "file" and fields[0][1]:
                payload = self.server.config_workspace.read_file(fields[0][1])
            else:
                raise ConfigWorkspaceValidationError(
                    "workspace query accepts only one opaque file ID"
                )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {
                "error": "invalid_workspace_query", "detail": str(exc),
            })
            return
        except ConfigWorkspaceError as exc:
            self._workspace_error(exc)
            return
        self._json(HTTPStatus.OK, payload)

    def _workspace_mutate(self, payload: object) -> None:
        if self.server.config_workspace is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "configuration_workspace_unavailable",
                "detail": "The persistent configuration workspace is not configured.",
            })
            return
        try:
            response = self.server.config_workspace.apply_action(payload)
        except ConfigWorkspaceError as exc:
            self._workspace_error(exc)
            return
        changed_file = response.get("file") if isinstance(response, dict) else None
        if (
            isinstance(changed_file, dict)
            and changed_file.get("directoryId") == "controller-config"
            and payload.get("action") == "save"
        ):
            try:
                configure_runtime_workspace(self.server.config_workspace)
                self.server.ai_control = LocalAiControlState(
                    CHARACTER_AI_CONTROL_CONFIG
                )
            except RuntimeError as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                    "error": "configuration_reload_failed",
                    "detail": str(exc),
                })
                return
            response["message"] = (
                f"{changed_file.get('name', 'Controller configuration')} saved, "
                "backed up, and applied live."
            )
        self._json(HTTPStatus.OK, response)

    def _workspace_error(self, exc: Exception) -> None:
        if isinstance(exc, ConfigWorkspaceConflict):
            status = HTTPStatus.CONFLICT
            error = "configuration_revision_conflict"
        elif isinstance(exc, ConfigWorkspaceNotFound):
            status = HTTPStatus.NOT_FOUND
            error = "configuration_file_not_found"
        elif isinstance(exc, ConfigWorkspaceValidationError):
            status = HTTPStatus.UNPROCESSABLE_ENTITY
            error = "configuration_validation_failed"
        elif isinstance(exc, ConfigWorkspaceSecurityError):
            status = HTTPStatus.FORBIDDEN
            error = "configuration_operation_forbidden"
        else:
            status = HTTPStatus.SERVICE_UNAVAILABLE
            error = "configuration_workspace_unavailable"
        self._json(status, {"error": error, "detail": str(exc)})

    def _renderer_character_status(self) -> None:
        state = read_renderer_state(self.server.live_root)
        if state is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "renderer_supervisor_unavailable",
            })
            return
        self._json(HTTPStatus.OK, state)

    def _renderer_character(self, payload: object) -> None:
        character = normalize_renderer_character_request(payload)
        state = read_renderer_state(self.server.live_root)
        if state is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "renderer_supervisor_unavailable",
                "detail": "The managed renderer switcher is not running.",
            })
            return
        if character not in state["availableCharacters"]:
            self._json(HTTPStatus.CONFLICT, {
                "error": "character_not_in_package",
                "character": character,
                "availableCharacters": state["availableCharacters"],
            })
            return
        if state["state"] == "ready" and state["activeCharacter"] == character:
            self._json(HTTPStatus.OK, {
                "ok": True,
                "status": "ready",
                "character": character,
                "packageGeneration": state["packageGeneration"],
            })
            return
        request = write_renderer_request(self.server.live_root, character)
        self._json(HTTPStatus.ACCEPTED, {
            "ok": True,
            "status": "requested",
            "character": character,
            "requestId": request["requestId"],
            "packageGeneration": state["packageGeneration"],
        })

    def _live_frame(self, head_only: bool = False) -> None:
        payload = read_live_frame(self.server.live_root)
        if payload is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "live_frame_unavailable"},
                       head_only=head_only)
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers("image/jpeg", {"Content-Length": str(len(payload))})
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _chat(self, payload: object) -> None:
        message = normalize_message(payload)
        try:
            reply, avatar_speech = self._chat_reply(message)
        except urllib.error.HTTPError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"Fay returned HTTP {exc.code}"})
            return
        except (KeyError, IndexError, TypeError, ValueError, OSError, urllib.error.URLError, socket.timeout):
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "Fay conversation is temporarily unavailable"})
            return
        self._json(HTTPStatus.OK, {
            "reply": reply,
            "liveRenderer": self._renderer_online(),
            "avatarSpeech": avatar_speech,
        })

    def _chat_reply(self, message: str) -> tuple[str, bool]:
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]
        if self.server.llm_base and self.server.llm_model:
            response = self._upstream_json(
                f"{self.server.llm_base}/v1/chat/completions",
                {
                    "model": self.server.llm_model,
                    "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "max_tokens": 256,
                    "temperature": 0.6,
                },
                timeout=180,
            )
            reply = normalize_reply(response["choices"][0]["message"]["content"])
            avatar_speech = False
            try:
                playback = self._upstream_json(
                    f"{self.server.fay_base}/transparent-pass",
                    {"user": "User", "text": reply},
                    timeout=180,
                )
                avatar_speech = playback.get("code") == 200
            except (OSError, ValueError, urllib.error.URLError, socket.timeout):
                pass
            return reply, avatar_speech

        response = self._upstream_json(
            f"{self.server.fay_base}/v1/chat/completions",
            {"model": "fay", "user": "User", "messages": messages},
            timeout=180,
        )
        return normalize_reply(response["choices"][0]["message"]["content"]), True

    def _action(self, payload: object) -> None:
        action = normalize_action(
            payload,
            provider_hint=motion_provider_for_ai_control_mode(
                self.server.ai_control.selected_mode()
            ),
        )
        status, response = self._dispatch_action(action)
        self._json(status, response)

    def _ai_control(self, payload: object) -> None:
        try:
            snapshot = self.server.ai_control.select(payload)
        except AssetAwareOptInRequired as exc:
            self._json(HTTPStatus.CONFLICT, {
                "error": "asset_aware_opt_in_required",
                "detail": str(exc),
            })
            return
        self._json(HTTPStatus.OK, snapshot)

    def _dispatch_action(self, action: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        try:
            response = self._upstream_json(
                f"{self.server.fay_base}/api/avatar/action", action, timeout=5,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.SERVICE_UNAVAILABLE:
                return HTTPStatus.OK, {
                    "ok": True, "live": False, "replay": True,
                    "behavior": action["behavior"], "detail": "renderer_offline",
                }
            return HTTPStatus.BAD_GATEWAY, {"error": "avatar action failed"}
        except (OSError, ValueError, urllib.error.URLError, socket.timeout):
            return HTTPStatus.BAD_GATEWAY, {"error": "avatar action service is unavailable"}
        return HTTPStatus.OK, {
            "ok": response.get("ok") is True, "live": response.get("ok") is True,
            "replay": False, "behavior": action["behavior"],
        }

    def _motion_command(self, payload: object) -> None:
        command, runtime_context = normalize_motion_request(payload)
        ai_control_mode = self.server.ai_control.selected_mode()
        if runtime_context is not None and ai_control_mode != "asset_aware_ai":
            raise ValueError("runtime context requires asset_aware_ai mode")

        # ARDY is a text-conditioned generative model. In either generative
        # mode, preserve the user's complete movement description instead of
        # reducing it to the deterministic quick-preset catalog. Prewarming is
        # intentionally completed before Fay tells Unreal to begin, because
        # Unreal's high-frequency pose requests have a much shorter timeout.
        if ai_control_mode != "deterministic":
            try:
                prepared = self._upstream_json(
                    f"{self.server.ardy_base}/v2/prompts",
                    {"prompt": command},
                    timeout=120,
                )
                prompt_id = prepared.get("promptId")
                if (
                    prepared.get("ok") is not True
                    or not isinstance(prompt_id, str)
                    or re.fullmatch(r"[0-9a-f]{64}", prompt_id) is None
                ):
                    raise ValueError("ARDY returned an invalid prompt receipt")
            except (
                OSError,
                ValueError,
                urllib.error.HTTPError,
                urllib.error.URLError,
                socket.timeout,
            ):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                    "error": "ardy_prompt_unavailable",
                    "detail": "ARDY could not prepare that movement prompt. Nothing was sent.",
                })
                return

            duration = 8.0
            intensity = 0.65
            action = normalize_action({
                # Explain is only the existing generated-provider/fallback
                # carrier. The prompt—not this carrier ID—conditions ARDY.
                "behavior": "explain",
                "prompt": command,
                "duration": duration,
                "intensity": intensity,
            }, provider_hint="hybrid")
            status, response = self._dispatch_action(action)
            if status != HTTPStatus.OK:
                self._json(status, response)
                return
            self._json(HTTPStatus.OK, {
                "status": "routed",
                **response,
                "label": "Generated movement",
                "prompt": command,
                "promptId": prompt_id,
                "promptForwarded": True,
                "duration": duration,
                "intensity": intensity,
                "rootMode": "locked",
                "rendererPackaged": True,
                "plannerAdvisoryUsed": False,
                "aiControlMode": ai_control_mode,
                "assetContextUsed": False,
            })
            return

        direct_catalog_id = direct_motion_catalog_id(command)
        asset_context_used = False
        planner_catalog_id = None
        plan = resolve_motion_command(command, planner_catalog_id)
        if plan is None:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {
                "error": "movement_not_in_catalog",
                "detail": (
                    "Try wave, explain, listen, jumping jacks, jog in place, "
                    "run in place, stretch, or a relaxed dance."
                ),
            })
            return

        public_plan = {
            key: plan[key]
            for key in ("catalogId", "label", "duration", "intensity", "rootMode", "rendererPackaged")
        }
        public_plan["plannerAdvisoryUsed"] = direct_catalog_id is None and planner_catalog_id is not None
        public_plan["aiControlMode"] = ai_control_mode
        public_plan["assetContextUsed"] = asset_context_used
        if not plan["rendererPackaged"] or not plan["routeBehavior"]:
            self._json(HTTPStatus.ACCEPTED, {
                "ok": True,
                "status": "staged",
                "live": False,
                "replay": False,
                **public_plan,
                "detail": (
                    f"{plan['label']} is in the reviewed ARDY catalog, but that motion "
                    "is not packaged in the current renderer. Nothing was sent to the avatar."
                ),
            })
            return

        action = normalize_action({
            "behavior": plan["routeBehavior"],
            "duration": plan["duration"],
            "intensity": plan["intensity"],
        }, provider_hint=motion_provider_for_ai_control_mode(ai_control_mode))
        status, response = self._dispatch_action(action)
        if status != HTTPStatus.OK:
            self._json(status, response)
            return
        self._json(HTTPStatus.OK, {"status": "routed", **response, **public_plan})

    def _motion_planner_suggestion(self, command: str) -> str | None:
        suggestion, _context_used = self._motion_planner_suggestion_with_context(
            command, None
        )
        return suggestion

    def _motion_planner_suggestion_with_context(
        self,
        command: str,
        runtime_context: dict[str, object] | None,
    ) -> tuple[str | None, bool]:
        if not self.server.llm_base or not self.server.motion_planner_model:
            return None, False
        context_used = runtime_context is not None
        user_content = command
        if runtime_context is not None:
            user_content = json.dumps(
                {"command": command, "runtimeContext": runtime_context},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        system_prompt = (
            ASSET_AWARE_MOTION_PLANNER_SYSTEM_PROMPT
            if runtime_context is not None
            else MOTION_PLANNER_SYSTEM_PROMPT
        )
        try:
            response = self._upstream_json(
                f"{self.server.llm_base}/v1/chat/completions",
                {
                    "model": self.server.motion_planner_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "chat_template_kwargs": {"enable_thinking": False},
                    "max_tokens": 32,
                    "temperature": 0.0,
                },
                timeout=30,
            )
            return (
                parse_planner_catalog_id(response["choices"][0]["message"]["content"]),
                context_used,
            )
        except (KeyError, IndexError, TypeError, ValueError, OSError, urllib.error.URLError, socket.timeout):
            return None, context_used

    def _wardrobe(self, payload: object) -> None:
        selection = normalize_wardrobe(payload)
        state = read_renderer_state(self.server.live_root)
        if (
            state is None
            or state["state"] != "ready"
            or state["activeCharacter"] != "casual-girl"
        ):
            self._json(HTTPStatus.CONFLICT, {
                "ok": False,
                "error": "casual_girl_renderer_not_active",
                "profileId": selection["profileId"],
                "detail": "Select Casual Girl and wait for her live stage before applying the outfit.",
            })
            return

        request = write_wardrobe_request(self.server.live_root, selection)
        deadline = time.monotonic() + 1.25
        while time.monotonic() < deadline:
            for filename in (WARDROBE_APPLIED_FILE, WARDROBE_REJECTED_FILE):
                receipt = read_wardrobe_receipt(self.server.live_root, filename)
                if receipt is None or receipt["requestId"] != request["requestId"]:
                    continue
                if receipt["status"] == "applied":
                    self._json(HTTPStatus.OK, {
                        "ok": True,
                        "status": "applied",
                        "profileId": receipt["profileId"],
                        "preset": receipt["preset"],
                        "slots": receipt["slots"],
                        "requestId": receipt["requestId"],
                    })
                else:
                    self._json(HTTPStatus.CONFLICT, {
                        "ok": False,
                        "status": "rejected",
                        "error": "wardrobe_runtime_rejected",
                        "profileId": selection["profileId"],
                        "requestId": request["requestId"],
                    })
                return
            time.sleep(0.05)

        self._json(HTTPStatus.ACCEPTED, {
            "ok": True,
            "status": "queued",
            "profileId": selection["profileId"],
            "preset": selection["preset"],
            "requestId": request["requestId"],
            "detail": "The reviewed outfit was queued for the live renderer.",
        })

    def _renderer_online(self) -> bool:
        try:
            status = self._upstream_json(
                f"{self.server.fay_base}/api/get-system-status?username=User", timeout=2,
            )
            return status.get("digital_human") is True
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def _upstream_json(self, url: str, payload: dict[str, Any] | None = None,
                       *, timeout: float) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != HTTPStatus.OK:
                raise ValueError("unexpected upstream status")
            body = response.read(1024 * 1024)
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("upstream JSON must be an object")
        return parsed

    def _media(self, name: str, head_only: bool = False) -> None:
        relative = MEDIA_MAP.get(name)
        if relative is None or PurePosixPath(name).name != name:
            self._json(HTTPStatus.NOT_FOUND, {"error": "media_not_found"}, head_only=head_only)
            return
        path = self.server.media_root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "media_not_found"}, head_only=head_only)
            return
        self._file(path, head_only=head_only, allow_range=True)

    def _static(self, requested: str, head_only: bool = False) -> None:
        decoded = urllib.parse.unquote(requested)
        relative = PurePosixPath(decoded.lstrip("/") or "index.html")
        if relative.is_absolute() or ".." in relative.parts:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=head_only)
            return
        path = self.server.dist.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            if path.suffix:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=head_only)
                return
            path = self.server.dist / "index.html"
        self._file(path, head_only=head_only, allow_range=False)

    def _file(self, path: Path, *, head_only: bool, allow_range: bool) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range") if allow_range else None
        if range_header:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
            if not match:
                self._empty(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if not 0 <= start <= end < size:
                self._empty(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {"Content-Length": str(length)}
        if allow_range:
            headers["Accept-Ranges"] = "bytes"
        if status == HTTPStatus.PARTIAL_CONTENT:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.send_response(status)
        self._security_headers(content_type, headers)
        self.end_headers()
        if not head_only:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

    def _json(self, status: HTTPStatus, payload: object, *, head_only: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self._security_headers("application/json; charset=utf-8", {"Content-Length": str(len(body))})
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._security_headers("text/plain; charset=utf-8", {"Content-Length": "0"})
        self.end_headers()

    def _security_headers(self, content_type: str, extra: dict[str, str]) -> None:
        self.send_header("Content-Type", content_type)
        for key, value in extra.items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), payment=(), usb=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; img-src 'self' blob:; media-src 'self'; "
            "object-src 'none'; script-src 'self'; style-src 'self'",
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", type=checked_bind_host)
    parser.add_argument("--port", type=int, default=8475)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--media-root", required=True, type=Path)
    parser.add_argument("--live-root", required=True, type=Path)
    parser.add_argument(
        "--config-workspace",
        type=Path,
        help="persistent private root for reviewed editable configuration",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="working UE5-Spark source root shown by the file workspace",
    )
    parser.add_argument("--fay-base", required=True)
    parser.add_argument("--ardy-base", default="http://127.0.0.1:8777")
    parser.add_argument("--llm-base")
    parser.add_argument("--llm-model", type=checked_model_name)
    parser.add_argument(
        "--motion-planner-model",
        type=checked_model_name,
        help="optional reviewed catalog classifier; defaults to --llm-model",
    )
    parser.add_argument(
        "--enable-service-control",
        action="store_true",
        help=(
            "allow the private controller to manage only the fixed "
            "ue5-spark-digital-human.target user unit"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be unprivileged")
    try:
        dist = safe_root(args.dist, "dist")
        media_root = safe_root(args.media_root, "media root")
        live_root = safe_private_root(args.live_root, "live root")
        if bool(args.config_workspace) != bool(args.project_root):
            raise ValueError(
                "config-workspace and project-root must be supplied together"
            )
        config_workspace = None
        if args.config_workspace is not None:
            workspace_root = safe_private_root(
                args.config_workspace, "config workspace"
            )
            project_root = safe_root(args.project_root, "project root")
            config_workspace = ConfigWorkspace(
                Path(__file__).resolve().parents[3],
                workspace_root,
                project_root=project_root,
            )
            configure_runtime_workspace(config_workspace)
        fay_base = checked_upstream(args.fay_base)
        ardy_base = checked_upstream(args.ardy_base, loopback_only=True)
        if bool(args.llm_base) != bool(args.llm_model):
            raise ValueError("llm-base and llm-model must be supplied together")
        if args.motion_planner_model and not args.llm_base:
            raise ValueError("motion-planner-model requires llm-base")
        llm_base = (
            checked_upstream(args.llm_base, loopback_only=True)
            if args.llm_base else None
        )
        if args.enable_service_control and (
            not SYSTEMCTL_PATH.is_file() or not os.access(SYSTEMCTL_PATH, os.X_OK)
        ):
            raise ValueError("fixed /usr/bin/systemctl is unavailable")
    except (ValueError, RuntimeError, argparse.ArgumentTypeError) as exc:
        raise SystemExit(str(exc)) from exc
    missing = [relative for relative in MEDIA_MAP.values() if not (media_root / relative).is_file()]
    if missing:
        raise SystemExit(f"missing private media: {', '.join(missing)}")
    server = ControllerServer(
        (args.host, args.port), dist, media_root, live_root, fay_base, ardy_base,
        llm_base, args.llm_model, args.motion_planner_model or args.llm_model,
        ProjectServiceManager(enabled=args.enable_service_control),
        config_workspace,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

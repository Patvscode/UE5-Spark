#!/usr/bin/env python3
"""Strictly verify the fixed Spark Fab review and offline-transition seals."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType


REVIEW_SCHEMA = 2
TRANSITION_SCHEMA = 2
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REVIEW_LOG_PATTERN = re.compile(r"review-session\.[A-Za-z0-9]+\.log")
DESCRIPTOR_TEMP_PATTERN = re.compile(
    r"\.FayFabAcquisition\.uproject\.[a-z0-9_]{8}"
)
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_PRIVATE_TREE_ENTRIES = 1_000_000

EXPECTED_MARKERS = {
    "MESHES_ASSET_COUNT": "19",
    "MAT_ASSET_COUNT": "31",
    "TEX_ASSET_COUNT": "97",
    "EXPECTED_PRODUCT_ASSETS": "OK",
    "ARKIT_EXPECTED_COUNT": "52",
    "ARKIT_BODY_FOUND_COUNT": "52",
    "ARKIT_COMPLETE_FOUND_COUNT": "52",
    "ARKIT_BODY_MISSING": "none",
    "ARKIT_COMPLETE_MISSING": "none",
    "EPIC_BODY_BONE_NAMES_EXPECTED": "21",
    "EPIC_BODY_BONE_NAMES_FOUND": "21",
    "EPIC_BODY_BONE_NAMES_MISSING": "none",
    "FULLY_UNCLOTHED": "disabled",
    "COMPLETE": "OK",
}

EXPECTED_IDENTIFIER_EVIDENCE = {
    "method": "raw_uasset_ascii_identifier_presence",
    "scope": "identifier_presence_only",
    "doesNotProve": [
        "morph_target_attachment",
        "bone_hierarchy",
        "deformation_quality",
        "retarget_compatibility",
    ],
}

REVIEW_KEYS = {
    "schema",
    "status",
    "inventoryScriptSha256",
    "inventoryLogPath",
    "logSha256",
    "contentManifestPath",
    "contentManifestSha256",
    "contentRootDigestSha256",
    "identifierEvidence",
    "markers",
}

TRANSITION_KEYS = {
    "schema",
    "status",
    "projectDescriptorPath",
    "acquisitionDescriptorSha256",
    "offlineDescriptorSha256",
    "acquisitionManifestPath",
    "acquisitionManifestSha256",
    "reviewReceiptPath",
    "reviewReceiptSha256",
    "contentManifestPath",
    "contentManifestSha256",
    "offlineManifestPath",
    "offlineManifestSha256",
    "recoveryCopy",
}

class TransitionVerificationError(RuntimeError):
    """Raised when any part of the sealed transition is not exact."""


@dataclass(frozen=True)
class Layout:
    workspace: Path
    engine: Path
    project: Path
    project_dir: Path
    acquisition_manifest: Path
    script_dir: Path
    acquisition_template: Path
    offline_template: Path
    non_content_tool: Path
    content_tool: Path
    inventory_script: Path
    private_logs: Path
    review_receipt: Path
    content_manifest: Path
    offline_manifest: Path
    transition_receipt: Path
    backup_parent: Path
    backup_generation: Path
    recovery_project: Path
    phase_lock: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise TransitionVerificationError(f"{label} is not one lowercase SHA-256")
    return value


def _lexical_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise TransitionVerificationError(f"{label} must be an absolute path")
    normalized = Path(os.path.normpath(os.fspath(path)))
    if normalized != path:
        raise TransitionVerificationError(f"{label} must be a normalized absolute path")
    return normalized


def _real_directory(path: Path, label: str) -> Path:
    path = _lexical_absolute(path, label)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise TransitionVerificationError(f"{label} is unavailable: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise TransitionVerificationError(f"{label} must be one real directory")
    return path.resolve(strict=True)


def _is_below(path: Path, parent: Path) -> bool:
    return path != parent and path.is_relative_to(parent)


def resolve_layout(
    workspace_input: Path,
    engine_input: Path,
    project_input: Path,
    acquisition_manifest_input: Path,
) -> Layout:
    workspace = _real_directory(workspace_input, "workspace")
    if workspace.stat().st_uid != os.geteuid():
        raise TransitionVerificationError("workspace must be owned by the invoking user")
    engine = _real_directory(engine_input, "Engine root")
    if not _is_below(engine, workspace):
        raise TransitionVerificationError("Engine root must remain below the workspace")

    expected_project = (
        workspace
        / "fab-acquisition-staging"
        / "FayFabAcquisition"
        / "FayFabAcquisition.uproject"
    )
    project_input = _lexical_absolute(project_input, "project descriptor")
    if project_input != expected_project:
        raise TransitionVerificationError(
            f"project descriptor must use the fixed path: {expected_project}"
        )
    _require_regular_no_symlink(project_input, "project descriptor")

    private_logs = workspace / "logs-private" / "fab-acquisition"
    expected_acquisition_manifest = private_logs / "before-import.json"
    acquisition_manifest_input = _lexical_absolute(
        acquisition_manifest_input, "acquisition baseline"
    )
    if acquisition_manifest_input != expected_acquisition_manifest:
        raise TransitionVerificationError(
            f"acquisition baseline must use the fixed path: {expected_acquisition_manifest}"
        )

    script_dir = Path(__file__).resolve(strict=True).parent
    backup_parent = workspace / "backups-private" / "fab-casual-girl"
    backup_generation = backup_parent / "acquisition-v1"
    return Layout(
        workspace=workspace,
        engine=engine,
        project=expected_project,
        project_dir=expected_project.parent,
        acquisition_manifest=expected_acquisition_manifest,
        script_dir=script_dir,
        acquisition_template=(
            script_dir
            / ".."
            / "staging"
            / "fab-acquisition-template"
            / "FayFabAcquisition.uproject"
        ).resolve(strict=True),
        offline_template=(
            script_dir
            / ".."
            / "staging"
            / "fab-offline-template"
            / "FayFabAcquisition.uproject"
        ).resolve(strict=True),
        non_content_tool=(script_dir / "fab-staging-manifest.py").resolve(strict=True),
        content_tool=(script_dir / "fab-content-manifest.py").resolve(strict=True),
        inventory_script=(script_dir / "inspect-fab-casual-girl.py").resolve(strict=True),
        private_logs=private_logs,
        review_receipt=private_logs / "casual-girl-inventory.json",
        content_manifest=private_logs / "casual-girl-content-before-migration.json",
        offline_manifest=private_logs / "offline-before-migration.json",
        transition_receipt=private_logs / "offline-transition.json",
        backup_parent=backup_parent,
        backup_generation=backup_generation,
        recovery_project=backup_generation / "FayFabAcquisition",
        phase_lock=workspace / "state" / "fab-phase" / "operation.lock",
    )


def _require_regular_no_symlink(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise TransitionVerificationError(f"{label} is unavailable: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise TransitionVerificationError(f"{label} must be one real regular file")
    return metadata


def _require_owned_private_file(path: Path, label: str) -> None:
    metadata = _require_regular_no_symlink(path, label)
    if metadata.st_uid != os.geteuid():
        raise TransitionVerificationError(f"{label} must be owned by the invoking user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TransitionVerificationError(f"{label} must not be group/world accessible")


def _validate_private_chain(layout: Layout, path: Path, label: str) -> None:
    if not _is_below(path, layout.workspace):
        raise TransitionVerificationError(f"{label} escaped the workspace")
    relative = path.relative_to(layout.workspace)
    if not relative.parts or relative.parts[0] not in {
        "logs-private",
        "backups-private",
        "state",
    }:
        raise TransitionVerificationError(f"{label} is not below a fixed private root")
    current = layout.workspace
    for index, component in enumerate(relative.parts):
        current /= component
        try:
            metadata = current.lstat()
        except OSError as error:
            raise TransitionVerificationError(f"{label} is unavailable: {current}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise TransitionVerificationError(f"{label} contains a symlink: {current}")
        if metadata.st_uid != os.geteuid():
            raise TransitionVerificationError(
                f"{label} contains a path not owned by the invoking user: {current}"
            )
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise TransitionVerificationError(
                f"{label} contains a non-directory component: {current}"
            )
        # The workspace's shared state/log/backup roots may intentionally serve
        # other project services. The dedicated Fab subroot (index 1) is the
        # confidentiality boundary and must be mode 0700-equivalent.
        if index == 1 and stat.S_ISDIR(metadata.st_mode):
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise TransitionVerificationError(
                    f"private root is group/world accessible: {current}"
                )


def _validate_owned_tree(path: Path, label: str) -> None:
    try:
        root_metadata = path.lstat()
    except OSError as error:
        raise TransitionVerificationError(f"{label} is unavailable: {path}") from error
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise TransitionVerificationError(f"{label} must be one real directory")
    if root_metadata.st_uid != os.geteuid():
        raise TransitionVerificationError(f"{label} must be user-owned")
    entry_count = 0
    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(directory_names) + tuple(file_names):
            child = directory_path / name
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise TransitionVerificationError(f"{label} contains a symlink: {child}")
            if metadata.st_uid != os.geteuid():
                raise TransitionVerificationError(
                    f"{label} contains a path not owned by the invoking user: {child}"
                )
        entry_count += len(directory_names) + len(file_names)
        if entry_count > MAX_PRIVATE_TREE_ENTRIES:
            raise TransitionVerificationError(f"{label} contains too many entries")


def recover_descriptor_temps(layout: Layout) -> int:
    """Remove only verified residue from an interrupted atomic descriptor swap."""
    project_metadata = layout.project_dir.lstat()
    if stat.S_ISLNK(project_metadata.st_mode) or not stat.S_ISDIR(project_metadata.st_mode):
        raise TransitionVerificationError("project descriptor parent is not one real directory")
    if project_metadata.st_uid != os.geteuid():
        raise TransitionVerificationError("project descriptor parent is not user-owned")
    descriptor_bytes = layout.project.read_bytes()
    acquisition_bytes = layout.acquisition_template.read_bytes()
    offline_bytes = layout.offline_template.read_bytes()
    known_payloads = (b"", acquisition_bytes, offline_bytes)
    if descriptor_bytes not in known_payloads[1:]:
        raise TransitionVerificationError(
            "project descriptor is unknown; refusing descriptor-temp recovery"
        )

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(layout.project_dir, directory_flags)
    removed = 0
    try:
        with os.scandir(layout.project_dir) as iterator:
            entries = tuple(iterator)
        for entry in entries:
            if DESCRIPTOR_TEMP_PATTERN.fullmatch(entry.name) is None:
                continue
            metadata = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise TransitionVerificationError(
                    f"descriptor-temp residue is not a real user-owned file: {entry.name}"
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(entry.name, flags, dir_fd=directory_descriptor)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_uid != os.geteuid()
                    or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                ):
                    raise TransitionVerificationError(
                        f"descriptor-temp residue changed while opening it: {entry.name}"
                    )
                maximum = max(len(payload) for payload in known_payloads)
                chunks: list[bytes] = []
                remaining = maximum + 1
                while remaining > 0:
                    chunk = os.read(descriptor, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if b"".join(chunks) not in known_payloads:
                    raise TransitionVerificationError(
                        f"descriptor-temp residue has unknown contents: {entry.name}"
                    )
            finally:
                os.close(descriptor)
            current = os.stat(
                entry.name, dir_fd=directory_descriptor, follow_symlinks=False
            )
            if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise TransitionVerificationError(
                    f"descriptor-temp residue changed before removal: {entry.name}"
                )
            os.unlink(entry.name, dir_fd=directory_descriptor)
            removed += 1
        if removed:
            os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return removed


def _load_json(path: Path, label: str) -> dict[str, object]:
    metadata = _require_regular_no_symlink(path, label)
    if metadata.st_size > MAX_RECEIPT_BYTES:
        raise TransitionVerificationError(f"{label} is unexpectedly large")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise TransitionVerificationError(
                    f"{label} contains a duplicate JSON key: {key}"
                )
            result[key] = item
        return result
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TransitionVerificationError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise TransitionVerificationError(f"{label} must contain one JSON object")
    return value


def _load_tool(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TransitionVerificationError(f"could not load required verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_manifest_tools(
    layout: Layout, root: Path, non_content_manifest: Path
) -> None:
    non_content = _load_tool(layout.non_content_tool, "_fab_staging_manifest")
    content = _load_tool(layout.content_tool, "_fab_content_manifest")
    try:
        non_content.verify(root, non_content_manifest)
        content.verify(root, layout.content_manifest)
    except (OSError, RuntimeError) as error:
        raise TransitionVerificationError(str(error)) from error


def _verify_content_manifest(layout: Layout, root: Path) -> dict[str, object]:
    content = _load_tool(layout.content_tool, "_fab_content_manifest_review")
    try:
        content.verify(root, layout.content_manifest)
    except (OSError, RuntimeError) as error:
        raise TransitionVerificationError(str(error)) from error
    value = _load_json(layout.content_manifest, "Content manifest")
    if (
        type(value.get("schema")) is not int
        or value.get("schema") != 2
        or not isinstance(value.get("rootDigestSha256"), str)
    ):
        raise TransitionVerificationError("Content manifest schema/root digest is invalid")
    _require_sha256(value["rootDigestSha256"], "Content root digest")
    return value


def _verify_review_receipt(
    layout: Layout, content_value: dict[str, object]
) -> dict[str, object]:
    _validate_private_chain(layout, layout.review_receipt, "review receipt")
    _require_owned_private_file(layout.review_receipt, "review receipt")
    value = _load_json(layout.review_receipt, "review receipt")
    if set(value) != REVIEW_KEYS:
        raise TransitionVerificationError("review receipt has an unsupported exact schema")
    if type(value.get("schema")) is not int or value.get("schema") != REVIEW_SCHEMA:
        raise TransitionVerificationError("review receipt schema is unsupported")
    if value.get("status") != "passed":
        raise TransitionVerificationError("review receipt did not pass")
    if value.get("markers") != EXPECTED_MARKERS:
        raise TransitionVerificationError("review receipt markers are not exact")
    if value.get("identifierEvidence") != EXPECTED_IDENTIFIER_EVIDENCE:
        raise TransitionVerificationError("review receipt evidence boundary is not exact")

    expected_content_path = str(layout.content_manifest)
    if value.get("contentManifestPath") != expected_content_path:
        raise TransitionVerificationError("review receipt names an unexpected Content manifest")
    content_hash = _require_sha256(
        value.get("contentManifestSha256"), "review Content-manifest hash"
    )
    if content_hash != _sha256(layout.content_manifest):
        raise TransitionVerificationError("review receipt does not bind the current Content manifest")
    root_digest = _require_sha256(
        value.get("contentRootDigestSha256"), "review Content-root digest"
    )
    if root_digest != content_value.get("rootDigestSha256"):
        raise TransitionVerificationError("review receipt Content-root digest is stale")

    script_hash = _require_sha256(
        value.get("inventoryScriptSha256"), "review inventory-script hash"
    )
    if script_hash != _sha256(layout.inventory_script):
        raise TransitionVerificationError("review receipt inventory script is stale")

    raw_log_path = value.get("inventoryLogPath")
    if not isinstance(raw_log_path, str):
        raise TransitionVerificationError("review receipt inventory log path is invalid")
    log_path = _lexical_absolute(Path(raw_log_path), "review inventory log")
    if log_path.parent != layout.private_logs or REVIEW_LOG_PATTERN.fullmatch(log_path.name) is None:
        raise TransitionVerificationError("review receipt inventory log is outside its fixed location")
    _validate_private_chain(layout, log_path, "review inventory log")
    _require_owned_private_file(log_path, "review inventory log")
    log_hash = _require_sha256(value.get("logSha256"), "review inventory-log hash")
    if log_hash != _sha256(log_path):
        raise TransitionVerificationError("review inventory log differs from its receipt")
    return value


def _validate_common_private_inputs(layout: Layout) -> None:
    for path, label in (
        (layout.acquisition_manifest, "acquisition baseline"),
        (layout.content_manifest, "Content manifest"),
        (layout.phase_lock, "Fab phase lock"),
    ):
        _validate_private_chain(layout, path, label)
        _require_owned_private_file(path, label)
    for path, label in (
        (layout.acquisition_template, "acquisition descriptor template"),
        (layout.offline_template, "offline descriptor template"),
        (layout.non_content_tool, "non-content verifier"),
        (layout.content_tool, "Content verifier"),
        (layout.inventory_script, "inventory script"),
    ):
        _require_regular_no_symlink(path, label)


def verify_review(layout: Layout) -> dict[str, object]:
    """Verify the exact acquisition baseline, current Content, and bound review."""
    _validate_common_private_inputs(layout)
    if layout.project.read_bytes() != layout.acquisition_template.read_bytes():
        raise TransitionVerificationError("project is not in the exact acquisition phase")
    content_value = _verify_content_manifest(layout, layout.project_dir)
    non_content = _load_tool(layout.non_content_tool, "_fab_review_staging_manifest")
    try:
        non_content.verify(layout.project_dir, layout.acquisition_manifest)
    except (OSError, RuntimeError) as error:
        raise TransitionVerificationError(str(error)) from error
    review = _verify_review_receipt(layout, content_value)
    return review


def expected_transition_payload(layout: Layout) -> dict[str, object]:
    return {
        "schema": TRANSITION_SCHEMA,
        "status": "passed",
        "projectDescriptorPath": str(layout.project),
        "acquisitionDescriptorSha256": _sha256(layout.acquisition_template),
        "offlineDescriptorSha256": _sha256(layout.offline_template),
        "acquisitionManifestPath": str(layout.acquisition_manifest),
        "acquisitionManifestSha256": _sha256(layout.acquisition_manifest),
        "reviewReceiptPath": str(layout.review_receipt),
        "reviewReceiptSha256": _sha256(layout.review_receipt),
        "contentManifestPath": str(layout.content_manifest),
        "contentManifestSha256": _sha256(layout.content_manifest),
        "offlineManifestPath": str(layout.offline_manifest),
        "offlineManifestSha256": _sha256(layout.offline_manifest),
        "recoveryCopy": str(layout.recovery_project),
    }


def verify_transition(layout: Layout) -> None:
    """Verify the complete offline state and its reusable recovery snapshot."""
    _validate_common_private_inputs(layout)
    for path, label in (
        (layout.offline_manifest, "offline non-content manifest"),
        (layout.transition_receipt, "transition receipt"),
    ):
        _validate_private_chain(layout, path, label)
        _require_owned_private_file(path, label)
    for path, label in (
        (layout.backup_parent, "recovery parent"),
        (layout.backup_generation, "recovery generation"),
        (layout.recovery_project, "recovery project"),
    ):
        _validate_private_chain(layout, path, label)
    _validate_owned_tree(layout.backup_generation, "recovery generation")

    if layout.project.read_bytes() != layout.offline_template.read_bytes():
        raise TransitionVerificationError("project is not in the exact offline phase")
    content_value = _verify_content_manifest(layout, layout.project_dir)
    _verify_manifest_tools(layout, layout.project_dir, layout.offline_manifest)
    _verify_review_receipt(layout, content_value)
    recovery_descriptor = layout.recovery_project / "FayFabAcquisition.uproject"
    if recovery_descriptor.read_bytes() != layout.acquisition_template.read_bytes():
        raise TransitionVerificationError("recovery descriptor is not the acquisition descriptor")
    _verify_manifest_tools(layout, layout.recovery_project, layout.acquisition_manifest)

    receipt = _load_json(layout.transition_receipt, "transition receipt")
    if set(receipt) != TRANSITION_KEYS:
        raise TransitionVerificationError("transition receipt has an unsupported exact schema")
    expected = expected_transition_payload(layout)
    if receipt != expected:
        raise TransitionVerificationError("transition receipt paths or hashes are stale")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--acquisition-manifest", required=True, type=Path)
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="verify the acquisition/review seal before mutating the descriptor",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        layout = resolve_layout(
            arguments.workspace,
            arguments.engine,
            arguments.project,
            arguments.acquisition_manifest,
        )
        if arguments.review_only:
            verify_review(layout)
            print("Fab acquisition review receipt and Content binding verified")
        else:
            verify_transition(layout)
            print("Fab offline transition and acquisition recovery copy verified")
    except (OSError, TransitionVerificationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

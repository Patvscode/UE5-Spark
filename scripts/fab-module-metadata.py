#!/usr/bin/env python3
"""Create one UBT-authored Fab module manifest with the Editor's BuildId.

An Unreal ``-Module=Fab`` build intentionally skips target-wide metadata so it
does not rebuild thousands of unrelated Editor modules.  This helper reduces
UBT's generated ``EngineMetadata.json`` to the single reviewed Fab entry and
pins the already-built Editor's BuildId.  UnrealBuildTool's ``WriteMetadata``
mode consumes the result and writes the normal ``UnrealEditor.modules`` file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


MAX_JSON_BYTES = 64 * 1024 * 1024


class FabMetadataError(RuntimeError):
    pass


def _load_json(path_input: Path) -> tuple[Path, dict[str, object]]:
    if path_input.is_symlink():
        raise FabMetadataError(f"JSON input is a symlink: {path_input}")
    path = path_input.resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise FabMetadataError(f"JSON input is not one bounded regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FabMetadataError(f"JSON input is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise FabMetadataError(f"JSON input is not an object: {path}")
    return path, value


def build_reduced_metadata(
    source_input: Path,
    manifest_input: Path,
    binary_input: Path,
    version_input: Path,
) -> dict[str, object]:
    source_path, source = _load_json(source_input)
    version_path, engine_version = _load_json(version_input)

    if binary_input.is_symlink():
        raise FabMetadataError("Fab binary must not be a symlink")
    binary_path = binary_input.resolve(strict=True)
    if not binary_path.is_file() or binary_path.name != "libUnrealEditor-Fab.so":
        raise FabMetadataError("Fab binary path is unexpected")

    if manifest_input.is_symlink():
        raise FabMetadataError("Fab manifest must not be a symlink")
    manifest_parent = manifest_input.parent.resolve(strict=True)
    manifest_path = manifest_parent / manifest_input.name
    if manifest_path.name != "UnrealEditor.modules" or manifest_parent != binary_path.parent:
        raise FabMetadataError("Fab manifest path is unexpected")

    manifests = source.get("FileToManifest")
    manifest_key = str(manifest_path)
    if not isinstance(manifests, dict):
        raise FabMetadataError(
            f"UBT metadata does not contain the Fab manifest: {source_path}"
        )
    matching_entries: list[object] = []
    for candidate_key, candidate_entry in manifests.items():
        if not isinstance(candidate_key, str):
            continue
        candidate = Path(candidate_key)
        try:
            resolved_candidate = candidate.parent.resolve(strict=True) / candidate.name
        except OSError:
            continue
        if resolved_candidate == manifest_path:
            matching_entries.append(candidate_entry)
    if len(matching_entries) != 1:
        raise FabMetadataError(
            f"UBT metadata does not contain exactly one Fab manifest: {source_path}"
        )
    entry = matching_entries[0]
    expected_entry = {
        "BuildId": "",
        "ModuleNameToFileName": {"Fab": binary_path.name},
        "LibraryDependencies": {},
    }
    if entry != expected_entry:
        raise FabMetadataError("UBT emitted an unexpected Fab manifest contract")
    source_version_path = source.get("VersionFile")
    if (
        not isinstance(source_version_path, str)
        or Path(source_version_path).resolve(strict=True) != version_path
    ):
        raise FabMetadataError("UBT metadata references an unexpected Editor version file")

    build_id = engine_version.get("BuildId")
    if not isinstance(build_id, str) or not build_id.strip():
        raise FabMetadataError("the existing Editor BuildId is missing")
    source_version = source.get("Version")
    if not isinstance(source_version, dict):
        raise FabMetadataError("UBT metadata does not contain an Engine version object")
    pinned_version = dict(source_version)
    pinned_version["BuildId"] = build_id

    # VersionFile is deliberately null. WriteMetadata uses pinned_version's
    # explicit BuildId but cannot rewrite the installed Editor version file.
    return {
        "ProjectFile": None,
        "VersionFile": None,
        "Version": pinned_version,
        "ReceiptFile": None,
        "Receipt": None,
        "FileToManifest": {manifest_key: entry},
        "MergeModules": False,
        "FileToLoadOrderManifest": {},
    }


def write_new_private(path_input: Path, value: dict[str, object]) -> Path:
    if path_input.exists() or path_input.is_symlink():
        raise FabMetadataError("metadata output already exists")
    parent = path_input.parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_symlink():
        raise FabMetadataError("metadata output parent is unsafe")
    path = parent / path_input.name
    payload = (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_metadata", type=Path)
    parser.add_argument("output_metadata", type=Path)
    parser.add_argument("fab_manifest", type=Path)
    parser.add_argument("fab_binary", type=Path)
    parser.add_argument("editor_version", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        reduced = build_reduced_metadata(
            arguments.source_metadata,
            arguments.fab_manifest,
            arguments.fab_binary,
            arguments.editor_version,
        )
        output = write_new_private(arguments.output_metadata, reduced)
        print(f"prepared pinned Fab metadata: {output}")
    except FabMetadataError as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

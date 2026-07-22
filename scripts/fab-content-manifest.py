#!/usr/bin/env python3
"""Create or verify a private SHA-256 manifest of staged Unreal content."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


SCHEMA = 1
ALLOWED_SUFFIXES = {".uasset", ".umap", ".ubulk", ".uexp", ".uptnl"}
MAX_FILES = 100_000


class ContentManifestError(RuntimeError):
    pass


def _safe_project(path: Path) -> tuple[Path, Path]:
    if path.is_symlink():
        raise ContentManifestError("project root must not be a symlink")
    project = path.resolve(strict=True)
    if not project.is_dir():
        raise ContentManifestError("project root must be a directory")
    descriptors = tuple(project.glob("*.uproject"))
    if len(descriptors) != 1 or descriptors[0].is_symlink():
        raise ContentManifestError("project must contain exactly one real .uproject")
    content = project / "Content"
    if content.is_symlink() or not content.is_dir():
        raise ContentManifestError("project Content must be one real directory")
    return project, content


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _walk_error(error: OSError) -> None:
    location = getattr(error, "filename", None) or "unknown path"
    raise ContentManifestError(f"could not inspect Content: {location}") from error


def snapshot(project_input: Path) -> dict[str, object]:
    project, content = _safe_project(project_input)
    records: dict[str, dict[str, object]] = {}
    for directory, directory_names, file_names in os.walk(
        content, followlinks=False, onerror=_walk_error
    ):
        directory_path = Path(directory)
        directory_names.sort()
        for name in tuple(directory_names):
            child = directory_path / name
            if child.is_symlink():
                raise ContentManifestError(
                    f"Content contains a symlinked directory: {child.relative_to(content)}"
                )
        for name in sorted(file_names):
            child = directory_path / name
            relative = child.relative_to(content).as_posix()
            if child.is_symlink() or not child.is_file():
                raise ContentManifestError(
                    f"Content contains a non-regular file: {relative}"
                )
            if child.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ContentManifestError(
                    f"Content contains an unexpected file type: {relative}"
                )
            metadata = child.stat()
            records[relative] = {
                "mode": stat.S_IMODE(metadata.st_mode),
                "size": metadata.st_size,
                "sha256": _sha256(child),
            }
            if len(records) > MAX_FILES:
                raise ContentManifestError("Content contains too many files")
    if not records:
        raise ContentManifestError("Content is empty")
    return {
        "schema": SCHEMA,
        "projectRootName": project.name,
        "contentDirectory": "Content",
        "allowedSuffixes": sorted(ALLOWED_SUFFIXES),
        "files": records,
    }


def _write_new_private(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ContentManifestError("manifest output already exists")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ContentManifestError("manifest parent must be one existing real directory")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise ContentManifestError("manifest must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > 64 * 1024 * 1024:
        raise ContentManifestError("manifest must be one bounded regular file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContentManifestError("manifest is not valid UTF-8 JSON") from error
    expected_keys = {
        "schema",
        "projectRootName",
        "contentDirectory",
        "allowedSuffixes",
        "files",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("schema") != SCHEMA
        or value.get("contentDirectory") != "Content"
        or value.get("allowedSuffixes") != sorted(ALLOWED_SUFFIXES)
        or not isinstance(value.get("files"), dict)
    ):
        raise ContentManifestError("manifest envelope is unsupported")
    return value


def verify(project: Path, manifest_path: Path) -> None:
    expected = _load(manifest_path)
    actual = snapshot(project)
    if expected == actual:
        return
    expected_files = expected.get("files", {})
    actual_files = actual.get("files", {})
    if not isinstance(expected_files, dict) or not isinstance(actual_files, dict):
        raise ContentManifestError("manifest file table is malformed")
    added = sorted(set(actual_files).difference(expected_files))
    removed = sorted(set(expected_files).difference(actual_files))
    changed = sorted(
        path
        for path in set(expected_files).intersection(actual_files)
        if expected_files[path] != actual_files[path]
    )
    raise ContentManifestError(
        "staged Content differs from its seal: "
        f"added={added[:10]}; removed={removed[:10]}; changed={changed[:10]}"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("project", type=Path)
    create.add_argument("manifest", type=Path)
    check = subparsers.add_parser("verify")
    check.add_argument("project", type=Path)
    check.add_argument("manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.command == "create":
            _write_new_private(arguments.manifest, snapshot(arguments.project))
            print(f"Created private Content manifest: {arguments.manifest}")
        else:
            verify(arguments.project, arguments.manifest)
            print("Staged Content matches its private manifest")
    except (ContentManifestError, OSError) as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

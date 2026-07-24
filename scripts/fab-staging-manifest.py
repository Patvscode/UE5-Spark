#!/usr/bin/env python3
"""Seal or verify the non-content files in a disposable Fab staging project.

Fab asset packs are expected to add Unreal assets below ``Content``.  Changes
to project configuration, plugins, source, binaries, or the .uproject are not
accepted implicitly.  Create the manifest after the staging Editor and Fab
plugin have been built, verify it immediately after Add to Project, and keep
the manifest outside the staging project in a private logs directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


SCHEMA = 1
IGNORED_TOP_LEVEL = {
    ".git",
    ".vs",
    "Content",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
}
MAX_FILES = 100_000
MAX_IGNORED_ENTRIES = 1_000_000


class StagingManifestError(RuntimeError):
    pass


def _safe_root(path: Path) -> Path:
    if path.is_symlink():
        raise StagingManifestError("staging project root must not be a symlink")
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise StagingManifestError("staging project root must be a directory")
    projects = tuple(root.glob("*.uproject"))
    if len(projects) != 1 or projects[0].is_symlink():
        raise StagingManifestError("staging root must contain exactly one real .uproject")
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _walk_error(error: OSError) -> None:
    location = getattr(error, "filename", None) or "unknown path"
    raise StagingManifestError(f"could not inspect staging tree: {location}") from error


def _validate_ignored_trees(root: Path) -> None:
    """Reject write escapes without hashing generated or licensed content."""
    entry_count = 0
    for name in sorted(IGNORED_TOP_LEVEL):
        ignored_root = root / name
        if ignored_root.is_symlink():
            raise StagingManifestError(f"ignored top-level path is a symlink: {name}")
        if not ignored_root.exists():
            continue
        if not ignored_root.is_dir():
            raise StagingManifestError(f"ignored top-level path is not a directory: {name}")
        for directory, directory_names, file_names in os.walk(
            ignored_root, followlinks=False, onerror=_walk_error
        ):
            directory_path = Path(directory)
            for child_name in tuple(directory_names):
                child = directory_path / child_name
                if child.is_symlink():
                    raise StagingManifestError(
                        f"ignored tree contains a symlink: {child.relative_to(root)}"
                    )
            for child_name in file_names:
                child = directory_path / child_name
                if child.is_symlink() or not child.is_file():
                    raise StagingManifestError(
                        "ignored tree contains a non-regular file: "
                        f"{child.relative_to(root)}"
                    )
            entry_count += len(directory_names) + len(file_names)
            if entry_count > MAX_IGNORED_ENTRIES:
                raise StagingManifestError("ignored staging trees contain too many entries")


def snapshot(root_input: Path) -> dict[str, object]:
    root = _safe_root(root_input)
    _validate_ignored_trees(root)
    records: dict[str, dict[str, object]] = {}
    for directory, directory_names, file_names in os.walk(
        root, followlinks=False, onerror=_walk_error
    ):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        if relative_directory == Path("."):
            directory_names[:] = sorted(
                name for name in directory_names if name not in IGNORED_TOP_LEVEL
            )
        else:
            directory_names.sort()
        for name in tuple(directory_names):
            candidate = directory_path / name
            if candidate.is_symlink():
                raise StagingManifestError(
                    f"non-content tree contains a symlink: {candidate.relative_to(root)}"
                )
        for name in sorted(file_names):
            candidate = directory_path / name
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise StagingManifestError(
                    f"non-content tree contains a symlink: {relative}"
                )
            if not candidate.is_file():
                raise StagingManifestError(
                    f"non-content tree contains a non-regular file: {relative}"
                )
            metadata = candidate.stat()
            records[relative] = {
                "mode": stat.S_IMODE(metadata.st_mode),
                "size": metadata.st_size,
                "sha256": _sha256(candidate),
            }
            if len(records) > MAX_FILES:
                raise StagingManifestError("staging project has too many non-content files")
    return {
        "schema": SCHEMA,
        "projectRootName": root.name,
        "uproject": next(root.glob("*.uproject")).name,
        "ignoredTopLevel": sorted(IGNORED_TOP_LEVEL),
        "files": records,
    }


def _write_new_private(path: Path, value: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise StagingManifestError("manifest output already exists")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise StagingManifestError("manifest parent must be an existing real directory")
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
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


def _load_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise StagingManifestError("manifest must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > 64 * 1024 * 1024:
        raise StagingManifestError("manifest must be one bounded regular file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagingManifestError("manifest is not valid UTF-8 JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema",
            "projectRootName",
            "uproject",
            "ignoredTopLevel",
            "files",
        }
        or value.get("schema") != SCHEMA
        or value.get("ignoredTopLevel") != sorted(IGNORED_TOP_LEVEL)
        or not isinstance(value.get("files"), dict)
    ):
        raise StagingManifestError("manifest envelope is unsupported")
    return value


def verify(root: Path, manifest_path: Path) -> None:
    expected = _load_manifest(manifest_path)
    actual = snapshot(root)
    if expected == actual:
        return
    expected_files = expected.get("files", {})
    actual_files = actual.get("files", {})
    if not isinstance(expected_files, dict) or not isinstance(actual_files, dict):
        raise StagingManifestError("manifest file table is malformed")
    added = sorted(set(actual_files).difference(expected_files))
    removed = sorted(set(expected_files).difference(actual_files))
    changed = sorted(
        path
        for path in set(expected_files).intersection(actual_files)
        if expected_files[path] != actual_files[path]
    )
    detail = "; ".join(
        (
            f"added={added[:10]}",
            f"removed={removed[:10]}",
            f"changed={changed[:10]}",
        )
    )
    raise StagingManifestError(f"Fab changed non-content project state: {detail}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("project_root", type=Path)
    create.add_argument("manifest", type=Path)
    check = subparsers.add_parser("verify")
    check.add_argument("project_root", type=Path)
    check.add_argument("manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.command == "create":
            value = snapshot(arguments.project_root)
            manifest = arguments.manifest.absolute()
            root = _safe_root(arguments.project_root)
            if manifest == root or manifest.is_relative_to(root):
                raise StagingManifestError("manifest must remain outside staging root")
            _write_new_private(manifest, value)
            print(f"sealed Fab staging non-content state: {manifest}")
        else:
            verify(arguments.project_root, arguments.manifest)
            print("Fab staging non-content state is unchanged")
    except StagingManifestError as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

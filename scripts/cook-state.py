#!/usr/bin/env python3
"""Record or validate the exact inputs and output of the Spark FEX cook."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 2
STATE_NAME = "fay-avatar-linuxarm64-cook.json"
PENDING_STATE_NAME = "fay-avatar-linuxarm64-cook.inputs.json"
IGNORED_PROJECT_DIRECTORIES = {
    ".git",
    "Binaries",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
    "StagedBuilds",
    "__pycache__",
}
CHUNK_BYTES = 4 * 1024 * 1024


class CookStateError(RuntimeError):
    pass


def hash_regular_file(path: Path) -> tuple[int, str]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise CookStateError("a file changed while its cook fingerprint was being calculated")
    return after.st_size, digest.hexdigest()


def add_path_fingerprint(digest: hashlib._Hash, label: str, path: Path) -> tuple[int, int]:
    if path.is_symlink():
        raise CookStateError(f"fingerprint input must not be a symlink: {label}")
    if not path.is_file():
        raise CookStateError(f"fingerprint input is not a regular file: {label}")

    size, file_digest = hash_regular_file(path)
    digest.update(f"F\0{label}\0{size}\0{file_digest}\0".encode("utf-8"))
    return 1, size


def add_tree_fingerprint(
    digest: hashlib._Hash,
    root: Path,
    label: str,
    ignored_directories: set[str] | None = None,
) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    if not root.is_dir():
        raise CookStateError(f"fingerprint tree is not a directory: {label}")

    ignored = ignored_directories or set()
    file_count = 0
    byte_count = 0
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_root)
        symlink_directories = [
            name for name in directory_names if (current / name).is_symlink()
        ]
        if symlink_directories:
            raise CookStateError(
                f"fingerprint tree contains a symlinked directory: {label}"
            )
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in ignored
        )
        for name in sorted(file_names):
            path = current / name
            relative = path.relative_to(root).as_posix()
            added_files, added_bytes = add_path_fingerprint(
                digest,
                f"{label}/{relative}",
                path,
            )
            file_count += added_files
            byte_count += added_bytes
    return file_count, byte_count


def project_input_fingerprint(project: Path, engine: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0

    added_files, added_bytes = add_path_fingerprint(
        digest,
        f"project/{project.name}",
        project,
    )
    file_count += added_files
    byte_count += added_bytes

    project_dir = project.parent
    for directory_name in ("Config", "Content", "Plugins", "Source"):
        added_files, added_bytes = add_tree_fingerprint(
            digest,
            project_dir / directory_name,
            f"project/{directory_name}",
            IGNORED_PROJECT_DIRECTORIES,
        )
        file_count += added_files
        byte_count += added_bytes

    engine_files = (
        engine / "Engine/Build/Build.version",
        engine / "Engine/Binaries/Linux/UnrealEditor.version",
        engine / "Engine/Binaries/Linux/UnrealEditor.modules",
        engine
        / "Engine/Plugins/Animation/AudioDrivenAnimation/StreamingADA/Content/"
        "xsada_face_base_fp32_v2_0_0.uasset",
    )
    for path in engine_files:
        if not path.is_file():
            raise CookStateError(f"required Engine cook input is missing: {path.name}")
        added_files, added_bytes = add_path_fingerprint(
            digest,
            f"engine/{path.relative_to(engine).as_posix()}",
            path,
        )
        file_count += added_files
        byte_count += added_bytes

    return {
        "sha256": digest.hexdigest(),
        "files": file_count,
        "bytes": byte_count,
    }


def cook_output_fingerprint(cook_root: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    file_count, byte_count = add_tree_fingerprint(digest, cook_root, "cook")
    if file_count == 0:
        raise CookStateError("the LinuxArm64 cook contains no files")
    return {
        "sha256": digest.hexdigest(),
        "files": file_count,
        "bytes": byte_count,
    }


def lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without following symlinks."""
    return Path(os.path.abspath(os.fspath(path)))


def reject_symlink_components(path: Path, anchor: Path, label: str) -> None:
    if not path.is_relative_to(anchor):
        raise CookStateError(f"{label} must remain inside the cooker workspace")
    current = anchor
    for component in path.relative_to(anchor).parts:
        current /= component
        if current.is_symlink():
            raise CookStateError(f"{label} contains a symlinked path component")


def canonical_inputs(
    args: argparse.Namespace,
    require_cook_root: bool,
) -> tuple[Path, Path, Path, Path]:
    workspace = args.workspace.resolve(strict=True)
    engine = args.engine.resolve(strict=True)
    project_input = lexical_absolute(args.project)
    if project_input.is_symlink():
        raise CookStateError("project must not be a symlink")
    project = project_input.resolve(strict=True)
    if not workspace.is_dir() or not engine.is_dir():
        raise CookStateError("workspace and Engine must be directories")
    if not project.is_file() or project.suffix != ".uproject":
        raise CookStateError("project must be an existing .uproject file")
    if not engine.is_relative_to(workspace) or not project.is_relative_to(workspace):
        raise CookStateError("Engine and project must remain inside the cooker workspace")
    state_directory = workspace / "state"
    reject_symlink_components(state_directory, workspace, "state directory")

    expected_cook_root = lexical_absolute(
        project.parent / "Saved/Cooked/LinuxArm64"
    )
    cook_root = lexical_absolute(args.cook_root)
    if cook_root != expected_cook_root:
        raise CookStateError("cook root does not match the project's LinuxArm64 cook directory")
    reject_symlink_components(cook_root, workspace, "cook root")
    if require_cook_root and not cook_root.is_dir():
        raise CookStateError("cook root must be an existing directory")
    if cook_root.exists() and not cook_root.is_dir():
        raise CookStateError("cook root must be a directory when it exists")
    return workspace, engine, project, cook_root


def calculate_state(
    workspace: Path,
    engine: Path,
    project: Path,
    cook_root: Path,
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "engine": str(engine),
        "project": str(project),
        "cook_root": str(cook_root),
        "inputs": project_input_fingerprint(project, engine),
        "cook": cook_output_fingerprint(cook_root),
    }


def calculate_input_state(
    workspace: Path,
    engine: Path,
    project: Path,
    cook_root: Path,
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "engine": str(engine),
        "project": str(project),
        "cook_root": str(cook_root),
        "inputs": project_input_fingerprint(project, engine),
    }


def require_same_inputs(
    recorded: dict[str, object],
    current: dict[str, object],
) -> None:
    for key in ("workspace", "engine", "project", "cook_root", "inputs"):
        if recorded.get(key) != current[key]:
            raise CookStateError(
                "cook inputs changed while Unreal was cooking; discard this cook"
            )


def write_state(state_path: Path, state: dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["created_utc"] = datetime.now(timezone.utc).isoformat()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.",
        dir=state_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state_path)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(state_path: Path, description: str) -> dict[str, object]:
    if not state_path.is_file():
        raise CookStateError(f"the {description} is missing")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CookStateError(f"the {description} is unreadable") from error
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise CookStateError(f"the {description} has an unsupported schema")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("begin", "record", "check"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cook-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        workspace, engine, project, cook_root = canonical_inputs(
            args,
            require_cook_root=args.mode != "begin",
        )
        state_path = workspace / "state" / STATE_NAME
        pending_state_path = workspace / "state" / PENDING_STATE_NAME
        if args.mode == "begin":
            current_inputs = calculate_input_state(
                workspace,
                engine,
                project,
                cook_root,
            )
            write_state(pending_state_path, current_inputs)
            print("Recorded the pre-cook input fingerprint.")
            return 0

        if args.mode == "record":
            recorded_inputs = read_state(
                pending_state_path,
                "pre-cook input fingerprint",
            )
            current_inputs = calculate_input_state(
                workspace,
                engine,
                project,
                cook_root,
            )
            require_same_inputs(recorded_inputs, current_inputs)
            cook_fingerprint = cook_output_fingerprint(cook_root)
            final_inputs = calculate_input_state(
                workspace,
                engine,
                project,
                cook_root,
            )
            require_same_inputs(recorded_inputs, final_inputs)
            current = dict(final_inputs)
            current["cook"] = cook_fingerprint
            write_state(state_path, current)
            pending_state_path.unlink(missing_ok=True)
            print("Recorded the successful LinuxArm64 cook fingerprint.")
            return 0

        recorded = read_state(
            state_path,
            "successful-cook state; run the FEX cook first",
        )
        expected_paths = {
            "workspace": str(workspace),
            "engine": str(engine),
            "project": str(project),
            "cook_root": str(cook_root),
        }
        for key, expected_value in expected_paths.items():
            if recorded.get(key) != expected_value:
                raise CookStateError(
                    "the successful-cook state belongs to different inputs"
                )
        current = calculate_state(workspace, engine, project, cook_root)
        for key in ("workspace", "engine", "project", "cook_root", "inputs", "cook"):
            if recorded.get(key) != current[key]:
                raise CookStateError(
                    "the successful cook is stale or changed; create a fresh FEX cook"
                )
        print("LinuxArm64 cook fingerprint matches its recorded inputs and output.")
        return 0
    except CookStateError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())

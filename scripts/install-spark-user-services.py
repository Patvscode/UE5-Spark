#!/usr/bin/env python3
"""Install fixed user units for an always-on controller and on-demand stack."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


UNIT_NAMES = (
    "ue5-spark-private-controller.service",
    "ue5-spark-ardy.service",
    "ue5-spark-ardy-ready.service",
    "ue5-spark-avatar.service",
    "ue5-spark-digital-human.target",
)
CONTROLLER_UNIT = UNIT_NAMES[0]
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "deploy" / "systemd" / "user"
SAFE_UNIT_VALUE = re.compile(r"[A-Za-z0-9_./-]+")
SAFE_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def fail(message: str) -> "None":
    raise ValueError(message)


def safe_path(value: str, *, directory: bool, executable: bool = False) -> Path:
    if SAFE_UNIT_VALUE.fullmatch(value) is None or not value.startswith("/"):
        fail("service paths must be absolute and contain no whitespace or unit metacharacters")
    path = Path(value)
    if path.is_symlink():
        fail(f"service path must not be a symlink: {path}")
    resolved = path.resolve(strict=True)
    if resolved != path:
        fail(f"service path must already be canonical and contain no symlink components: {path}")
    if SAFE_UNIT_VALUE.fullmatch(str(resolved)) is None:
        fail(f"resolved service path contains unsafe unit characters: {resolved}")
    if directory and not resolved.is_dir():
        fail(f"service directory does not exist: {resolved}")
    if not directory and not resolved.is_file():
        fail(f"service file does not exist: {resolved}")
    if executable and not os.access(resolved, os.X_OK):
        fail(f"service executable is not executable: {resolved}")
    return resolved


def private_directory(value: str, *, create: bool) -> Path:
    if SAFE_UNIT_VALUE.fullmatch(value) is None or not value.startswith("/"):
        fail("private service directories must be absolute simple paths")
    path = Path(value)
    if not path.exists():
        if not create:
            fail(f"private service directory does not exist: {path}")
        parent = path.parent
        if parent.is_symlink() or parent.resolve(strict=True) != parent:
            fail(f"private service directory parent must be canonical: {parent}")
        path.mkdir(mode=0o700)
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    if (
        resolved != path
        or resolved.is_symlink()
        or not resolved.is_dir()
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        fail(f"private service directory must be user-owned mode 0700: {resolved}")
    return resolved


def unit_directory(value: str) -> Path:
    """Validate the shared user-unit directory without changing its permissions."""

    if SAFE_UNIT_VALUE.fullmatch(value) is None or not value.startswith("/"):
        fail("user unit directory must be an absolute simple path")
    path = Path(value)
    if not path.exists():
        parent = path.parent
        if parent.is_symlink() or parent.resolve(strict=True) != parent:
            fail(f"user unit directory parent must be canonical: {parent}")
        path.mkdir(mode=0o700)
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    if (
        resolved != path
        or path.is_symlink()
        or not resolved.is_dir()
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        fail(f"user unit directory must be canonical, user-owned, and not writable by others: {resolved}")
    return resolved


def generation(value: str) -> str:
    if SAFE_GENERATION.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("generation must be a simple 1-64 character ID")
    return value


def render_template(path: Path, replacements: dict[str, str]) -> str:
    template = path.read_text(encoding="utf-8")
    for token, replacement in replacements.items():
        template = template.replace(f"@{token}@", replacement)
    if re.search(r"@[A-Z_]+@", template):
        fail(f"unit template has an unresolved placeholder: {path.name}")
    return template


def atomic_write(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--dist-root", required=True)
    parser.add_argument("--live-root", required=True)
    parser.add_argument("--config-workspace-root", required=True)
    parser.add_argument("--asset-project-root", required=True)
    parser.add_argument("--models-root", required=True)
    parser.add_argument("--encoder-cache-root", required=True)
    parser.add_argument("--package-exe", required=True)
    parser.add_argument("--rollback-exe", required=True)
    parser.add_argument("--log-root", required=True)
    parser.add_argument("--generation", required=True, type=generation)
    parser.add_argument("--rollback-generation", required=True, type=generation)
    parser.add_argument(
        "--initial-character",
        choices=("ada", "aoi", "casual-girl"),
        default="casual-girl",
    )
    parser.add_argument(
        "--unit-root",
        default=str(Path.home() / ".config" / "systemd" / "user"),
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    if sys.platform != "linux" or os.geteuid() == 0:
        print("error: run as the normal DGX Spark Linux user", file=sys.stderr)
        return 1
    args = build_parser().parse_args()
    try:
        project_root = safe_path(args.project_root, directory=True)
        for script_name in (
            "run-private-controller.sh",
            "run-ardy-open-text-container.sh",
            "run-avatar-renderer-supervisor.py",
            "check-spark-stack-preflight.py",
            "warm-ardy-service.py",
        ):
            script = project_root / "scripts" / script_name
            if (
                script.is_symlink()
                or not script.is_file()
                or not os.access(script, os.X_OK)
            ):
                fail(f"project release is missing an executable {script_name}")
        media_root = safe_path(args.media_root, directory=True)
        dist_root = safe_path(args.dist_root, directory=True)
        if not (dist_root / "index.html").is_file():
            fail("built controller dist root is missing index.html")
        live_root = private_directory(args.live_root, create=True)
        config_workspace_root = private_directory(
            args.config_workspace_root, create=True
        )
        asset_project_root = safe_path(args.asset_project_root, directory=True)
        models_root = safe_path(args.models_root, directory=True)
        encoder_root = safe_path(args.encoder_cache_root, directory=True)
        package_exe = safe_path(args.package_exe, directory=False, executable=True)
        rollback_exe = safe_path(args.rollback_exe, directory=False, executable=True)
        log_root = private_directory(args.log_root, create=True)
        unit_root = unit_directory(args.unit_root)
        replacements = {
            "PROJECT_ROOT": str(project_root),
            "MEDIA_ROOT": str(media_root),
            "DIST_ROOT": str(dist_root),
            "LIVE_ROOT": str(live_root),
            "CONFIG_WORKSPACE_ROOT": str(config_workspace_root),
            "ASSET_PROJECT_ROOT": str(asset_project_root),
            "MODELS_ROOT": str(models_root),
            "ENCODER_CACHE_ROOT": str(encoder_root),
            "PACKAGE_EXE": str(package_exe),
            "ROLLBACK_EXE": str(rollback_exe),
            "LOG_ROOT": str(log_root),
            "GENERATION": args.generation,
            "ROLLBACK_GENERATION": args.rollback_generation,
            "INITIAL_CHARACTER": args.initial_character,
        }
        for unit_name in UNIT_NAMES:
            source = TEMPLATE_ROOT / f"{unit_name}.in"
            if source.is_symlink() or not source.is_file():
                fail(f"missing fixed unit template: {source}")
            atomic_write(unit_root / unit_name, render_template(source, replacements))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    fixed_systemctl = Path("/usr/bin/systemctl")
    if not fixed_systemctl.is_file() or not os.access(fixed_systemctl, os.X_OK):
        print("error: /usr/bin/systemctl is unavailable", file=sys.stderr)
        return 1
    for command in (
        [str(fixed_systemctl), "--user", "daemon-reload"],
        [str(fixed_systemctl), "--user", "enable", CONTROLLER_UNIT],
    ):
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            print(
                "error: user units were written, but systemd could not enable "
                "the lightweight controller",
                file=sys.stderr,
            )
            return 1
    print(
        "Installed and enabled the lightweight controller. The heavy "
        "ue5-spark-digital-human.target remains disabled and starts only from "
        "the private controller."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

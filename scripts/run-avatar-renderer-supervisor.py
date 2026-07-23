#!/usr/bin/env python3
"""Own one packaged Unreal renderer and switch reviewed character profiles safely.

The controller writes a small request into LIVE_ROOT.  This supervisor is the
only process that acts on it, and it publishes a fresh, private state heartbeat
that lets the browser prove which character produced the current live frame.
It never discovers packages from a request and never stops a process it did not
start itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


CHARACTER_PROFILES = {
    "ada": "Ada",
    "aoi": "Aoi",
    "casual-girl": "CasualGirl",
}
STATE_FILE = "renderer-state.json"
REQUEST_FILE = "renderer-request.json"
MAX_CONTROL_BYTES = 16 * 1024
REQUEST_ID_PATTERN = re.compile(r"[0-9a-f]{24}")
GENERATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class Package:
    executable: Path
    launcher: Path
    root: Path
    generation: str
    profiles: dict[str, str]
    framings: dict[str, str]


@dataclass
class OwnedRenderer:
    package: Package
    character: str
    renderer: subprocess.Popen[bytes]
    preview: subprocess.Popen[bytes]
    renderer_log: object
    preview_log: object


def fail(message: str) -> "None":
    raise RuntimeError(message)


def private_directory(path: Path, label: str, *, create: bool = False) -> Path:
    path = path.expanduser().resolve(strict=False)
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.stat()
    if (
        not path.is_dir()
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        fail(f"{label} must be a real, user-owned 0700 directory")
    return path


def _private_json(path: Path) -> dict[str, object] | None:
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
            or not 2 <= metadata.st_size <= MAX_CONTROL_BYTES
        ):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(MAX_CONTROL_BYTES + 1)
        if len(body) != metadata.st_size:
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        os.close(descriptor)


def atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    nonce = f"{os.getpid()}-{time.time_ns()}"
    temporary = path.parent / f".{path.name}.{nonce}.tmp"
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
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
        os.replace(temporary, path)
    finally:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def find_package_root(executable: Path) -> Path:
    for parent in executable.parents:
        if (parent / ".ue5-spark-characters.json").is_file():
            return parent
    fail("the package has no sealed .ue5-spark-characters.json manifest")


def load_package(executable_input: Path, generation: str | None = None) -> Package:
    executable = executable_input.expanduser().resolve(strict=True)
    if (
        not executable.is_file()
        or executable.is_symlink()
        or executable.name != "FayAvatarRuntime"
        or not os.access(executable, os.X_OK)
        or executable.parts[-3:] != ("Binaries", "LinuxArm64", "FayAvatarRuntime")
    ):
        fail("renderer executable is not the packaged LinuxArm64 FayAvatarRuntime")
    root = find_package_root(executable)
    launcher = root / "FayAvatarRuntime-Arm64.sh"
    if (
        not launcher.is_file()
        or launcher.is_symlink()
        or not os.access(launcher, os.X_OK)
    ):
        fail("package is missing its real executable FayAvatarRuntime-Arm64.sh launcher")
    manifest_path = root / ".ue5-spark-characters.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 64 * 1024:
        fail("package character manifest is unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("package character manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") not in {1, 2}:
        fail("package character manifest schema is unsupported")
    entries = manifest.get("characters")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        fail("package character manifest has no bounded character list")

    reviewed_by_runtime = {runtime_id: slug for slug, runtime_id in CHARACTER_PROFILES.items()}
    profiles: dict[str, str] = {}
    framings: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            fail("package character manifest entry is invalid")
        runtime_id = entry.get("id")
        slug = reviewed_by_runtime.get(runtime_id)
        if slug is None:
            continue
        available_framings = entry.get("cameraFramings", ["Portrait"])
        if not isinstance(available_framings, list):
            fail(f"package framing contract for {runtime_id} is invalid")
        framing = "FullBody" if "FullBody" in available_framings else "Portrait"
        profiles[slug] = runtime_id
        framings[slug] = framing
    if not profiles:
        fail("package contains no reviewed renderer profiles")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:12]
    resolved_generation = generation or f"pkg-{digest}"
    if GENERATION_PATTERN.fullmatch(resolved_generation) is None:
        fail("package generation must be a simple 1-64 character identifier")
    return Package(executable, launcher, root, resolved_generation, profiles, framings)


def read_request(live_root: Path) -> dict[str, object] | None:
    payload = _private_json(live_root / REQUEST_FILE)
    if payload is None or set(payload) != {
        "schemaVersion", "character", "requestId", "requestedAtUnixMs",
    }:
        return None
    requested_ms = payload.get("requestedAtUnixMs")
    if (
        payload.get("schemaVersion") != 1
        or payload.get("character") not in CHARACTER_PROFILES
        or not isinstance(payload.get("requestId"), str)
        or REQUEST_ID_PATTERN.fullmatch(payload["requestId"]) is None
        or type(requested_ms) is not int
        or requested_ms > int(time.time() * 1000) + 2_000
    ):
        return None
    return payload


def any_unowned_renderer() -> bool:
    for process_dir in Path("/proc").glob("[1-9]*"):
        try:
            executable = (process_dir / "exe").resolve(strict=True)
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if executable.name == "FayAvatarRuntime":
            return True
    return False


def stop_owned(process: subprocess.Popen[bytes] | None, timeout: float = 10.0) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def stop_renderer(owned: OwnedRenderer | None) -> None:
    if owned is None:
        return
    stop_owned(owned.preview)
    stop_owned(owned.renderer)
    owned.preview_log.close()
    owned.renderer_log.close()


class Supervisor:
    def __init__(
        self,
        package: Package,
        rollback: Package | None,
        live_root: Path,
        log_root: Path,
        stack_launcher: Path,
        preview_script: Path,
        startup_timeout: int,
    ):
        self.package = package
        self.rollback = rollback
        self.live_root = live_root
        self.log_root = log_root
        self.stack_launcher = stack_launcher
        self.preview_script = preview_script
        self.startup_timeout = startup_timeout
        self.owned: OwnedRenderer | None = None
        self.requested_character: str | None = None
        self.last_request_id: str | None = None
        self.stopping = False

    def available(self) -> list[str]:
        return [slug for slug in CHARACTER_PROFILES if slug in self.package.profiles]

    def state(self, state: str, active: str | None, generation: str | None = None) -> None:
        atomic_private_json(self.live_root / STATE_FILE, {
            "schemaVersion": 1,
            "state": state,
            "activeCharacter": active,
            "requestedCharacter": self.requested_character,
            "availableCharacters": self.available(),
            "packageGeneration": generation or self.package.generation,
            "updatedAtUnixMs": int(time.time() * 1000),
        })

    def _fresh_frame(self, after_ns: int) -> bool:
        frame = self.live_root / "frame.jpg"
        try:
            metadata = frame.stat(follow_symlinks=False)
        except (FileNotFoundError, OSError):
            return False
        return (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_mtime_ns >= after_ns
            and metadata.st_size >= 4
        )

    def launch(self, package: Package, character: str) -> OwnedRenderer:
        if character not in package.profiles:
            fail(f"{character} is not present in package {package.generation}")
        frame = self.live_root / "frame.jpg"
        if frame.exists() or frame.is_symlink():
            metadata = frame.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                fail("refusing to remove an unsafe prior live frame")
            frame.unlink()

        stamp = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{time.time_ns()}"
        renderer_log_path = self.log_root / f"renderer-{package.generation}-{character}-{stamp}.log"
        preview_log_path = self.log_root / f"preview-{package.generation}-{character}-{stamp}.log"
        renderer_log = renderer_log_path.open("xb", buffering=0)
        preview_log = preview_log_path.open("xb", buffering=0)
        os.chmod(renderer_log_path, 0o600)
        os.chmod(preview_log_path, 0o600)
        command = [
            str(self.stack_launcher), str(package.launcher),
            f"-FayCharacter={package.profiles[character]}",
            f"-FayCameraFraming={package.framings[character]}",
            "-FayResetSpeechCache=0", "-FayTrimSpeechMemory=1",
            "-ResX=1280", "-ResY=720", "-Windowed", "-WinX=0", "-WinY=0",
        ]
        renderer = subprocess.Popen(
            command,
            cwd=package.executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=renderer_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        launch_ns = time.time_ns()
        try:
            time.sleep(1.0)
            if renderer.poll() is not None:
                fail(f"renderer exited during launch with status {renderer.returncode}")
            preview = subprocess.Popen(
                [
                    str(self.preview_script), str(package.executable),
                    str(self.live_root), str(self.startup_timeout), "12",
                ],
                stdin=subprocess.DEVNULL,
                stdout=preview_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if renderer.poll() is not None:
                    fail(f"renderer exited during preview startup with status {renderer.returncode}")
                if preview.poll() is not None:
                    fail(f"preview exited during startup with status {preview.returncode}")
                if self._fresh_frame(launch_ns):
                    return OwnedRenderer(
                        package, character, renderer, preview, renderer_log, preview_log,
                    )
                time.sleep(0.2)
            fail("renderer did not publish a fresh live frame before the startup deadline")
        except Exception:
            stop_owned(locals().get("preview"))
            stop_owned(renderer)
            preview_log.close()
            renderer_log.close()
            raise

    def switch(self, character: str) -> None:
        previous = self.owned
        previous_character = previous.character if previous else None
        if previous and previous.character == character:
            self.requested_character = character
            self.state("ready", character, previous.package.generation)
            return
        self.requested_character = character
        self.state("switching" if previous else "starting", previous_character)
        stop_renderer(previous)
        self.owned = None
        try:
            self.owned = self.launch(self.package, character)
            self.state("ready", character, self.package.generation)
            return
        except Exception as exc:
            print(f"target launch failed: {exc}", file=sys.stderr, flush=True)

        restore_character = previous_character or "ada"
        restore_packages = [self.package]
        if self.rollback is not None:
            restore_packages.append(self.rollback)
        self.state("rollback", None)
        for package in restore_packages:
            if restore_character not in package.profiles:
                continue
            try:
                self.owned = self.launch(package, restore_character)
                self.requested_character = restore_character
                self.state("ready", restore_character, package.generation)
                return
            except Exception as exc:
                print(f"rollback launch failed for {package.generation}: {exc}", file=sys.stderr, flush=True)
        self.state("failed", None)
        fail("target and rollback renderers both failed")

    def run(self, initial_character: str) -> None:
        self.requested_character = initial_character
        self.state("starting", None)
        self.switch(initial_character)
        while not self.stopping:
            if (
                self.owned is None
                or self.owned.renderer.poll() is not None
                or self.owned.preview.poll() is not None
            ):
                interrupted_character = self.owned.character if self.owned else self.requested_character
                stop_renderer(self.owned)
                self.owned = None
                if interrupted_character is None:
                    fail("renderer stopped without a recoverable character")
                self.switch(interrupted_character)

            request = read_request(self.live_root)
            if request is not None and request["requestId"] != self.last_request_id:
                self.last_request_id = str(request["requestId"])
                character = str(request["character"])
                if character in self.available():
                    self.switch(character)
            active = self.owned.character if self.owned else None
            generation = self.owned.package.generation if self.owned else None
            self.state("ready" if self.owned else "failed", active, generation)
            time.sleep(1.0)

    def shutdown(self) -> None:
        self.stopping = True
        stop_renderer(self.owned)
        self.owned = None
        self.state("failed", None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-exe", required=True, type=Path)
    parser.add_argument("--rollback-exe", type=Path)
    parser.add_argument("--live-root", required=True, type=Path)
    parser.add_argument("--log-root", required=True, type=Path)
    parser.add_argument("--stack-launcher", type=Path, default=Path(__file__).with_name("run-spark-digital-human.sh"))
    parser.add_argument("--preview-script", type=Path, default=Path(__file__).with_name("run-avatar-live-preview.sh"))
    parser.add_argument("--initial-character", choices=tuple(CHARACTER_PROFILES), default="ada")
    parser.add_argument("--generation")
    parser.add_argument("--rollback-generation")
    parser.add_argument("--startup-timeout", type=int, default=120)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("renderer supervisor must run on Linux/aarch64 DGX Spark")
    if os.geteuid() == 0:
        raise SystemExit("run the renderer supervisor as the normal desktop owner")
    if not 15 <= args.startup_timeout <= 300:
        raise SystemExit("startup timeout must be 15 through 300 seconds")
    try:
        live_root = private_directory(args.live_root, "live root")
        log_root = private_directory(args.log_root, "log root", create=True)
        stack_launcher = args.stack_launcher.expanduser().resolve(strict=True)
        preview_script = args.preview_script.expanduser().resolve(strict=True)
        for launcher, label in (
            (stack_launcher, "stack launcher"),
            (preview_script, "preview script"),
        ):
            if launcher.is_symlink() or not launcher.is_file() or not os.access(launcher, os.X_OK):
                fail(f"{label} must be one real executable file")
        package = load_package(args.package_exe, args.generation)
        rollback = (
            load_package(args.rollback_exe, args.rollback_generation)
            if args.rollback_exe else None
        )
        if args.initial_character not in package.profiles:
            fail("initial character is not present in the selected package")
        if any_unowned_renderer():
            fail("an unmanaged FayAvatarRuntime is already running; nothing was stopped")
        supervisor = Supervisor(
            package, rollback, live_root, log_root, stack_launcher, preview_script,
            args.startup_timeout,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    def request_stop(_signum: int, _frame: object) -> None:
        supervisor.stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        supervisor.run(args.initial_character)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        supervisor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

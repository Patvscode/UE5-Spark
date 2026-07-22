#!/usr/bin/env python3
"""Quarantine, validate, and explicitly finalize temporary ARDY HF authorization.

This tool is deliberately credential-only.  It never moves or deletes the default
Hugging Face home, the reusable text-encoder cache, ARDY checkpoints, embeddings,
or any container other than the immutable-ID canary that it creates itself.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import platform
import pwd
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
AUTH_DIRECTORY_NAME = "hf-ardy-device"
AUTH_INVENTORY = {
    "token": 0o600,
    "stored_tokens": 0o600,
    ".check_for_update_done": 0o644,
    ".agent_harnesses.json": 0o644,
}
SECRET_AUTH_FILES = frozenset({"token", "stored_tokens"})
ENCODER_CACHE_NAME = ".hf-text-encoder-cache"
EXPECTED_ENCODER_CACHE_INVENTORY = frozenset(
    {"hub", "xet", ".agent_harnesses.json"}
)
EXPECTED_EMBEDDING_INVENTORY = frozenset(
    {"manifest.json", "idle.npz", "listen.npz", "explain.npz"}
)
EXPECTED_CHECKPOINTS = (
    "ARDY-Core-RP-20FPS-Horizon8",
    "ARDY-Core-RP-20FPS-Horizon40",
)
CHECKPOINT_MARKERS = ("config.yaml", "denoiser.safetensors", "tokenizer.safetensors")
PRODUCTION_CONTAINER = "ue5-spark-ardy"
CANARY_CONTAINER = "ue5-spark-ardy-auth-cleanup-canary"
TARGET_IMAGE = "ue5-spark-ardy:0.2.0"
PRODUCTION_PORT = 8777
CANARY_PORT = 18777
VALIDATION_BATCHES = 30
MAX_PRIVATE_FILE_BYTES = 2 * 1024 * 1024
IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
CREDENTIAL_NAME_RE = re.compile(
    r"(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIAL|API_KEY|ACCESS_KEY)(?:_|$)",
    re.I,
)
HF_TOKEN_RE = re.compile(rb"hf_[A-Za-z0-9_-]{10,}")
SIMPLE_EVIDENCE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class CleanupError(RuntimeError):
    """A fail-closed cleanup precondition or validation failed."""


@dataclass(frozen=True)
class CleanupPaths:
    repository: Path
    workspace: Path
    auth_original: Path
    encoder_cache: Path
    runtime_models: Path
    default_hf_home: Path
    default_token: Path
    evidence: Path


@dataclass
class QuarantineMove:
    source: Path
    destination: Path
    expected_identity: Mapping[str, object]
    moved: bool = False

    def move(self) -> None:
        if self.moved:
            raise CleanupError("authorization quarantine move was attempted twice")
        if self.destination.exists() or self.destination.is_symlink():
            raise CleanupError("authorization quarantine destination already exists")
        _assert_identity(self.source, self.expected_identity, "authorization directory")
        if self.source.parent.stat().st_dev != self.destination.parent.stat().st_dev:
            raise CleanupError("authorization quarantine must remain on one filesystem")
        os.rename(self.source, self.destination)
        self.moved = True
        _assert_identity(
            self.destination, self.expected_identity, "quarantined authorization directory"
        )

    def restore(self) -> None:
        if not self.moved:
            return
        if self.source.exists() or self.source.is_symlink():
            raise CleanupError("cannot restore authorization: original path was claimed")
        _assert_identity(
            self.destination, self.expected_identity, "quarantined authorization directory"
        )
        os.rename(self.destination, self.source)
        self.moved = False
        _assert_identity(self.source, self.expected_identity, "restored authorization directory")


class CommandRunner:
    """Small non-shell command runner, replaceable by unit tests."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                tuple(arguments),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CleanupError(f"command failed to execute: {arguments[0]}") from error
        if check and result.returncode != 0:
            raise CleanupError(f"command failed: {arguments[0]} {arguments[1]}")
        return result


def _canonical_existing_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise CleanupError(f"{label} must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise CleanupError(f"{label} does not exist") from error
    if resolved != path:
        raise CleanupError(f"{label} must be canonical and contain no symlink")
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode):
        raise CleanupError(f"{label} must be a real directory")
    return resolved


def _assert_private_directory(path: Path, uid: int, label: str) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise CleanupError(f"{label} is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CleanupError(f"{label} must be a non-symlink directory")
    try:
        if path.resolve(strict=True) != path:
            raise CleanupError(f"{label} must contain no symlinked path component")
    except OSError as error:
        raise CleanupError(f"{label} cannot be resolved safely") from error
    if metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise CleanupError(f"{label} must be owned by the caller with mode 700")
    return metadata


def _identity(metadata: os.stat_result, kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "mode": stat.S_IMODE(metadata.st_mode),
        "nlink": metadata.st_nlink,
    }


def _path_identity(path: Path, label: str) -> dict[str, object]:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise CleanupError(f"{label} is missing") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise CleanupError(f"{label} cannot be a symlink")
    if stat.S_ISDIR(metadata.st_mode):
        kind = "directory"
    elif stat.S_ISREG(metadata.st_mode):
        kind = "file"
    else:
        raise CleanupError(f"{label} must be a regular file or directory")
    return _identity(metadata, kind)


def _assert_identity(path: Path, expected: Mapping[str, object], label: str) -> None:
    actual = _path_identity(path, label)
    if actual != dict(expected):
        raise CleanupError(f"{label} identity changed")


def resolve_paths(
    repository: Path,
    workspace_argument: str,
    evidence_argument: str,
    *,
    evidence_must_exist: bool,
) -> CleanupPaths:
    repository = _canonical_existing_directory(repository, "repository")
    workspace = _canonical_existing_directory(Path(workspace_argument), "WORKSPACE_ROOT")
    if repository != workspace / "UE5-Spark":
        raise CleanupError("WORKSPACE_ROOT must directly contain this UE5-Spark checkout")

    evidence_input = Path(evidence_argument)
    if not evidence_input.is_absolute() or not SIMPLE_EVIDENCE_NAME_RE.fullmatch(
        evidence_input.name
    ):
        raise CleanupError("PRIVATE_EVIDENCE_DIR must be absolute with a simple run name")
    logs_private = _canonical_existing_directory(
        workspace / "logs-private", "workspace logs-private"
    )
    if evidence_input.parent != logs_private:
        raise CleanupError("PRIVATE_EVIDENCE_DIR must be a direct child of workspace logs-private")
    if evidence_must_exist:
        evidence = _canonical_existing_directory(evidence_input, "PRIVATE_EVIDENCE_DIR")
    else:
        if evidence_input.exists() or evidence_input.is_symlink():
            raise CleanupError("PRIVATE_EVIDENCE_DIR must not already exist")
        evidence = evidence_input

    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    home = _canonical_existing_directory(home, "passwd home")
    default_hf_home = home / ".cache" / "huggingface"
    paths = CleanupPaths(
        repository=repository,
        workspace=workspace,
        auth_original=workspace / "secrets-private" / AUTH_DIRECTORY_NAME,
        encoder_cache=workspace / "models-private" / ENCODER_CACHE_NAME,
        runtime_models=workspace / "models-private" / "ardy",
        default_hf_home=default_hf_home,
        default_token=default_hf_home / "token",
        evidence=evidence,
    )
    protected = (
        paths.encoder_cache,
        paths.runtime_models,
        paths.default_hf_home,
        paths.evidence,
    )
    for protected_path in protected:
        if paths_overlap(paths.auth_original, protected_path):
            raise CleanupError("authorization target overlaps a protected path")
    return paths


def paths_overlap(first: Path, second: Path) -> bool:
    first_value = Path(os.path.realpath(first))
    second_value = Path(os.path.realpath(second))
    try:
        first_value.relative_to(second_value)
        return True
    except ValueError:
        pass
    try:
        second_value.relative_to(first_value)
        return True
    except ValueError:
        return False


def _read_regular_file(
    path: Path,
    *,
    uid: int,
    modes: frozenset[int],
    maximum_bytes: int,
    allow_empty: bool,
    label: str,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CleanupError(f"{label} is missing or unsafe") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CleanupError(f"{label} must be a singly linked regular file")
        if before.st_uid != uid or stat.S_IMODE(before.st_mode) not in modes:
            raise CleanupError(f"{label} has unsafe owner or permissions")
        if before.st_size > maximum_bytes or (before.st_size == 0 and not allow_empty):
            raise CleanupError(f"{label} has an invalid size")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 128 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum_bytes:
            raise CleanupError(f"{label} exceeds its size bound")
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise CleanupError(f"{label} changed while it was read")
        return payload, before
    finally:
        os.close(descriptor)


def _stat_regular_file(
    path: Path,
    *,
    uid: int,
    modes: frozenset[int],
    label: str,
) -> os.stat_result:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CleanupError(f"{label} is missing or unsafe") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
        ):
            raise CleanupError(f"{label} must be a nonempty regular file")
        if metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) not in modes:
            raise CleanupError(f"{label} has unsafe owner or permissions")
        return metadata
    finally:
        os.close(descriptor)


def _hash_regular_file(
    path: Path,
    *,
    uid: int,
    modes: frozenset[int],
    maximum_bytes: int,
    label: str,
) -> tuple[str, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CleanupError(f"{label} is missing or unsafe") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise CleanupError(f"{label} has an invalid regular-file contract")
        if before.st_uid != uid or stat.S_IMODE(before.st_mode) not in modes:
            raise CleanupError(f"{label} has unsafe owner or permissions")
        digest = hashlib.sha256()
        bytes_read = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > maximum_bytes:
                raise CleanupError(f"{label} exceeds its size bound")
            digest.update(chunk)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_gid",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
        )
        if bytes_read != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise CleanupError(f"{label} changed while it was hashed")
        return digest.hexdigest(), before
    finally:
        os.close(descriptor)


def _hmac_hex(key: bytes, payload: bytes) -> str:
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _credential_candidates(payload: bytes) -> tuple[bytes, ...]:
    candidates = {payload.strip()}
    candidates.update(HF_TOKEN_RE.findall(payload))
    candidates.discard(b"")
    return tuple(sorted(candidates))


def compare_token_fingerprints(
    temporary_payloads: Mapping[str, bytes], default_payload: bytes, key: bytes
) -> dict[str, object]:
    if len(key) != 32:
        raise CleanupError("credential fingerprint key must contain exactly 32 bytes")
    default_digests = tuple(
        _hmac_hex(key, candidate) for candidate in _credential_candidates(default_payload)
    )
    temporary_digests: dict[str, list[str]] = {}
    for name, payload in temporary_payloads.items():
        digests = [_hmac_hex(key, candidate) for candidate in _credential_candidates(payload)]
        temporary_digests[name] = digests
        for temporary_digest in digests:
            if any(
                hmac.compare_digest(temporary_digest, default_digest)
                for default_digest in default_digests
            ):
                raise CleanupError(
                    "temporary and default Hugging Face credentials are not distinct"
                )
    return {
        "default": _hmac_hex(key, default_payload),
        "temporary": {
            name: _hmac_hex(key, payload)
            for name, payload in sorted(temporary_payloads.items())
        },
        "candidate_counts": {
            "default": len(default_digests),
            "temporary": {
                name: len(values) for name, values in sorted(temporary_digests.items())
            },
        },
    }


def validate_auth_inventory(path: Path, uid: int, key: bytes) -> dict[str, object]:
    directory_metadata = _assert_private_directory(path, uid, "temporary authorization directory")
    entries = set(os.listdir(path))
    if entries != set(AUTH_INVENTORY):
        raise CleanupError("temporary authorization directory inventory is not exact")
    records: dict[str, object] = {}
    secret_payloads: dict[str, bytes] = {}
    for name, expected_mode in AUTH_INVENTORY.items():
        payload, metadata = _read_regular_file(
            path / name,
            uid=uid,
            modes=frozenset({expected_mode}),
            maximum_bytes=MAX_PRIVATE_FILE_BYTES,
            allow_empty=name == ".check_for_update_done",
            label=f"temporary authorization file {name}",
        )
        if name == ".check_for_update_done" and payload:
            raise CleanupError("authorization update sidecar must be empty")
        if name == ".agent_harnesses.json":
            try:
                parsed = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CleanupError("authorization harness sidecar is not valid JSON") from error
            if not isinstance(parsed, (dict, list)):
                raise CleanupError("authorization harness sidecar has an invalid JSON envelope")
        record = _identity(metadata, "file")
        record.update({"size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns})
        if name in SECRET_AUTH_FILES:
            record["content_hmac_sha256"] = _hmac_hex(key, payload)
            secret_payloads[name] = payload
        else:
            record["content_sha256"] = hashlib.sha256(payload).hexdigest()
        records[name] = record
    return {
        "directory": _identity(directory_metadata, "directory"),
        "entries": records,
        "secret_payloads": secret_payloads,
    }


def _validate_default_token(path: Path, uid: int) -> tuple[bytes, dict[str, object]]:
    payload, metadata = _read_regular_file(
        path,
        uid=uid,
        modes=frozenset({0o400, 0o600}),
        maximum_bytes=MAX_PRIVATE_FILE_BYTES,
        allow_empty=False,
        label="default Hugging Face token",
    )
    record = _identity(metadata, "file")
    record.update({"size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns})
    return payload, record


def _snapshot_encoder_cache(path: Path, uid: int) -> dict[str, object]:
    root_metadata = _assert_private_directory(path, uid, "protected text-encoder cache")
    entries = set(os.listdir(path))
    if entries != set(EXPECTED_ENCODER_CACHE_INVENTORY):
        raise CleanupError("protected text-encoder cache top-level inventory changed")
    children: dict[str, object] = {}
    for name in sorted(entries):
        child = path / name
        metadata = os.lstat(child)
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != uid:
            raise CleanupError("protected text-encoder cache contains an unsafe top-level entry")
        if name in {"hub", "xet"}:
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o755:
                raise CleanupError("protected text-encoder cache directory contract changed")
            kind = "directory"
        else:
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o644:
                raise CleanupError("protected text-encoder cache sidecar contract changed")
            kind = "file"
        children[name] = _identity(metadata, kind)
    return {"root": _identity(root_metadata, "directory"), "children": children}


def _snapshot_runtime_models(path: Path, uid: int) -> dict[str, object]:
    root_metadata = _assert_private_directory(path, uid, "protected ARDY model root")
    checkpoints: dict[str, object] = {}
    for checkpoint_name in EXPECTED_CHECKPOINTS:
        checkpoint = path / checkpoint_name
        checkpoint_metadata = _assert_private_directory(
            checkpoint, uid, f"protected checkpoint {checkpoint_name}"
        )
        markers: dict[str, object] = {}
        for marker_name in CHECKPOINT_MARKERS:
            marker_path = checkpoint / marker_name
            if marker_name == "config.yaml":
                marker_payload, marker_metadata = _read_regular_file(
                    marker_path,
                    uid=uid,
                    modes=frozenset({0o400, 0o600, 0o644}),
                    maximum_bytes=4 * 1024 * 1024,
                    allow_empty=False,
                    label=f"checkpoint marker {checkpoint_name}/{marker_name}",
                )
            else:
                marker_payload = b""
                marker_metadata = _stat_regular_file(
                    marker_path,
                    uid=uid,
                    modes=frozenset({0o400, 0o600, 0o644}),
                    label=f"checkpoint marker {checkpoint_name}/{marker_name}",
                )
            marker_record = _identity(marker_metadata, "file")
            marker_record.update(
                {"size": marker_metadata.st_size, "mtime_ns": marker_metadata.st_mtime_ns}
            )
            if marker_name == "config.yaml":
                marker_record["content_sha256"] = hashlib.sha256(marker_payload).hexdigest()
            markers[marker_name] = marker_record
        checkpoints[checkpoint_name] = {
            "directory": _identity(checkpoint_metadata, "directory"),
            "markers": markers,
        }

    embeddings = path / "embeddings"
    embeddings_metadata = _assert_private_directory(embeddings, uid, "protected embeddings")
    if set(os.listdir(embeddings)) != set(EXPECTED_EMBEDDING_INVENTORY):
        raise CleanupError("protected embedding inventory is not exact")
    embedding_records: dict[str, object] = {}
    for name in sorted(EXPECTED_EMBEDDING_INVENTORY):
        content_digest, metadata = _hash_regular_file(
            embeddings / name,
            uid=uid,
            modes=frozenset({0o400, 0o600, 0o644}),
            maximum_bytes=1024 * 1024 * 1024,
            label=f"protected embedding {name}",
        )
        record = _identity(metadata, "file")
        record.update(
            {
                "size": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "content_sha256": content_digest,
            }
        )
        embedding_records[name] = record
    return {
        "root": _identity(root_metadata, "directory"),
        "checkpoints": checkpoints,
        "embeddings": {
            "directory": _identity(embeddings_metadata, "directory"),
            "entries": embedding_records,
        },
    }


def capture_protected_state(paths: CleanupPaths, uid: int, key: bytes) -> dict[str, object]:
    default_home_metadata = _assert_private_directory(
        paths.default_hf_home, uid, "protected default Hugging Face home"
    )
    default_payload, default_record = _validate_default_token(paths.default_token, uid)
    return {
        "encoder_cache": _snapshot_encoder_cache(paths.encoder_cache, uid),
        "runtime_models": _snapshot_runtime_models(paths.runtime_models, uid),
        "default_hf_home": _identity(default_home_metadata, "directory"),
        "default_token": {
            "record": default_record,
            "content_hmac_sha256": _hmac_hex(key, default_payload),
        },
        "default_token_payload": default_payload,
    }


def validate_workspace_private_roots(paths: CleanupPaths, uid: int) -> None:
    _assert_private_directory(
        paths.auth_original.parent, uid, "workspace secrets-private root"
    )
    _assert_private_directory(
        paths.runtime_models.parent, uid, "workspace models-private root"
    )
    _assert_private_directory(paths.evidence.parent, uid, "workspace logs-private root")


def protected_state_for_record(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in snapshot.items() if key != "default_token_payload"}


def assert_protected_state_unchanged(
    expected: Mapping[str, object], paths: CleanupPaths, uid: int, key: bytes
) -> None:
    actual = protected_state_for_record(capture_protected_state(paths, uid, key))
    if actual != dict(expected):
        raise CleanupError("a protected Hugging Face or ARDY asset changed")


def ensure_no_container_mount_overlap(
    container_records: Sequence[Mapping[str, object]], protected_paths: Sequence[Path]
) -> None:
    for record in container_records:
        mounts = record.get("Mounts")
        if not isinstance(mounts, list):
            raise CleanupError("Docker returned an invalid container mount inventory")
        for mount in mounts:
            if not isinstance(mount, dict):
                raise CleanupError("Docker returned an invalid container mount record")
            source = mount.get("Source")
            if not isinstance(source, str) or not source.startswith("/"):
                continue
            if any(paths_overlap(Path(source), target) for target in protected_paths):
                raise CleanupError("a Docker container mount overlaps temporary authorization")


def _docker_container_records(runner: CommandRunner) -> list[dict[str, object]]:
    result = runner.run(("docker", "ps", "--all", "--quiet", "--no-trunc"))
    identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if any(not CONTAINER_ID_RE.fullmatch(identifier) for identifier in identifiers):
        raise CleanupError("Docker returned an invalid container identifier")
    records: list[dict[str, object]] = []
    for identifier in identifiers:
        inspected = runner.run(("docker", "inspect", "--type", "container", identifier))
        try:
            value = json.loads(inspected.stdout)
        except json.JSONDecodeError as error:
            raise CleanupError("Docker returned invalid container inspection JSON") from error
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise CleanupError("Docker returned an invalid container inspection envelope")
        records.append(value[0])
    return records


def _image_id(runner: CommandRunner, image: str) -> str:
    result = runner.run(("docker", "image", "inspect", "--format", "{{.Id}}", image))
    value = result.stdout.strip()
    if not IMAGE_ID_RE.fullmatch(value):
        raise CleanupError("the fixed ARDY image did not resolve to one immutable image ID")
    return value


def _inspect_container(runner: CommandRunner, identifier: str) -> dict[str, object]:
    result = runner.run(("docker", "inspect", "--type", "container", identifier))
    try:
        records = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CleanupError("Docker returned invalid container inspection JSON") from error
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise CleanupError("Docker returned an invalid container inspection envelope")
    return records[0]


def _contains_gpu_request(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for request in value:
        if not isinstance(request, dict):
            continue
        capabilities = request.get("Capabilities")
        if isinstance(capabilities, list) and any(
            isinstance(group, list) and "gpu" in group for group in capabilities
        ):
            return True
    return False


def validate_real_ardy_container(
    record: Mapping[str, object],
    *,
    expected_name: str,
    expected_image_id: str,
    expected_port: int,
    expected_auto_remove: bool,
    models_root: Path,
    uid: int,
    gid: int,
) -> dict[str, object]:
    config = record.get("Config")
    host = record.get("HostConfig")
    state = record.get("State")
    mounts = record.get("Mounts")
    if not all(isinstance(value, dict) for value in (config, host, state)):
        raise CleanupError("ARDY container inspection is incomplete")
    assert isinstance(config, dict) and isinstance(host, dict) and isinstance(state, dict)
    container_id = record.get("Id")
    expected_command = [
        "--host",
        "127.0.0.1",
        "--port",
        str(expected_port),
        "--provider",
        "ardy",
        "--models-root",
        "/models",
    ]
    if (
        not isinstance(container_id, str)
        or not CONTAINER_ID_RE.fullmatch(container_id)
        or record.get("Name") != f"/{expected_name}"
        or record.get("Image") != expected_image_id
        or config.get("Image") not in {TARGET_IMAGE, expected_image_id}
        or config.get("Cmd") != expected_command
        or config.get("User") != f"{uid}:{gid}"
        or state.get("Running") is not True
        or state.get("Dead") is not False
        or state.get("OOMKilled") is not False
        or state.get("Error") not in {None, ""}
        or not isinstance(state.get("Pid"), int)
        or state.get("Pid", 0) <= 0
        or record.get("RestartCount") != 0
        or host.get("AutoRemove") is not expected_auto_remove
        or host.get("NetworkMode") != "host"
        or host.get("ReadonlyRootfs") is not True
        or host.get("CapDrop") != ["ALL"]
        or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
        or host.get("PidsLimit") != 512
        or host.get("ShmSize") != 4 * 1024**3
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=1g"}
        or not _contains_gpu_request(host.get("DeviceRequests"))
    ):
        raise CleanupError("ARDY container does not match the sealed real-provider contract")
    if not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict):
        raise CleanupError("ARDY container must have exactly one model mount")
    mount = mounts[0]
    if (
        mount.get("Type") != "bind"
        or mount.get("Source") != str(models_root)
        or mount.get("Destination") != "/models"
        or mount.get("RW") is not False
    ):
        raise CleanupError("ARDY container model mount is not exact and read-only")
    environment = config.get("Env") or []
    if not isinstance(environment, list):
        raise CleanupError("ARDY container environment is invalid")
    for entry in environment:
        if not isinstance(entry, str) or "=" not in entry:
            raise CleanupError("ARDY container environment contains an invalid entry")
        name, value = entry.split("=", 1)
        if CREDENTIAL_NAME_RE.search(name) or HF_TOKEN_RE.search(value.encode("utf-8")):
            raise CleanupError("ARDY container environment contains credential material")
    return {
        "container_id": container_id,
        "pid": state["Pid"],
        "started_at": state.get("StartedAt"),
        "image_id": record["Image"],
        "configured_image": config["Image"],
        "name": record["Name"],
        "command": config["Cmd"],
        "mount_source": mount["Source"],
    }


def assert_production_identity_unchanged(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> None:
    if dict(expected) != dict(actual):
        raise CleanupError("production ARDY container identity changed")


def _validate_service(
    runner: CommandRunner, validator: Path, port: int, evidence_file: Path
) -> None:
    result = runner.run(
        (
            str(validator),
            "--port",
            str(port),
            "--batches",
            str(VALIDATION_BATCHES),
            "--startup-timeout",
            "180",
        ),
        timeout=1200,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CleanupError("ARDY validator returned invalid JSON") from error
    if not isinstance(value, dict) or value.get("status") != "passed" or value.get(
        "batches"
    ) != VALIDATION_BATCHES:
        raise CleanupError("ARDY validator did not prove 30 real pose batches")
    _write_private_bytes(
        evidence_file,
        json.dumps(value, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        exclusive=True,
    )


def _validator_path(repository: Path) -> Path:
    validator = repository / "tools" / "validate_ardy_service.py"
    if validator.is_symlink() or not validator.is_file() or not os.access(validator, os.X_OK):
        raise CleanupError("strict ARDY validator is missing or unsafe")
    if validator.resolve(strict=True) != validator:
        raise CleanupError("strict ARDY validator path contains a symlink")
    return validator


def _loopback_port_unused(runner: CommandRunner, port: int) -> None:
    result = runner.run(("ss", "-H", "-ltn", "sport", "=", f":{port}"))
    if result.stdout.strip():
        raise CleanupError("fixed ARDY cleanup canary port is already listening")


def _launch_canary(
    runner: CommandRunner,
    *,
    image_id: str,
    models_root: Path,
    uid: int,
    gid: int,
) -> str:
    result = runner.run(
        (
            "docker",
            "run",
            "--detach",
            "--name",
            CANARY_CONTAINER,
            "--gpus",
            "all",
            "--network",
            "host",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "512",
            "--shm-size",
            "4g",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=1g",
            "--user",
            f"{uid}:{gid}",
            "--mount",
            f"type=bind,src={models_root},dst=/models,readonly",
            image_id,
            "--host",
            "127.0.0.1",
            "--port",
            str(CANARY_PORT),
            "--provider",
            "ardy",
            "--models-root",
            "/models",
        ),
        timeout=300,
    )
    container_id = result.stdout.strip()
    if not CONTAINER_ID_RE.fullmatch(container_id):
        raise CleanupError("cleanup canary did not return one immutable container ID")
    return container_id


def _stop_remove_exact_canary(runner: CommandRunner, container_id: str) -> None:
    if not CONTAINER_ID_RE.fullmatch(container_id):
        raise CleanupError("refusing to clean up a non-exact canary container ID")
    record = _inspect_container(runner, container_id)
    if record.get("Id") != container_id or record.get("Name") != f"/{CANARY_CONTAINER}":
        raise CleanupError("refusing to clean up a container not owned by this cleanup run")
    state = record.get("State")
    if not isinstance(state, dict):
        raise CleanupError("cleanup canary state is invalid")
    if state.get("Running") is True:
        runner.run(("docker", "stop", "--time", "20", container_id), timeout=60)
    runner.run(("docker", "rm", container_id), timeout=60)
    remaining = _docker_container_records(runner)
    if any(record.get("Id") == container_id for record in remaining):
        raise CleanupError("cleanup canary still exists after exact-ID removal")


def _write_private_bytes(path: Path, payload: bytes, *, exclusive: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_private_bytes(path: Path, payload: bytes) -> None:
    if path.is_symlink():
        raise CleanupError("private evidence record cannot be a symlink")
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    _write_private_bytes(temporary, payload, exclusive=True)
    os.replace(temporary, path)


def _write_signed_state(evidence: Path, state_value: Mapping[str, object], key: bytes) -> None:
    state_payload = json.dumps(
        state_value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    envelope = {
        "state": state_value,
        "state_hmac_sha256": _hmac_hex(key, state_payload),
    }
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    _atomic_private_bytes(evidence / "state.json", payload + b"\n")


def _read_signed_state(evidence: Path, uid: int) -> tuple[dict[str, object], bytes]:
    key, _ = _read_regular_file(
        evidence / "fingerprint.key",
        uid=uid,
        modes=frozenset({0o600}),
        maximum_bytes=32,
        allow_empty=False,
        label="cleanup fingerprint key",
    )
    if len(key) != 32:
        raise CleanupError("cleanup fingerprint key has an invalid size")
    state_payload, _ = _read_regular_file(
        evidence / "state.json",
        uid=uid,
        modes=frozenset({0o600}),
        maximum_bytes=8 * 1024 * 1024,
        allow_empty=False,
        label="cleanup state",
    )
    try:
        envelope = json.loads(state_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CleanupError("cleanup state is invalid JSON") from error
    if not isinstance(envelope, dict) or set(envelope) != {"state", "state_hmac_sha256"}:
        raise CleanupError("cleanup state envelope is invalid")
    state_value = envelope["state"]
    signature = envelope["state_hmac_sha256"]
    if not isinstance(state_value, dict) or not isinstance(signature, str):
        raise CleanupError("cleanup state envelope has invalid fields")
    canonical_payload = json.dumps(
        state_value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_signature = _hmac_hex(key, canonical_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise CleanupError("cleanup state signature is invalid")
    if not isinstance(state_value, dict) or state_value.get("schema_version") != SCHEMA_VERSION:
        raise CleanupError("cleanup state schema is invalid")
    return state_value, key


def _create_evidence(path: Path, uid: int) -> None:
    os.mkdir(path, 0o700)
    metadata = _assert_private_directory(path, uid, "private cleanup evidence")
    if metadata.st_nlink < 2:
        raise CleanupError("private cleanup evidence directory is invalid")


@contextmanager
def _fixed_lock(path: Path, uid: int) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != uid
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise CleanupError("fixed cleanup lock has unsafe owner or permissions")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CleanupError("a conflicting Hugging Face or ARDY operation is running") from error
        yield
    finally:
        os.close(descriptor)


@contextmanager
def acquire_cleanup_locks(uid: int) -> Iterator[None]:
    runtime = Path(f"/run/user/{uid}")
    resolved = _canonical_existing_directory(runtime, "fixed per-user runtime directory")
    runtime_metadata = os.lstat(runtime)
    if (
        resolved != runtime
        or runtime_metadata.st_uid != uid
        or stat.S_IMODE(runtime_metadata.st_mode) != 0o700
    ):
        raise CleanupError("fixed per-user runtime directory owner is unsafe")
    with ExitStack() as stack:
        stack.enter_context(_fixed_lock(runtime / "ue5-spark-hf-authorization-cleanup.lock", uid))
        stack.enter_context(_fixed_lock(runtime / "ue5-spark-ardy.activation.lock", uid))
        yield


def run_quarantine_transaction(move: QuarantineMove, operation: Callable[[], None]) -> None:
    move.move()
    try:
        operation()
    except BaseException:
        move.restore()
        raise


def _verify_auth_snapshot(
    quarantine: Path, expected: Mapping[str, object], uid: int, key: bytes
) -> dict[str, object]:
    actual = validate_auth_inventory(quarantine, uid, key)
    actual_record = {key_name: value for key_name, value in actual.items() if key_name != "secret_payloads"}
    if actual_record != dict(expected):
        raise CleanupError("quarantined authorization identity or content changed")
    return actual


def delete_exact_authorization_directory(
    quarantine: Path, expected: Mapping[str, object], uid: int, key: bytes
) -> None:
    _verify_auth_snapshot(quarantine, expected, uid, key)
    expected_directory = expected.get("directory")
    expected_entries = expected.get("entries")
    if not isinstance(expected_directory, dict) or not isinstance(expected_entries, dict):
        raise CleanupError("authorization deletion state is invalid")
    parent = quarantine.parent
    parent_descriptor = os.open(
        parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_descriptor = os.open(
        quarantine, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        if _identity(os.fstat(directory_descriptor), "directory") != expected_directory:
            raise CleanupError("authorization directory changed before final deletion")
        if set(os.listdir(directory_descriptor)) != set(AUTH_INVENTORY):
            raise CleanupError("authorization inventory changed before final deletion")
        for name in AUTH_INVENTORY:
            metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            expected_record = expected_entries.get(name)
            if not isinstance(expected_record, dict):
                raise CleanupError("authorization deletion entry state is invalid")
            actual_identity = _identity(metadata, "file")
            if any(actual_identity[field] != expected_record.get(field) for field in actual_identity):
                raise CleanupError("authorization file identity changed before final deletion")
            os.unlink(name, dir_fd=directory_descriptor)
        if os.listdir(directory_descriptor):
            raise CleanupError("authorization directory was not empty after exact deletion")
        parent_metadata = os.stat(quarantine.name, dir_fd=parent_descriptor, follow_symlinks=False)
        final_directory_identity = _identity(parent_metadata, "directory")
        if any(
            final_directory_identity[field] != expected_directory.get(field)
            for field in final_directory_identity
            if field != "nlink"
        ):
            raise CleanupError("authorization directory identity changed before removal")
        os.rmdir(quarantine.name, dir_fd=parent_descriptor)
    finally:
        os.close(directory_descriptor)
        os.close(parent_descriptor)


def _state_paths_match(state_value: Mapping[str, object], paths: CleanupPaths) -> Path:
    expected = {
        "workspace": str(paths.workspace),
        "auth_original": str(paths.auth_original),
        "encoder_cache": str(paths.encoder_cache),
        "runtime_models": str(paths.runtime_models),
        "default_hf_home": str(paths.default_hf_home),
        "evidence": str(paths.evidence),
    }
    if state_value.get("paths") != expected:
        raise CleanupError("cleanup state paths do not match the requested workspace")
    quarantine_value = state_value.get("auth_quarantine")
    if not isinstance(quarantine_value, str):
        raise CleanupError("cleanup state has no exact quarantine path")
    quarantine = Path(quarantine_value)
    expected_prefix = f".{AUTH_DIRECTORY_NAME}.quarantine."
    if (
        quarantine.parent != paths.auth_original.parent
        or not quarantine.name.startswith(expected_prefix)
        or not re.fullmatch(re.escape(expected_prefix) + r"[0-9a-f]{24}", quarantine.name)
    ):
        raise CleanupError("cleanup state quarantine path is outside the fixed private root")
    return quarantine


def _capture_production(
    runner: CommandRunner, paths: CleanupPaths, image_id: str, uid: int, gid: int
) -> dict[str, object]:
    record = _inspect_container(runner, PRODUCTION_CONTAINER)
    return validate_real_ardy_container(
        record,
        expected_name=PRODUCTION_CONTAINER,
        expected_image_id=image_id,
        expected_port=PRODUCTION_PORT,
        expected_auto_remove=True,
        models_root=paths.runtime_models,
        uid=uid,
        gid=gid,
    )


def _assert_fixed_canary_name_absent(records: Sequence[Mapping[str, object]]) -> None:
    if any(record.get("Name") == f"/{CANARY_CONTAINER}" for record in records):
        raise CleanupError("fixed cleanup canary container name is already present")


def quarantine_authorization(paths: CleanupPaths, runner: CommandRunner) -> None:
    uid, gid = os.getuid(), os.getgid()
    validate_workspace_private_roots(paths, uid)
    _create_evidence(paths.evidence, uid)
    key = secrets.token_bytes(32)
    _write_private_bytes(paths.evidence / "fingerprint.key", key, exclusive=True)

    auth = validate_auth_inventory(paths.auth_original, uid, key)
    auth_record = {name: value for name, value in auth.items() if name != "secret_payloads"}
    protected = capture_protected_state(paths, uid, key)
    token_fingerprints = compare_token_fingerprints(
        auth["secret_payloads"], protected["default_token_payload"], key
    )
    container_records = _docker_container_records(runner)
    ensure_no_container_mount_overlap(container_records, (paths.auth_original,))
    _assert_fixed_canary_name_absent(container_records)
    image_id = _image_id(runner, TARGET_IMAGE)
    production_identity = _capture_production(runner, paths, image_id, uid, gid)
    validator = _validator_path(paths.repository)
    _validate_service(
        runner, validator, PRODUCTION_PORT, paths.evidence / "production-before.json"
    )

    quarantine = paths.auth_original.parent / (
        f".{AUTH_DIRECTORY_NAME}.quarantine.{secrets.token_hex(12)}"
    )
    state_value: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "prepared",
        "created_unix": int(time.time()),
        "paths": {
            "workspace": str(paths.workspace),
            "auth_original": str(paths.auth_original),
            "encoder_cache": str(paths.encoder_cache),
            "runtime_models": str(paths.runtime_models),
            "default_hf_home": str(paths.default_hf_home),
            "evidence": str(paths.evidence),
        },
        "auth_quarantine": str(quarantine),
        "authorization": auth_record,
        "token_fingerprints": token_fingerprints,
        "protected": protected_state_for_record(protected),
        "image_id": image_id,
        "production_identity": production_identity,
    }
    _write_signed_state(paths.evidence, state_value, key)
    move = QuarantineMove(
        paths.auth_original, quarantine, auth_record["directory"]  # type: ignore[arg-type]
    )
    canary_container_id = ""

    def validate_quarantine() -> None:
        nonlocal canary_container_id
        state_value["phase"] = "moved"
        _write_signed_state(paths.evidence, state_value, key)
        records_after_move = _docker_container_records(runner)
        ensure_no_container_mount_overlap(
            records_after_move, (paths.auth_original, quarantine)
        )
        _assert_fixed_canary_name_absent(records_after_move)
        assert_production_identity_unchanged(
            production_identity, _capture_production(runner, paths, image_id, uid, gid)
        )
        if _image_id(runner, TARGET_IMAGE) != image_id:
            raise CleanupError("fixed ARDY image tag changed during authorization quarantine")
        _loopback_port_unused(runner, CANARY_PORT)
        canary_container_id = _launch_canary(
            runner,
            image_id=image_id,
            models_root=paths.runtime_models,
            uid=uid,
            gid=gid,
        )
        try:
            canary_record = _inspect_container(runner, canary_container_id)
            canary_identity = validate_real_ardy_container(
                canary_record,
                expected_name=CANARY_CONTAINER,
                expected_image_id=image_id,
                expected_port=CANARY_PORT,
                expected_auto_remove=False,
                models_root=paths.runtime_models,
                uid=uid,
                gid=gid,
            )
            if canary_identity["container_id"] != canary_container_id:
                raise CleanupError("cleanup canary identity changed after launch")
            _validate_service(
                runner, validator, CANARY_PORT, paths.evidence / "canary.json"
            )
        finally:
            if canary_container_id:
                _stop_remove_exact_canary(runner, canary_container_id)
                canary_container_id = ""
        _validate_service(
            runner, validator, PRODUCTION_PORT, paths.evidence / "production-after.json"
        )
        assert_production_identity_unchanged(
            production_identity, _capture_production(runner, paths, image_id, uid, gid)
        )
        assert_protected_state_unchanged(
            state_value["protected"], paths, uid, key  # type: ignore[arg-type]
        )
        _verify_auth_snapshot(quarantine, auth_record, uid, key)
        if _image_id(runner, TARGET_IMAGE) != image_id:
            raise CleanupError("fixed ARDY image tag changed during cleanup validation")
        state_value["phase"] = "quarantined_validated"
        state_value["validated_unix"] = int(time.time())
        _write_signed_state(paths.evidence, state_value, key)

    try:
        run_quarantine_transaction(move, validate_quarantine)
    except BaseException as error:
        if move.moved:
            move.restore()
        state_value["phase"] = "restored_after_failure"
        state_value["failure_type"] = type(error).__name__
        _write_signed_state(paths.evidence, state_value, key)
        raise


def finalize_authorization(paths: CleanupPaths, runner: CommandRunner) -> None:
    uid, gid = os.getuid(), os.getgid()
    validate_workspace_private_roots(paths, uid)
    _assert_private_directory(paths.evidence, uid, "private cleanup evidence")
    state_value, key = _read_signed_state(paths.evidence, uid)
    if state_value.get("phase") != "quarantined_validated":
        raise CleanupError("cleanup state is not ready for explicit finalization")
    quarantine = _state_paths_match(state_value, paths)
    if paths.auth_original.exists() or paths.auth_original.is_symlink():
        raise CleanupError("original authorization path reappeared before finalization")
    authorization = state_value.get("authorization")
    protected = state_value.get("protected")
    production_identity = state_value.get("production_identity")
    image_id = state_value.get("image_id")
    if not all(isinstance(value, dict) for value in (authorization, protected, production_identity)):
        raise CleanupError("cleanup state is missing required sealed records")
    if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
        raise CleanupError("cleanup state image ID is invalid")
    _verify_auth_snapshot(quarantine, authorization, uid, key)  # type: ignore[arg-type]
    assert_protected_state_unchanged(protected, paths, uid, key)  # type: ignore[arg-type]
    records = _docker_container_records(runner)
    ensure_no_container_mount_overlap(records, (paths.auth_original, quarantine))
    _assert_fixed_canary_name_absent(records)
    if _image_id(runner, TARGET_IMAGE) != image_id:
        raise CleanupError("fixed ARDY image tag changed before finalization")
    current_production = _capture_production(runner, paths, image_id, uid, gid)
    assert_production_identity_unchanged(production_identity, current_production)  # type: ignore[arg-type]
    validator = _validator_path(paths.repository)
    attempt = secrets.token_hex(8)
    _validate_service(
        runner,
        validator,
        PRODUCTION_PORT,
        paths.evidence / f"production-finalize-before-{attempt}.json",
    )
    _write_private_bytes(
        paths.evidence / f"finalize-authorized-{attempt}.json",
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "authorized_unix": int(time.time())},
            sort_keys=True,
        ).encode("utf-8")
        + b"\n",
        exclusive=True,
    )

    deletion_started = False
    try:
        deletion_started = True
        delete_exact_authorization_directory(
            quarantine, authorization, uid, key  # type: ignore[arg-type]
        )
        if quarantine.exists() or quarantine.is_symlink():
            raise CleanupError("authorization quarantine still exists after finalization")
        assert_protected_state_unchanged(protected, paths, uid, key)  # type: ignore[arg-type]
        assert_production_identity_unchanged(
            production_identity, _capture_production(runner, paths, image_id, uid, gid)  # type: ignore[arg-type]
        )
        if _image_id(runner, TARGET_IMAGE) != image_id:
            raise CleanupError("fixed ARDY image tag changed during finalization")
        _validate_service(
            runner,
            validator,
            PRODUCTION_PORT,
            paths.evidence / f"production-finalize-after-{attempt}.json",
        )
        state_value["phase"] = "finalized"
        state_value["finalized_unix"] = int(time.time())
        _write_signed_state(paths.evidence, state_value, key)
        _write_private_bytes(
            paths.evidence / "finalized.json",
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "finalized",
                    "authorization_files_removed": sorted(AUTH_INVENTORY),
                    "protected_roots_preserved": True,
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
            exclusive=True,
        )
    except BaseException:
        if deletion_started:
            _write_private_bytes(
                paths.evidence / "FINALIZATION-PARTIAL-FAILURE.txt",
                b"Final deletion began but did not reach a verified success state.\n",
                exclusive=not (paths.evidence / "FINALIZATION-PARTIAL-FAILURE.txt").exists(),
            )
        raise


def _install_signal_failures() -> None:
    def interrupted(signum: int, _frame: object) -> None:
        raise CleanupError(f"cleanup interrupted by signal {signum}")

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)


def _usage() -> None:
    print(
        "Usage: cleanup-hf-ardy-authorization.py "
        "{quarantine|finalize} WORKSPACE_ROOT PRIVATE_EVIDENCE_DIR",
        file=sys.stderr,
    )


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in {"quarantine", "finalize"}:
        _usage()
        return 64
    if sys.platform != "linux" or platform.machine() != "aarch64":
        print("error: cleanup requires Linux/aarch64 on DGX Spark", file=sys.stderr)
        return 1
    if os.geteuid() == 0:
        print("error: run cleanup as the normal workspace owner, not root", file=sys.stderr)
        return 1
    for command in ("docker", "ss"):
        if not any(
            os.access(Path(directory) / command, os.X_OK)
            for directory in os.environ.get("PATH", "").split(os.pathsep)
            if directory
        ):
            print(f"error: missing command: {command}", file=sys.stderr)
            return 1
    os.umask(0o077)
    _install_signal_failures()
    repository = Path(__file__).resolve().parent.parent
    try:
        paths = resolve_paths(
            repository,
            sys.argv[2],
            sys.argv[3],
            evidence_must_exist=sys.argv[1] == "finalize",
        )
        with acquire_cleanup_locks(os.getuid()):
            if sys.argv[1] == "quarantine":
                quarantine_authorization(paths, CommandRunner())
                print(
                    "Temporary Hugging Face authorization is quarantined and the isolated "
                    "ARDY canary passed. Revoke the temporary OAuth grant server-side, then "
                    "run the explicit finalize command with the same paths."
                )
            else:
                finalize_authorization(paths, CommandRunner())
                print(
                    "Temporary local Hugging Face authorization was removed. Confirm the "
                    "temporary OAuth grant is also revoked in Hugging Face settings."
                )
    except (CleanupError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

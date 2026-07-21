#!/usr/bin/env python3
"""Validate and expose the reviewed Fay character profiles.

The same fail-closed configuration drives runtime selection, cooking, and
package verification.  This helper deliberately supports only the virtual
content roots used by the reviewed UE 5.8 MetaHuman pipeline.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA = 1
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
ACTOR_PATTERN = re.compile(
    r"^/Game/FayMetaHumans/Built/[A-Za-z][A-Za-z0-9_-]{0,63}/"
    r"BP_[A-Za-z][A-Za-z0-9_-]{0,63}\.BP_[A-Za-z][A-Za-z0-9_-]{0,63}_C$"
)
PACKAGE_ASSET_PATTERN = re.compile(
    r"^FayAvatarRuntime/Content/FayMetaHumans/Built/"
    r"[A-Za-z][A-Za-z0-9_-]{0,63}/BP_[A-Za-z][A-Za-z0-9_-]{0,63}\.uasset$"
)


class ProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class CharacterProfile:
    id: str
    actor_class: str
    adapter: str
    face_component: str
    body_component: str
    spawn_location: str
    spawn_rotation: str
    camera_location: str
    camera_rotation: str
    camera_fov: float
    cook_directories: tuple[str, ...]
    project_asset: str
    package_asset: str


def split_list(value: str, label: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(";") if part.strip())
    if not values:
        raise ProfileError(f"{label} must contain at least one value")
    if len(values) != len(set(values)):
        raise ProfileError(f"{label} contains a duplicate value")
    return values


def require_simple_name(value: str, label: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ProfileError(f"{label} is not a reviewed identifier")
    return value


def load_profiles(config_path: Path) -> tuple[str, dict[str, CharacterProfile], str]:
    config_path = config_path.resolve(strict=True)
    if not config_path.is_file() or config_path.is_symlink():
        raise ProfileError("character configuration must be a regular file")

    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    with config_path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)

    if not parser.has_section("FayAvatar"):
        raise ProfileError("DefaultGame.ini has no [FayAvatar] section")
    default_id = require_simple_name(
        parser.get("FayAvatar", "DefaultCharacter", fallback="").strip(),
        "DefaultCharacter",
    )

    profiles: dict[str, CharacterProfile] = {}
    prefix = "FayCharacter."
    for section in parser.sections():
        if not section.startswith(prefix):
            continue
        character_id = require_simple_name(section[len(prefix) :], "character ID")
        if character_id in profiles:
            raise ProfileError(f"duplicate character profile: {character_id}")

        def required(key: str) -> str:
            value = parser.get(section, key, fallback="").strip()
            if not value:
                raise ProfileError(f"[{section}] is missing {key}")
            return value

        actor_class = required("ActorClass")
        if not ACTOR_PATTERN.fullmatch(actor_class):
            raise ProfileError(f"[{section}] ActorClass is outside the reviewed asset root")
        adapter = required("Adapter")
        if adapter != "UE58MetaHuman":
            raise ProfileError(f"[{section}] uses unsupported adapter {adapter!r}")
        face_component = require_simple_name(required("FaceComponent"), "FaceComponent")
        body_component = require_simple_name(required("BodyComponent"), "BodyComponent")
        if (face_component, body_component) != ("Face", "Body"):
            raise ProfileError(
                f"[{section}] UE58MetaHuman requires exact Face and Body components"
            )
        try:
            camera_fov = float(required("CameraFieldOfView"))
        except ValueError as exc:
            raise ProfileError(f"[{section}] CameraFieldOfView is not numeric") from exc
        if not 20.0 <= camera_fov <= 90.0:
            raise ProfileError(f"[{section}] CameraFieldOfView is outside 20-90 degrees")

        cook_directories = split_list(required("CookDirectories"), f"[{section}] CookDirectories")
        for directory in cook_directories:
            if not (
                directory.startswith("/Game/FayMetaHumans/Built/")
                or directory == "/Game/FayMetaHumans/Common_UE58"
                or directory == "/StreamingADA"
            ):
                raise ProfileError(
                    f"[{section}] cook directory is outside the reviewed roots: {directory}"
                )

        project_asset = required("ProjectAsset")
        project_path = Path(project_asset)
        if (
            project_path.is_absolute()
            or ".." in project_path.parts
            or project_path.suffix != ".uasset"
            or not project_asset.startswith("Content/FayMetaHumans/Built/")
        ):
            raise ProfileError(f"[{section}] ProjectAsset is unsafe")
        package_asset = required("PackageAsset")
        if not PACKAGE_ASSET_PATTERN.fullmatch(package_asset):
            raise ProfileError(f"[{section}] PackageAsset is outside the reviewed package root")

        profiles[character_id] = CharacterProfile(
            id=character_id,
            actor_class=actor_class,
            adapter=adapter,
            face_component=face_component,
            body_component=body_component,
            spawn_location=required("SpawnLocation"),
            spawn_rotation=required("SpawnRotation"),
            camera_location=required("CameraRelativeLocation"),
            camera_rotation=required("CameraRelativeRotation"),
            camera_fov=camera_fov,
            cook_directories=cook_directories,
            project_asset=project_asset,
            package_asset=package_asset,
        )

    if not profiles:
        raise ProfileError("DefaultGame.ini contains no character profiles")
    if default_id not in profiles:
        raise ProfileError("DefaultCharacter does not name a reviewed profile")
    config_digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    return default_id, profiles, config_digest


def selected_profiles(
    default_id: str,
    profiles: dict[str, CharacterProfile],
    requested_ids: list[str],
) -> list[CharacterProfile]:
    ids = requested_ids or [default_id]
    result: list[CharacterProfile] = []
    seen: set[str] = set()
    for character_id in ids:
        require_simple_name(character_id, "requested character ID")
        if character_id not in profiles:
            raise ProfileError(f"unknown reviewed character profile: {character_id}")
        if character_id not in seen:
            result.append(profiles[character_id])
            seen.add(character_id)
    return result


def virtual_to_physical(directory: str, project: Path, engine: Path) -> Path:
    if directory.startswith("/Game/"):
        return project.parent / "Content" / directory.removeprefix("/Game/")
    if directory == "/StreamingADA":
        return (
            engine
            / "Engine/Plugins/Animation/AudioDrivenAnimation/StreamingADA/Content"
        )
    raise ProfileError(f"unsupported virtual cook root: {directory}")


def validate_physical_path(path: Path, anchor: Path, label: str) -> Path:
    anchor = anchor.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    if not lexical.is_relative_to(anchor):
        raise ProfileError(f"{label} escapes its reviewed root")
    current = anchor
    for component in lexical.relative_to(anchor).parts:
        current /= component
        if current.is_symlink():
            raise ProfileError(f"{label} contains a symlinked path component")
    if not lexical.is_dir():
        raise ProfileError(f"{label} is missing: {lexical}")
    return lexical


def manifest_payload(
    config_digest: str,
    profiles: list[CharacterProfile],
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "profileConfigSha256": config_digest,
        "characters": [
            {
                "id": profile.id,
                "adapter": profile.adapter,
                "actorClass": profile.actor_class,
                "packageAsset": profile.package_asset,
            }
            for profile in profiles
        ],
    }


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path = Path(os.path.abspath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--character", action="append", default=[])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("default")
    subparsers.add_parser("json")
    paths = subparsers.add_parser("cook-paths")
    paths.add_argument("--project", required=True, type=Path)
    paths.add_argument("--engine", required=True, type=Path)
    assets = subparsers.add_parser("project-assets")
    assets.add_argument("--project", required=True, type=Path)
    subparsers.add_parser("package-assets")
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    default_id, all_profiles, config_digest = load_profiles(args.config)
    profiles = selected_profiles(default_id, all_profiles, args.character)

    if args.command == "validate":
        print(f"validated {len(all_profiles)} profile(s); default={default_id}")
    elif args.command == "default":
        print(default_id)
    elif args.command == "json":
        print(json.dumps([asdict(profile) for profile in profiles], indent=2))
    elif args.command == "cook-paths":
        project = args.project.resolve(strict=True)
        engine = args.engine.resolve(strict=True)
        if not project.is_file() or project.suffix != ".uproject":
            raise ProfileError("--project must name an existing .uproject")
        directories: list[str] = []
        for profile in profiles:
            for virtual in profile.cook_directories:
                physical = virtual_to_physical(virtual, project, engine)
                anchor = project.parent if virtual.startswith("/Game/") else engine
                resolved = validate_physical_path(physical, anchor, "cook directory")
                value = str(resolved)
                if value not in directories:
                    directories.append(value)
        print("\n".join(directories))
    elif args.command == "project-assets":
        project = args.project.resolve(strict=True)
        for profile in profiles:
            asset = Path(os.path.abspath(project.parent / profile.project_asset))
            if not asset.is_relative_to(project.parent):
                raise ProfileError("project asset escapes the project root")
            print(asset)
    elif args.command == "package-assets":
        print("\n".join(profile.package_asset for profile in profiles))
    elif args.command == "manifest":
        atomic_json(args.output, manifest_payload(config_digest, profiles))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ProfileError, configparser.Error) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        raise SystemExit(1)

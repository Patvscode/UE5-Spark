#!/usr/bin/env python3
"""Validate and expose the reviewed Fay character profiles.

The same fail-closed configuration drives runtime selection, cooking, and
package verification.  This helper deliberately supports only the virtual
content roots used by reviewed character adapters.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA = 2
DEFAULT_CAMERA_FRAMING = "Portrait"
CAMERA_FRAMING_IDS = (DEFAULT_CAMERA_FRAMING, "FullBody")
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
UNREAL_DECIMAL = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
UNREAL_VECTOR_PATTERN = re.compile(
    rf"X=({UNREAL_DECIMAL}) Y=({UNREAL_DECIMAL}) Z=({UNREAL_DECIMAL})"
)
UNREAL_ROTATOR_PATTERN = re.compile(
    rf"P=({UNREAL_DECIMAL}) Y=({UNREAL_DECIMAL}) R=({UNREAL_DECIMAL})"
)
METAHUMAN_ACTOR_PATTERN = re.compile(
    r"^/Game/FayMetaHumans/Built/[A-Za-z][A-Za-z0-9_-]{0,63}/"
    r"BP_[A-Za-z][A-Za-z0-9_-]{0,63}\.BP_[A-Za-z][A-Za-z0-9_-]{0,63}_C$"
)
METAHUMAN_PACKAGE_ASSET_PATTERN = re.compile(
    r"^FayAvatarRuntime/Content/FayMetaHumans/Built/"
    r"[A-Za-z][A-Za-z0-9_-]{0,63}/BP_[A-Za-z][A-Za-z0-9_-]{0,63}\.uasset$"
)
METAHUMAN_ADAPTER = "UE58MetaHuman"
EPIC_ARKIT_ADAPTER = "UE5EpicArkit"
EPIC_ARKIT_ACTOR_CLASS = "/Script/FayAvatarRuntime.FayCasualGirlActor"
EPIC_ARKIT_COOK_ROOT = "/Game/Sample"
EPIC_ARKIT_PROJECT_ASSET = "Content/Sample/Meshes/SK_Complete.uasset"
EPIC_ARKIT_PACKAGE_ASSET = (
    "FayAvatarRuntime/Content/Sample/Meshes/SK_Complete.uasset"
)


class ProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class CameraFramingProfile:
    id: str
    location: str
    rotation: str
    field_of_view: float


@dataclass(frozen=True)
class CharacterProfile:
    id: str
    actor_class: str
    adapter: str
    face_component: str
    body_component: str
    spawn_location: str
    spawn_rotation: str
    camera_framings: tuple[CameraFramingProfile, ...]
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


def require_unreal_transform(
    value: str,
    label: str,
    pattern: re.Pattern[str],
    syntax: str,
) -> str:
    match = pattern.fullmatch(value)
    if match is None or not all(
        math.isfinite(float(component)) for component in match.groups()
    ):
        raise ProfileError(f"{label} must use exact reviewed Unreal syntax: {syntax}")
    return value


def require_unreal_vector(value: str, label: str) -> str:
    return require_unreal_transform(
        value,
        label,
        UNREAL_VECTOR_PATTERN,
        "X=<decimal> Y=<decimal> Z=<decimal>",
    )


def require_unreal_rotator(value: str, label: str) -> str:
    return require_unreal_transform(
        value,
        label,
        UNREAL_ROTATOR_PATTERN,
        "P=<decimal> Y=<decimal> R=<decimal>",
    )


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
    default_camera_framing = parser.get(
        "FayAvatar", "DefaultCameraFraming", fallback=""
    ).strip()
    if default_camera_framing != DEFAULT_CAMERA_FRAMING:
        raise ProfileError("DefaultCameraFraming must be the reviewed Portrait preset")

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

        adapter = required("Adapter")
        if adapter not in (METAHUMAN_ADAPTER, EPIC_ARKIT_ADAPTER):
            raise ProfileError(f"[{section}] uses unsupported adapter {adapter!r}")
        actor_class = required("ActorClass")
        if adapter == METAHUMAN_ADAPTER:
            if not METAHUMAN_ACTOR_PATTERN.fullmatch(actor_class):
                raise ProfileError(
                    f"[{section}] ActorClass is outside the reviewed asset root"
                )
        elif actor_class != EPIC_ARKIT_ACTOR_CLASS:
            raise ProfileError(
                f"[{section}] ActorClass is not the reviewed UE5EpicArkit asset"
            )
        face_component = require_simple_name(required("FaceComponent"), "FaceComponent")
        body_component = require_simple_name(required("BodyComponent"), "BodyComponent")
        expected_components = (
            ("Face", "Body")
            if adapter == METAHUMAN_ADAPTER
            else ("Body", "Body")
        )
        if (face_component, body_component) != expected_components:
            raise ProfileError(
                f"[{section}] {adapter} requires exact reviewed face/body components"
            )
        spawn_location = require_unreal_vector(
            required("SpawnLocation"), f"[{section}] SpawnLocation"
        )
        spawn_rotation = require_unreal_rotator(
            required("SpawnRotation"), f"[{section}] SpawnRotation"
        )
        camera_framings: list[CameraFramingProfile] = []
        for framing_id in CAMERA_FRAMING_IDS:
            key_prefix = f"Camera{framing_id}"
            try:
                field_of_view = float(required(f"{key_prefix}FieldOfView"))
            except ValueError as exc:
                raise ProfileError(
                    f"[{section}] {key_prefix}FieldOfView is not numeric"
                ) from exc
            if not 20.0 <= field_of_view <= 90.0:
                raise ProfileError(
                    f"[{section}] {key_prefix}FieldOfView is outside 20-90 degrees"
                )
            camera_framings.append(
                CameraFramingProfile(
                    id=framing_id,
                    location=require_unreal_vector(
                        required(f"{key_prefix}RelativeLocation"),
                        f"[{section}] {key_prefix}RelativeLocation",
                    ),
                    rotation=require_unreal_rotator(
                        required(f"{key_prefix}RelativeRotation"),
                        f"[{section}] {key_prefix}RelativeRotation",
                    ),
                    field_of_view=field_of_view,
                )
            )

        cook_directories = split_list(required("CookDirectories"), f"[{section}] CookDirectories")
        if adapter == METAHUMAN_ADAPTER:
            for directory in cook_directories:
                if not (
                    directory.startswith("/Game/FayMetaHumans/Built/")
                    or directory == "/Game/FayMetaHumans/Common_UE58"
                    or directory == "/StreamingADA"
                ):
                    raise ProfileError(
                        f"[{section}] cook directory is outside the reviewed roots: {directory}"
                    )
        else:
            allowed_cook_directories = {EPIC_ARKIT_COOK_ROOT, "/StreamingADA"}
            if EPIC_ARKIT_COOK_ROOT not in cook_directories:
                raise ProfileError(
                    f"[{section}] UE5EpicArkit requires {EPIC_ARKIT_COOK_ROOT}"
                )
            for directory in cook_directories:
                if directory not in allowed_cook_directories:
                    raise ProfileError(
                        f"[{section}] cook directory is outside the reviewed roots: {directory}"
                    )

        project_asset = required("ProjectAsset")
        if adapter == METAHUMAN_ADAPTER:
            project_path = Path(project_asset)
            if (
                project_path.is_absolute()
                or ".." in project_path.parts
                or project_path.suffix != ".uasset"
                or not project_asset.startswith("Content/FayMetaHumans/Built/")
            ):
                raise ProfileError(f"[{section}] ProjectAsset is unsafe")
        elif project_asset != EPIC_ARKIT_PROJECT_ASSET:
            raise ProfileError(
                f"[{section}] ProjectAsset is not the reviewed UE5EpicArkit asset"
            )
        package_asset = required("PackageAsset")
        if adapter == METAHUMAN_ADAPTER:
            if not METAHUMAN_PACKAGE_ASSET_PATTERN.fullmatch(package_asset):
                raise ProfileError(
                    f"[{section}] PackageAsset is outside the reviewed package root"
                )
        elif package_asset != EPIC_ARKIT_PACKAGE_ASSET:
            raise ProfileError(
                f"[{section}] PackageAsset is not the reviewed UE5EpicArkit asset"
            )

        profiles[character_id] = CharacterProfile(
            id=character_id,
            actor_class=actor_class,
            adapter=adapter,
            face_component=face_component,
            body_component=body_component,
            spawn_location=spawn_location,
            spawn_rotation=spawn_rotation,
            camera_framings=tuple(camera_framings),
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
        "defaultCameraFraming": DEFAULT_CAMERA_FRAMING,
        "characters": [
            {
                "id": profile.id,
                "adapter": profile.adapter,
                "actorClass": profile.actor_class,
                "packageAsset": profile.package_asset,
                "cameraFramings": [
                    framing.id for framing in profile.camera_framings
                ],
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

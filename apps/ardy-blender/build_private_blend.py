#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Build a private Blender scene containing both supported ARDY characters.

Run with Blender, not regular Python:

  blender --background --factory-startup --python build_private_blend.py -- \
    --nvidia-skin /private/ardy/cskel27/skin_standard.npz \
    --casual-fbx-root /private/casual-girl/fbx \
    --casual-manifest-root /private/casual-girl/npz \
    --output /staging/ardy-characters.blend
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import bpy


APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ardy_blender import blender_adapter  # noqa: E402


def _arguments() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--nvidia-skin",
        default=os.environ.get("ARDY_NVIDIA_SKIN", ""),
    )
    parser.add_argument(
        "--casual-fbx-root",
        default=os.environ.get("ARDY_CASUAL_GIRL_FBX_ROOT", ""),
    )
    parser.add_argument(
        "--casual-body-fbx",
        default=os.environ.get("ARDY_CASUAL_GIRL_BODY_FBX", ""),
    )
    parser.add_argument(
        "--casual-manifest-root",
        default=os.environ.get("ARDY_CASUAL_GIRL_MANIFEST_ROOT", ""),
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="explicitly replace an existing private .blend output",
    )
    return parser.parse_args(raw)


def main() -> int:
    args = _arguments()
    output = Path(args.output).expanduser()
    if output.suffix.casefold() != ".blend":
        raise SystemExit("--output must end in .blend")
    if not output.parent.is_dir():
        raise SystemExit("--output parent must already exist")
    if output.exists() and not args.replace_output:
        raise SystemExit("output already exists; use --replace-output explicitly")
    if not args.nvidia_skin:
        raise SystemExit("--nvidia-skin is required")
    if not args.casual_fbx_root and not args.casual_manifest_root:
        raise SystemExit("Casual Girl needs --casual-fbx-root or --casual-manifest-root")

    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in tuple(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene["ardy_adapter_version"] = "1.0.0"
    scene["ardy_blender_target"] = "4.0.2+"

    blender_adapter.load_nvidia_skin(args.nvidia_skin)
    blender_adapter.load_casual(
        fbx_root=args.casual_fbx_root or None,
        manifest_root=args.casual_manifest_root or None,
        body_fbx=args.casual_body_fbx or None,
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(output.resolve()), check_existing=False)
    print(f"ARDY private Blender scene written: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

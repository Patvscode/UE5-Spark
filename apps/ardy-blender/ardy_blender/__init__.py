# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Blender-native ARDY character adapter."""

bl_info = {
    "name": "ARDY Character Adapter",
    "author": "UE5-Spark",
    "version": (1, 1, 0),
    "blender": (4, 0, 2),
    "location": "View3D > Sidebar > ARDY",
    "description": "Rig Core27/Casual Girl and preview real prompt-driven ARDY motion",
    "category": "Rigging",
}


def register():
    from . import blender_adapter

    blender_adapter.register()


def unregister():
    from . import blender_adapter

    blender_adapter.unregister()

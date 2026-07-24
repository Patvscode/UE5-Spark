# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT
#
# This module extends NVIDIA's Apache-2.0 ARDY Interactive Demo without
# modifying the pinned vendor source.

"""Two-character project overlay for NVIDIA's official ARDY Viser demo."""

from __future__ import annotations

import argparse
import os

from interactive_demo.common import VelocityArrowMesh
from run_demo import InteractiveTimelineDemo as NvidiaInteractiveTimelineDemo

from casual_girl import CasualGirlCharacter
from wardrobe import load_manifest

NVIDIA_ORIGINAL = "NVIDIA Original"
CASUAL_GIRL = "Casual Girl"
CHARACTER_OPTIONS = (NVIDIA_ORIGINAL, CASUAL_GIRL)


class ProjectInteractiveTimelineDemo(NvidiaInteractiveTimelineDemo):
    def __init__(self, *, wardrobe_root: str, compile_model: bool = False):
        self.wardrobe_manifest = load_manifest(wardrobe_root)
        super().__init__(compile_model=compile_model)

    def create_gui(self, client, constraint_tracks):
        gui_elements, timeline_tracks, timeline_data = super().create_gui(client, constraint_tracks)
        # Casual Girl is exported against Core27. Keep NVIDIA's official
        # Horizon8/Horizon40 choice, but prevent an incompatible G1/SOMA
        # skeleton from being loaded into this two-character lab.
        gui_elements.gui_skeleton_dropdown.options = ["Core"]
        gui_elements.gui_skeleton_dropdown.value = "Core"
        gui_elements.gui_skeleton_dropdown.disabled = True

        with client.gui.add_folder("Character & Wardrobe", expand_by_default=True):
            character = client.gui.add_dropdown(
                "Character",
                options=CHARACTER_OPTIONS,
                initial_value=CASUAL_GIRL,
                hint="This lab intentionally contains only NVIDIA Original and Casual Girl.",
            )
            client.gui.add_markdown(
                "Casual Girl pieces share the live ARDY pose. Choose **None** to remove a category."
            )
            controls = {}
            option_ids = {}
            labels = {
                "hair": "Hair",
                "top": "Top",
                "bottom": "Bottom",
                "feet": "Footwear",
                "underwear": "Underwear",
                "body": "Body / base",
            }
            for category in ("hair", "top", "bottom", "feet", "underwear", "body"):
                part_ids = self.wardrobe_manifest.options(category)
                category_options = {
                    self.wardrobe_manifest.parts[part_id].label: part_id
                    for part_id in part_ids
                }
                option_ids[category] = category_options
                options = ["None", *category_options]
                raw_default = self.wardrobe_manifest.defaults.get(category)
                if isinstance(raw_default, bool):
                    default_id = part_ids[0] if raw_default and part_ids else None
                else:
                    default_id = raw_default if raw_default in part_ids else None
                default = (
                    self.wardrobe_manifest.parts[default_id].label
                    if default_id is not None
                    else "None"
                )
                controls[category] = client.gui.add_dropdown(
                    labels[category],
                    options=options,
                    initial_value=default,
                )

        gui_elements.project_character = character
        gui_elements.project_wardrobe = controls
        gui_elements.project_wardrobe_option_ids = option_ids

        def refresh_control_state() -> None:
            enabled = character.value == CASUAL_GIRL
            for control in controls.values():
                control.disabled = not enabled

        @character.on_update
        def _(_event) -> None:
            refresh_control_state()
            if not self.client_active(client.client_id):
                return
            self._replace_characters(client.client_id)

        for category, control in controls.items():
            @control.on_update
            def _(_event, category=category, control=control) -> None:
                if not self.client_active(client.client_id):
                    return
                selected = option_ids[category].get(control.value)
                session = self.client_sessions[client.client_id]
                with session.characters_lock:
                    for active_character in session.characters.values():
                        if isinstance(active_character, CasualGirlCharacter):
                            active_character.set_wardrobe(category, selected)

        refresh_control_state()
        return gui_elements, timeline_tracks, timeline_data

    def _replace_characters(self, client_id: int) -> None:
        if not self.client_active(client_id):
            return
        session = self.client_sessions[client_id]
        with session.characters_lock:
            count = len(session.characters)
            old = list(session.characters.values())
            session.characters.clear()
            for character in old:
                character.clear()
        if count == 0 or session.motion_rep is None:
            session.client.add_notification(
                title="Character selected",
                body="The selection will be used when motion is generated.",
                color="blue",
                auto_close_seconds=2.0,
            )
            return
        for index in range(count):
            self.add_character(client_id, session.motion_rep.skeleton, index)
        if session.frame_idx >= 0 and session.frame_idx <= session.max_frame_idx:
            self.set_frame(client_id, session.frame_idx)
        session.client.add_notification(
            title="Character changed",
            body=f"Now showing {session.gui_elements.project_character.value}",
            color="green",
            auto_close_seconds=2.0,
        )

    def add_character(self, client_id: int, skeleton, index: int):
        if not self.client_active(client_id):
            return
        session = self.client_sessions[client_id]
        selected = session.gui_elements.project_character.value
        if selected == NVIDIA_ORIGINAL:
            return super().add_character(client_id, skeleton, index)

        character_name = f"character{index}"
        new_character = CasualGirlCharacter(
            character_name,
            session.client,
            skeleton,
            create_skeleton_mesh=True,
            visible_skeleton=session.gui_elements.gui_viz_skeleton_checkbox.value,
            visible_skinned_mesh=session.gui_elements.gui_viz_skinned_mesh_checkbox.value,
            skinned_mesh_opacity=session.gui_elements.gui_viz_skinned_mesh_opacity_slider.value,
            show_foot_contacts=session.gui_elements.gui_viz_foot_contacts_checkbox.value,
            dark_mode=session.gui_elements.gui_dark_mode_checkbox.value,
            mesh_mode="core_skin",
            show_root_2d_projection=True,
            wardrobe_manifest=self.wardrobe_manifest,
        )
        controls = session.gui_elements.project_wardrobe
        for category, control in controls.items():
            selected = session.gui_elements.project_wardrobe_option_ids[category].get(
                control.value
            )
            new_character.set_wardrobe(category, selected)
        with session.characters_lock:
            session.characters[character_name] = new_character

        if index == 0 and session.target_velocity_arrow is None:
            session.target_velocity_arrow = VelocityArrowMesh(
                name=f"target_velocity_{client_id}",
                server=session.client,
                skeleton=skeleton,
                color=(255, 100, 0),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="ARDY Viser Character Lab")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument(
        "--wardrobe-root",
        default=os.environ.get("CASUAL_GIRL_ROOT", "/characters/casual-girl"),
    )
    args = parser.parse_args()
    demo = ProjectInteractiveTimelineDemo(
        wardrobe_root=args.wardrobe_root,
        compile_model=not args.no_compile,
    )
    demo.run()


if __name__ == "__main__":
    main()

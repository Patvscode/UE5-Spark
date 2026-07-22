from __future__ import annotations

import json
import os
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "staging/fab-acquisition-template"


class FexFabStagingContractTests(unittest.TestCase):
    def test_staging_descriptor_is_content_only_and_fab_only(self) -> None:
        project = json.loads(
            (TEMPLATE_ROOT / "FayFabAcquisition.uproject").read_text(encoding="utf-8")
        )
        self.assertIs(project.get("DisableEnginePluginsByDefault"), True)
        self.assertNotIn("Modules", project)
        self.assertEqual(
            project.get("Plugins"),
            [{"Name": "Fab", "Enabled": True, "TargetAllowList": ["Editor"]}],
        )

    def test_runtime_project_does_not_enable_fab(self) -> None:
        runtime = json.loads(
            (REPO_ROOT / "Project/FayAvatarRuntime/FayAvatarRuntime.uproject").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("Fab", {item.get("Name") for item in runtime.get("Plugins", [])})

    def test_project_build_steps_cannot_match_reviewed_descriptor(self) -> None:
        template_path = TEMPLATE_ROOT / "FayFabAcquisition.uproject"
        project = json.loads(template_path.read_text(encoding="utf-8"))
        project["PreBuildSteps"] = {"Linux": ["unexpected command"]}
        modified = (json.dumps(project, indent=2) + "\n").encode("utf-8")
        self.assertNotEqual(modified, template_path.read_bytes())
        for wrapper in (
            "scripts/build-fex-fab-staging.sh",
            "scripts/run-fex-fab-staging.sh",
        ):
            source = (REPO_ROOT / wrapper).read_text(encoding="utf-8")
            self.assertIn('cmp -s "$project_template" "$project"', source)

    def test_launch_wrapper_keeps_state_private_and_requires_seal(self) -> None:
        source = (REPO_ROOT / "scripts/run-fex-fab-staging.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            'python3 "$manifest_tool" verify',
            'export HOME="$private_state/home"',
            'export XDG_CONFIG_HOME="$private_state/config"',
            'export XDG_CACHE_HOME="$private_state/cache"',
            'export XDG_DATA_HOME="$private_state/data"',
            'export XDG_STATE_HOME="$private_state/state"',
            'grep -qx \'# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V3\'',
            '-onethread',
            '-norhithread',
            '>"$log" 2>&1',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("-unattended", source)
        self.assertNotIn("| tee", source)
        self.assertIn('for forbidden in Source Plugins; do', source)
        self.assertIn('cmp -s "$project_template" "$project"', source)

    def test_launch_wrapper_exposes_only_reviewed_listing_action(self) -> None:
        source = (REPO_ROOT / "scripts/run-fex-fab-staging.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("fab_action=${UE5_SPARK_FAB_ACTION:-none}", source)
        self.assertIn("casual-girl)", source)
        self.assertIn("fab_exec_command='Fab.OpenReviewedCasualGirl'", source)
        self.assertIn('editor_args+=("-ExecCmds=$fab_exec_command")', source)
        self.assertIn("must be none or casual-girl", source)
        self.assertNotIn('editor_args+=("-ExecCmds=$UE5_SPARK_FAB_ACTION")', source)

    def test_reviewed_listing_installer_is_fixed_reversible_and_isolated(self) -> None:
        installer = REPO_ROOT / "scripts/install-fex-fab-reviewed-listing-command.sh"
        source = installer.read_text(encoding="utf-8")
        self.assertTrue(os.access(installer, os.X_OK))
        for marker in (
            "0b76f9e4abf8286daa87cd46d63529cacb168fb754c4a3db4e398c0bcb2aaeee",
            "Fab.OpenReviewedCasualGirl",
            "https://www.fab.com/plugins/ue5/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300",
            'FFabBrowser::OpenInNewTab(ListingUrl);',
            'backup_root="$private_root/fab-listing-command-backup"',
            'cp -p "$source_backup" "$source_file"',
            'cp -p "$binary_backup" "$fab_binary"',
            'cp -p "$modules_backup" "$fab_modules"',
            'systemctl --user is-active ue5-spark-avatar-live.service',
            '"$builder" "$workspace" "$engine_root" "$project"',
            "verify_binary_literals",
            '("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("FFabBrowser::GetUrl()", source)
        self.assertNotIn("FConsoleCommandWithArgsDelegate", source)

    def test_read_only_review_wrapper_is_sealed_and_disables_fab(self) -> None:
        wrapper = REPO_ROOT / "scripts/run-fex-fab-review.sh"
        source = wrapper.read_text(encoding="utf-8")
        self.assertTrue(os.access(wrapper, os.X_OK))
        for marker in (
            'python3 "$manifest_tool" verify',
            'cmp -s "$project_template" "$project"',
            "-EnablePlugins=PythonScriptPlugin,EditorScriptingUtilities",
            "-DisablePlugins=Fab",
            "-run=pythonscript",
            'export FAY_FAB_STAGING_BASELINE_VERIFIED=1',
            "FAY_FAB_INVENTORY_COMPLETE=OK",
            "systemctl --user is-active ue5-spark-avatar-live.service",
            '-nullrhi',
            '>"$log" 2>&1',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("UE5_SPARK_FAB_ACTION", source)
        self.assertNotIn("-ExecutePythonScript", source)

    def test_casual_girl_inventory_is_fixed_and_read_only(self) -> None:
        source = (REPO_ROOT / "scripts/inspect-fab-casual-girl.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            'SOURCE_ROOT = "/Game/Sample"',
            '"BP_ThirdPersonCharacter"',
            '"SK_Body"',
            '"SK_Complete"',
            '"SK_Underwear"',
            '"Sk_Arms"',
            '"Sk_Legs"',
            'emit("FULLY_UNCLOTHED", "disabled")',
            'emit("NOAI_BOUNDARY", "deterministic_retarget_only")',
            'emit("COMPLETE", "OK")',
            "dirty_packages() != dirty_before",
        ):
            self.assertIn(marker, source)
        for mutation in (
            "save_asset(",
            "save_directory(",
            "rename_asset(",
            "rename_directory(",
            "duplicate_asset(",
            "delete_asset(",
            "export_assets(",
        ):
            self.assertNotIn(mutation, source)

    def test_build_wrapper_targets_generic_editor_not_live_project(self) -> None:
        source = (REPO_ROOT / "scripts/build-fex-fab-staging.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$dotnet" "$ubt" UnrealEditor Linux Development', source)
        self.assertIn("-SkipBuild -NoUBA -NoDumpSyms", source)
        self.assertIn(
            '-Module=Fab -NoUBA -NoDumpSyms -MaxParallelActions="$parallel_actions"',
            source,
        )
        self.assertIn('"$dotnet" "$ubt" -Mode=WriteMetadata', source)
        self.assertIn('metadata_tool="$script_dir/fab-module-metadata.py"', source)
        self.assertIn('for forbidden in Source Plugins; do', source)
        self.assertIn('cmp -s "$project_template" "$project"', source)
        self.assertIn("did not include exactly one Fab module", source)
        self.assertIn('fab_binary="$engine_root/Engine/Plugins/Fab/Binaries/Linux/', source)
        self.assertNotIn("FayAvatarRuntimeEditor", source)


if __name__ == "__main__":
    unittest.main()

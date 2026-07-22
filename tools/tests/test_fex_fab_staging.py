from __future__ import annotations

import json
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

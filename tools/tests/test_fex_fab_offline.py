from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
OFFLINE_TEMPLATE = REPO_ROOT / "staging/fab-offline-template/FayFabAcquisition.uproject"
CONTENT_MANIFEST_PATH = REPO_ROOT / "scripts/fab-content-manifest.py"
ROOTLESS_RUNNER = REPO_ROOT / "scripts/run-fex-rootless.sh"


def load_content_manifest_module():
    spec = importlib.util.spec_from_file_location(
        "fab_content_manifest", CONTENT_MANIFEST_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FabOfflineContractTests(unittest.TestCase):
    def test_offline_descriptor_disables_fab_and_enables_fixed_tools(self) -> None:
        project = json.loads(OFFLINE_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIs(project.get("DisableEnginePluginsByDefault"), True)
        self.assertNotIn("Modules", project)
        self.assertEqual(
            project.get("Plugins"),
            [
                {"Name": "Fab", "Enabled": False, "TargetAllowList": ["Editor"]},
                {
                    "Name": "PythonScriptPlugin",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
                {
                    "Name": "EditorScriptingUtilities",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
                {
                    "Name": "ChaosCloth",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
            ],
        )

    def test_content_manifest_detects_content_changes_and_symlinks(self) -> None:
        module = load_content_manifest_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "FayFabAcquisition"
            content = root / "Content/Sample"
            content.mkdir(parents=True)
            (root / "FayFabAcquisition.uproject").write_text("{}\n", encoding="utf-8")
            asset = content / "SK_Body.uasset"
            asset.write_bytes(b"first")
            manifest = Path(temporary) / "content.json"
            module.create(root, manifest)
            module.verify(root, manifest)
            value = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], 2)
            self.assertRegex(value["rootDigestSha256"], r"^[0-9a-f]{64}$")
            asset.write_bytes(b"changed")
            with self.assertRaises(module.ContentManifestError):
                module.verify(root, manifest)
            asset.write_bytes(b"first")
            link = content / "unsafe.uasset"
            try:
                link.symlink_to(asset)
            except OSError:
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(module.ContentManifestError):
                module.snapshot(root)

    def test_content_manifest_replaces_atomically_and_stays_outside_project(self) -> None:
        module = load_content_manifest_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "FayFabAcquisition"
            content = root / "Content"
            content.mkdir(parents=True)
            (root / "FayFabAcquisition.uproject").write_text("{}\n", encoding="utf-8")
            asset = content / "SK_Body.uasset"
            asset.write_bytes(b"first")
            manifest = Path(temporary) / "content.json"
            module.create(root, manifest)
            original = manifest.read_bytes()
            asset.write_bytes(b"second")
            module.create(root, manifest)
            self.assertNotEqual(manifest.read_bytes(), original)
            module.verify(root, manifest)
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(module.ContentManifestError):
                module.create(root, root / "private-content.json")

    def test_transition_is_backed_up_atomic_and_fail_closed(self) -> None:
        script = REPO_ROOT / "scripts/transition-fex-fab-offline.sh"
        source = script.read_text(encoding="utf-8")
        self.assertTrue(os.access(script, os.X_OK))
        for marker in (
            'source "$phase_lock_tool"',
            'fab_phase_lock_acquire "$workspace"',
            'transition_verifier="$script_dir/verify-fab-offline-transition.py"',
            '"$host_python" "$transition_verifier" "${verifier_args[@]}" --review-only',
            '"$host_python" "$non_content_tool" verify',
            '"$host_python" "$non_content_tool" create',
            '"$host_python" "$content_tool" verify',
            'cp -a --reflink=auto "$project_dir/." "$temporary_project/"',
            'cmp -s "$offline_template" "$project"',
            'atomic_replace_descriptor "$offline_template" "$project"',
            'os.replace(temporary, target)',
            'backup="$backup_generation/FayFabAcquisition"',
            'systemctl --user is-active ue5-spark-avatar-live.service',
        ):
            self.assertIn(marker, source)
        self.assertLess(
            source.index('switched=1'),
            source.index('atomic_replace_descriptor "$offline_template" "$project"'),
        )
        self.assertGreaterEqual(
            source.count(
                '"$host_python" "$transition_verifier" "${verifier_args[@]}"'
            ),
            2,
        )
        self.assertNotIn("sudo", source)
        self.assertNotIn("systemctl stop", source)
        self.assertNotIn("systemctl restart", source)
        self.assertNotIn("ln ", source)

    def test_offline_runner_uses_auth_free_state_and_blocks_ip_sockets(self) -> None:
        script = REPO_ROOT / "scripts/run-fex-fab-offline-review.sh"
        source = script.read_text(encoding="utf-8")
        self.assertTrue(os.access(script, os.X_OK))
        for marker in (
            'expected_manifest="$workspace/logs-private/fab-acquisition/offline-before-migration.json"',
            'transition_verifier="$script_dir/verify-fab-offline-transition.py"',
            '--acquisition-manifest "$acquisition_manifest"',
            'source "$phase_lock_tool"',
            'fab_phase_lock_acquire "$workspace"',
            'private_state="$workspace/state/fab-offline"',
            'private_logs="$workspace/logs-private/fab-offline"',
            'offline_fex_state="$private_state/fex"',
            'file -L "$guest_python_host"',
            "sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64",
            'host_docker=/usr/bin/docker',
            '"$host_docker" image inspect',
            "image_architecture == arm64",
            '"$host_docker" run --rm --pull=never',
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            '--user "$container_user"',
            "--tmpfs '/tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777'",
            '--mount "type=bind,src=$script_dir,dst=$script_dir,readonly"',
            '--mount "type=bind,src=$fex_root,dst=$fex_root,readonly"',
            '--mount "type=bind,src=$rootfs_root,dst=$rootfs_root,readonly"',
            '--mount "type=bind,src=$engine_root,dst=$engine_root,readonly"',
            '--mount "type=bind,src=$project_dir,dst=$project_dir,readonly"',
            '--mount "type=bind,src=$project_saved,dst=$project_saved"',
            '--mount "type=bind,src=$project_intermediate,dst=$project_intermediate"',
            '--mount "type=bind,src=$project_ddc,dst=$project_ddc"',
            '--entrypoint /usr/bin/env',
            '"FEX_STATE_ROOT=$offline_fex_state"',
            "FAY_FAB_EXPECT_OFFLINE=1",
            '"$host_python" "$content_tool" verify',
            '"$host_python" "$non_content_tool" verify',
            'fab_phase_lock_exec_without_fd "${docker_base[@]}"',
            '"$runner" "$workspace" -- /usr/bin/python3 -c "$sandbox_probe"',
            'unreachable(socket.AF_INET, ("192.0.2.1", 443), 44, 45)',
            'unreachable(socket.AF_INET6, ("2001:db8::1", 443), 46, 47)',
            '"/run/docker.sock", "/var/run/docker.sock"',
            '"/run/tailscale/tailscaled.sock", "/var/run/tailscale/tailscaled.sock"',
            '"/run/dbus/system_bus_socket"',
            'Path.home() / ".ssh"',
            'forbidden_probe="$project_dir/Content/.fay-offline-forbidden-',
            'state_probe="$offline_fex_state/.fay-offline-state-',
            'generated_probe="$project_saved/.fay-offline-generated-',
            "raise SystemExit(40)",
            "raise SystemExit(48)",
            "write_probe(sys.argv[2], 50)",
            "write_probe(sys.argv[3], 51)",
            "container_name='ue5-spark-fab-offline-review'",
            '"$host_docker" container stop --time 10',
            '"$host_docker" container kill',
            '"$host_docker" container rm --force',
            'else\n        inspect_status=$?\n    fi\n    case $inspect_status in',
            'preflight_log=$(mktemp "$private_state/preflight.XXXXXX.log")',
            '>"$preflight_log" 2>&1',
            'private diagnostics: $preflight_log',
            "trap '' HUP INT TERM",
            "FAY_FAB_INVENTORY_OFFLINE_PLUGINS=OK",
            "FAY_FAB_INVENTORY_COMPLETE=OK",
            "systemctl --user is-active ue5-spark-avatar-live.service",
        ):
            self.assertIn(marker, source)
        self.assertLess(
            source.index('fab_phase_lock_acquire "$workspace"'),
            source.index("process_list=$(ps"),
        )
        sandbox_wrapper = source.split("run_in_offline_sandbox() {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertEqual(sandbox_wrapper.count("\n    ("), 1)
        self.assertIn("fab_phase_lock_exec_without_fd", sandbox_wrapper)
        self.assertNotIn("fab_phase_lock_run_without_fd", source)
        self.assertNotIn("systemd-run", source)
        self.assertNotIn("docker pull", source)
        self.assertNotIn('src=$workspace,dst=$workspace', source)
        self.assertNotIn('src=$private_state,dst=$private_state', source)
        self.assertNotIn('private_state="$workspace/state/fab-acquisition"', source)
        self.assertNotIn("-EnablePlugins=", source)
        self.assertNotIn("-DisablePlugins=", source)
        self.assertNotIn("sudo", source)

    def test_rootless_runner_confines_private_fex_state_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary).resolve()
            workspace = temporary_path / "workspace"
            fex = workspace / "fex-root/usr/bin/FEX"
            guest_uname = workspace / "rootfs/ubuntu-24.04-x86_64/usr/bin/uname"
            fex.parent.mkdir(parents=True)
            guest_uname.parent.mkdir(parents=True)
            guest_uname.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            guest_uname.chmod(0o755)
            fex.write_text(
                "#!/bin/sh\n"
                "printf 'state=%s\\nsocket=%s\\narg1=%s\\narg2=%s\\n' "
                '"$FEX_STATE_ROOT" "$FEX_SERVERSOCKETPATH" "$1" "$2"\n'
                "/usr/bin/env\n",
                encoding="utf-8",
            )
            fex.chmod(0o755)
            private_parent = workspace / "state/fab-offline"
            private_parent.mkdir(parents=True)
            private_state = private_parent / "fex"
            environment = os.environ.copy()
            environment.pop("FEX_THUNKCONFIG", None)
            environment["FEX_STATE_ROOT"] = str(private_state)
            result = subprocess.run(
                [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/python3", "-V"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            self.assertEqual(values["state"], str(private_state))
            self.assertEqual(values["socket"], str(private_state / "fex-server.socket"))
            self.assertEqual(
                values["UE-LocalDataCachePath"], str(private_state / "ue-ddc")
            )
            self.assertEqual(values["arg1"], "/usr/bin/python3")
            self.assertEqual(values["arg2"], "-V")
            for path in (
                private_state,
                private_state / "data",
                private_state / "config",
                private_state / "cache",
                private_state / "ue-ddc",
            ):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)

            shared_state = workspace / "state"
            shared_state.chmod(0o755)
            for child_name in ("data", "config", "cache", "ue-ddc"):
                child = shared_state / child_name
                child.mkdir(mode=0o755)
                child.chmod(0o755)
            environment.pop("FEX_STATE_ROOT")
            shared_result = subprocess.run(
                [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/true"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(shared_result.returncode, 0, shared_result.stderr)
            self.assertEqual(shared_state.stat().st_mode & 0o777, 0o755)
            for child_name in ("data", "config", "cache", "ue-ddc"):
                self.assertEqual(
                    (shared_state / child_name).stat().st_mode & 0o777, 0o755
                )

            outside = temporary_path / "outside"
            outside.mkdir()
            environment["FEX_STATE_ROOT"] = str(outside)
            rejected = subprocess.run(
                [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/true"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("workspace state root", rejected.stderr)

            environment["FEX_STATE_ROOT"] = str(workspace)
            root_rejected = subprocess.run(
                [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/true"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertNotEqual(root_rejected.returncode, 0)
            self.assertIn("workspace state root", root_rejected.stderr)

            environment["FEX_STATE_ROOT"] = str(workspace / "engine-state")
            sibling_rejected = subprocess.run(
                [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/true"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertNotEqual(sibling_rejected.returncode, 0)
            self.assertIn("workspace state root", sibling_rejected.stderr)

            state_link = workspace / "state-link"
            try:
                state_link.symlink_to(outside, target_is_directory=True)
            except OSError:
                pass
            else:
                environment["FEX_STATE_ROOT"] = str(state_link / "fex")
                link_rejected = subprocess.run(
                    [str(ROOTLESS_RUNNER), str(workspace), "--", "/usr/bin/true"],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertNotEqual(link_rejected.returncode, 0)

    def test_acquisition_review_writes_a_hashed_private_receipt(self) -> None:
        source = (REPO_ROOT / "scripts/run-fex-fab-review.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            'receipt="$private_logs/casual-girl-inventory.json"',
            'content_manifest="$private_logs/casual-girl-content-before-migration.json"',
            'source "$phase_lock_tool"',
            'fab_phase_lock_acquire "$workspace"',
            'rm -f -- "$receipt"',
            'host_python=/usr/bin/python3',
            'host_docker=/usr/bin/docker',
            '"$host_python" "$content_tool" create "$project_dir" "$content_manifest"',
            '"inventoryScriptSha256"',
            '"logSha256"',
            '"contentManifestPath"',
            '"contentManifestSha256"',
            '"contentRootDigestSha256"',
            '"raw_uasset_ascii_identifier_presence"',
            '"identifier_presence_only"',
            '"morph_target_attachment"',
            '"ARKIT_BODY_FOUND_COUNT": "52"',
            '"EPIC_BODY_BONE_NAMES_FOUND": "21"',
            '"$host_docker" run --rm --pull=never',
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges",
            '--user "$container_user"',
            '--mount "type=bind,src=$project_dir,dst=$project_dir,readonly"',
            '--mount "type=bind,src=$project_saved,dst=$project_saved"',
            '--mount "type=bind,src=$review_fex_state,dst=$review_fex_state"',
            '--mount "type=bind,src=$review_sandbox_logs,dst=$review_sandbox_logs"',
            '--entrypoint /usr/bin/env',
            'fab_phase_lock_exec_without_fd "${docker_base[@]}"',
            'forbidden_probe="$project_dir/Content/.fay-review-forbidden-',
            "container_name='ue5-spark-fab-acquisition-review'",
            'cleanup_exact_container || fail',
            'else\n        inspect_status=$?\n    fi\n    case $inspect_status in',
            'preflight_log=$(mktemp "$private_state/preflight.XXXXXX.log")',
            '>"$preflight_log" 2>&1',
            'private diagnostics: $preflight_log',
            "trap '' HUP INT TERM",
            'os.replace(name, output)',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("AI_CONTROL_MODE_SELECTION", source)
        self.assertNotIn("NOAI_BOUNDARY", source)
        self.assertLess(
            source.index('fab_phase_lock_acquire "$workspace"'),
            source.index('if ps -u "$(id -u)"'),
        )
        self.assertLess(
            source.index('rm -f -- "$receipt"'),
            source.index("Starting the isolated read-only Casual Girl inventory."),
        )
        self.assertLess(
            source.index('"$host_python" "$content_tool" create'),
            source.index('"$host_python" - "$inventory_script"'),
        )
        self.assertLess(
            source.index("run_in_review_sandbox nice"),
            source.index('"$host_python" "$content_tool" create'),
        )
        review_wrapper = source.split("run_in_review_sandbox() {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertEqual(review_wrapper.count("\n    ("), 1)
        self.assertNotIn("fab_phase_lock_run_without_fd", source)
        self.assertNotIn("systemd-run", source)
        self.assertNotIn("docker pull", source)
        self.assertNotIn('--mount "type=bind,src=$private_logs', source)
        self.assertNotIn('src=$workspace,dst=$workspace', source)

    def test_acquisition_receipt_binds_the_exact_content_seal(self) -> None:
        source = (REPO_ROOT / "scripts/run-fex-fab-review.sh").read_text(
            encoding="utf-8"
        )
        receipt_program = source.rsplit("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        markers = {
            "MESHES_ASSET_COUNT": "19",
            "MAT_ASSET_COUNT": "31",
            "TEX_ASSET_COUNT": "97",
            "EXPECTED_PRODUCT_ASSETS": "OK",
            "ARKIT_EXPECTED_COUNT": "52",
            "ARKIT_BODY_FOUND_COUNT": "52",
            "ARKIT_COMPLETE_FOUND_COUNT": "52",
            "ARKIT_BODY_MISSING": "none",
            "ARKIT_COMPLETE_MISSING": "none",
            "EPIC_BODY_BONE_NAMES_EXPECTED": "21",
            "EPIC_BODY_BONE_NAMES_FOUND": "21",
            "EPIC_BODY_BONE_NAMES_MISSING": "none",
            "FULLY_UNCLOTHED": "disabled",
            "COMPLETE": "OK",
        }
        module = load_content_manifest_module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            root = temporary_path / "FayFabAcquisition"
            content = root / "Content"
            content.mkdir(parents=True)
            (root / "FayFabAcquisition.uproject").write_text("{}\n", encoding="utf-8")
            (content / "SK_Body.uasset").write_bytes(b"body")
            content_manifest = temporary_path / "content.json"
            module.create(root, content_manifest)
            inventory_script = temporary_path / "inventory.py"
            inventory_script.write_text("# reviewed inventory\n", encoding="utf-8")
            log = temporary_path / "review.log"
            log.write_text(
                "\n".join(
                    f"FAY_FAB_INVENTORY_{name}={value}"
                    for name, value in markers.items()
                )
                + "\n",
                encoding="utf-8",
            )
            receipt = temporary_path / "receipt.json"
            subprocess.run(
                [
                    sys.executable,
                    "-",
                    str(inventory_script),
                    str(log),
                    str(receipt),
                    str(content_manifest),
                ],
                input=receipt_program,
                check=True,
                text=True,
            )
            value = json.loads(receipt.read_text(encoding="utf-8"))
            manifest_bytes = content_manifest.read_bytes()
            manifest_value = json.loads(manifest_bytes)
            self.assertEqual(value["schema"], 2)
            self.assertEqual(
                value["contentManifestPath"], str(content_manifest.resolve())
            )
            self.assertEqual(
                value["contentManifestSha256"], sha256(manifest_bytes).hexdigest()
            )
            self.assertEqual(
                value["contentRootDigestSha256"],
                manifest_value["rootDigestSha256"],
            )
            self.assertEqual(value["identifierEvidence"]["scope"], "identifier_presence_only")
            self.assertIn(
                "bone_hierarchy", value["identifierEvidence"]["doesNotProve"]
            )
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

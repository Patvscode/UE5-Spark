from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "activate-ardy-provider.sh"


class ActivateArdyProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_bash_syntax_and_exact_arity(self) -> None:
        result = subprocess.run(
            ("bash", "-n", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            ("bash", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("Usage:", result.stderr)
        self.assertIn("if (( $# != 2 )); then", self.source)

    def test_names_images_and_ports_are_fixed(self) -> None:
        for assignment in (
            "readonly PRODUCTION_CONTAINER='ue5-spark-ardy'",
            "readonly CANARY_CONTAINER='ue5-spark-ardy-canary'",
            "readonly TARGET_IMAGE='ue5-spark-ardy:0.2.0'",
            "readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.1.0'",
            "readonly PRODUCTION_PORT=8777",
            "readonly CANARY_PORT=18777",
        ):
            self.assertEqual(self.source.count(assignment), 1)
        self.assertNotRegex(
            self.source,
            r"(?:PRODUCTION_CONTAINER|CANARY_CONTAINER|TARGET_IMAGE|ROLLBACK_IMAGE|"
            r"PRODUCTION_PORT|CANARY_PORT)=\$",
        )

    def test_lifecycle_is_confined_to_exact_owned_containers(self) -> None:
        self.assertNotIn("systemctl", self.source)
        self.assertNotRegex(
            self.source,
            r"\bdocker\s+(?:start|restart|kill|pause|unpause|update|exec|system|volume|image\s+rm)\b",
        )
        stop_targets = re.findall(r'docker stop --time 20 "\$([A-Za-z0-9_]+)"', self.source)
        self.assertEqual(
            sorted(stop_targets),
            sorted(["canary_container_id", "target_container_id", "old_container_id"]),
        )
        self.assertEqual(
            re.findall(r'docker rm "\$([A-Za-z0-9_]+)"', self.source),
            ["canary_container_id"],
        )
        self.assertNotIn("fay", self.source.lower())
        self.assertIn('[[ $container_id =~ ^[0-9a-f]{64}$', self.source)

    def test_canary_passes_before_production_stop_and_rollback_is_armed(self) -> None:
        canary_validation = self.source.index(
            '"$validator" --port "$CANARY_PORT" --batches 30'
        )
        production_reverified = self.source.index(
            "capture_verified_container production_reverified"
        )
        rollback_arm = self.source.index("rollback_armed=1", production_reverified)
        production_stop = self.source.index(
            'docker stop --time 20 "$old_container_id"', rollback_arm
        )
        target_launch = self.source.index(
            'target_container_id=$(launch_container "$PRODUCTION_CONTAINER"',
            production_stop,
        )
        production_validation = self.source.index(
            '"$validator" --port "$PRODUCTION_PORT" --batches 30', target_launch
        )
        self.assertLess(canary_validation, production_reverified)
        self.assertLess(production_reverified, rollback_arm)
        self.assertLess(rollback_arm, production_stop)
        self.assertLess(production_stop, target_launch)
        self.assertLess(target_launch, production_validation)
        self.assertIn("restore_rollback", self.source)
        self.assertIn("rollback_verified=1", self.source)

    def test_launches_use_captured_immutable_image_ids(self) -> None:
        for marker in (
            'launch_container "$CANARY_CONTAINER" "$target_image_id"',
            'launch_container "$PRODUCTION_CONTAINER" "$target_image_id"',
            'launch_container "$PRODUCTION_CONTAINER" "$rollback_image_id"',
            'current_runtime_image_id=$(docker inspect',
            'current_runtime_image_id == "$target_image_id"',
            'current_runtime_image_id == "$rollback_image_id"',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn(
            'launch_container "$CANARY_CONTAINER" "$TARGET_IMAGE"',
            self.source,
        )

    def test_absent_service_recovery_requires_an_unused_fixed_port(self) -> None:
        for marker in (
            "recovery_mode=1",
            'loopback_port_is_unused "$PRODUCTION_PORT"',
            "production ARDY is absent but its fixed loopback port is unexpectedly owned",
            "If the real canary or relaunch fails, restore the sealed mock endpoint.",
            "the production container name was claimed during recovery qualification",
            "the production loopback port was claimed during recovery qualification",
            '"recovery_mode=$recovery_mode"',
        ):
            self.assertIn(marker, self.source)
        port_check = self.source[
            self.source.index("loopback_port_is_unused()") :
            self.source.index("capture_verified_container()")
        ]
        self.assertNotIn("|| true", port_check)

    def test_lock_and_exit_recovery_are_global_and_auditable(self) -> None:
        for marker in (
            'lock_file="$lock_parent/ue5-spark-ardy.activation.lock"',
            "rollback_attempted=1",
            "rollback_status='verified'",
            "rollback_status='failed'",
            "cleanup_status='failed'",
            "EMERGENCY: sealed ARDY rollback could not be verified",
            '"rollback_status=$rollback_status"',
            '"cleanup_status=$cleanup_status"',
            'rollback-blocked.txt',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn('lock_file="$private_root/.ardy-activation.lock"', self.source)

    def test_private_evidence_and_runtime_isolation_are_sealed(self) -> None:
        for marker in (
            "PRIVATE_EVIDENCE_DIR must not already exist",
            "PRIVATE_EVIDENCE_DIR must be below a logs-private root",
            'flock -n 9',
            'mkdir -m 700 -- "$evidence_root"',
            "--network host",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--pids-limit 512",
            "--shm-size 4g",
            "--tmpfs /tmp:rw,noexec,nosuid,size=1g",
            'type=bind,src=$models_root,dst=/models,readonly',
            '"$validator" --port "$CANARY_PORT" --batches 30',
            '"$validator" --port "$PRODUCTION_PORT" --batches 30',
            're.search(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)$"',
        ):
            self.assertIn(marker, self.source)


@unittest.skipUnless(
    platform.system() == "Linux"
    and platform.machine() == "aarch64"
    and Path(f"/run/user/{os.getuid()}").is_dir(),
    "the activation state-machine harness requires Linux/aarch64 user runtime state",
)
class ActivateArdyProviderStateMachineTests(unittest.TestCase):
    target_image_id = "sha256:" + "1" * 64
    rollback_image_id = "sha256:" + "2" * 64

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ardy-activation-test-")
        self.root = Path(self.temporary.name)
        self.test_repo = self.root / "repo"
        self.script = self.test_repo / "scripts" / SCRIPT_PATH.name
        self.validator = self.test_repo / "tools" / "validate_ardy_service.py"
        self.models = self.root / "models-private" / "ardy"
        self.logs = self.root / "logs-private"
        self.fake_bin = self.root / "fake-bin"
        self.state_file = self.root / "docker-state.json"
        self.command_log = self.root / "docker-commands.jsonl"
        self.validator_count = self.root / "validator-count.txt"

        self.script.parent.mkdir(parents=True)
        self.validator.parent.mkdir(parents=True)
        (self.models / "embeddings").mkdir(parents=True)
        self.logs.mkdir()
        self.fake_bin.mkdir()
        self.state_file.write_text("{}", encoding="utf-8")
        self.script.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        self.script.chmod(0o755)
        self._write_executable("docker", self._fake_docker_source())
        self._write_executable("ss", self._fake_ss_source())
        self._write_executable("curl", self._fake_curl_source())
        self._write_executable("sleep", "#!/usr/bin/env bash\nexit 0\n")
        self.validator.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path

                counter = Path(os.environ["FAKE_VALIDATOR_COUNT"])
                count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                counter.write_text(str(count + 1), encoding="utf-8")
                statuses = [int(value) for value in os.environ.get(
                    "FAKE_VALIDATOR_STATUSES", "0"
                ).split(",")]
                status = statuses[min(count, len(statuses) - 1)]
                if status == 0:
                    print(json.dumps({"status": "passed", "batchCount": 30}))
                raise SystemExit(status)
                """
            ),
            encoding="utf-8",
        )
        self.validator.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PATH": f"{self.fake_bin}:{self.environment['PATH']}",
                "FAKE_DOCKER_STATE": str(self.state_file),
                "FAKE_DOCKER_LOG": str(self.command_log),
                "FAKE_MODELS_ROOT": str(self.models.resolve()),
                "FAKE_VALIDATOR_COUNT": str(self.validator_count),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_executable(self, name: str, source: str) -> None:
        destination = self.fake_bin / name
        destination.write_text(source, encoding="utf-8")
        destination.chmod(0o755)

    @staticmethod
    def _fake_docker_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["FAKE_DOCKER_STATE"])
            log_path = Path(os.environ["FAKE_DOCKER_LOG"])
            target_image_id = "sha256:" + "1" * 64
            rollback_image_id = "sha256:" + "2" * 64
            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(args) + "\\n")

            def load():
                return json.loads(state_path.read_text(encoding="utf-8"))

            def save(value):
                state_path.write_text(json.dumps(value), encoding="utf-8")

            def locate(value, identifier):
                for name, record in value.items():
                    if identifier in {name, record["Id"], record["Name"].lstrip("/")}:
                        return name, record
                return None, None

            if args[:2] == ["image", "inspect"]:
                image = args[-1]
                identifiers = {
                    "ue5-spark-ardy:0.2.0": target_image_id,
                    "ue5-spark-ardy:0.1.0": rollback_image_id,
                }
                if image not in identifiers:
                    raise SystemExit(1)
                print(identifiers[image])
                raise SystemExit(0)

            if args and args[0] == "inspect":
                identifier = args[-1]
                state = load()
                _name, record = locate(state, identifier)
                if record is None:
                    raise SystemExit(1)
                if "--format" in args:
                    template = args[args.index("--format") + 1]
                    values = {
                        "{{.Id}}": record["Id"],
                        "{{.Image}}": record["Image"],
                        "{{.Config.Image}}": record["Config"]["Image"],
                    }
                    if template not in values:
                        raise SystemExit(2)
                    print(values[template])
                else:
                    print(json.dumps([record]))
                raise SystemExit(0)

            if args and args[0] == "run":
                options = {}
                auto_remove = False
                index = 1
                value_options = {
                    "--name", "--gpus", "--network", "--cap-drop", "--security-opt",
                    "--pids-limit", "--shm-size", "--tmpfs", "--user", "--mount",
                }
                flag_options = {"--detach", "--read-only"}
                while index < len(args):
                    item = args[index]
                    if item == "--rm":
                        auto_remove = True
                        index += 1
                    elif item in flag_options:
                        options[item] = True
                        index += 1
                    elif item in value_options:
                        options[item] = args[index + 1]
                        index += 2
                    else:
                        break
                image = args[index]
                command = args[index + 1 :]
                name = options["--name"]
                provider = command[command.index("--provider") + 1]
                port = command[command.index("--port") + 1]
                if name == "ue5-spark-ardy-canary":
                    container_id, pid = "c" * 64, 4101
                elif provider == "ardy":
                    container_id, pid = "a" * 64, 4102
                else:
                    container_id, pid = "b" * 64, 4103
                state = load()
                if name in state:
                    raise SystemExit(125)
                mount = dict(
                    part.split("=", 1) if "=" in part else (part, "")
                    for part in options["--mount"].split(",")
                )
                state[name] = {
                    "Id": container_id,
                    "Name": "/" + name,
                    "Image": image,
                    "RestartCount": 0,
                    "State": {
                        "Running": True,
                        "Dead": False,
                        "OOMKilled": False,
                        "Error": "",
                        "Pid": pid,
                        "StartedAt": "2026-07-21T00:00:00Z",
                    },
                    "Config": {
                        "Image": image,
                        "User": options["--user"],
                        "Cmd": command,
                        "Env": [],
                    },
                    "HostConfig": {
                        "AutoRemove": auto_remove,
                        "NetworkMode": options["--network"],
                        "ReadonlyRootfs": True,
                        "CapDrop": [options["--cap-drop"]],
                        "SecurityOpt": [options["--security-opt"]],
                        "PidsLimit": int(options["--pids-limit"]),
                        "ShmSize": 4 * 1024**3,
                        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=1g"},
                        "DeviceRequests": [{"Capabilities": [["gpu"]]}],
                    },
                    "Mounts": [{
                        "Type": "bind",
                        "Source": mount["src"],
                        "Destination": mount["dst"],
                        "RW": False,
                    }],
                    "FakePort": port,
                    "FakeProvider": provider,
                }
                save(state)
                print(container_id)
                raise SystemExit(0)

            if args and args[0] in {"logs", "stop", "rm"}:
                operation = args[0]
                identifier = args[-1]
                state = load()
                name, record = locate(state, identifier)
                if record is None:
                    raise SystemExit(1)
                if operation == "logs":
                    print("fake isolated ARDY container log")
                elif operation == "stop":
                    if record["HostConfig"]["AutoRemove"]:
                        del state[name]
                    else:
                        record["State"]["Running"] = False
                    save(state)
                    print(identifier)
                else:
                    del state[name]
                    save(state)
                    print(identifier)
                raise SystemExit(0)

            raise SystemExit(2)
            """
        )

    @staticmethod
    def _fake_ss_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import re
            import sys
            from pathlib import Path

            if os.environ.get("FAKE_SS_FAIL") == "1":
                raise SystemExit(2)
            match = re.search(r":([0-9]+)", " ".join(sys.argv[1:]))
            if match is None:
                raise SystemExit(2)
            port = match.group(1)
            state = json.loads(Path(os.environ["FAKE_DOCKER_STATE"]).read_text(
                encoding="utf-8"
            ))
            for record in state.values():
                if record["State"]["Running"] and record["FakePort"] == port:
                    suffix = ""
                    if any("p" in argument for argument in sys.argv[1:] if argument.startswith("-")):
                        suffix = f' users:(("python",pid={record["State"]["Pid"]},fd=3))'
                    print(f"LISTEN 0 128 127.0.0.1:{port} 0.0.0.0:*{suffix}")
            """
        )

    @staticmethod
    def _fake_curl_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import re
            import sys
            from pathlib import Path

            match = re.search(r":([0-9]+)/healthz$", sys.argv[-1])
            if match is None:
                raise SystemExit(2)
            port = match.group(1)
            state = json.loads(Path(os.environ["FAKE_DOCKER_STATE"]).read_text(
                encoding="utf-8"
            ))
            for record in state.values():
                if record["State"]["Running"] and record["FakePort"] == port:
                    if record["FakeProvider"] != "mock":
                        raise SystemExit(1)
                    print(json.dumps({
                        "status": "ready",
                        "provider": "mock",
                        "protocolVersion": 1,
                        "fps": 20,
                        "bufferFrames": 8,
                        "facialControl": "excluded",
                        "checkpoint": None,
                        "embeddingCount": 0,
                        "p95GenerationMs": 0.0,
                    }))
                    raise SystemExit(0)
            raise SystemExit(1)
            """
        )

    def _run(self, name: str, statuses: str, *, ss_failure: bool = False):
        evidence = self.logs / name
        environment = self.environment.copy()
        environment["FAKE_VALIDATOR_STATUSES"] = statuses
        if ss_failure:
            environment["FAKE_SS_FAIL"] = "1"
        result = subprocess.run(
            ("bash", str(self.script), str(self.models), str(evidence)),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            env=environment,
        )
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        commands = [
            json.loads(line)
            for line in self.command_log.read_text(encoding="utf-8").splitlines()
        ]
        return result, evidence, state, commands

    @staticmethod
    def _result_record(evidence: Path) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in (evidence / "activation-result.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if "=" in line
        )

    def test_ss_error_fails_before_any_container_launch(self) -> None:
        result, evidence, state, commands = self._run(
            "ss-failure", "0", ss_failure=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state, {})
        self.assertFalse(any(command and command[0] == "run" for command in commands))
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["rollback_attempted"], "0")

    def test_canary_failure_restores_and_verifies_mock(self) -> None:
        result, evidence, state, _commands = self._run("canary-failure", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        production = state["ue5-spark-ardy"]
        self.assertEqual(production["FakeProvider"], "mock")
        self.assertEqual(production["Config"]["Image"], self.rollback_image_id)
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_attempted"], "1")
        self.assertEqual(record["rollback_verified"], "1")
        self.assertEqual(record["rollback_status"], "verified")
        self.assertEqual(record["cleanup_status"], "verified")

    def test_target_failure_stops_exact_target_then_restores_mock(self) -> None:
        result, evidence, state, commands = self._run("target-failure", "0,1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(state["ue5-spark-ardy"]["FakeProvider"], "mock")
        stopped_ids = [
            command[-1] for command in commands if command and command[0] == "stop"
        ]
        self.assertIn("a" * 64, stopped_ids)
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_status"], "verified")

    def test_successful_absent_recovery_leaves_only_real_provider(self) -> None:
        result, evidence, state, commands = self._run("recovery-success", "0,0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        production = state["ue5-spark-ardy"]
        self.assertEqual(production["FakeProvider"], "ardy")
        self.assertEqual(production["Config"]["Image"], self.target_image_id)
        run_images = [
            next(item for item in command if item.startswith("sha256:"))
            for command in commands
            if command and command[0] == "run"
        ]
        self.assertEqual(run_images, [self.target_image_id, self.target_image_id])
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["activation_complete"], "1")
        self.assertEqual(record["rollback_attempted"], "0")


if __name__ == "__main__":
    unittest.main()

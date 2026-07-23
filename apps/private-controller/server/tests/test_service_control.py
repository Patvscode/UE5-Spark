import importlib.util
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "controller_server.py"
SPEC = importlib.util.spec_from_file_location("controller_server_services", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


class FakeSystemctl:
    def __init__(self, states=None, action_returncode=0):
        self.states = states or {}
        self.action_returncode = action_returncode
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(list(command))
        if "show" in command:
            unit = command[-1]
            active = self.states.get(unit, "inactive")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "LoadState=loaded\n"
                    f"ActiveState={active}\n"
                    f"SubState={'running' if active == 'active' else 'dead'}\n"
                    f"Result={'success' if active != 'failed' else 'exit-code'}\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command, self.action_returncode, stdout="", stderr=""
        )


class ServiceControlTests(unittest.TestCase):
    def test_request_accepts_only_one_fixed_action(self):
        for action in SERVER.SERVICE_CONTROL_ACTIONS:
            self.assertEqual(
                SERVER.normalize_service_control_request({"action": action}),
                action,
            )
        for payload in (
            {},
            {"action": "start", "unit": "fay.service"},
            {"action": "start ue5-spark-avatar.service"},
            {"action": "enable"},
            {"target": "stack"},
        ):
            with self.assertRaises(ValueError):
                SERVER.normalize_service_control_request(payload)

    def test_systemctl_mutation_has_fixed_argv_and_never_names_fay(self):
        runner = FakeSystemctl()
        manager = SERVER.ProjectServiceManager(
            enabled=True,
            systemctl_path=Path("/fixed/systemctl"),
            runner=runner,
        )
        manager.request("restart")
        self.assertEqual(
            runner.calls,
            [
                [
                    "/fixed/systemctl",
                    "--user",
                    "reset-failed",
                    "ue5-spark-ardy.service",
                    "ue5-spark-ardy-ready.service",
                    "ue5-spark-avatar.service",
                ],
                [
                    "/fixed/systemctl",
                    "--user",
                    "--no-block",
                    "restart",
                    "ue5-spark-digital-human.target",
                ],
            ],
        )
        self.assertNotIn("fay", " ".join(sum(runner.calls, [])).casefold())

    def test_snapshot_uses_only_fixed_component_units(self):
        states = {
            SERVER.PROJECT_STACK_UNIT: "active",
            SERVER.PROJECT_SERVICE_UNITS["ardy"]: "active",
            SERVER.PROJECT_SERVICE_UNITS["ardy-ready"]: "active",
            SERVER.PROJECT_SERVICE_UNITS["avatar"]: "active",
        }
        runner = FakeSystemctl(states)
        manager = SERVER.ProjectServiceManager(
            enabled=True,
            systemctl_path=Path("/fixed/systemctl"),
            runner=runner,
        )
        value = manager.snapshot(fay_online=True)
        self.assertEqual(value["targetState"], "running")
        self.assertEqual(value["companion"]["status"], "running")
        self.assertFalse(value["companion"]["canStart"])
        self.assertTrue(value["companion"]["canStop"])
        self.assertEqual(
            {item["id"] for item in value["services"]},
            {"controller", "fay", "ardy", "ardy-ready", "avatar"},
        )
        fay = next(item for item in value["services"] if item["id"] == "fay")
        self.assertFalse(fay["managed"])
        queried_units = [call[-1] for call in runner.calls]
        self.assertEqual(
            queried_units,
            [SERVER.PROJECT_STACK_UNIT, *SERVER.PROJECT_SERVICE_UNITS.values()],
        )
        self.assertTrue(all("fay" not in unit.casefold() for unit in queried_units))

    def test_disabled_manager_is_status_only_and_unavailable(self):
        runner = FakeSystemctl()
        manager = SERVER.ProjectServiceManager(
            enabled=False,
            systemctl_path=Path("/fixed/systemctl"),
            runner=runner,
        )
        snapshot = manager.snapshot(fay_online=None)
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["targetState"], "unavailable")
        self.assertEqual(snapshot["allowedActions"], [])
        self.assertEqual(runner.calls, [])
        with self.assertRaises(SERVER.ProjectServiceControlError):
            manager.request("start")

    def test_handler_status_and_start_return_frontend_contract(self):
        runner = FakeSystemctl()
        manager = SERVER.ProjectServiceManager(
            enabled=True,
            systemctl_path=Path("/fixed/systemctl"),
            runner=runner,
        )
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(service_manager=manager)
        handler._fay_service_online = lambda: True
        responses = []
        handler._json = lambda status, payload: responses.append((status, payload))

        handler._service_control({"action": "status"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.OK)
        self.assertIn("services", responses[-1][1])
        self.assertIn("companion", responses[-1][1])

        handler._service_control({"action": "start"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.ACCEPTED)
        self.assertEqual(responses[-1][1]["acceptedAction"], "start")
        action_calls = [call for call in runner.calls if "--no-block" in call]
        self.assertEqual(len(action_calls), 1)
        self.assertEqual(action_calls[0][-1], SERVER.PROJECT_STACK_UNIT)

    def test_failed_systemctl_request_is_reported_without_stderr_reflection(self):
        runner = FakeSystemctl(action_returncode=1)
        manager = SERVER.ProjectServiceManager(
            enabled=True,
            systemctl_path=Path("/fixed/systemctl"),
            runner=runner,
        )
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(service_manager=manager)
        responses = []
        handler._json = lambda status, payload: responses.append((status, payload))
        handler._service_control({"action": "stop"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(
            responses[-1][1]["error"],
            "project_service_control_unavailable",
        )


if __name__ == "__main__":
    unittest.main()

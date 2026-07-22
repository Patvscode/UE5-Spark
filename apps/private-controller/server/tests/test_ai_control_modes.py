import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "controller_server.py"
SPEC = importlib.util.spec_from_file_location("controller_server_ai_control", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)
REPO_ROOT = MODULE_PATH.parents[3]
CONFIG_PATH = REPO_ROOT / "config/character-ai-control.json"
SCHEMA_PATH = REPO_ROOT / "config/character-ai-control.schema.json"
APP_PATH = REPO_ROOT / "apps/private-controller/src/App.jsx"


class CharacterAiControlTests(unittest.TestCase):
    def test_public_config_is_neutral_sealed_and_defaults_to_ai_motion(self):
        config = SERVER.load_character_ai_control(CONFIG_PATH)
        self.assertEqual(config["defaultMode"], "ai_motion")
        self.assertEqual(
            [mode["id"] for mode in config["modes"]],
            ["deterministic", "ai_motion", "asset_aware_ai"],
        )
        semantics = {
            mode["id"]: (
                mode["usesGenerativeMotion"],
                mode["acceptsCharacterAssetContext"],
                mode["requiresExplicitLocalOptIn"],
            )
            for mode in config["modes"]
        }
        self.assertEqual(semantics, SERVER.AI_CONTROL_SEMANTICS)
        serialized = CONFIG_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "CasualGirl",
            "casual-girl",
            "characterId",
            "assetAwareAiAllowed",
            "permissionReceipt",
            "license",
        ):
            self.assertNotIn(forbidden, serialized)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["defaultMode"]["const"], "ai_motion")

    def test_validator_rejects_semantic_drift_extra_fields_and_duplicates(self):
        original = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "character-ai-control.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            self.assertEqual(
                SERVER.load_character_ai_control(path)["controlConfigId"],
                "ue5-spark-local-ai-control-v1",
            )

            original["defaultMode"] = "asset_aware_ai"
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SERVER.load_character_ai_control(path)

            original = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            original["modes"][1]["acceptsCharacterAssetContext"] = True
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SERVER.load_character_ai_control(path)

            duplicate = CONFIG_PATH.read_text(encoding="utf-8").replace(
                '"schemaVersion": 1,',
                '"schemaVersion": 1,\n  "schemaVersion": 1,',
                1,
            )
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SERVER.load_character_ai_control(path)

    def test_asset_aware_mode_needs_explicit_controller_wide_opt_in(self):
        config = SERVER.load_character_ai_control(CONFIG_PATH)
        state = SERVER.LocalAiControlState(config)
        self.assertEqual(state.selected_mode(), "ai_motion")
        self.assertTrue(state.motion_planner_enabled())

        state.select({"mode": "deterministic"})
        self.assertEqual(state.selected_mode(), "deterministic")
        self.assertFalse(state.motion_planner_enabled())
        for payload in (
            {"mode": "asset_aware_ai"},
            {"mode": "asset_aware_ai", "acknowledgeAssetContext": False},
            {"mode": "asset_aware_ai", "acknowledgeAssetContext": 1},
        ):
            with self.assertRaises(SERVER.AssetAwareOptInRequired):
                state.select(payload)
            self.assertEqual(state.selected_mode(), "deterministic")

        snapshot = state.select({
            "mode": "asset_aware_ai",
            "acknowledgeAssetContext": True,
        })
        self.assertEqual(snapshot["selectedMode"], "asset_aware_ai")
        self.assertTrue(snapshot["assetAwareEnabled"])
        self.assertNotIn("characterId", snapshot)
        self.assertNotIn("characters", snapshot)
        self.assertNotIn("receipt", json.dumps(snapshot).lower())

    def test_endpoint_returns_conflict_then_accepts_opt_in(self):
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(
            ai_control=SERVER.LocalAiControlState(
                SERVER.load_character_ai_control(CONFIG_PATH)
            )
        )
        responses = []
        handler._json = lambda status, payload: responses.append((status, payload))

        handler._ai_control({"mode": "asset_aware_ai"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.CONFLICT)
        self.assertEqual(responses[-1][1]["error"], "asset_aware_opt_in_required")
        self.assertEqual(handler.server.ai_control.selected_mode(), "ai_motion")

        handler._ai_control({
            "mode": "asset_aware_ai",
            "acknowledgeAssetContext": True,
        })
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.OK)
        self.assertEqual(responses[-1][1]["selectedMode"], "asset_aware_ai")

    def test_same_origin_get_and_post_endpoint_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("dist", "media", "live"):
                (root / name).mkdir()
            with mock.patch.object(SERVER.socket, "getfqdn", return_value="localhost"):
                server = SERVER.ControllerServer(
                    ("127.0.0.1", 0),
                    root / "dist",
                    root / "media",
                    root / "live",
                    "http://127.0.0.1:5000",
                    "http://127.0.0.1:8777",
                    None,
                    None,
                    None,
                )
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(f"{origin}/api/ai-control", timeout=2) as response:
                    initial = json.loads(response.read())
                self.assertEqual(initial["selectedMode"], "ai_motion")
                self.assertFalse(initial["assetAwareEnabled"])

                missing_ack = urllib.request.Request(
                    f"{origin}/api/ai-control",
                    data=b'{"mode":"asset_aware_ai"}',
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(missing_ack, timeout=2)
                self.assertEqual(failure.exception.code, 409)

                opted_in = urllib.request.Request(
                    f"{origin}/api/ai-control",
                    data=(
                        b'{"mode":"asset_aware_ai",'
                        b'"acknowledgeAssetContext":true}'
                    ),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(opted_in, timeout=2) as response:
                    selected = json.loads(response.read())
                self.assertEqual(selected["selectedMode"], "asset_aware_ai")
                self.assertTrue(selected["assetAwareEnabled"])

                with urllib.request.urlopen(f"{origin}/api/ai-control", timeout=2) as response:
                    reflected = json.loads(response.read())
                self.assertEqual(reflected["selectedMode"], "asset_aware_ai")
                self.assertTrue(reflected["assetAwareEnabled"])

                disabled = urllib.request.Request(
                    f"{origin}/api/ai-control",
                    data=b'{"mode":"ai_motion"}',
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(disabled, timeout=2) as response:
                    reset = json.loads(response.read())
                self.assertEqual(reset["selectedMode"], "ai_motion")
                self.assertFalse(reset["assetAwareEnabled"])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)

    def test_deterministic_mode_bypasses_model_and_ai_motion_is_generic(self):
        handler = object.__new__(SERVER.ControllerHandler)
        state = SERVER.LocalAiControlState(SERVER.load_character_ai_control(CONFIG_PATH))
        handler.server = SimpleNamespace(ai_control=state)
        responses = []
        suggestions = []
        dispatched = []
        handler._json = lambda status, payload: responses.append((status, payload))
        handler._motion_planner_suggestion = lambda command: (
            suggestions.append(command) or "wave"
        )
        handler._dispatch_action = lambda action: (
            dispatched.append(action) or (
                SERVER.HTTPStatus.OK,
                {"ok": True, "live": True, "replay": False, "behavior": "wave"},
            )
        )

        state.select({"mode": "deterministic"})
        handler._motion_command({"command": "make a friendly greeting"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(suggestions, [])
        self.assertEqual(dispatched, [])

        state.select({"mode": "ai_motion"})
        handler._motion_command({"command": "make a friendly greeting"})
        self.assertEqual(suggestions, ["make a friendly greeting"])
        self.assertEqual(responses[-1][1]["aiControlMode"], "ai_motion")
        self.assertFalse(responses[-1][1]["assetContextUsed"])
        self.assertEqual(dispatched[-1]["behavior"], "wave")

    def test_ui_uses_one_neutral_controller_wide_selector(self):
        source = APP_PATH.read_text(encoding="utf-8")
        for marker in (
            'fetch("/api/ai-control", { cache: "no-store" })',
            'fetch("/api/ai-control", {',
            'role="radiogroup" aria-label="AI motion control mode"',
            "acknowledgeAssetContext: true",
            'setAssetContextAcknowledged(payload.selectedMode === "asset_aware_ai")',
            "Enable asset-aware mode for this controller",
            "Controller-wide · resets to AI motion",
        ):
            self.assertIn(marker, source)
        selector = source[source.index('className="sheet-section ai-control-section"'):]
        self.assertNotIn("Casual Girl", selector.split("</section>", 1)[0])


if __name__ == "__main__":
    unittest.main()

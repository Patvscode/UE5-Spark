from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_PATH = REPO_ROOT / "apps/private-controller/server/controller_server.py"
BRIDGE_ROOT = REPO_ROOT / "Project/FayAvatarRuntime/Plugins/FayAvatarBridge/Source/FayAvatarBridge"
MOTION_ROOT = REPO_ROOT / "Project/FayAvatarRuntime/Plugins/FayBodyMotion/Source/FayBodyMotion"
APP_PATH = REPO_ROOT / "apps/private-controller/src/App.jsx"
THIRD_PARTY_PATH = REPO_ROOT / "THIRD_PARTY.md"
SPEC = importlib.util.spec_from_file_location("controller_provider_contract", CONTROLLER_PATH)
CONTROLLER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CONTROLLER)


class AiMotionProviderContractTests(unittest.TestCase):
    @staticmethod
    def runtime_context() -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "characterProfile": "ada",
            "wardrobePreset": "not-applicable",
            "cameraFraming": "fit",
            "stageZoom": 1.0,
            "rendererState": "live-preview",
        }

    def test_control_modes_map_to_one_closed_provider_hint(self) -> None:
        self.assertEqual(
            {
                mode: CONTROLLER.motion_provider_for_ai_control_mode(mode)
                for mode in CONTROLLER.AI_CONTROL_MODES
            },
            {
                "deterministic": "baked",
                "ai_motion": "hybrid",
                "asset_aware_ai": "hybrid",
            },
        )
        for invalid in (None, "", "ardy", "auto", 1):
            with self.assertRaises(ValueError):
                CONTROLLER.motion_provider_for_ai_control_mode(invalid)

    def test_action_normalization_preserves_legacy_callers_and_bounds_hints(self) -> None:
        legacy = CONTROLLER.normalize_action({"behavior": "wave"})
        self.assertNotIn("provider", legacy)
        self.assertEqual(
            CONTROLLER.normalize_action(
                {"behavior": "wave"}, provider_hint="baked"
            )["provider"],
            "baked",
        )
        for invalid in ("ardy", "auto", "", 1):
            with self.assertRaises(ValueError):
                CONTROLLER.normalize_action(
                    {"behavior": "wave"}, provider_hint=invalid
                )

    def test_direct_action_uses_the_process_selected_provider(self) -> None:
        for mode, expected in (
            ("deterministic", "baked"),
            ("ai_motion", "hybrid"),
            ("asset_aware_ai", "hybrid"),
        ):
            handler = object.__new__(CONTROLLER.ControllerHandler)
            handler.server = SimpleNamespace(
                ai_control=SimpleNamespace(selected_mode=lambda selected=mode: selected)
            )
            dispatched = []
            responses = []
            handler._dispatch_action = lambda action: (
                dispatched.append(action)
                or (CONTROLLER.HTTPStatus.OK, {"ok": True})
            )
            handler._json = lambda status, payload: responses.append((status, payload))
            handler._action({"behavior": "wave"})
            self.assertEqual(dispatched[0]["provider"], expected)
            self.assertEqual(responses[0][0], CONTROLLER.HTTPStatus.OK)

    def test_runtime_context_is_closed_and_requires_asset_aware_mode(self) -> None:
        self.assertEqual(
            CONTROLLER.normalize_motion_context(self.runtime_context()),
            self.runtime_context(),
        )
        for key, invalid in (
            ("characterProfile", "../../other"),
            ("wardrobePreset", "custom prompt"),
            ("cameraFraming", "cinematic"),
            ("stageZoom", float("nan")),
            ("rendererState", "online<script>"),
        ):
            context = self.runtime_context()
            context[key] = invalid
            with self.assertRaises(ValueError):
                CONTROLLER.normalize_motion_context(context)

        handler = object.__new__(CONTROLLER.ControllerHandler)
        handler.server = SimpleNamespace(
            ai_control=SimpleNamespace(selected_mode=lambda: "ai_motion")
        )
        with self.assertRaisesRegex(ValueError, "asset_aware_ai"):
            handler._motion_command({
                "command": "make a friendly greeting",
                "context": self.runtime_context(),
            })

    def test_asset_aware_mode_still_forwards_unrestricted_ardy_text(self) -> None:
        handler = object.__new__(CONTROLLER.ControllerHandler)
        handler.server = SimpleNamespace(
            ai_control=SimpleNamespace(selected_mode=lambda: "asset_aware_ai"),
            ardy_base="http://127.0.0.1:8777",
        )
        captured = {}
        dispatched = []
        responses = []

        def fake_upstream(url, payload, *, timeout):
            captured.update({"url": url, "payload": payload, "timeout": timeout})
            return {"ok": True, "promptId": "c" * 64, "cached": False}

        handler._upstream_json = fake_upstream
        handler._dispatch_action = lambda action: (
            dispatched.append(action)
            or (
                CONTROLLER.HTTPStatus.OK,
                {"ok": True, "live": True, "behavior": action["behavior"]},
            )
        )
        handler._json = lambda status, payload: responses.append((status, payload))
        handler._motion_command({
            "command": "make a friendly greeting",
            "context": self.runtime_context(),
        })

        self.assertEqual(captured["url"], "http://127.0.0.1:8777/v2/prompts")
        self.assertEqual(captured["payload"], {"prompt": "make a friendly greeting"})
        self.assertFalse(responses[0][1]["assetContextUsed"])
        self.assertEqual(responses[0][1]["aiControlMode"], "asset_aware_ai")
        self.assertEqual(dispatched[0]["provider"], "hybrid")
        self.assertEqual(dispatched[0]["prompt"], "make a friendly greeting")

    def test_browser_sends_context_only_while_controller_is_asset_aware(self) -> None:
        source = APP_PATH.read_text()
        request = source[
            source.index("async function requestMovement") :
            source.index("function applyMovementPayload")
        ]
        self.assertIn(
            'aiControl.selectedMode === "asset_aware_ai" && assetContextAcknowledged',
            request,
        )
        for field in (
            "schemaVersion", "characterProfile", "wardrobePreset",
            "cameraFraming", "stageZoom", "rendererState",
        ):
            self.assertIn(field, request)
        self.assertNotIn("mesh", request.lower())
        self.assertNotIn("texture", request.lower())
        self.assertNotIn("image", request.lower())

    def test_license_information_does_not_encode_an_ai_eligibility_rule(self) -> None:
        third_party = THIRD_PARTY_PATH.read_text()
        self.assertIn("user is responsible", third_party)
        self.assertNotIn("not used as generative-model", third_party)
        self.assertNotIn("training or conditioning data", third_party)

    def test_bridge_rejects_unknown_hints_and_missing_hint_remains_hybrid(self) -> None:
        header = (BRIDGE_ROOT / "Public/FayAvatarBridgeComponent.h").read_text()
        source = (BRIDGE_ROOT / "Private/FayAvatarBridgeComponent.cpp").read_text()
        self.assertIn("FString Provider;", header)
        self.assertIn("FString Prompt;", header)
        self.assertIn('Action->HasField(TEXT("provider"))', source)
        self.assertIn('OutMessage.Action.Provider != TEXT("baked")', source)
        self.assertIn('OutMessage.Action.Provider != TEXT("hybrid")', source)
        self.assertIn("unsupported motion provider hint", source)
        self.assertIn('Action->HasField(TEXT("prompt"))', source)

    def test_deterministic_route_cannot_reach_ardy(self) -> None:
        types = (MOTION_ROOT / "Public/FayBodyMotionTypes.h").read_text()
        motion = (MOTION_ROOT / "Private/FayBodyMotionComponent.cpp").read_text()
        self.assertIn("EFayBodyMotionRoutingMode::Hybrid", types)
        self.assertIn('Message.Action.Provider == TEXT("baked")', motion)
        dispatch = motion[
            motion.index("bool UFayBodyMotionComponent::Dispatch") :
            motion.index("void UFayBodyMotionComponent::EnterBakedIdle")
        ]
        self.assertIn("const bool bDeterministicOnly", dispatch)
        self.assertIn(
            "if (!bDeterministicOnly && bReviewedGeneratedAction &&", dispatch
        )
        self.assertIn(
            "if (!bDeterministicOnly && Preferred == BakedProvider.Get()", dispatch
        )
        self.assertIn('TEXT("deterministic motion was unavailable")', dispatch)


if __name__ == "__main__":
    unittest.main()

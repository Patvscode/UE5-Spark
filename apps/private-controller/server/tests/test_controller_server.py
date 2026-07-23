import argparse
import importlib.util
import ipaddress
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "controller_server.py"
SPEC = importlib.util.spec_from_file_location("controller_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


class ValidationTests(unittest.TestCase):
    def test_bind_accepts_loopback_and_tailnet(self):
        tail_address = str(SERVER.TAILSCALE_NET.network_address + (28 << 16) + (1 << 8) + 2)
        self.assertEqual(SERVER.checked_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(SERVER.checked_bind_host(tail_address), tail_address)

    def test_bind_rejects_public_and_unspecified(self):
        for address in ("0.0.0.0", "8.8.8.8"):
            with self.assertRaises(argparse.ArgumentTypeError):
                SERVER.checked_bind_host(address)

    def test_upstream_contracts(self):
        tail_address = str(SERVER.TAILSCALE_NET.network_address + (28 << 16) + (1 << 8) + 2)
        tail_origin = f"http://{tail_address}:5000"
        tail_ardy_origin = f"http://{tail_address}:8777"
        self.assertEqual(SERVER.checked_upstream("http://127.0.0.1:5000"), "http://127.0.0.1:5000")
        self.assertEqual(SERVER.checked_upstream(tail_origin), tail_origin)
        with self.assertRaises(argparse.ArgumentTypeError):
            SERVER.checked_upstream("https://example.com")
        with self.assertRaises(argparse.ArgumentTypeError):
            SERVER.checked_upstream(tail_ardy_origin, loopback_only=True)

    def test_action_is_allowlisted_and_bounded(self):
        self.assertEqual(SERVER.normalize_action({"behavior": " WAVE "})["behavior"], "wave")
        for payload in (
            {"behavior": "dance"},
            {"behavior": "wave", "duration": 100},
            {"behavior": "wave", "intensity": -1},
            {"behavior": "wave", "path": "/tmp/x"},
        ):
            with self.assertRaises(ValueError):
                SERVER.normalize_action(payload)

    def test_motion_command_preserves_free_text_with_only_transport_bounds(self):
        self.assertEqual(
            SERVER.normalize_motion_command({"command": "  please do jumping jacks  "}),
            "please do jumping jacks",
        )
        for payload in (
            {},
            {"command": ""},
            {"command": "wave", "duration": 100},
            {"command": "x" * 513},
        ):
            with self.assertRaises(ValueError):
                SERVER.normalize_motion_command(payload)
        self.assertEqual(
            SERVER.normalize_motion_command({"command": "walk toward https://example.com/door"}),
            "walk toward https://example.com/door",
        )

    def test_motion_catalog_owns_parameters_and_route(self):
        planned = SERVER.resolve_motion_command(
            "Could you do ten jumping jacks please?",
            planner_catalog_id="wave",
        )
        self.assertEqual(planned["catalogId"], "jumping_jacks")
        self.assertEqual(planned["duration"], 8.0)
        self.assertEqual(planned["intensity"], 0.72)
        self.assertEqual(planned["rootMode"], "locked")
        self.assertTrue(planned["rendererPackaged"])
        self.assertEqual(planned["routeBehavior"], "jumping_jacks")

        routed = SERVER.resolve_motion_command("please wave", planner_catalog_id="stretch")
        self.assertEqual(routed["catalogId"], "wave")
        self.assertEqual(routed["routeBehavior"], "wave")
        self.assertTrue(routed["rendererPackaged"])

    def test_planner_may_only_suggest_one_catalog_id(self):
        self.assertEqual(
            SERVER.parse_planner_catalog_id('{"catalogId":"run_in_place"}'),
            "run_in_place",
        )
        for value in (
            '{"catalogId":"unknown"}',
            '{"catalogId":"wave","duration":100}',
            '{"catalogId":"delete_files"}',
            "```json\n{\"catalogId\":\"wave\"}\n```",
            {"catalogId": "wave"},
        ):
            self.assertIsNone(SERVER.parse_planner_catalog_id(value))

    def test_routable_motion_catalog_is_a_subset_of_existing_actions(self):
        for catalog_id, item in SERVER.MOTION_CATALOG.items():
            behavior = item["routeBehavior"]
            if item["rendererPackaged"]:
                self.assertIn(behavior, SERVER.ALLOWED_BEHAVIORS, catalog_id)
            else:
                self.assertEqual(behavior, catalog_id)

    def test_deterministic_catalog_motion_is_normalized_before_dispatch(self):
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(
            ai_control=SERVER.LocalAiControlState(SERVER.CHARACTER_AI_CONTROL_CONFIG),
            ardy_base="http://127.0.0.1:8777",
        )
        handler.server.ai_control.select({"mode": "deterministic"})
        responses = []
        dispatched = []
        handler._motion_planner_suggestion = lambda _command: None
        handler._json = lambda status, payload: responses.append((status, payload))
        handler._dispatch_action = lambda action: (
            dispatched.append(action) or (
                SERVER.HTTPStatus.OK,
                {"ok": True, "live": True, "replay": False, "behavior": action["behavior"]},
            )
        )

        handler._motion_command({"command": "do jumping jacks"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.OK)
        self.assertEqual(responses[-1][1]["status"], "routed")
        self.assertEqual(dispatched[-1]["behavior"], "jumping_jacks")
        self.assertEqual(dispatched[-1]["provider"], "baked")

        handler._motion_command({"command": "wave hello"})
        self.assertEqual(responses[-1][0], SERVER.HTTPStatus.OK)
        self.assertEqual(responses[-1][1]["status"], "routed")
        self.assertEqual(dispatched[-1], {
            "behavior": "wave", "duration": 2.4, "intensity": 0.65,
            "user": "User", "provider": "baked",
        })

    def test_ai_motion_prewarms_and_forwards_the_complete_prompt(self):
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(
            ai_control=SERVER.LocalAiControlState(SERVER.CHARACTER_AI_CONTROL_CONFIG),
            ardy_base="http://127.0.0.1:8777",
        )
        responses = []
        dispatched = []
        upstream = []
        handler._json = lambda status, payload: responses.append((status, payload))
        handler._upstream_json = lambda url, payload, *, timeout: (
            upstream.append((url, payload, timeout))
            or {"ok": True, "promptId": "a" * 64, "cached": False}
        )
        handler._dispatch_action = lambda action: (
            dispatched.append(action) or (
                SERVER.HTTPStatus.OK,
                {"ok": True, "live": True, "replay": False, "behavior": action["behavior"]},
            )
        )

        prompt = "Crouch twice, recover your balance, then wave with your left hand."
        handler._motion_command({"command": prompt})
        self.assertEqual(upstream, [(
            "http://127.0.0.1:8777/v2/prompts", {"prompt": prompt}, 120,
        )])
        self.assertEqual(dispatched[-1]["behavior"], "explain")
        self.assertEqual(dispatched[-1]["prompt"], prompt)
        self.assertEqual(dispatched[-1]["provider"], "hybrid")
        self.assertTrue(responses[-1][1]["promptForwarded"])
        self.assertEqual(responses[-1][1]["prompt"], prompt)

    def test_motion_planner_can_use_a_model_independent_from_chat(self):
        handler = object.__new__(SERVER.ControllerHandler)
        handler.server = SimpleNamespace(
            llm_base="http://127.0.0.1:8080",
            llm_model="qwen3-4b-q4-k-m",
            motion_planner_model="hauhau-qwen-9b",
        )
        captured = {}

        def fake_upstream(url, payload, *, timeout):
            captured.update({"url": url, "payload": payload, "timeout": timeout})
            return {"choices": [{"message": {"content": '{"catalogId":"stretch"}'}}]}

        handler._upstream_json = fake_upstream
        self.assertEqual(handler._motion_planner_suggestion("loosen up"), "stretch")
        self.assertEqual(captured["payload"]["model"], "hauhau-qwen-9b")
        self.assertEqual(captured["payload"]["temperature"], 0.0)
        self.assertEqual(captured["payload"]["max_tokens"], 32)

    def test_shared_motion_catalog_loader_fails_closed(self):
        catalog = json.loads(SERVER.MOTION_CATALOG_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "motion-catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            loaded = SERVER.load_motion_catalog(path)
            self.assertEqual(set(loaded), SERVER.MOTION_CATALOG_IDS)
            self.assertEqual(loaded["wave"]["routeBehavior"], "wave")

            catalog["items"]["wave"]["duration"] = 100
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SERVER.load_motion_catalog(path)

    def test_wardrobe_is_sealed_and_full_undress_remains_disabled(self):
        profile = SERVER.WARDROBE_PROFILE
        self.assertTrue(profile["installed"])
        self.assertEqual(profile["state"], "installed_default_only")
        self.assertEqual(profile["scope"], "default_outfit_only")
        self.assertFalse(profile["fullyUnclothed"]["enabled"])
        self.assertEqual(
            {item["id"] for item in profile["presets"]},
            {"casual"},
        )
        self.assertEqual(
            SERVER.normalize_wardrobe({
                "profileId": "casual-girl",
                "preset": "casual",
                "slots": {"top": "tank", "bottom": "pants", "feet": "shoes_socks", "hair": "style_1"},
            }),
            {
                "profileId": "casual-girl",
                "preset": "casual",
                "slots": {"top": "tank", "bottom": "pants", "feet": "shoes_socks", "hair": "style_1"},
            },
        )
        for payload in (
            {"profileId": "casual-girl", "fullyUnclothed": True},
            {"profileId": "casual-girl", "preset": "hoodie"},
            {"profileId": "casual-girl", "slots": {"top": "/Game/Anything"}},
            {"profileId": "casual-girl", "preset": "casual", "slots": {"top": "tank"}},
            {"profileId": "other", "preset": "casual"},
        ):
            with self.assertRaises(ValueError):
                SERVER.normalize_wardrobe(payload)

    def test_wardrobe_request_and_runtime_receipt_stay_in_private_live_root(self):
        selection = {
            "profileId": "casual-girl",
            "preset": "casual",
            "slots": dict(SERVER.CURRENT_WARDROBE_SELECTION),
        }
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            request = SERVER.write_wardrobe_request(live_root, selection)
            request_path = live_root / SERVER.WARDROBE_REQUEST_FILE
            self.assertEqual(request_path.stat().st_mode & 0o777, 0o600)
            self.assertRegex(request["requestId"], r"^[0-9a-f]{24}$")
            receipt_path = live_root / SERVER.WARDROBE_APPLIED_FILE
            request_path.replace(receipt_path)
            receipt = SERVER.read_wardrobe_receipt(
                live_root, SERVER.WARDROBE_APPLIED_FILE
            )
            self.assertEqual(receipt["status"], "applied")
            self.assertEqual(receipt["requestId"], request["requestId"])

    def test_wardrobe_post_waits_for_matching_live_runtime_receipt(self):
        selection = {
            "profileId": "casual-girl",
            "preset": "casual",
            "slots": dict(SERVER.CURRENT_WARDROBE_SELECTION),
        }
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            state_path = live_root / SERVER.RENDERER_STATE_FILE
            state_path.write_text(json.dumps({
                "schemaVersion": 1,
                "state": "ready",
                "activeCharacter": "casual-girl",
                "requestedCharacter": "casual-girl",
                "availableCharacters": ["ada", "aoi", "casual-girl"],
                "packageGeneration": "v30",
                "updatedAtUnixMs": int(time.time() * 1000),
            }), encoding="utf-8")
            state_path.chmod(0o600)

            def runtime_receipt() -> None:
                request = live_root / SERVER.WARDROBE_REQUEST_FILE
                deadline = time.monotonic() + 1
                while not request.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                request.replace(live_root / SERVER.WARDROBE_APPLIED_FILE)

            worker = threading.Thread(target=runtime_receipt)
            worker.start()
            handler = object.__new__(SERVER.ControllerHandler)
            handler.server = SimpleNamespace(live_root=live_root)
            responses = []
            handler._json = lambda status, payload: responses.append((status, payload))
            handler._wardrobe(selection)
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(responses[0][0], SERVER.HTTPStatus.OK)
            self.assertEqual(responses[0][1]["status"], "applied")

    def test_shared_pending_wardrobe_loader_is_sanitized_and_fails_closed(self):
        profile = json.loads(SERVER.WARDROBE_PROFILE_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CasualGirl.pending.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            public, slots, presets = SERVER.load_wardrobe_profile(path)
            self.assertEqual(public["profileId"], "casual-girl")
            self.assertTrue(public["installed"])
            self.assertEqual(public["state"], "installed_default_only")
            self.assertNotIn("sourceListing", public)
            self.assertNotIn("reviewedAssetRoot", public)
            self.assertEqual(slots, SERVER.EXPECTED_WARDROBE_SLOT_VALUES)
            self.assertEqual(presets, SERVER.EXPECTED_WARDROBE_PRESETS)

            profile["allowFullyUnclothed"] = True
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SERVER.load_wardrobe_profile(path)

    def test_message_is_narrow(self):
        self.assertEqual(SERVER.normalize_message({"message": " hello "}), "hello")
        for payload in ({}, {"message": ""}, {"message": "x", "user": "admin"}, {"message": "x" * 2001}):
            with self.assertRaises(ValueError):
                SERVER.normalize_message(payload)

    def test_reply_removes_hidden_reasoning(self):
        self.assertEqual(
            SERVER.normalize_reply(
                "One moment. <think>执行耗时: 3.1s</think>\n\nHello from Ada."
            ),
            "One moment. \n\nHello from Ada.",
        )
        self.assertEqual(
            SERVER.normalize_reply("<think>unfinished private reasoning"),
            "I’m ready—please try that again.",
        )
        with self.assertRaises(ValueError):
            SERVER.normalize_reply({"reply": "no"})

    def test_llm_model_name_is_narrow(self):
        self.assertEqual(
            SERVER.checked_model_name("qwen3-4b-q4-k-m"),
            "qwen3-4b-q4-k-m",
        )
        for value in ("", "../model", "model name", "model/variant"):
            with self.assertRaises(argparse.ArgumentTypeError):
                SERVER.checked_model_name(value)

    def test_media_paths_are_relative(self):
        for path in SERVER.MEDIA_MAP.values():
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)

    def test_live_frame_requires_fresh_private_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            frame = live_root / "frame.jpg"
            payload = b"\xff\xd8private-preview\xff\xd9"
            frame.write_bytes(payload)
            frame.chmod(0o600)
            now_ns = time.time_ns()
            os.utime(frame, ns=(now_ns, now_ns))
            self.assertEqual(SERVER.read_live_frame(live_root, now_ns=now_ns), payload)

            stale_ns = now_ns + int((SERVER.MAX_LIVE_FRAME_AGE_SECONDS + 0.1) * 1e9)
            self.assertIsNone(SERVER.read_live_frame(live_root, now_ns=stale_ns))
            frame.write_bytes(b"not-a-jpeg")
            frame.chmod(0o600)
            os.utime(frame, ns=(now_ns, now_ns))
            self.assertIsNone(SERVER.read_live_frame(live_root, now_ns=now_ns))

    def test_live_frame_rejects_symlink_and_nonprivate_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            target = live_root / "target.jpg"
            target.write_bytes(b"\xff\xd8frame\xff\xd9")
            target.chmod(0o600)
            frame = live_root / "frame.jpg"
            frame.symlink_to(target.name)
            self.assertIsNone(SERVER.read_live_frame(live_root))
            frame.unlink()
            target.rename(frame)
            frame.chmod(0o644)
            self.assertIsNone(SERVER.read_live_frame(live_root))

    def test_stream_requires_renderer_and_fresh_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            frame = live_root / "frame.jpg"
            frame.write_bytes(b"\xff\xd8frame\xff\xd9")
            frame.chmod(0o600)
            self.assertFalse(SERVER.live_stream_ready(False, live_root))
            self.assertTrue(SERVER.live_stream_ready(True, live_root))

    def test_renderer_state_is_private_fresh_and_profile_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            now_ms = int(time.time() * 1000)
            state_path = live_root / SERVER.RENDERER_STATE_FILE
            state_path.write_text(json.dumps({
                "schemaVersion": 1,
                "state": "ready",
                "activeCharacter": "casual-girl",
                "requestedCharacter": "casual-girl",
                "availableCharacters": ["ada", "aoi", "casual-girl"],
                "packageGeneration": "v30",
                "updatedAtUnixMs": now_ms,
            }), encoding="utf-8")
            state_path.chmod(0o600)
            state = SERVER.read_renderer_state(live_root, now_unix_ms=now_ms)
            self.assertEqual(state["activeCharacter"], "casual-girl")
            self.assertEqual(state["packageGeneration"], "v30")

            state_path.chmod(0o644)
            self.assertIsNone(SERVER.read_renderer_state(live_root, now_unix_ms=now_ms))
            state_path.chmod(0o600)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            payload["availableCharacters"].append("arbitrary")
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            state_path.chmod(0o600)
            self.assertIsNone(SERVER.read_renderer_state(live_root, now_unix_ms=now_ms))

    def test_renderer_character_request_is_atomic_and_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o700)
            request = SERVER.write_renderer_request(live_root, "casual-girl")
            self.assertRegex(request["requestId"], r"^[0-9a-f]{24}$")
            request_path = live_root / SERVER.RENDERER_REQUEST_FILE
            self.assertEqual(request_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(request_path.read_text(encoding="utf-8"))["character"],
                "casual-girl",
            )
        for payload in (
            {}, {"character": "CasualGirl"}, {"character": "../Ada"},
            {"character": "ada", "path": "/tmp/runtime"},
        ):
            with self.assertRaises(ValueError):
                SERVER.normalize_renderer_character_request(payload)

    def test_private_live_root_rejects_shared_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            live_root.chmod(0o755)
            with self.assertRaises(ValueError):
                SERVER.safe_private_root(live_root, "live root")
            live_root.chmod(0o700)
            self.assertEqual(SERVER.safe_private_root(live_root, "live root"), live_root.resolve())

    def test_live_blob_preview_is_allowed_by_the_csp(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("img-src 'self' blob:", source)


if __name__ == "__main__":
    unittest.main()

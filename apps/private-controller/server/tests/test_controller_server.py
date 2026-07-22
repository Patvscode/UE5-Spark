import argparse
import importlib.util
import ipaddress
import os
import tempfile
import time
import unittest
from pathlib import Path


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

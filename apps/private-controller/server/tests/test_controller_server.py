import argparse
import importlib.util
import ipaddress
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

    def test_media_paths_are_relative(self):
        for path in SERVER.MEDIA_MAP.values():
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)


if __name__ == "__main__":
    unittest.main()

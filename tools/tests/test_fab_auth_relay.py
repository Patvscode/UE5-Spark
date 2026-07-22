from __future__ import annotations

from http import HTTPStatus
from http.client import HTTPConnection
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "fab-auth-relay.py"
SPEC = importlib.util.spec_from_file_location("fab_auth_relay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


class ActivationUrlValidationTests(unittest.TestCase):
    def test_accepts_observed_fab_activation_shape(self) -> None:
        value = "https://www.epicgames.com/activate?userCode=ABCD1234"
        self.assertEqual(relay.validate_activation_url(value), value)

    def test_rejects_non_https(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("http://www.epicgames.com/activate?userCode=ABCD1234")

    def test_rejects_lookalike_host(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://www.epicgames.com.example.test/activate?userCode=ABCD1234")

    def test_rejects_credentials_in_authority(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://user:pass@www.epicgames.com/activate?userCode=ABCD1234")

    def test_rejects_unreviewed_path(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://www.epicgames.com/store?userCode=ABCD1234")

    def test_rejects_unreviewed_query_parameter(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url(
                "https://www.epicgames.com/activate?userCode=ABCD1234&redirect_uri=https://example.test"
            )

    def test_rejects_missing_user_code(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://www.epicgames.com/activate?client_id=fab")

    def test_rejects_duplicate_user_code(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url(
                "https://www.epicgames.com/activate?userCode=ABCD1234&userCode=EFGH5678"
            )

    def test_rejects_legacy_bare_user_code_shape(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://www.epicgames.com/activate?ABCD1234")

    def test_rejects_unobserved_epic_host_and_path(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://epicgames.com/id/activate?userCode=ABCD1234")

    def test_rejects_malformed_user_code(self) -> None:
        rejected = ("", "abc12345", "ABCD-123", "ABCD12345", "ABCD123%00")
        for code in rejected:
            with self.subTest(code=code), self.assertRaises(ValueError):
                relay.validate_activation_url(f"https://www.epicgames.com/activate?userCode={code}")

    def test_rejects_fragment(self) -> None:
        with self.assertRaises(ValueError):
            relay.validate_activation_url("https://www.epicgames.com/activate?userCode=ABCD1234#fragment")


class RelayStateTests(unittest.TestCase):
    def test_ready_state_exposes_only_the_validated_user_code(self) -> None:
        state = relay.RelayState()
        value = "https://www.epicgames.com/activate?userCode=ABCD1234"
        state.offer(value)
        self.assertEqual(state.read_user_code(), "ABCD1234")

    def test_activation_url_is_consumed_once(self) -> None:
        state = relay.RelayState()
        value = "https://www.epicgames.com/activate?userCode=ABCD1234"
        state.offer(value)
        self.assertEqual(state.consume(), value)
        self.assertIsNone(state.consume())
        self.assertEqual(state.read_status(), "consumed")

    def test_rejected_state_never_accepts_later_url(self) -> None:
        state = relay.RelayState()
        state.reject()
        state.offer("https://www.epicgames.com/activate?userCode=ABCD1234")
        self.assertIsNone(state.consume())
        self.assertEqual(state.read_status(), "rejected")

    def test_later_rejection_cannot_clear_ready_or_consumed_state(self) -> None:
        state = relay.RelayState()
        value = "https://www.epicgames.com/activate?userCode=ABCD1234"
        state.offer(value)

        state.reject()
        self.assertEqual(state.read_status(), "ready")
        self.assertEqual(state.consume(), value)

        state.reject()
        self.assertEqual(state.read_status(), "consumed")
        self.assertIsNone(state.consume())


class RelayHttpTests(unittest.TestCase):
    token = "a" * 48
    activation_url = "https://www.epicgames.com/activate?userCode=ABCD1234"
    expected_security_headers = {
        "cache-control": "no-store, max-age=0",
        "pragma": "no-cache",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "x-robots-tag": "noindex, nofollow",
        "content-security-policy": (
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        ),
    }

    def setUp(self) -> None:
        self.state = relay.RelayState()
        handler = relay.make_handler(self.token, self.state)
        # HTTPServer performs a reverse-DNS lookup while binding.  Keep this
        # unit test deterministic on hosts whose resolver cannot answer PTR
        # queries for loopback promptly.
        with mock.patch("socket.getfqdn", return_value="localhost"):
            self.server = relay.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.assertFalse(self.server_thread.is_alive(), "relay HTTP server did not stop")

    def request(self, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
        host, port = self.server.server_address
        connection = HTTPConnection(host, port, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, headers, response.read()
        finally:
            connection.close()

    def assert_security_headers(self, headers: dict[str, str]) -> None:
        for name, expected in self.expected_security_headers.items():
            self.assertEqual(headers.get(name), expected, name)
        self.assertNotIn("set-cookie", headers)

    def test_every_response_class_uses_security_headers(self) -> None:
        cases = (
            ("GET", "/healthz", HTTPStatus.OK),
            ("GET", f"/{self.token}", HTTPStatus.OK),
            ("POST", f"/{self.token}", HTTPStatus.METHOD_NOT_ALLOWED),
            ("GET", "/unknown", HTTPStatus.NOT_FOUND),
            ("DELETE", f"/{self.token}", HTTPStatus.NOT_IMPLEMENTED),
        )
        for method, path, expected_status in cases:
            with self.subTest(method=method, path=path):
                status, headers, _body = self.request(method, path)
                self.assertEqual(status, expected_status)
                self.assert_security_headers(headers)

    def test_ready_page_shows_code_without_rendering_the_full_capability_url(self) -> None:
        self.state.offer(self.activation_url)

        status, headers, body = self.request("GET", f"/{self.token}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"ABCD1234", body)
        self.assertIn(b"https://www.epicgames.com/activate", body)
        self.assertNotIn(self.activation_url.encode(), body)
        self.assertNotIn(b"userCode=", body)
        self.assertNotIn("location", headers)
        self.assert_security_headers(headers)

        # Reloads are safe: the code remains available until EOS or the outer
        # launcher expires, rather than consuming a fragile browser redirect.
        self.assertEqual(self.state.read_status(), "ready")
        self.assertEqual(self.state.read_user_code(), "ABCD1234")

    def test_token_routes_are_exact_and_do_not_reflect_the_token(self) -> None:
        wrong_token = "b" * 48
        cases = (
            ("GET", "/"),
            ("GET", f"/{wrong_token}"),
            ("GET", f"/{self.token}/"),
            ("GET", f"/{self.token}?query=1"),
            ("GET", f"/unknown/{self.token}"),
        )
        for method, path in cases:
            with self.subTest(method=method, path=path):
                status, headers, body = self.request(method, path)
                self.assertEqual(status, HTTPStatus.NOT_FOUND)
                response = repr(headers).encode() + body
                self.assertNotIn(self.token.encode(), response)
                self.assertNotIn(self.activation_url.encode(), response)
                self.assert_security_headers(headers)

    def test_all_post_requests_are_rejected_without_redirecting(self) -> None:
        self.state.offer(self.activation_url)
        for path in (f"/{self.token}", f"/authorize/{self.token}", "/unknown"):
            with self.subTest(path=path):
                status, headers, body = self.request("POST", path)
                self.assertEqual(status, HTTPStatus.METHOD_NOT_ALLOWED)
                self.assertNotIn("location", headers)
                self.assertNotIn(self.activation_url.encode(), body)
                self.assert_security_headers(headers)


class FifoDrainTests(unittest.TestCase):
    activation_url = "https://www.epicgames.com/activate?userCode=ABCD1234"

    def write_line(self, fifo: Path, line: str, timeout: float = 2.0) -> None:
        completed = threading.Event()
        failures: list[BaseException] = []

        def write() -> None:
            try:
                with fifo.open("w", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except BaseException as exc:  # pragma: no cover - surfaced in caller
                failures.append(exc)
            finally:
                completed.set()

        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        self.assertTrue(completed.wait(timeout), "FIFO writer blocked waiting for a reader")
        if failures:
            raise failures[0]

    def wait_for_status(
        self,
        state: relay.RelayState,
        expected: str,
        timeout: float = 2.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if state.read_status() == expected:
                return
            time.sleep(0.01)
        self.fail(f"relay state did not become {expected!r}")

    def stop_reader(
        self,
        fifo: Path,
        stop_event: threading.Event,
        reader: threading.Thread,
    ) -> None:
        completed = threading.Event()

        def wake_and_stop() -> None:
            with fifo.open("w", encoding="utf-8") as stream:
                stop_event.set()
                stream.write(self.activation_url + "\n")
            completed.set()

        writer = threading.Thread(target=wake_and_stop, daemon=True)
        writer.start()
        self.assertTrue(completed.wait(2), "FIFO reader could not be woken for shutdown")
        reader.join(timeout=2)
        self.assertFalse(reader.is_alive(), "FIFO reader did not stop after its wakeup")

    def test_reader_keeps_draining_after_the_code_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "activation.fifo"
            os.mkfifo(fifo, mode=0o600)
            state = relay.RelayState()
            stop_event = threading.Event()
            reader = threading.Thread(
                target=relay.read_fifo,
                args=(fifo, state, stop_event),
                daemon=True,
            )
            reader.start()
            try:
                self.write_line(fifo, self.activation_url)
                self.wait_for_status(state, "ready")
                self.assertEqual(state.read_user_code(), "ABCD1234")

                # A later browser-open request must still be drained even though
                # the one-time activation code is already displayed.
                self.write_line(fifo, self.activation_url)
                self.assertEqual(state.read_status(), "ready")
                self.assertEqual(state.read_user_code(), "ABCD1234")
            finally:
                self.stop_reader(fifo, stop_event, reader)


if __name__ == "__main__":
    unittest.main()

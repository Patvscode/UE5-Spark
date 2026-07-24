from __future__ import annotations

import hashlib
import http.client
import json
import sys
import threading
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from ardy_pose_service import PoseServer  # noqa: E402
from motion_catalog import GENERATED_BEHAVIORS  # noqa: E402
from pose_protocol import (  # noqa: E402
    COORDINATE_SYSTEM,
    PROTOCOL_VERSION,
    source_descriptor,
)
from providers import MockPoseProvider  # noqa: E402


class DynamicMockPoseProvider(MockPoseProvider):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: set[str] = set()

    @property
    def health(self) -> dict[str, object]:
        return {**super().health, "dynamicTextReady": True}

    def prewarm_prompt(self, prompt: str) -> dict[str, object]:
        prompt_id = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cached = prompt_id in self.prompts
        self.prompts.add(prompt_id)
        return {"ok": True, "promptId": prompt_id, "cached": cached}


class PoseHttpServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = PoseServer(("127.0.0.1", 0), MockPoseProvider())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def _request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2.0)
        body = None
        headers = {"Accept": "application/json", "Connection": "close"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        value = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, value

    def test_health_advertises_complete_v2_source_and_catalog(self) -> None:
        status, value = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(
            set(value),
            {
                "status",
                "provider",
                "protocolVersion",
                "fps",
                "bufferFrames",
                "facialControl",
                "coordinateSystem",
                "source",
                "motionCatalog",
                "checkpoint",
                "embeddingCount",
                "p95GenerationMs",
                "dynamicTextReady",
            },
        )
        self.assertEqual(value["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(value["coordinateSystem"], COORDINATE_SYSTEM)
        self.assertEqual(value["source"], source_descriptor())
        self.assertEqual(value["motionCatalog"], list(GENERATED_BEHAVIORS))
        self.assertFalse(value["dynamicTextReady"])

    def test_v1_fails_closed_and_v2_returns_v2_envelope(self) -> None:
        payload = {"behavior": "wave", "intensity": 0.5, "duration": 2.0, "afterSequence": 0}
        old_status, old_value = self._request("POST", "/v1/poses", payload)
        self.assertEqual(old_status, 404)
        self.assertEqual(old_value, {"error": "not_found"})

        status, value = self._request("POST", "/v2/poses", payload)
        self.assertEqual(status, 200)
        self.assertEqual(value["version"], PROTOCOL_VERSION)
        self.assertEqual(value["source"], source_descriptor())
        self.assertEqual(len(value["frames"]), 8)

    def test_pose_request_accepts_dynamic_prompt_without_changing_response(self) -> None:
        status, value = self._request("POST", "/v2/poses", {
            "behavior": "explain",
            "prompt": "squat and stand back up",
            "intensity": 0.5,
            "duration": 4.0,
            "afterSequence": 0,
        })
        self.assertEqual(status, 200)
        self.assertEqual(set(value), {
            "version", "sequence", "fps", "coordinateSystem", "source", "frames"
        })

    def test_prompt_prewarm_is_strict_idempotent_and_unavailable_on_mock(self) -> None:
        status, value = self._request("POST", "/v2/prompts", {"prompt": "squat"})
        self.assertEqual(status, 503)
        self.assertEqual(value, {"error": "dynamic_text_unavailable"})

        self.server.provider = DynamicMockPoseProvider()
        first_status, first = self._request(
            "POST", "/v2/prompts", {"prompt": "  squat  "}
        )
        second_status, second = self._request(
            "POST", "/v2/prompts", {"prompt": "squat"}
        )
        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["promptId"], hashlib.sha256(b"squat").hexdigest())
        self.assertEqual(second["promptId"], first["promptId"])

        invalid_status, invalid = self._request(
            "POST", "/v2/prompts", {"prompt": "squat", "extra": True}
        )
        self.assertEqual(invalid_status, 400)
        self.assertEqual(invalid["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()

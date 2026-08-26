import json
import hashlib
import hmac
from threading import Thread
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from soulforge.server import build_server


class HealthServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = build_server("127.0.0.1", 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_endpoint(self) -> None:
        with urlopen(f"{self.base_url}/health", timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["stage"], "operational")
        self.assertEqual(payload["model"], "qwen3.5:4b")

    def test_unknown_endpoint_is_404(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            urlopen(f"{self.base_url}/v1/events", timeout=2)
        self.assertEqual(raised.exception.code, 404)

    def test_signed_event_is_accepted_and_deduplicated(self) -> None:
        event_id = str(uuid4())
        event = {
            "schema_version": "1.0", "event_id": event_id, "realm_id": "test",
            "event_type": "chat.whisper", "occurred_at": "2026-08-26T00:00:00Z",
            "actor": {"guid": "1", "kind": "human", "name": "Owner"},
            "participants": [{"guid": "2", "kind": "soul", "name": "Companion"}],
            "channel": "whisper", "text": "Remember me",
            "context": {},
            "trace": {"trace_id": str(uuid4()), "origin": "human", "hop_count": 0},
        }
        first = self._post_event(event)
        second = self._post_event(event)
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(second["status"], "duplicate")

    def _post_event(self, event: dict[str, object]) -> dict[str, str]:
        body = json.dumps(event, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce = str(uuid4())
        canonical = b"POST\n/v1/events\n" + timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
        signature = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
        request = Request(
            f"{self.base_url}/v1/events", data=body,
            headers={"Content-Type": "application/json", "X-Soulforge-Timestamp": timestamp,
                     "X-Soulforge-Nonce": nonce, "X-Soulforge-Signature": signature},
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)


if __name__ == "__main__":
    unittest.main()

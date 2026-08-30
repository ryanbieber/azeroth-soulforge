import json
import hashlib
import hmac
import io
from threading import Thread
import time
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
import zipfile

from soulforge.server import SoulStore, build_server


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

    def test_admin_session_requires_password_and_csrf(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self._request("POST", "/admin/v1/session", {"password": "wrong"})
        self.assertEqual(raised.exception.code, 401)

        payload, headers = self._request(
            "POST", "/admin/v1/session", {"password": "test-admin-password"}, include_headers=True
        )
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        csrf = payload["csrf_token"]
        self.assertIn("Secure", headers["Set-Cookie"])
        with self.assertRaises(HTTPError) as raised:
            self._request(
                "POST", "/admin/v1/souls",
                {"realm_id": "test", "bot_guid": "2", "name": "Companion"},
                headers={"Cookie": cookie},
            )
        self.assertEqual(raised.exception.code, 403)

        soul, _ = self._request(
            "POST", "/admin/v1/souls",
            {"realm_id": "test", "bot_guid": "2", "name": "Companion"},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf}, include_headers=True,
        )
        self.assertEqual(soul["name"], "Companion")

        saved, _ = self._request(
            "PATCH", "/admin/v1/souls/test/2",
            {"archetype": "stalwart guardian", "voice": "plainspoken", "values_text": "loyalty", "enabled": False},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf}, include_headers=True,
        )
        self.assertEqual(saved["status"], "saved")
        souls, _ = self._request(
            "GET", "/admin/v1/souls", headers={"Cookie": cookie}, include_headers=True
        )
        self.assertEqual(souls["souls"][0]["enabled"], 0)
        self.assertEqual(souls["souls"][0]["archetype"], "stalwart guardian")

        skill, _ = self._request(
            "GET", "/admin/v1/souls/test/2/skill", headers={"Cookie": cookie}, include_headers=True
        )
        self.assertIn("Roleplay guidance", skill["document"])
        self._request(
            "PUT", "/admin/v1/souls/test/2/skill",
            {"document": "## History\n\nCompanion once guarded the gates of Ironforge."},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf}, include_headers=True,
        )
        updated, _ = self._request(
            "GET", "/admin/v1/souls/test/2/skill", headers={"Cookie": cookie}, include_headers=True
        )
        self.assertIn("Ironforge", updated["document"])

    def test_addon_download_infers_companions_from_active_world(self) -> None:
        self.server.addon_dir = Path(__file__).resolve().parents[2] / "addons" / "SoulforgeCommander"
        self.server.worlds.companions = lambda: [
            {"name": "Firstbot"}, {"name": "Secondbot"},
        ]
        _, headers = self._request(
            "POST", "/admin/v1/session", {"password": "test-admin-password"}, include_headers=True
        )
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        request = Request(
            f"{self.base_url}/admin/v1/addon/download", headers={"Cookie": cookie}
        )
        with urlopen(request, timeout=2) as response:
            archive_bytes = response.read()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            roster = archive.read("SoulforgeCommander/Companions.lua").decode()
            source = archive.read("SoulforgeCommander/SoulforgeCommander.lua").decode()
        self.assertIn('"Firstbot"', roster)
        self.assertIn('"Secondbot"', roster)
        self.assertNotIn("Firstbot", source)

    def test_skill_file_uses_character_name_but_preserves_internal_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SoulStore(str(Path(directory) / "soulforge.sqlite3"))
            store.seed_soul("test-realm", "1842", "Thorn")
            store.update_skill_document("test-realm", "1842", "## History\n\nThorn remembers the old road.")
            skill_path = Path(directory) / "profiles" / "test-realm" / "Thorn" / "SKILL.md"
            self.assertTrue(skill_path.is_file())
            text = skill_path.read_text(encoding="utf-8")
            self.assertIn("character_guid: 1842", text)
            self.assertIn("Thorn remembers the old road", text)
            self.assertFalse((Path(directory) / "profiles" / "test-realm" / "1842").exists())

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

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None,
                 headers: dict[str, str] | None = None, include_headers: bool = False):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}", data=body, method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urlopen(request, timeout=2) as response:
            result = json.load(response) if response.status != 204 else None
            return (result, response.headers) if include_headers else result


if __name__ == "__main__":
    unittest.main()

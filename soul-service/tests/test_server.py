import json
import hashlib
import hmac
import io
from contextlib import redirect_stdout
from threading import Thread
import time
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
import zipfile
from unittest.mock import patch

from soulforge.providers import InferenceResult
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

    def test_ai_route_logs_token_counts_without_prompt_or_response_text(self) -> None:
        self.server.provider_gateway.generate = lambda *args, **kwargs: InferenceResult(
            "private generated response",
            {"input_tokens": 21, "cached_input_tokens": 3, "output_tokens": 8,
             "reasoning_tokens": 2, "total_tokens": 31},
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.server._route_generation("dialogue", "private prompt text")
        log = output.getvalue()
        self.assertEqual(result, "private generated response")
        self.assertIn('\"event\":\"ai_call\"', log)
        self.assertIn('\"route\":\"dialogue\"', log)
        self.assertIn('\"input_tokens\":21', log)
        self.assertIn('\"output_tokens\":8', log)
        self.assertIn('\"total_tokens\":31', log)
        self.assertNotIn("private prompt text", log)
        self.assertNotIn("private generated response", log)

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

    def test_replies_return_to_the_human_initiated_chat_channel(self) -> None:
        store = self.server.store
        for channel in ("say", "whisper", "party", "raid", "guild", "channel"):
            with self.subTest(channel=channel):
                event_id = str(uuid4())
                context = {"channel_name": "General - Elwynn Forest"} if channel == "channel" else {}
                event = {
                    "event_id": event_id,
                    "realm_id": "test",
                    "participants": [{"guid": "2", "kind": "soul", "name": "Companion"}],
                    "actor": {"guid": "1", "kind": "human", "name": "Owner"},
                    "channel": channel,
                    "text": "Companion, what do you think?",
                    "context": context,
                    "trace": {"trace_id": str(uuid4()), "origin": "human", "hop_count": 0},
                }
                store.accept(event, json.dumps(event))
                store.complete(event, "I think we should keep moving.")
                reply = next(item for item in store.pending("test", 20) if item["source_event_id"] == event_id)
                self.assertEqual(reply["channel"], channel)
                self.assertEqual(reply["channel_name"], context.get("channel_name", ""))

    def test_public_channel_event_requires_a_channel_name(self) -> None:
        event = {
            "event_id": str(uuid4()), "realm_id": "test", "event_type": "chat.channel",
            "actor": {"guid": "1", "kind": "human", "name": "Owner"},
            "participants": [{"guid": "2", "kind": "soul", "name": "Companion"}],
            "channel": "channel", "text": "Companion?", "context": {},
            "trace": {"trace_id": str(uuid4()), "origin": "human", "hop_count": 0},
        }
        with self.assertRaisesRegex(ValueError, "channel name"):
            self.server.RequestHandlerClass._validate_event(event)

    def test_ambient_random_bot_uses_small_route_without_personal_memory(self) -> None:
        event = {
            "event_id": str(uuid4()), "realm_id": "test", "event_type": "chat.channel",
            "actor": {"guid": "1", "kind": "human", "name": "Owner"},
            "participants": [{"guid": "99", "kind": "playerbot", "name": "Roadwarrior"}],
            "channel": "channel", "text": "anyone know where Mankrik is?",
            "context": {"dialogue_tier": "ambient", "channel_name": "General - The Barrens",
                        "zone_name": "The Barrens", "zone_id": 17},
            "trace": {"trace_id": str(uuid4()), "origin": "human", "hop_count": 0},
        }
        self.server.store.accept(event, json.dumps(event))
        self.server.worlds.save_ai_state({"ambient_reply_percent": 25, "ambient_cooldown_seconds": 5})
        observed = {}
        def generate(purpose, prompt):
            observed.update(purpose=purpose, prompt=prompt)
            return "check near the quilboar camps, unless chat sends you to Thunder Bluff again"
        self.server._route_generation = generate
        with patch("soulforge.server.secrets.randbelow", return_value=0):
            self.server._ambient_dialogue(event)
        self.assertEqual(observed["purpose"], "ambient")
        self.assertIn("The Barrens", observed["prompt"])
        self.assertIn("2004-2009-era", observed["prompt"])
        reply = self.server.store.pending("test", 5)[0]
        self.assertEqual(reply["channel"], "channel")
        self.assertEqual(reply["channel_name"], "General - The Barrens")
        self.assertEqual(self.server.store.souls(), [])

    def test_companion_prompt_preview_shows_bounded_layers(self) -> None:
        self.server.store.seed_soul("test", "2", "Companion")
        preview = self.server.store.prompt_preview("test", "2")
        self.assertIn("Your character skill document", preview["prompt"])
        self.assertIn("Immutable world canon", preview["prompt"])
        self.assertIn("Recent memories", preview["prompt"])

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

    def test_addon_download_is_generic_and_roster_sync_uses_active_world(self) -> None:
        self.server.addon_dir = Path(__file__).resolve().parents[2] / "addons" / "SoulforgeCommander"
        self.server.worlds.companions = lambda: [
            {"name": "Firstbot", "role": "tank"}, {"name": "Secondbot", "role": "healer"},
        ]
        self.server.worlds.active_world = lambda: {"realm_id": "azeroth-soulforge"}
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
            files = archive.namelist()
            source = archive.read("SoulforgeCommander/SoulforgeCommander.lua").decode()
            toc = archive.read("SoulforgeCommander/SoulforgeCommander.toc").decode()
        self.assertNotIn("SoulforgeCommander/Companions.lua", files)
        self.assertIn("SoulforgeCommander/Bindings.xml", files)
        self.assertIn("Bindings.xml", toc.splitlines())
        self.assertNotIn("Firstbot", source)
        self.assertIn(".soulforge roster", source)

        roster = self._signed_get("/v1/companion-roster?realm_id=azeroth-soulforge")
        self.assertEqual(roster["companions"], [
            {"name": "Firstbot", "role": "tank"},
            {"name": "Secondbot", "role": "healer"},
        ])

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

    def _signed_get(self, path: str) -> dict[str, object]:
        timestamp = str(int(time.time()))
        nonce = str(uuid4())
        canonical = f"GET\n{path}\n{timestamp}\n{nonce}\n".encode()
        signature = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
        request = Request(
            f"{self.base_url}{path}",
            headers={"X-Soulforge-Timestamp": timestamp, "X-Soulforge-Nonce": nonce,
                     "X-Soulforge-Signature": signature},
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

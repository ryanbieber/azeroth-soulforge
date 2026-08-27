"""Local, durable Soulforge bridge service.

The game thread only exchanges events and replies with this service. Ollama and
SQLite work happen here, outside AzerothCore's world update loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import mimetypes
import os
from pathlib import Path
from queue import Queue
import re
import secrets
import sqlite3
from threading import Lock, Thread
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

MAX_BODY = 64 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SoulStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.profile_root = None if path == ":memory:" else Path(path).parent / "profiles"
        self._profile_lock = Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection = sqlite3.connect(path, check_same_thread=False) if path == ":memory:" else None
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = self._memory_connection or sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def close(self, connection: sqlite3.Connection) -> None:
        if connection is not self._memory_connection:
            connection.close()

    def _initialize(self) -> None:
        connection = self.connect()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY, realm_id TEXT NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS souls (
              realm_id TEXT NOT NULL, bot_guid TEXT NOT NULL, name TEXT NOT NULL,
              archetype TEXT NOT NULL DEFAULT 'adventuring companion',
              voice TEXT NOT NULL DEFAULT 'warm, concise, and grounded in Azeroth',
              values_text TEXT NOT NULL DEFAULT 'loyalty, courage, curiosity',
              updated_at TEXT NOT NULL, PRIMARY KEY (realm_id, bot_guid)
            );
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT, realm_id TEXT NOT NULL,
              bot_guid TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS memories_soul_idx
              ON memories(realm_id, bot_guid, id DESC);
            CREATE TABLE IF NOT EXISTS outbox (
              reply_id TEXT PRIMARY KEY, source_event_id TEXT NOT NULL UNIQUE,
              realm_id TEXT NOT NULL, bot_guid TEXT NOT NULL,
              recipient_guid TEXT NOT NULL, channel TEXT NOT NULL, text TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT NOT NULL, trace_id TEXT NOT NULL,
              acknowledged_at TEXT
            );
            CREATE TABLE IF NOT EXISTS nonces (
              nonce TEXT PRIMARY KEY, seen_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
              token_hash TEXT PRIMARY KEY, csrf_token TEXT NOT NULL,
              created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
              name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        try:
            connection.execute("ALTER TABLE souls ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError as error:
            if "duplicate column" not in str(error).lower():
                raise
        try:
            connection.execute("ALTER TABLE souls ADD COLUMN skill_document TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError as error:
            if "duplicate column" not in str(error).lower():
                raise
        connection.commit()
        self.close(connection)

    def remember_nonce(self, nonce: str, seen_at: int) -> bool:
        connection = self.connect()
        try:
            connection.execute("DELETE FROM nonces WHERE seen_at < ?", (seen_at - 300,))
            connection.execute("INSERT INTO nonces(nonce, seen_at) VALUES(?, ?)", (nonce, seen_at))
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            self.close(connection)

    def accept(self, event: dict[str, Any], raw: str) -> str:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO events(event_id, realm_id, payload, created_at) VALUES(?, ?, ?, ?)",
                (event["event_id"], event["realm_id"], raw, utc_now()),
            )
            connection.commit()
            return "accepted" if cursor.rowcount else "duplicate"
        finally:
            self.close(connection)

    def build_prompt(self, event: dict[str, Any]) -> tuple[str, str, str] | None:
        soul = event["participants"][0]
        realm, guid, name = event["realm_id"], str(soul["guid"]), soul["name"]
        connection = self.connect()
        connection.execute(
            "INSERT OR IGNORE INTO souls(realm_id, bot_guid, name, updated_at) VALUES(?, ?, ?, ?)",
            (realm, guid, name, utc_now()),
        )
        connection.execute(
            "UPDATE souls SET name=?, updated_at=? WHERE realm_id=? AND bot_guid=?",
            (name, utc_now(), realm, guid),
        )
        profile = connection.execute(
            "SELECT * FROM souls WHERE realm_id=? AND bot_guid=?", (realm, guid)
        ).fetchone()
        if not profile["enabled"]:
            connection.execute("UPDATE events SET status='paused' WHERE event_id=?", (event["event_id"],))
            connection.commit()
            self.close(connection)
            return None
        guidance = profile["skill_document"] or self._default_guidance(name)
        if not profile["skill_document"]:
            connection.execute(
                "UPDATE souls SET skill_document=? WHERE realm_id=? AND bot_guid=?",
                (guidance, realm, guid),
            )
        memories = connection.execute(
            "SELECT role, text FROM memories WHERE realm_id=? AND bot_guid=? ORDER BY id DESC LIMIT 12",
            (realm, guid),
        ).fetchall()[::-1]
        connection.commit()
        self.close(connection)
        memory_text = "\n".join(f"{row['role']}: {row['text']}" for row in memories) or "No prior memories yet."
        actor = event["actor"]
        prompt = (
            f"You are {name}, a persistent World of Warcraft companion—not an AI assistant. "
            f"Archetype: {profile['archetype']}. Voice: {profile['voice']}. "
            f"Values: {profile['values_text']}. Stay in character, never claim consciousness, "
            "never issue gameplay commands, and answer in at most 3 short sentences.\n"
            f"Your character skill document:\n{guidance}\n"
            f"Recent memories:\n{memory_text}\n"
            f"{actor['name']} says in {event['channel']}: {event['text']}"
        )
        self._materialize_skill(realm, guid)
        return realm, guid, prompt

    def complete(self, event: dict[str, Any], reply: str) -> None:
        soul = event["participants"][0]
        realm, guid = event["realm_id"], str(soul["guid"])
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        connection = self.connect()
        connection.execute(
            "INSERT INTO memories(realm_id, bot_guid, role, text, created_at) VALUES(?, ?, 'human', ?, ?)",
            (realm, guid, event["text"][:2048], now),
        )
        connection.execute(
            "INSERT INTO memories(realm_id, bot_guid, role, text, created_at) VALUES(?, ?, 'soul', ?, ?)",
            (realm, guid, reply[:2048], now),
        )
        connection.execute(
            """INSERT OR IGNORE INTO outbox
               (reply_id, source_event_id, realm_id, bot_guid, recipient_guid, channel,
                text, created_at, expires_at, trace_id)
               VALUES(?, ?, ?, ?, ?, 'whisper', ?, ?, ?, ?)""",
            (str(uuid4()), event["event_id"], realm, guid, str(event["actor"]["guid"]),
             reply[:1024], now, expires, event["trace"]["trace_id"]),
        )
        connection.execute("UPDATE events SET status='complete' WHERE event_id=?", (event["event_id"],))
        connection.commit()
        self.close(connection)
        self._materialize_skill(realm, guid)

    def pending(self, realm: str, limit: int) -> list[dict[str, Any]]:
        connection = self.connect()
        rows = connection.execute(
            """SELECT * FROM outbox WHERE realm_id=? AND acknowledged_at IS NULL
               AND expires_at > ? ORDER BY created_at LIMIT ?""", (realm, utc_now(), limit)
        ).fetchall()
        self.close(connection)
        return [{
            "reply_id": row["reply_id"], "source_event_id": row["source_event_id"],
            "realm_id": row["realm_id"], "bot_guid": row["bot_guid"],
            "recipient_guid": row["recipient_guid"], "channel": row["channel"],
            "text": row["text"], "created_at": row["created_at"], "expires_at": row["expires_at"],
            "trace": {"trace_id": row["trace_id"], "origin": "generated", "hop_count": 1},
        } for row in rows]

    def acknowledge(self, reply_id: str, delivered_at: str) -> bool:
        connection = self.connect()
        cursor = connection.execute(
            "UPDATE outbox SET acknowledged_at=COALESCE(acknowledged_at, ?) WHERE reply_id=?",
            (delivered_at, reply_id),
        )
        connection.commit()
        self.close(connection)
        return bool(cursor.rowcount)

    def souls(self) -> list[dict[str, Any]]:
        connection = self.connect()
        rows = connection.execute(
            """SELECT s.*, COUNT(m.id) AS memory_count FROM souls s
               LEFT JOIN memories m ON m.realm_id=s.realm_id AND m.bot_guid=s.bot_guid
               GROUP BY s.realm_id,s.bot_guid ORDER BY s.name"""
        ).fetchall()
        self.close(connection)
        return [dict(row) for row in rows]

    def seed_soul(self, realm: str, guid: str, name: str) -> dict[str, Any]:
        connection = self.connect()
        connection.execute(
            "INSERT OR IGNORE INTO souls(realm_id,bot_guid,name,updated_at) VALUES(?,?,?,?)",
            (realm, guid, name[:24], utc_now()),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM souls WHERE realm_id=? AND bot_guid=?", (realm, guid)
        ).fetchone()
        self.close(connection)
        self._materialize_skill(realm, guid)
        return dict(row)

    def update_soul(self, realm: str, guid: str, fields: dict[str, Any]) -> bool:
        connection = self.connect()
        cursor = connection.execute(
            """UPDATE souls SET archetype=?, voice=?, values_text=?, enabled=?, updated_at=?
               WHERE realm_id=? AND bot_guid=?""",
            (fields["archetype"][:200], fields["voice"][:300], fields["values_text"][:300],
             1 if fields.get("enabled", True) else 0, utc_now(), realm, guid),
        )
        connection.commit()
        self.close(connection)
        if cursor.rowcount:
            self._materialize_skill(realm, guid)
        return bool(cursor.rowcount)

    def soul_memories(self, realm: str, guid: str, limit: int = 100) -> list[dict[str, Any]]:
        connection = self.connect()
        rows = connection.execute(
            """SELECT id,role,text,created_at FROM memories
               WHERE realm_id=? AND bot_guid=? ORDER BY id DESC LIMIT ?""",
            (realm, guid, min(max(limit, 1), 200)),
        ).fetchall()
        self.close(connection)
        return [dict(row) for row in rows]

    def delete_memory(self, realm: str, guid: str, memory_id: int) -> bool:
        connection = self.connect()
        cursor = connection.execute(
            "DELETE FROM memories WHERE id=? AND realm_id=? AND bot_guid=?",
            (memory_id, realm, guid),
        )
        connection.commit()
        self.close(connection)
        if cursor.rowcount:
            self._materialize_skill(realm, guid)
        return bool(cursor.rowcount)

    def skill_document(self, realm: str, guid: str) -> str | None:
        connection = self.connect()
        row = connection.execute(
            "SELECT name,skill_document FROM souls WHERE realm_id=? AND bot_guid=?", (realm, guid)
        ).fetchone()
        if not row:
            self.close(connection)
            return None
        document = row["skill_document"] or self._default_guidance(row["name"])
        if not row["skill_document"]:
            connection.execute(
                "UPDATE souls SET skill_document=? WHERE realm_id=? AND bot_guid=?",
                (document, realm, guid),
            )
            connection.commit()
        self.close(connection)
        self._materialize_skill(realm, guid)
        return document

    def update_skill_document(self, realm: str, guid: str, document: str) -> bool:
        document = document.strip()
        if not 1 <= len(document) <= 32_000:
            raise ValueError("skill document must be between 1 and 32000 characters")
        if "<!-- soulforge:memories:" in document:
            raise ValueError("managed memory markers cannot be edited")
        connection = self.connect()
        cursor = connection.execute(
            "UPDATE souls SET skill_document=?,updated_at=? WHERE realm_id=? AND bot_guid=?",
            (document, utc_now(), realm, guid),
        )
        connection.commit()
        self.close(connection)
        if cursor.rowcount:
            self._materialize_skill(realm, guid)
        return bool(cursor.rowcount)

    @staticmethod
    def _default_guidance(name: str) -> str:
        return (
            f"## Roleplay guidance\n\n"
            f"{name} should grow through shared adventures while remaining consistent with the canonical profile.\n\n"
            "## History and mannerisms\n\n"
            "Add formative history, loyalties, fears, habits, humor, and speech patterns here.\n\n"
            "## Goals and boundaries\n\n"
            "Add personal goals and roleplay boundaries here. Generated recollections never override canonical facts."
        )

    def _materialize_skill(self, realm: str, guid: str) -> None:
        if self.profile_root is None or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", realm) \
                or not re.fullmatch(r"[1-9][0-9]{0,19}", guid):
            return
        with self._profile_lock:
            connection = self.connect()
            profile = connection.execute(
                "SELECT * FROM souls WHERE realm_id=? AND bot_guid=?", (realm, guid)
            ).fetchone()
            memories = connection.execute(
                """SELECT role,text,created_at FROM memories WHERE realm_id=? AND bot_guid=?
                   ORDER BY id DESC LIMIT 50""", (realm, guid)
            ).fetchall()
            self.close(connection)
            if not profile:
                return
            guidance = profile["skill_document"] or self._default_guidance(profile["name"])
            memory_lines = []
            for memory in memories:
                text = memory["text"].replace("<", "&lt;").replace("\n", " ")
                memory_lines.append(f"- {memory['created_at']} · **{memory['role']}** — {text}")
            ledger = "\n".join(memory_lines) or "- No memories recorded yet."
            document = (
                "---\n"
                "schema_version: 1.0\n"
                f"realm_id: {realm}\n"
                f"character_guid: {guid}\n"
                f"name: {json.dumps(profile['name'], ensure_ascii=False)}\n"
                f"enabled: {'true' if profile['enabled'] else 'false'}\n"
                "---\n\n"
                f"# {profile['name']}\n\n"
                "> This file is the durable character skill for one simulated companion. "
                "It does not claim consciousness or sentience.\n\n"
                "## Canonical profile (Soulforge managed)\n\n"
                f"- **Archetype:** {profile['archetype']}\n"
                f"- **Voice:** {profile['voice']}\n"
                f"- **Values:** {profile['values_text']}\n\n"
                "## Character skill (owner editable)\n\n"
                f"{guidance}\n\n"
                "<!-- soulforge:memories:start -->\n"
                "## Memory ledger (Soulforge managed)\n\n"
                f"{ledger}\n"
                "<!-- soulforge:memories:end -->\n"
            )
            realm_directory = self.profile_root / realm
            realm_directory.mkdir(parents=True, exist_ok=True)
            display_name = re.sub(r"[^A-Za-z0-9_-]", "_", profile["name"])[:32] or "Unnamed"
            directory = realm_directory / display_name
            for prior in realm_directory.iterdir():
                prior_skill = prior / "SKILL.md"
                if prior == directory or not prior.is_dir() or not prior_skill.is_file():
                    continue
                if f"character_guid: {guid}\n" in prior_skill.read_text(encoding="utf-8", errors="ignore"):
                    if not directory.exists():
                        prior.rename(directory)
                    break
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / "SKILL.md.tmp"
            destination = directory / "SKILL.md"
            temporary.write_text(document, encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(destination)

    def get_settings(self) -> dict[str, str]:
        connection = self.connect()
        rows = connection.execute("SELECT name,value FROM settings").fetchall()
        self.close(connection)
        return {row["name"]: row["value"] for row in rows}

    def set_settings(self, values: dict[str, str]) -> None:
        connection = self.connect()
        for name, value in values.items():
            connection.execute(
                """INSERT INTO settings(name,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (name, value, utc_now()),
            )
        connection.commit()
        self.close(connection)

    def create_session(self) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        now = int(time.time())
        connection = self.connect()
        connection.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))
        connection.execute(
            "INSERT INTO admin_sessions(token_hash,csrf_token,created_at,expires_at) VALUES(?,?,?,?)",
            (sha256(token.encode()).hexdigest(), csrf, now, now + 12 * 60 * 60),
        )
        connection.commit()
        self.close(connection)
        return token, csrf

    def session_csrf(self, token: str) -> str | None:
        if not token:
            return None
        connection = self.connect()
        row = connection.execute(
            "SELECT csrf_token FROM admin_sessions WHERE token_hash=? AND expires_at>?",
            (sha256(token.encode()).hexdigest(), int(time.time())),
        ).fetchone()
        self.close(connection)
        return row["csrf_token"] if row else None

    def delete_session(self, token: str) -> None:
        connection = self.connect()
        connection.execute(
            "DELETE FROM admin_sessions WHERE token_hash=?", (sha256(token.encode()).hexdigest(),)
        )
        connection.commit()
        self.close(connection)


class SoulforgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: SoulStore, secret: str,
                 admin_password: str = "test-admin-password", start_worker: bool = True) -> None:
        super().__init__(address, SoulHandler)
        self.store = store
        self.secret = secret.encode()
        persisted = store.get_settings()
        self.model = persisted.get("chat_model", os.environ.get("SOULFORGE_CHAT_MODEL", "qwen3.5:4b"))
        self.souls_enabled = persisted.get("souls_enabled", "true") == "true"
        self.temperature = float(persisted.get("temperature", "0.75"))
        self.max_tokens = int(persisted.get("max_tokens", "180"))
        self.ollama_url = os.environ.get("SOULFORGE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.admin_password = admin_password
        self.control_url = os.environ.get("SOULFORGE_CONTROL_URL", "http://control-agent:8770").rstrip("/")
        self.control_secret = os.environ.get("SOULFORGE_CONTROL_SECRET", "test-control-secret")
        self.dashboard_dir = Path(os.environ.get("SOULFORGE_DASHBOARD_DIR", "/app/dashboard"))
        self.login_attempts: dict[str, list[float]] = {}
        self.login_lock = Lock()
        self.jobs: Queue[dict[str, Any]] = Queue(maxsize=2048)
        if start_worker:
            Thread(target=self._worker, daemon=True, name="soulforge-inference").start()

    def _worker(self) -> None:
        while True:
            event = self.jobs.get()
            try:
                if not self.souls_enabled:
                    continue
                prompt_data = self.store.build_prompt(event)
                if prompt_data is None:
                    continue
                _, _, prompt = prompt_data
                body = json.dumps({
                    "model": self.model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
                }).encode()
                request = Request(f"{self.ollama_url}/api/chat", data=body, headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=120) as response:
                    reply = json.load(response)["message"]["content"].strip()
                if reply:
                    self.store.complete(event, reply)
            except Exception as error:  # Stay silent in game when inference is unavailable.
                print(f"inference failed for {event.get('event_id')}: {error}", flush=True)
            finally:
                self.jobs.task_done()

    def control(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload or {}, separators=(",", ":")).encode() if method != "GET" else None
        request = Request(
            f"{self.control_url}{path}", data=body, method=method,
            headers={"Authorization": f"Bearer {self.control_secret}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=150) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error)
            except json.JSONDecodeError:
                detail = {"error": "control_failed", "detail": str(error)}
            raise RuntimeError(detail.get("detail", detail.get("error", str(error)))) from error
        except URLError as error:
            raise RuntimeError("control agent is unavailable") from error

    def installed_models(self) -> list[str]:
        try:
            with urlopen(f"{self.ollama_url}/api/tags", timeout=5) as response:
                payload = json.load(response)
            return [item["name"] for item in payload.get("models", []) if item.get("name")]
        except (URLError, HTTPError, ValueError, KeyError):
            return []


class SoulHandler(BaseHTTPRequestHandler):
    server: SoulforgeServer
    server_version = "Soulforge/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "stage": "operational", "model": self.server.model})
        elif parsed.path == "/v1/outbox":
            if not self._authorized(b""):
                return
            query = parse_qs(parsed.query)
            realm = query.get("realm_id", [""])[0]
            limit = min(max(int(query.get("limit", ["20"])[0]), 1), 100)
            self._json(HTTPStatus.OK, {"replies": self.server.store.pending(realm, limit)})
        elif parsed.path == "/admin/v1/session":
            csrf = self._admin_session()
            if csrf:
                self._json(HTTPStatus.OK, {"authenticated": True, "csrf_token": csrf})
        elif parsed.path == "/admin/v1/souls":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"souls": self.server.store.souls()})
        elif parsed.path.startswith("/admin/v1/souls/") and parsed.path.endswith("/skill"):
            if not self._admin_session():
                return
            parts = parsed.path.split("/")
            if len(parts) != 7:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            document = self.server.store.skill_document(unquote(parts[4]), parts[5])
            if document is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            else:
                self._json(HTTPStatus.OK, {"document": document, "filename": "SKILL.md"})
        elif parsed.path.startswith("/admin/v1/souls/") and parsed.path.endswith("/memories"):
            if not self._admin_session():
                return
            parts = parsed.path.split("/")
            if len(parts) != 7:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(HTTPStatus.OK, {
                "memories": self.server.store.soul_memories(unquote(parts[4]), parts[5])
            })
        elif parsed.path == "/admin/v1/server/status":
            if self._admin_session():
                self._admin_control("GET", "/v1/status")
        elif parsed.path == "/admin/v1/server/settings":
            if not self._admin_session():
                return
            try:
                settings = self.server.control("GET", "/v1/settings")
                settings.update({
                    "chat_model": self.server.model,
                    "souls_enabled": self.server.souls_enabled,
                    "temperature": self.server.temperature,
                    "max_tokens": self.server.max_tokens,
                })
                self._json(HTTPStatus.OK, settings)
            except RuntimeError as error:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "control_unavailable", "detail": str(error)})
        elif parsed.path == "/admin/v1/bots":
            if self._admin_session():
                self._admin_control("GET", "/v1/bots")
        elif parsed.path == "/admin/v1/auction-house/characters":
            if self._admin_session():
                self._admin_control("GET", "/v1/auction-house/characters")
        elif parsed.path == "/admin/v1/models":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"models": self.server.installed_models(), "active": self.server.model})
        elif parsed.path.startswith("/admin/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        else:
            self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too_large"})
            return
        body = self.rfile.read(length)
        if self.path == "/v1/events":
            if not self._authorized(body):
                return
            try:
                event = json.loads(body)
                self._validate_event(event)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_event", "detail": str(error)})
                return
            status = self.server.store.accept(event, body.decode())
            if status == "accepted":
                self.server.jobs.put_nowait(event)
            self._json(HTTPStatus.ACCEPTED, {"event_id": event["event_id"], "status": status})
        elif self.path.startswith("/v1/outbox/") and self.path.endswith("/ack"):
            if not self._authorized(body):
                return
            reply_id = self.path.split("/")[3]
            payload = json.loads(body or b"{}")
            if self.server.store.acknowledge(reply_id, payload.get("delivered_at", utc_now())):
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        elif self.path == "/admin/v1/session":
            self._login(body)
        elif self.path == "/admin/v1/souls":
            if not self._admin_session(csrf=True):
                return
            try:
                payload = json.loads(body)
                realm, guid, name = str(payload["realm_id"]), str(payload["bot_guid"]), str(payload["name"])
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", realm):
                    raise ValueError("invalid realm")
                if not re.fullmatch(r"[1-9][0-9]{0,19}", guid) or not 1 <= len(name) <= 24:
                    raise ValueError("invalid bot identity")
                self._json(HTTPStatus.CREATED, self.server.store.seed_soul(realm, guid, name))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_soul", "detail": str(error)})
        elif self.path.startswith("/admin/v1/server/actions/"):
            if not self._admin_session(csrf=True):
                return
            action = self.path.rsplit("/", 1)[-1]
            if action not in {"start", "stop", "restart"}:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_action"})
            else:
                self._admin_control("POST", f"/v1/actions/{action}", {})
        elif self.path == "/admin/v1/models/pull":
            if not self._admin_session(csrf=True):
                return
            try:
                payload = json.loads(body)
                model = self._model_name(str(payload.get("model", "")))
                request = Request(
                    f"{self.server.ollama_url}/api/pull",
                    data=json.dumps({"model": model, "stream": False}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=1800) as response:
                    result = json.load(response)
                self._json(HTTPStatus.OK, {"status": result.get("status", "success"), "model": model})
            except (ValueError, HTTPError, URLError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "model_pull_failed", "detail": str(error)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._admin_session(csrf=True):
            return
        body = self._read_admin_body()
        if body is None:
            return
        parts = urlparse(self.path).path.split("/")
        if len(parts) != 6 or parts[1:4] != ["admin", "v1", "souls"]:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            payload = json.loads(body)
            fields = {
                "archetype": str(payload["archetype"]),
                "voice": str(payload["voice"]),
                "values_text": str(payload["values_text"]),
                "enabled": payload.get("enabled", True),
            }
            if not all(value.strip() for key, value in fields.items() if key != "enabled"):
                raise ValueError("profile fields cannot be empty")
            if not isinstance(fields["enabled"], bool):
                raise ValueError("enabled must be boolean")
            if not self.server.store.update_soul(unquote(parts[4]), parts[5], fields):
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(HTTPStatus.OK, {"status": "saved"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_profile", "detail": str(error)})

    def do_PUT(self) -> None:  # noqa: N802
        parsed_path = urlparse(self.path).path
        if parsed_path.startswith("/admin/v1/souls/") and parsed_path.endswith("/skill"):
            if not self._admin_session(csrf=True):
                return
            body = self._read_admin_body()
            if body is None:
                return
            parts = parsed_path.split("/")
            if len(parts) != 7:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                document = str(json.loads(body)["document"])
                if not self.server.store.update_skill_document(unquote(parts[4]), parts[5], document):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                self._json(HTTPStatus.OK, {"status": "saved"})
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_skill", "detail": str(error)})
            return
        if parsed_path != "/admin/v1/server/settings":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._admin_session(csrf=True):
            return
        body = self._read_admin_body()
        if body is None:
            return
        try:
            payload = json.loads(body)
            local: dict[str, str] = {}
            if "chat_model" in payload:
                model = self._model_name(str(payload["chat_model"]))
                installed = self.server.installed_models()
                if model not in installed:
                    raise ValueError("install the model before activating it")
                self.server.model = model
                local["chat_model"] = model
            if "souls_enabled" in payload:
                if not isinstance(payload["souls_enabled"], bool):
                    raise ValueError("souls_enabled must be boolean")
                self.server.souls_enabled = payload["souls_enabled"]
                local["souls_enabled"] = "true" if payload["souls_enabled"] else "false"
            if "temperature" in payload:
                temperature = float(payload["temperature"])
                if not 0 <= temperature <= 2:
                    raise ValueError("temperature must be between 0 and 2")
                self.server.temperature = temperature
                local["temperature"] = str(temperature)
            if "max_tokens" in payload:
                tokens = int(payload["max_tokens"])
                if not 32 <= tokens <= 512:
                    raise ValueError("max_tokens must be between 32 and 512")
                self.server.max_tokens = tokens
                local["max_tokens"] = str(tokens)
            remote_keys = {
                "realm_name", "realm_type", "random_bots", "max_added_bots", "player_limit",
                "xp_rate", "reputation_rate", "loot_rate", "money_rate", "honor_rate",
                "profession_skill_rate",
                "auction_house_character_guid", "auction_house_seller", "auction_house_buyer",
                "auction_house_items_per_cycle",
            }
            remote = {key: value for key, value in payload.items() if key in remote_keys}
            if local:
                self.server.store.set_settings(local)
            result = self.server.control("POST", "/v1/settings", remote) if remote else {
                "status": "applied", "world_restarted": False
            }
            self._json(HTTPStatus.OK, result)
        except (ValueError, TypeError, RuntimeError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_settings", "detail": str(error)})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path == "/admin/v1/session":
            token = self._session_token()
            if self._admin_session(csrf=True):
                self.server.store.delete_session(token)
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Set-Cookie", "soulforge_session=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.end_headers()
            return
        if not self._admin_session(csrf=True):
            return
        parts = urlparse(self.path).path.split("/")
        if len(parts) == 8 and parts[1:4] == ["admin", "v1", "souls"] and parts[6] == "memories":
            try:
                deleted = self.server.store.delete_memory(unquote(parts[4]), parts[5], int(parts[7]))
            except ValueError:
                deleted = False
            if deleted:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _login(self, body: bytes) -> None:
        address = self.client_address[0]
        now = time.time()
        with self.server.login_lock:
            recent = [attempt for attempt in self.server.login_attempts.get(address, []) if now - attempt < 300]
            self.server.login_attempts[address] = recent
            if len(recent) >= 5:
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "rate_limited"})
                return
        try:
            supplied = str(json.loads(body).get("password", ""))
        except json.JSONDecodeError:
            supplied = ""
        if not hmac.compare_digest(supplied, self.server.admin_password):
            with self.server.login_lock:
                self.server.login_attempts[address].append(now)
            time.sleep(0.25)
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
            return
        with self.server.login_lock:
            self.server.login_attempts.pop(address, None)
        token, csrf = self.server.store.create_session()
        payload = json.dumps({"authenticated": True, "csrf_token": csrf}, separators=(",", ":")).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Set-Cookie",
            f"soulforge_session={token}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200",
        )
        self._security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _session_token(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("soulforge_session")
        return morsel.value if morsel else ""

    def _admin_session(self, csrf: bool = False) -> str | None:
        session_csrf = self.server.store.session_csrf(self._session_token())
        if not session_csrf:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
            return None
        if csrf and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session_csrf):
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid_csrf"})
            return None
        return session_csrf

    def _read_admin_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too_large"})
            return None
        return self.rfile.read(length)

    def _admin_control(self, method: str, path: str, payload: dict[str, Any] | None = None) -> None:
        try:
            self._json(HTTPStatus.OK, self.server.control(method, path, payload))
        except RuntimeError as error:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "control_unavailable", "detail": str(error)})

    @staticmethod
    def _model_name(value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", value):
            raise ValueError("invalid Ollama model name")
        return value

    def _static(self, request_path: str) -> None:
        root = self.server.dashboard_dir.resolve()
        relative = request_path.lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        if root not in candidate.parents and candidate != root:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "dashboard_not_built"})
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, body: bytes) -> bool:
        timestamp = self.headers.get("X-Soulforge-Timestamp", "")
        nonce = self.headers.get("X-Soulforge-Nonce", "")
        signature = self.headers.get("X-Soulforge-Signature", "")
        try:
            now, sent = int(time.time()), int(timestamp)
        except ValueError:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_signature"})
            return False
        canonical = f"{self.command}\n{self.path}\n{timestamp}\n{nonce}\n".encode() + body
        expected = hmac.new(self.server.secret, canonical, sha256).hexdigest()
        if abs(now - sent) > 30 or not nonce or not hmac.compare_digest(signature, expected):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_signature"})
            return False
        if not self.server.store.remember_nonce(nonce, now):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "replayed_nonce"})
            return False
        return True

    @staticmethod
    def _validate_event(event: dict[str, Any]) -> None:
        for key in ("event_id", "realm_id", "actor", "participants", "channel", "text", "trace"):
            if key not in event:
                raise ValueError(f"missing {key}")
        if not event["participants"] or event["participants"][0].get("kind") != "soul":
            raise ValueError("first participant must be a soul")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(event["realm_id"])):
            raise ValueError("invalid realm identity")
        for character in [event["actor"], *event["participants"]]:
            if not re.fullmatch(r"[1-9][0-9]{0,19}", str(character.get("guid", ""))):
                raise ValueError("invalid character identity")
            if character.get("name") is not None and not 1 <= len(str(character["name"])) <= 24:
                raise ValueError("invalid character name")
        if event["trace"].get("origin") != "human" or event["trace"].get("hop_count") != 0:
            raise ValueError("generated-event loops are forbidden")
        if not 0 < len(event["text"]) <= 4096:
            raise ValueError("invalid text length")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

def build_server(host: str, port: int, database: str = ":memory:", secret: str = "test-secret",
                 admin_password: str = "test-admin-password", start_worker: bool = False) -> SoulforgeServer:
    return SoulforgeServer((host, port), SoulStore(database), secret, admin_password, start_worker)


def main() -> None:
    host = os.environ.get("SOULFORGE_HOST", "127.0.0.1")
    port = int(os.environ.get("SOULFORGE_PORT", "8765"))
    database = os.environ.get("SOULFORGE_DATABASE", "/data/soulforge.sqlite3")
    secret = os.environ.get("SOULFORGE_BRIDGE_SECRET", "")
    admin_password = os.environ.get("SOULFORGE_ADMIN_PASSWORD", "")
    if not secret or not admin_password:
        raise SystemExit("SOULFORGE_BRIDGE_SECRET and SOULFORGE_ADMIN_PASSWORD must be set")
    server = build_server(host, port, database, secret, admin_password, start_worker=True)
    print(f"Soulforge listening on http://{host}:{port} with {server.model}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

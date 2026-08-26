"""Local, durable Soulforge bridge service.

The game thread only exchanges events and replies with this service. Ollama and
SQLite work happen here, outside AzerothCore's world update loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
from queue import Queue
import sqlite3
from threading import Thread
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

MAX_BODY = 64 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SoulStore:
    def __init__(self, path: str) -> None:
        self.path = path
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
            """
        )
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

    def build_prompt(self, event: dict[str, Any]) -> tuple[str, str, str]:
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
            f"Recent memories:\n{memory_text}\n"
            f"{actor['name']} says in {event['channel']}: {event['text']}"
        )
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

    def souls(self) -> list[dict[str, str]]:
        connection = self.connect()
        rows = connection.execute("SELECT * FROM souls ORDER BY name").fetchall()
        self.close(connection)
        return [dict(row) for row in rows]

    def update_soul(self, realm: str, guid: str, fields: dict[str, str]) -> bool:
        connection = self.connect()
        cursor = connection.execute(
            """UPDATE souls SET archetype=?, voice=?, values_text=?, updated_at=?
               WHERE realm_id=? AND bot_guid=?""",
            (fields["archetype"][:200], fields["voice"][:300], fields["values_text"][:300],
             utc_now(), realm, guid),
        )
        connection.commit()
        self.close(connection)
        return bool(cursor.rowcount)


class SoulforgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: SoulStore, secret: str, start_worker: bool = True) -> None:
        super().__init__(address, SoulHandler)
        self.store = store
        self.secret = secret.encode()
        self.model = os.environ.get("SOULFORGE_CHAT_MODEL", "qwen3.5:4b")
        self.ollama_url = os.environ.get("SOULFORGE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.jobs: Queue[dict[str, Any]] = Queue(maxsize=2048)
        if start_worker:
            Thread(target=self._worker, daemon=True, name="soulforge-inference").start()

    def _worker(self) -> None:
        while True:
            event = self.jobs.get()
            try:
                _, _, prompt = self.store.build_prompt(event)
                body = json.dumps({
                    "model": self.model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": 0.75, "num_predict": 180},
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


class SoulHandler(BaseHTTPRequestHandler):
    server: SoulforgeServer
    server_version = "Soulforge/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "stage": "operational", "model": self.server.model})
        elif parsed.path == "/":
            self._dashboard()
        elif parsed.path == "/v1/outbox":
            if not self._authorized(b""):
                return
            query = parse_qs(parsed.query)
            realm = query.get("realm_id", [""])[0]
            limit = min(max(int(query.get("limit", ["20"])[0]), 1), 100)
            self._json(HTTPStatus.OK, {"replies": self.server.store.pending(realm, limit)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

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
        elif self.path.startswith("/dashboard/souls/"):
            fields = {key: values[0] for key, values in parse_qs(body.decode()).items()}
            parts = self.path.split("/")
            realm, guid = (parts[3], parts[4]) if len(parts) == 5 else ("", "")
            if realm and guid and all(key in fields for key in ("archetype", "voice", "values_text")):
                self.server.store.update_soul(realm, guid, fields)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

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
        if event["trace"].get("origin") != "human" or event["trace"].get("hop_count") != 0:
            raise ValueError("generated-event loops are forbidden")
        if not 0 < len(event["text"]) <= 4096:
            raise ValueError("invalid text length")

    def _dashboard(self) -> None:
        rows = []
        for soul in self.server.store.souls():
            realm, guid = soul["realm_id"], soul["bot_guid"]
            rows.append(f"""<section><h2>{_html(soul['name'])}</h2>
<form method=post action='/dashboard/souls/{_html(realm)}/{_html(guid)}'>
<label>Archetype <input name=archetype value='{_html(soul['archetype'])}'></label>
<label>Voice <input name=voice value='{_html(soul['voice'])}'></label>
<label>Values <input name=values_text value='{_html(soul['values_text'])}'></label>
<button>Save soul</button></form></section>""")
        html = ("<!doctype html><meta charset=utf-8><title>Azeroth Soulforge</title>"
                "<style>body{font:16px system-ui;max-width:850px;margin:3rem auto;background:#111827;color:#eee}"
                "section{background:#1f2937;padding:1rem;margin:1rem 0;border-radius:8px}label{display:block;margin:.6rem 0}"
                "input{width:65%;float:right}button{margin-top:.5rem}</style>"
                "<h1>Azeroth Soulforge</h1><p>Souls appear here after you first speak to a bot.</p>" + "".join(rows))
        encoded = html.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def _html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")


def build_server(host: str, port: int, database: str = ":memory:", secret: str = "test-secret",
                 start_worker: bool = False) -> SoulforgeServer:
    return SoulforgeServer((host, port), SoulStore(database), secret, start_worker)


def main() -> None:
    host = os.environ.get("SOULFORGE_HOST", "127.0.0.1")
    port = int(os.environ.get("SOULFORGE_PORT", "8765"))
    database = os.environ.get("SOULFORGE_DATABASE", "/data/soulforge.sqlite3")
    secret = os.environ.get("SOULFORGE_BRIDGE_SECRET", "")
    if not secret:
        raise SystemExit("SOULFORGE_BRIDGE_SECRET must be set")
    server = build_server(host, port, database, secret, start_worker=True)
    print(f"Soulforge listening on http://{host}:{port} with {server.model}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

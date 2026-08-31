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
import io
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
import zipfile

from .providers import ProviderGateway, SecretCipher
from .world import WorldRepository

MAX_BODY = 64 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_chat_reply(text: str, speaker: str) -> str:
    """Return literal in-game chat text, never model narration or a speaker label."""
    reply = str(text).strip()
    reply = re.sub(r"^```(?:text)?\s*", "", reply, flags=re.IGNORECASE)
    reply = re.sub(r"\s*```$", "", reply).strip()
    if not reply:
        return ""
    name = re.escape(str(speaker).strip())
    cleaned: list[str] = []
    narrative = re.compile(
        rf"^(?:{name}|he|she|they)\s+(?:laughs?|smiles?|grins?|sighs?|nods?|shrugs?|"
        r"turns?|looks?|thinks?|says?|replies?|asks?|exclaims?|whispers?)\b",
        re.IGNORECASE,
    )
    for raw_line in reply.splitlines():
        line = raw_line.strip()
        line = re.sub(
            rf"^(?:\*\*)?(?:\[{name}\]|{name})\s*(?::\s*(?:\*\*)?|\*\*\s*:)\s*",
            "", line, flags=re.IGNORECASE,
        ).strip()
        line = re.sub(r"^(?:assistant|character|response)\s*:\s*", "", line,
                      flags=re.IGNORECASE).strip()
        line = re.sub(r"^\*[^*\n]{1,160}\*\s*", "", line).strip()
        line = re.sub(r"^\([^()\n]{1,160}\)\s*", "", line).strip()
        if not line:
            continue
        if narrative.match(line):
            return ""
        quote_pairs = (("\"", "\""), ("“", "”"), ("'", "'"))
        for opening, closing in quote_pairs:
            if len(line) >= 2 and line.startswith(opening) and line.endswith(closing):
                line = line[len(opening):-len(closing)].strip()
                break
        if line:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


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
              recipient_guid TEXT NOT NULL, channel TEXT NOT NULL,
              channel_name TEXT NOT NULL DEFAULT '', text TEXT NOT NULL,
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
        try:
            connection.execute("ALTER TABLE outbox ADD COLUMN channel_name TEXT NOT NULL DEFAULT ''")
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
        world_row = connection.execute(
            "SELECT id,canon_json FROM worlds WHERE realm_id=? AND active=1 LIMIT 1", (realm,)
        ).fetchone()
        world_memory_rows = [] if not world_row else connection.execute(
            """SELECT kind,text FROM world_memories WHERE world_id=? AND redacted=0
               ORDER BY id DESC LIMIT 12""", (world_row["id"],)
        ).fetchall()[::-1]
        connection.commit()
        self.close(connection)
        memory_text = "\n".join(f"{row['role']}: {row['text']}" for row in memories) or "No prior memories yet."
        canon_text = json.dumps(json.loads(world_row["canon_json"]), ensure_ascii=False) if world_row else "No world canon has been forged."
        world_memory_text = "\n".join(
            f"{row['kind']}: {row['text']}" for row in world_memory_rows
        ) or "No shared world history yet."
        actor = event["actor"]
        prompt = (
            f"You are {name}, a persistent World of Warcraft companion—not an AI assistant. "
            f"Archetype: {profile['archetype']}. Voice: {profile['voice']}. "
            f"Values: {profile['values_text']}. Stay in character, never claim consciousness, "
            "never issue gameplay commands, and answer in at most 3 short sentences. "
            f"Output only the exact words {name} would type into the WoW chat box, speaking as {name} "
            "in first person. Never include a speaker label, quotation marks around the reply, narration, "
            "stage directions, emotes, or descriptions of actions, expressions, or tone.\n"
            f"Your character skill document:\n{guidance}\n"
            f"Immutable world canon:\n{canon_text}\n"
            f"Shared world history:\n{world_memory_text}\n"
            f"Recent memories:\n{memory_text}\n"
            f"{actor['name']} says in {event['channel']}: {event['text']}"
        )
        self._materialize_skill(realm, guid)
        return realm, guid, prompt

    def complete(self, event: dict[str, Any], reply: str) -> str | None:
        soul = event["participants"][0]
        realm, guid = event["realm_id"], str(soul["guid"])
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        channel = str(event.get("channel", "whisper"))
        if channel not in {"say", "whisper", "party", "raid", "guild", "channel"}:
            channel = "whisper"
        channel_name = str(event.get("context", {}).get("channel_name", ""))[:128]
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
            """DELETE FROM memories WHERE id IN (
                 SELECT id FROM memories WHERE realm_id=? AND bot_guid=?
                 ORDER BY id DESC LIMIT -1 OFFSET 60
               )""",
            (realm, guid),
        )
        connection.execute(
            """INSERT OR IGNORE INTO outbox
               (reply_id, source_event_id, realm_id, bot_guid, recipient_guid, channel,
                channel_name, text, created_at, expires_at, trace_id)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), event["event_id"], realm, guid, str(event["actor"]["guid"]),
             channel, channel_name, reply[:1024], now, expires, event["trace"]["trace_id"]),
        )
        connection.execute("UPDATE events SET status='complete' WHERE event_id=?", (event["event_id"],))
        raw_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        connection.execute(
            "DELETE FROM events WHERE status='complete' AND created_at < ?", (raw_cutoff,)
        )
        connection.execute(
            """DELETE FROM events WHERE event_id IN (
                 SELECT event_id FROM events WHERE status='complete'
                 ORDER BY created_at DESC LIMIT -1 OFFSET 2000
               )"""
        )
        connection.execute(
            "DELETE FROM outbox WHERE expires_at <= ? OR (acknowledged_at IS NOT NULL AND created_at < ?)",
            (now, raw_cutoff),
        )
        world = connection.execute(
            "SELECT id FROM worlds WHERE realm_id=? AND active=1 LIMIT 1", (realm,)
        ).fetchone()
        compact_world_id = None
        if world:
            actor_name = str(event["actor"].get("name", "A traveler"))[:24]
            soul_name = str(soul.get("name", "A companion"))[:24]
            shared = f"{actor_name} said: {event['text'][:700]} {soul_name} answered: {reply[:700]}"
            connection.execute(
                "INSERT INTO world_memory_candidates(world_id,text,created_at) VALUES(?,?,?)",
                (world["id"], shared, now),
            )
            connection.execute(
                """DELETE FROM world_memory_candidates WHERE id IN (
                     SELECT id FROM world_memory_candidates WHERE world_id=?
                     ORDER BY id DESC LIMIT -1 OFFSET 12
                   )""",
                (world["id"],),
            )
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM world_memory_candidates WHERE world_id=?",
                (world["id"],),
            ).fetchone()["count"]
            if count >= 8:
                compact_world_id = world["id"]
        connection.commit()
        self.close(connection)
        self._materialize_skill(realm, guid)
        return compact_world_id

    def complete_ambient(self, event: dict[str, Any], reply: str) -> None:
        soul = event["participants"][0]
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        channel = str(event.get("channel", "say"))
        channel_name = str(event.get("context", {}).get("channel_name", ""))[:128]
        connection = self.connect()
        connection.execute(
            """INSERT OR IGNORE INTO outbox
               (reply_id,source_event_id,realm_id,bot_guid,recipient_guid,channel,
                channel_name,text,created_at,expires_at,trace_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid4()), event["event_id"], event["realm_id"], str(soul["guid"]),
             str(event["actor"]["guid"]), channel, channel_name, reply[:280], now,
             expires, event["trace"]["trace_id"]),
        )
        connection.execute("UPDATE events SET status='complete' WHERE event_id=?", (event["event_id"],))
        connection.commit()
        self.close(connection)

    def dismiss(self, event_id: str) -> None:
        connection = self.connect()
        connection.execute("UPDATE events SET status='ignored' WHERE event_id=?", (event_id,))
        connection.commit()
        self.close(connection)

    def enqueue_proactive(self, source_id: str, realm: str, bot_guid: str,
                          recipient_guid: str, text: str, channel: str = "whisper",
                          channel_name: str = "") -> None:
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        connection = self.connect()
        connection.execute(
            """INSERT OR IGNORE INTO outbox
               (reply_id,source_event_id,realm_id,bot_guid,recipient_guid,channel,
                channel_name,text,created_at,expires_at,trace_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid4()), source_id, realm, bot_guid, recipient_guid, channel,
             channel_name[:128], text[:1024], now, expires, str(uuid4())),
        )
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
            "channel_name": row["channel_name"],
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

    def prompt_preview(self, realm: str, guid: str) -> dict[str, str] | None:
        connection = self.connect()
        profile = connection.execute(
            "SELECT * FROM souls WHERE realm_id=? AND bot_guid=?", (realm, guid)
        ).fetchone()
        if not profile:
            self.close(connection)
            return None
        memories = connection.execute(
            "SELECT role,text FROM memories WHERE realm_id=? AND bot_guid=? ORDER BY id DESC LIMIT 12",
            (realm, guid),
        ).fetchall()[::-1]
        world = connection.execute(
            "SELECT canon_json FROM worlds WHERE realm_id=? AND active=1 LIMIT 1", (realm,)
        ).fetchone()
        world_memories = [] if not world else connection.execute(
            """SELECT kind,text FROM world_memories WHERE world_id=(
                 SELECT id FROM worlds WHERE realm_id=? AND active=1 LIMIT 1)
               AND redacted=0 ORDER BY id DESC LIMIT 12""", (realm,)
        ).fetchall()[::-1]
        self.close(connection)
        guidance = profile["skill_document"] or self._default_guidance(profile["name"])
        memory_text = "\n".join(f"{row['role']}: {row['text']}" for row in memories) or "No prior memories yet."
        shared_text = "\n".join(f"{row['kind']}: {row['text']}" for row in world_memories) or "No shared world history yet."
        canon_text = world["canon_json"] if world else "No world canon has been forged."
        prompt = (
            f"You are {profile['name']}, a persistent World of Warcraft companion—not an AI assistant. "
            f"Archetype: {profile['archetype']}. Voice: {profile['voice']}. "
            f"Values: {profile['values_text']}. Stay in character, never claim consciousness, "
            "never issue gameplay commands, and answer in at most 3 short sentences. "
            f"Output only the exact words {profile['name']} would type into the WoW chat box, speaking as "
            f"{profile['name']} in first person. Never include a speaker label, quotation marks around the "
            "reply, narration, stage directions, emotes, or descriptions of actions, expressions, or tone.\n"
            f"Your character skill document:\n{guidance}\n"
            f"Immutable world canon:\n{canon_text}\n"
            f"Shared world history:\n{shared_text}\n"
            f"Recent memories:\n{memory_text}\n"
            "[Player name] says in [chat channel]: [new message]"
        )
        return {"name": profile["name"], "prompt": prompt}

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
        self.addon_dir = Path(os.environ.get("SOULFORGE_ADDON_DIR", "/app/addons/SoulforgeCommander"))
        master_key = os.environ.get("SOULFORGE_SECRETS_KEY") or (
            f"development-only:{admin_password}:{secret}"
        )
        self.provider_gateway = ProviderGateway(SecretCipher(master_key))
        self.ambient_model = os.environ.get("SOULFORGE_AMBIENT_MODEL", "qwen3:1.7b")
        self.worlds = WorldRepository(store, self.ollama_url, self.model, self.ambient_model)
        bootstrap_key = os.environ.get("SOULFORGE_OPENAI_API_KEY", "").strip()
        if bootstrap_key and not self.worlds.provider("openai-primary"):
            base_url = os.environ.get("SOULFORGE_OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            model = os.environ.get("SOULFORGE_OPENAI_MODEL", "gpt-5.6-luna").strip()
            self.worlds.save_provider({
                "id": "openai-primary", "name": "OpenAI", "kind": "openai",
                "base_url": base_url, "enabled": True,
            }, self.provider_gateway.cipher.encrypt(bootstrap_key))
            self.worlds.save_routes({
                "director": {"provider_id": "openai-primary", "model": model,
                             "temperature": 0.7, "max_tokens": 4096},
                "dialogue": {"provider_id": "openai-primary", "model": model,
                             "temperature": 0.75, "max_tokens": 180},
            })
        self.ai_enabled = self.worlds.ai_state()["enabled"]
        self.login_attempts: dict[str, list[float]] = {}
        self.login_lock = Lock()
        self.jobs: Queue[dict[str, Any]] = Queue(maxsize=2048)
        self.humans_online = 0
        self._last_presence_tick = time.monotonic()
        self._empty_since: float | None = None
        self._auto_stop_fired = False
        self._ambient_lock = Lock()
        self._last_ambient_reply = 0.0
        if start_worker:
            Thread(target=self._worker, daemon=True, name="soulforge-inference").start()
            Thread(target=self._presence_monitor, daemon=True, name="soulforge-presence").start()

    def _worker(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                if job.get("kind") == "world_forge":
                    self._forge_world(job)
                elif job.get("kind") == "director_event":
                    self._director_event(job)
                elif job.get("kind") == "memory_compaction":
                    self._compact_world_memory(job["world_id"])
                else:
                    self._dialogue(job["event"])
            except Exception as error:  # Stay silent in game when inference is unavailable.
                if job.get("kind") == "world_forge":
                    self.worlds.update_job(job["job_id"], "failed", "The forge cooled", error=str(error))
                elif job.get("kind") == "director_event":
                    self.worlds.release_plan(job["plan"]["id"])
                print(f"inference failed for {job.get('job_id') or job.get('event', {}).get('event_id')}: {error}", flush=True)
            finally:
                self.jobs.task_done()

    def _route_generation(self, purpose: str, prompt: str) -> str:
        if not self.ai_enabled:
            raise RuntimeError("AI is disabled by the kill switch")
        route = self.worlds.routes()[purpose]
        profile = self.worlds.provider(route["provider_id"], include_secret=True)
        if not profile or not profile["enabled"]:
            raise RuntimeError(f"the {purpose} provider is unavailable")
        if not self.worlds.paid_budget_available(profile):
            fallback = self.worlds.provider("ollama-local", include_secret=True)
            if not fallback or not fallback["enabled"]:
                raise RuntimeError("the paid AI cap was reached and local fallback is unavailable")
            profile = fallback
            route = {**route, "provider_id": "ollama-local"}
        started = time.monotonic()
        try:
            result = self.provider_gateway.generate(
                profile, route["model"], prompt, float(route["temperature"]), int(route["max_tokens"])
            )
            latency = int((time.monotonic() - started) * 1000)
            if not self.ai_enabled:
                raise RuntimeError("AI was disabled while the response was in flight")
            self.worlds.record_usage(purpose, profile, route["model"], result.usage, latency, True)
            self._log_ai_call(purpose, profile, route["model"], result.usage, latency, "ok")
            return result.text
        except Exception as error:
            latency = int((time.monotonic() - started) * 1000)
            self.worlds.record_usage(purpose, profile, route["model"], {}, latency, False,
                                     type(error).__name__)
            self._log_ai_call(
                purpose, profile, route["model"], {}, latency, "error", type(error).__name__
            )
            raise

    @staticmethod
    def _log_ai_call(purpose: str, profile: dict[str, Any], model: str,
                     usage: dict[str, int], latency_ms: int, status: str,
                     error_code: str = "") -> None:
        entry: dict[str, Any] = {
            "event": "ai_call",
            "route": purpose,
            "provider": profile["id"],
            "provider_kind": profile["kind"],
            "model": model,
            "status": status,
            "latency_ms": latency_ms,
            "input_tokens": usage.get("input_tokens", 0),
            "cached_input_tokens": usage.get("cached_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "reasoning_tokens": usage.get("reasoning_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if error_code:
            entry["error_code"] = error_code
        print(f"ai_call {json.dumps(entry, separators=(',', ':'), sort_keys=True)}", flush=True)

    def _dialogue(self, event: dict[str, Any]) -> None:
        if not self.ai_enabled:
            return
        if event.get("context", {}).get("dialogue_tier") == "ambient":
            self._ambient_dialogue(event)
            return
        prompt_data = self.store.build_prompt(event)
        if prompt_data is None:
            return
        _, _, prompt = prompt_data
        reply = normalize_chat_reply(
            self._route_generation("dialogue", prompt), event["participants"][0]["name"]
        )
        if reply and self.ai_enabled:
            world_id = self.store.complete(event, reply)
            if event.get("channel") in {"party", "raid", "guild"}:
                self._banter_followup(event, reply)
            if world_id:
                self.jobs.put_nowait({"kind": "memory_compaction", "world_id": world_id})

    def _ambient_dialogue(self, event: dict[str, Any]) -> None:
        state = self.worlds.ai_state()
        if not state["ambient_enabled"] or event.get("channel") not in {"say", "channel"}:
            self.store.dismiss(event["event_id"])
            return
        now = time.monotonic()
        with self._ambient_lock:
            if now - self._last_ambient_reply < state["ambient_cooldown_seconds"]:
                self.store.dismiss(event["event_id"])
                return
            if secrets.randbelow(100) >= state["ambient_reply_percent"]:
                self.store.dismiss(event["event_id"])
                return
            self._last_ambient_reply = now
        bot = event["participants"][0]
        context = event.get("context", {})
        zone = str(context.get("zone_name") or "Azeroth")[:80]
        channel_name = str(context.get("channel_name") or event["channel"])[:128]
        world = self.worlds.active_world() or {}
        canon = world.get("canon") or {}
        flavor = str(canon.get("regional_flavor") or canon.get("tone") or canon.get("premise") or "classic Azeroth")[:240]
        prompt = (
            f"You are {bot['name']}, an ordinary player on a busy 2004-2009-era World of Warcraft realm. "
            f"You are in {zone}, reading {channel_name}. World flavor: {flavor}. "
            "Make the realm feel inhabited: react like a real player of that era with zone-aware quest help, "
            "LFG/trade chatter, arguments, local jokes, rumors, typos, playful item-or-spell-link wordplay, or "
            "occasional nonsense. Barrens chat may be especially chaotic. Do not force a famous meme every time. "
            f"{event['actor']['name']} says: {event['text'][:300]}\n"
            f"Output only the exact words {bot['name']} would type into the WoW chat box, speaking as "
            f"{bot['name']} in first person. Reply naturally in one or two short chat lines, usually under "
            "45 words. Do not add a speaker label, quotation marks around the reply, narration, stage "
            "directions, emotes, or descriptions of actions, expressions, or tone. Never mention AI, prompts, "
            "or servers, and never issue a bot-control command. Return [silence] if replying would feel forced."
        )
        reply = normalize_chat_reply(self._route_generation("ambient", prompt), bot["name"])
        if not reply or reply.lower() == "[silence]":
            self.store.dismiss(event["event_id"])
            return
        self.store.complete_ambient(event, reply)

    def _banter_followup(self, event: dict[str, Any], first_reply: str) -> None:
        companions = self.worlds.companions()
        if len(companions) < 2:
            return
        first_guid = str(event["participants"][0]["guid"])
        first_index = next(
            (index for index, item in enumerate(companions) if str(item["bot_guid"]) == first_guid),
            0,
        )
        responder = companions[(first_index + 1) % len(companions)]
        first_name = str(event["participants"][0]["name"])
        synthetic = {
            "realm_id": event["realm_id"],
            "participants": [{"guid": str(responder["bot_guid"]), "name": responder["name"]}],
            "actor": {"guid": first_guid, "kind": "soul", "name": first_name},
            "channel": event.get("channel", "party"),
            "context": event.get("context", {}),
            "text": first_reply,
        }
        prompt_data = self.store.build_prompt(synthetic)
        if prompt_data is None:
            return
        prompt = prompt_data[2] + (
            "\nReply as a witty in-character party interjection to the other companion. "
            "Keep it to one or two short sentences and add personality rather than exposition. "
            "Output only the literal first-person words this companion types into party chat—no name label, "
            "narration, stage directions, emotes, action descriptions, or gameplay commands."
        )
        reply = normalize_chat_reply(
            self._route_generation("dialogue", prompt), str(responder["name"])
        )
        if reply and self.ai_enabled:
            self.store.enqueue_proactive(
                f"{event['event_id']}:banter", event["realm_id"], str(responder["bot_guid"]),
                str(event["actor"]["guid"]), reply, str(event.get("channel", "party")),
                str(event.get("context", {}).get("channel_name", "")),
            )

    def _compact_world_memory(self, world_id: str) -> None:
        candidates = self.worlds.memory_candidates(world_id)
        if not candidates:
            return
        world = self.worlds.active_world()
        if not world or world["id"] != world_id:
            return
        prompt = (
            "Distill these recent roleplay exchanges into durable world memory. Keep only facts that "
            "could matter later: promises, relationships, discoveries, decisions, unresolved fears, "
            "or changes in belief. Discard greetings, jokes, repetition, commands, and casual chatter. "
            "Never alter immutable canon. Return strict JSON as {\"memories\":[{\"kind\":\"relationship\","
            "\"text\":\"one self-contained fact\",\"importance\":3}]}; return an empty array when nothing "
            "deserves long-term memory. Use at most six concise memories.\n"
            f"Canon: {json.dumps(world['canon'], ensure_ascii=False)}\n"
            f"Existing durable memory: {json.dumps(self.worlds.memories(20), ensure_ascii=False)}\n"
            f"Temporary exchanges: {json.dumps(candidates, ensure_ascii=False)}"
        )
        result = self._json_object(self._route_generation("director", prompt), require_premise=False)
        memories = result.get("memories", [])
        if not isinstance(memories, list):
            raise ValueError("memory compactor returned invalid memories")
        self.worlds.finish_memory_compaction(
            world_id, [int(item["id"]) for item in candidates],
            [item for item in memories if isinstance(item, dict)],
        )

    def _forge_world(self, job: dict[str, Any]) -> None:
        job_id, request = job["job_id"], job["request"]
        self.worlds.update_job(job_id, "running", "Reading the w0rld seed")
        bots = self.control("GET", "/v1/bots").get("bots", [])
        prompt = (
            "Create an immutable narrative canon for a private World of Warcraft 3.3.5 realm opening "
            "in a fresh Vanilla phase. AI controls only identity, relationships, dialogue, rumors, and "
            "story beats; never invent gameplay rewards, quests, or commands. Return strict JSON with "
            "keys premise, tone, social_rules, regional_flavor, factions, dialogue_guidance, taboos, "
            "themes, starting_tensions (array), initial_plans (array of title, hint, after_played_minutes), "
            "and companion_profiles (array of bot_guid, archetype, voice, values). Base companion profiles "
            "only on these available character facts:\n"
            f"{json.dumps(bots[:200], ensure_ascii=False)}\n"
            f"Faction: {request['faction']}; player role: {request['player_role']}.\n"
            f"W0RLD PROMPT:\n{request['seed_prompt']}"
        )
        self.worlds.update_job(job_id, "running", "Shaping canon and companions")
        text = self._route_generation("director", prompt)
        canon = self._json_object(text)
        profiles = canon.pop("companion_profiles", [])
        self.worlds.update_job(job_id, "running", "Binding the dungeon group")
        world = self.worlds.activate_world(request, canon, bots, profiles)
        self.worlds.update_job(job_id, "complete", "Your world is ready", result={"world": world})

    def _director_event(self, job: dict[str, Any]) -> None:
        world, plan = self.worlds.active_world(), job["plan"]
        if not world:
            return
        memories = self.worlds.memories(30)
        prompt = (
            "Write one short in-world whisper, no more than three sentences, through which a trusted "
            "companion naturally reveals this emerging story beat. Never mention AI, prompts, servers, "
            "or future plans. Do not issue gameplay commands or promise rewards.\n"
            f"Canon: {json.dumps(world['canon'], ensure_ascii=False)}\n"
            f"Recent world memories: {json.dumps(memories, ensure_ascii=False)}\n"
            f"Story beat: {json.dumps(plan, ensure_ascii=False)}"
        )
        text = self._route_generation("director", prompt)
        if text and self.ai_enabled:
            self.store.enqueue_proactive(plan["id"], world["realm_id"], job["bot_guid"],
                                         job["recipient_guid"], text)
            self.worlds.finish_plan(plan["id"], f"{plan['title']}: {text}")

    @staticmethod
    def _json_object(text: str, require_premise: bool = True) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("director did not return a JSON canon")
        value = json.loads(candidate[start:end + 1])
        if not isinstance(value, dict) or (require_premise and not str(value.get("premise", "")).strip()):
            raise ValueError("director returned an incomplete canon")
        return value

    def _presence_monitor(self) -> None:
        while True:
            try:
                now = time.monotonic()
                payload = self.control("GET", "/v1/presence")
                count = max(int(payload.get("humans_online", 0)), 0)
                elapsed = int(now - self._last_presence_tick) if count > 0 and self.humans_online > 0 else 0
                self.worlds.record_presence(count, elapsed)
                if count > 0:
                    self._empty_since = None
                    self._auto_stop_fired = False
                elif self.humans_online > 0:
                    self._empty_since = now
                self.humans_online = count
                self._last_presence_tick = now
                if count > 0 and self.ai_enabled:
                    plan = self.worlds.claim_due_plan()
                    companions = self.worlds.companions()
                    players = payload.get("players") or []
                    if plan and companions and players:
                        self.jobs.put_nowait({
                            "kind": "director_event", "plan": plan,
                            "bot_guid": str(companions[0]["bot_guid"]),
                            "recipient_guid": str(players[0]["guid"]),
                        })
                    elif plan:
                        self.worlds.release_plan(plan["id"])
                grace = self.worlds.ai_state()["auto_stop_minutes"]
                if (grace and self._empty_since is not None and not self._auto_stop_fired
                        and now - self._empty_since >= grace * 60):
                    self.control("POST", "/v1/actions/stop", {})
                    self._auto_stop_fired = True
            except Exception as error:
                print(f"presence monitor unavailable: {error}", flush=True)
            time.sleep(30)

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
        elif parsed.path == "/v1/companion-roster":
            if not self._authorized(b""):
                return
            realm = parse_qs(parsed.query).get("realm_id", [""])[0]
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", realm):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_realm"})
                return
            world = self.server.worlds.active_world()
            roster = self.server.worlds.companions() if world and world["realm_id"] == realm else []
            companions = [
                {"name": item["name"], "role": item["role"]}
                for item in roster
                if item.get("name") and item.get("role")
            ]
            self._json(HTTPStatus.OK, {"companions": companions})
        elif parsed.path == "/admin/v1/session":
            csrf = self._admin_session()
            if csrf:
                self._json(HTTPStatus.OK, {"authenticated": True, "csrf_token": csrf})
        elif parsed.path == "/admin/v1/souls":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"souls": self.server.store.souls()})
        elif parsed.path == "/admin/v1/home":
            if not self._admin_session():
                return
            try:
                control = self.server.control("GET", "/v1/status")
            except RuntimeError as error:
                control = {"services": [], "control_error": str(error)}
            self._json(HTTPStatus.OK, {
                "world": self.server.worlds.active_world(),
                "companions": self.server.worlds.companions(),
                "rumors": self.server.worlds.rumors()[:3],
                "ai": self.server.worlds.ai_state(),
                "routes": self.server.worlds.routes(),
                "usage": self.server.worlds.usage_summary(),
                **control,
            })
        elif parsed.path == "/admin/v1/world":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"world": self.server.worlds.active_world()})
        elif parsed.path == "/admin/v1/world/chronicle":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"memories": self.server.worlds.memories()})
        elif parsed.path == "/admin/v1/world/rumors":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"rumors": self.server.worlds.rumors()})
        elif parsed.path == "/admin/v1/world/companions":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"companions": self.server.worlds.companions()})
        elif parsed.path.startswith("/admin/v1/world/companions/") and parsed.path.endswith("/prompt"):
            if not self._admin_session():
                return
            parts = parsed.path.split("/")
            world = self.server.worlds.active_world()
            preview = None if not world or len(parts) != 7 else self.server.store.prompt_preview(
                world["realm_id"], parts[5]
            )
            if preview:
                self._json(HTTPStatus.OK, preview)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        elif parsed.path.startswith("/admin/v1/jobs/"):
            if not self._admin_session():
                return
            job = self.server.worlds.job(parsed.path.rsplit("/", 1)[-1])
            if job:
                self._json(HTTPStatus.OK, job)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        elif parsed.path == "/admin/v1/ai/providers":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"providers": self.server.worlds.providers()})
        elif parsed.path == "/admin/v1/ai/routing":
            if self._admin_session():
                self._json(HTTPStatus.OK, {"routes": self.server.worlds.routes()})
        elif parsed.path == "/admin/v1/ai/state":
            if self._admin_session():
                self._json(HTTPStatus.OK, self.server.worlds.ai_state())
        elif parsed.path == "/admin/v1/ai/usage":
            if self._admin_session():
                self._json(HTTPStatus.OK, self.server.worlds.usage_summary())
        elif parsed.path == "/admin/v1/addon/download":
            if self._admin_session():
                self._addon_download()
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
                self.server.jobs.put_nowait({"kind": "dialogue", "event": event})
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
        elif self.path == "/admin/v1/world/forge":
            if not self._admin_session(csrf=True):
                return
            try:
                payload = json.loads(body)
                job = self.server.worlds.create_forge_job(
                    str(payload.get("seed_prompt", "")), str(payload.get("faction", "")),
                    str(payload.get("player_role", "")),
                )
                self.server.jobs.put_nowait({"kind": "world_forge", "job_id": job["job_id"],
                                             "request": {key: job[key] for key in ("seed_prompt", "faction", "player_role")}})
                self._json(HTTPStatus.ACCEPTED, job)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "forge_failed", "detail": str(error)})
        elif self.path == "/admin/v1/world/companions":
            if not self._admin_session(csrf=True):
                return
            try:
                payload = json.loads(body)
                guid = str(payload.get("bot_guid", ""))
                bots = self.server.control("GET", "/v1/bots").get("bots", [])
                bot = next((item for item in bots if str(item.get("guid")) == guid), None)
                if not bot:
                    raise ValueError("bot is not available in this realm")
                companion = self.server.worlds.promote_companion(
                    guid, str(bot["name"]), str(payload.get("role", "dps"))
                )
                self._json(HTTPStatus.CREATED, companion)
            except (ValueError, TypeError, RuntimeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "promotion_failed", "detail": str(error)})
        elif self.path in {"/admin/v1/world/actions/enter", "/admin/v1/world/actions/leave"}:
            if not self._admin_session(csrf=True):
                return
            action = "start" if self.path.endswith("/enter") else "stop"
            self._admin_control("POST", f"/v1/actions/{action}", {})
        elif self.path == "/admin/v1/ai/providers":
            if not self._admin_session(csrf=True):
                return
            try:
                payload = json.loads(body)
                secret = str(payload.pop("api_key", ""))
                encrypted = self.server.provider_gateway.cipher.encrypt(secret) if secret else ""
                self._json(HTTPStatus.CREATED, self.server.worlds.save_provider(payload, encrypted))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_provider", "detail": str(error)})
        elif self.path.startswith("/admin/v1/ai/providers/") and self.path.endswith("/test"):
            if not self._admin_session(csrf=True):
                return
            provider_id = self.path.split("/")[-2]
            profile = self.server.worlds.provider(provider_id, include_secret=True)
            try:
                payload = json.loads(body or b"{}")
                if not profile:
                    raise ValueError("unknown provider")
                model = str(payload.get("model") or self.server.worlds.routes()["dialogue"]["model"])
                result = self.server.provider_gateway.generate(profile, model, "Reply with exactly: connected", 0, 32, timeout=30)
                self._json(HTTPStatus.OK, {"status": "connected", "reply": result.text[:120]})
            except Exception as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "provider_test_failed", "detail": str(error)})
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
        if parsed_path in {"/admin/v1/ai/state", "/admin/v1/ai/routing"}:
            if not self._admin_session(csrf=True):
                return
            body = self._read_admin_body()
            if body is None:
                return
            try:
                payload = json.loads(body)
                if parsed_path.endswith("/state"):
                    result = self.server.worlds.save_ai_state(payload)
                    self.server.ai_enabled = result["enabled"]
                    self.server.souls_enabled = result["enabled"]
                else:
                    result = {"routes": self.server.worlds.save_routes(payload)}
                self._json(HTTPStatus.OK, result)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_ai_configuration", "detail": str(error)})
            return
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
                routes = self.server.worlds.routes()
                routes["dialogue"]["model"] = model
                self.server.worlds.save_routes({"dialogue": routes["dialogue"]})
            if "souls_enabled" in payload:
                if not isinstance(payload["souls_enabled"], bool):
                    raise ValueError("souls_enabled must be boolean")
                self.server.souls_enabled = payload["souls_enabled"]
                self.server.ai_enabled = payload["souls_enabled"]
                local["souls_enabled"] = "true" if payload["souls_enabled"] else "false"
                local["ai_enabled"] = local["souls_enabled"]
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
                "realm_name", "realm_type", "random_bots", "max_added_bots", "player_limit", "new_character_level",
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
        if len(parts) == 6 and parts[1:5] == ["admin", "v1", "ai", "providers"]:
            provider_id = parts[5]
            if provider_id == "ollama-local":
                self._json(HTTPStatus.BAD_REQUEST, {"error": "local_provider_required"})
                return
            connection = self.server.store.connect()
            try:
                cursor = connection.execute("DELETE FROM provider_profiles WHERE id=?", (provider_id,))
                connection.commit()
            except sqlite3.IntegrityError:
                self._json(HTTPStatus.CONFLICT, {"error": "provider_in_use"})
                self.server.store.close(connection)
                return
            self.server.store.close(connection)
            if cursor.rowcount:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
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

    def _addon_download(self) -> None:
        root = self.server.addon_dir
        if not root.is_dir():
            self._json(HTTPStatus.NOT_FOUND, {"error": "addon_not_packaged"})
            return
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.iterdir()):
                if path.is_file():
                    archive.writestr(f"SoulforgeCommander/{path.name}", path.read_bytes())
        body = buffer.getvalue()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="SoulforgeCommander.zip"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        for key in ("event_id", "realm_id", "event_type", "actor", "participants", "channel", "text", "trace"):
            if key not in event:
                raise ValueError(f"missing {key}")
        if not event["participants"]:
            raise ValueError("one chat participant is required")
        participant_kind = event["participants"][0].get("kind")
        tier = event.get("context", {}).get("dialogue_tier") if isinstance(event.get("context", {}), dict) else None
        if participant_kind != "soul" and not (participant_kind == "playerbot" and tier == "ambient"):
            raise ValueError("first participant must be a soul or ambient playerbot")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(event["realm_id"])):
            raise ValueError("invalid realm identity")
        for character in [event["actor"], *event["participants"]]:
            if not re.fullmatch(r"[1-9][0-9]{0,19}", str(character.get("guid", ""))):
                raise ValueError("invalid character identity")
            if character.get("name") is not None and not 1 <= len(str(character["name"])) <= 24:
                raise ValueError("invalid character name")
        if event["trace"].get("origin") != "human" or event["trace"].get("hop_count") != 0:
            raise ValueError("generated-event loops are forbidden")
        channel = str(event["channel"])
        if channel not in {"say", "whisper", "party", "raid", "guild", "channel"}:
            raise ValueError("invalid chat channel")
        if event["event_type"] != f"chat.{channel}":
            raise ValueError("event type does not match chat channel")
        context = event.get("context", {})
        if not isinstance(context, dict):
            raise ValueError("invalid event context")
        channel_name = str(context.get("channel_name", ""))
        if channel == "channel" and not 1 <= len(channel_name) <= 128:
            raise ValueError("public channel name is required")
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

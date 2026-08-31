"""Persistent prompted-world, companion, provider, and usage state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any
from uuid import uuid4


REALM_ID = "azeroth-soulforge"
PROVIDER_KINDS = {"ollama", "openai", "anthropic", "gemini", "openai_compatible"}
FACTION_RACES = {
    "alliance": {1, 3, 4, 7, 11},
    "horde": {2, 5, 6, 8, 10},
}
TANK_CLASSES = {1, 2, 6, 11}
HEALER_CLASSES = {2, 5, 7, 11}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class WorldRepository:
    def __init__(self, store: Any, ollama_url: str, chat_model: str,
                 ambient_model: str = "qwen3:1.7b") -> None:
        self.store = store
        self._initialize(ollama_url, chat_model, ambient_model)

    def _initialize(self, ollama_url: str, chat_model: str, ambient_model: str) -> None:
        connection = self.store.connect()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS worlds (
              id TEXT PRIMARY KEY, realm_id TEXT NOT NULL, status TEXT NOT NULL,
              seed_prompt TEXT NOT NULL, canon_json TEXT NOT NULL DEFAULT '{}',
              faction TEXT NOT NULL, player_role TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'vanilla_fresh',
              played_seconds INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL, activated_at TEXT, updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_world_idx ON worlds(active) WHERE active=1;
            CREATE TABLE IF NOT EXISTS world_memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT, world_id TEXT NOT NULL,
              kind TEXT NOT NULL, text TEXT NOT NULL, source_event_id TEXT,
              importance INTEGER NOT NULL DEFAULT 3, supersedes_id INTEGER,
              redacted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
              FOREIGN KEY(world_id) REFERENCES worlds(id)
            );
            CREATE TABLE IF NOT EXISTS world_memory_candidates (
              id INTEGER PRIMARY KEY AUTOINCREMENT, world_id TEXT NOT NULL,
              text TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(world_id) REFERENCES worlds(id)
            );
            CREATE INDEX IF NOT EXISTS world_memory_candidates_idx
              ON world_memory_candidates(world_id,id);
            CREATE TABLE IF NOT EXISTS planned_events (
              id TEXT PRIMARY KEY, world_id TEXT NOT NULL, title TEXT NOT NULL,
              hint TEXT NOT NULL, plan_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
              due_played_seconds INTEGER, created_at TEXT NOT NULL, occurred_at TEXT,
              FOREIGN KEY(world_id) REFERENCES worlds(id)
            );
            CREATE TABLE IF NOT EXISTS world_sessions (
              id TEXT PRIMARY KEY, world_id TEXT NOT NULL, started_at TEXT NOT NULL,
              ended_at TEXT, played_seconds INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(world_id) REFERENCES worlds(id)
            );
            CREATE TABLE IF NOT EXISTS companion_bindings (
              world_id TEXT NOT NULL, realm_id TEXT NOT NULL, bot_guid TEXT NOT NULL,
              role TEXT NOT NULL, party_position INTEGER NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(world_id, bot_guid),
              FOREIGN KEY(world_id) REFERENCES worlds(id)
            );
            CREATE TABLE IF NOT EXISTS generation_jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
              progress TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT,
              error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_profiles (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
              base_url TEXT NOT NULL, secret_ciphertext TEXT NOT NULL DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1, has_secret INTEGER NOT NULL DEFAULT 0,
              input_cost_micros INTEGER NOT NULL DEFAULT 0,
              cached_input_cost_micros INTEGER NOT NULL DEFAULT 0,
              output_cost_micros INTEGER NOT NULL DEFAULT 0,
              verified_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_routes (
              purpose TEXT PRIMARY KEY, provider_id TEXT NOT NULL, model TEXT NOT NULL,
              temperature REAL NOT NULL, max_tokens INTEGER NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(provider_id) REFERENCES provider_profiles(id)
            );
            CREATE TABLE IF NOT EXISTS ai_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT, purpose TEXT NOT NULL,
              provider_id TEXT NOT NULL, model TEXT NOT NULL,
              input_tokens INTEGER NOT NULL DEFAULT 0,
              cached_input_tokens INTEGER NOT NULL DEFAULT 0,
              reasoning_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0,
              total_tokens INTEGER NOT NULL DEFAULT 0,
              estimated_cost_micros INTEGER NOT NULL DEFAULT 0,
              latency_ms INTEGER NOT NULL DEFAULT 0, success INTEGER NOT NULL,
              error_code TEXT, created_at TEXT NOT NULL
            );
            """
        )
        now = utc_now()
        connection.execute(
            """INSERT OR IGNORE INTO provider_profiles
               (id,name,kind,base_url,created_at,updated_at)
               VALUES('ollama-local','Local Ollama','ollama',?,?,?)""",
            (ollama_url, now, now),
        )
        for purpose, model, temperature, tokens in (
            ("director", chat_model, 0.7, 1200),
            ("dialogue", chat_model, 0.75, 180),
            ("ambient", ambient_model, 0.9, 96),
        ):
            connection.execute(
                """INSERT OR IGNORE INTO ai_routes
                   (purpose,provider_id,model,temperature,max_tokens,updated_at)
                   VALUES(?,'ollama-local',?,?,?,?)""",
                (purpose, model, temperature, tokens, now),
            )
        connection.commit()
        self.store.close(connection)

    def active_world(self) -> dict[str, Any] | None:
        connection = self.store.connect()
        row = connection.execute("SELECT * FROM worlds WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        self.store.close(connection)
        return self._world(row) if row else None

    def memory_candidates(self, world_id: str) -> list[dict[str, Any]]:
        connection = self.store.connect()
        rows = connection.execute(
            "SELECT id,text,created_at FROM world_memory_candidates WHERE world_id=? ORDER BY id",
            (world_id,),
        ).fetchall()
        self.store.close(connection)
        return [dict(row) for row in rows]

    def finish_memory_compaction(self, world_id: str, candidate_ids: list[int],
                                 memories: list[dict[str, Any]]) -> None:
        if not candidate_ids:
            return
        now = utc_now()
        connection = self.store.connect()
        for memory in memories[:6]:
            text = str(memory.get("text", "")).strip()
            if not text:
                continue
            kind = re.sub(r"[^a-z_]", "", str(memory.get("kind", "relationship")).lower())[:32]
            importance = max(1, min(int(memory.get("importance", 3)), 5))
            connection.execute(
                """INSERT INTO world_memories(world_id,kind,text,importance,created_at)
                   VALUES(?,?,?,?,?)""",
                (world_id, kind or "relationship", text[:2000], importance, now),
            )
        placeholders = ",".join("?" for _ in candidate_ids)
        connection.execute(
            f"DELETE FROM world_memory_candidates WHERE world_id=? AND id IN ({placeholders})",
            (world_id, *candidate_ids),
        )
        removable = connection.execute(
            """SELECT id FROM world_memories WHERE world_id=?
               AND kind NOT IN ('founding','narrative_event')
               ORDER BY importance DESC,id DESC""",
            (world_id,),
        ).fetchall()
        for row in removable[400:]:
            connection.execute("DELETE FROM world_memories WHERE id=?", (row["id"],))
        connection.commit()
        self.store.close(connection)

    @staticmethod
    def _world(row: Any) -> dict[str, Any]:
        value = dict(row)
        value["canon"] = json.loads(value.pop("canon_json") or "{}")
        value["active"] = bool(value["active"])
        return value

    def create_forge_job(self, seed_prompt: str, faction: str, player_role: str) -> dict[str, Any]:
        seed_prompt = seed_prompt.strip()
        if not 20 <= len(seed_prompt) <= 12_000:
            raise ValueError("w0rld prompt must be between 20 and 12000 characters")
        if faction not in FACTION_RACES:
            raise ValueError("faction must be alliance or horde")
        if player_role not in {"tank", "healer", "dps"}:
            raise ValueError("player_role must be tank, healer, or dps")
        if self.active_world():
            raise ValueError("archive the active world before forging another")
        job_id = str(uuid4())
        request = {"seed_prompt": seed_prompt, "faction": faction, "player_role": player_role}
        now = utc_now()
        connection = self.store.connect()
        connection.execute(
            """INSERT INTO generation_jobs(id,kind,status,progress,request_json,created_at,updated_at)
               VALUES(?,'world_forge','queued','Waiting for the forge',?,?,?)""",
            (job_id, json.dumps(request), now, now),
        )
        connection.commit()
        self.store.close(connection)
        return {"job_id": job_id, "status": "queued", **request}

    def update_job(self, job_id: str, status: str, progress: str, *,
                   result: dict[str, Any] | None = None, error: str | None = None) -> None:
        connection = self.store.connect()
        connection.execute(
            """UPDATE generation_jobs SET status=?,progress=?,result_json=?,error=?,updated_at=? WHERE id=?""",
            (status, progress, json.dumps(result) if result is not None else None,
             (error or "")[:1000] or None, utc_now(), job_id),
        )
        connection.commit()
        self.store.close(connection)

    def job(self, job_id: str) -> dict[str, Any] | None:
        connection = self.store.connect()
        row = connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        self.store.close(connection)
        if not row:
            return None
        value = dict(row)
        value["request"] = json.loads(value.pop("request_json"))
        value["result"] = json.loads(value.pop("result_json")) if value.get("result_json") else None
        return value

    def activate_world(self, request: dict[str, Any], canon: dict[str, Any],
                       candidates: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any]:
        if self.active_world():
            raise ValueError("an active world already exists")
        selected = select_dungeon_group(candidates, request["faction"], request["player_role"])
        profile_by_guid = {str(item.get("bot_guid")): item for item in profiles}
        world_id, now = str(uuid4()), utc_now()
        connection = self.store.connect()
        connection.execute(
            """INSERT INTO worlds
               (id,realm_id,status,seed_prompt,canon_json,faction,player_role,created_at,activated_at,updated_at)
               VALUES(?,?,'ready',?,?,?,?,?,?,?)""",
            (world_id, REALM_ID, request["seed_prompt"], json.dumps(canon), request["faction"],
             request["player_role"], now, now, now),
        )
        roles = companion_roles(request["player_role"])
        for position, (bot, role) in enumerate(zip(selected, roles), 1):
            guid = str(bot["guid"])
            connection.execute(
                """INSERT INTO companion_bindings
                   (world_id,realm_id,bot_guid,role,party_position,created_at) VALUES(?,?,?,?,?,?)""",
                (world_id, REALM_ID, guid, role, position, now),
            )
        for memory in canon.get("starting_tensions", [])[:8]:
            connection.execute(
                """INSERT INTO world_memories(world_id,kind,text,importance,created_at)
                   VALUES(?,'founding',?,4,?)""",
                (world_id, str(memory)[:2000], now),
            )
        for index, plan in enumerate(canon.get("initial_plans", [])[:6]):
            title = str(plan.get("title", f"Unfolding thread {index + 1}"))[:120]
            hint = str(plan.get("hint", "Something is beginning to stir."))[:500]
            connection.execute(
                """INSERT INTO planned_events
                   (id,world_id,title,hint,plan_json,due_played_seconds,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (str(uuid4()), world_id, title, hint, json.dumps(plan),
                 max(int(plan.get("after_played_minutes", 60)), 1) * 60, now),
            )
        connection.commit()
        self.store.close(connection)
        for bot, role in zip(selected, roles):
            guid = str(bot["guid"])
            self.store.seed_soul(REALM_ID, guid, str(bot["name"]))
            generated = profile_by_guid.get(guid, {})
            self.store.update_soul(REALM_ID, guid, {
                "archetype": str(generated.get("archetype", f"{role} companion")),
                "voice": str(generated.get("voice", "grounded, observant, and shaped by the world canon")),
                "values_text": str(generated.get("values", "loyalty, courage, shared history")),
                "enabled": True,
            })
        return self.active_world() or {}

    def memories(self, limit: int = 100) -> list[dict[str, Any]]:
        world = self.active_world()
        if not world:
            return []
        connection = self.store.connect()
        rows = connection.execute(
            """SELECT id,kind,text,importance,supersedes_id,redacted,created_at
               FROM world_memories WHERE world_id=? ORDER BY id DESC LIMIT ?""",
            (world["id"], min(max(limit, 1), 200)),
        ).fetchall()
        self.store.close(connection)
        return [{**dict(row), "redacted": bool(row["redacted"])} for row in rows]

    def rumors(self) -> list[dict[str, Any]]:
        world = self.active_world()
        if not world:
            return []
        connection = self.store.connect()
        rows = connection.execute(
            """SELECT id,title,hint,status,created_at FROM planned_events
               WHERE world_id=? AND status IN ('planned','armed') ORDER BY due_played_seconds LIMIT 20""",
            (world["id"],),
        ).fetchall()
        self.store.close(connection)
        return [dict(row) for row in rows]

    def claim_due_plan(self) -> dict[str, Any] | None:
        world = self.active_world()
        if not world:
            return None
        connection = self.store.connect()
        row = connection.execute(
            """SELECT * FROM planned_events WHERE world_id=? AND status='planned'
               AND due_played_seconds<=? ORDER BY due_played_seconds LIMIT 1""",
            (world["id"], world["played_seconds"]),
        ).fetchone()
        if row:
            connection.execute("UPDATE planned_events SET status='armed' WHERE id=?", (row["id"],))
            connection.commit()
        self.store.close(connection)
        if not row:
            return None
        value = dict(row)
        value["plan"] = json.loads(value.pop("plan_json"))
        return value

    def finish_plan(self, plan_id: str, memory_text: str) -> None:
        connection = self.store.connect()
        row = connection.execute("SELECT world_id FROM planned_events WHERE id=?", (plan_id,)).fetchone()
        if row:
            now = utc_now()
            connection.execute(
                "UPDATE planned_events SET status='occurred',occurred_at=? WHERE id=?", (now, plan_id)
            )
            connection.execute(
                """INSERT INTO world_memories(world_id,kind,text,source_event_id,importance,created_at)
                   VALUES(?,'narrative_event',?,?,4,?)""",
                (row["world_id"], memory_text[:2000], plan_id, now),
            )
            connection.commit()
        self.store.close(connection)

    def release_plan(self, plan_id: str) -> None:
        connection = self.store.connect()
        connection.execute("UPDATE planned_events SET status='planned' WHERE id=? AND status='armed'", (plan_id,))
        connection.commit()
        self.store.close(connection)

    def companions(self) -> list[dict[str, Any]]:
        world = self.active_world()
        if not world:
            return []
        connection = self.store.connect()
        rows = connection.execute(
            """SELECT b.role,b.party_position,s.*,COUNT(m.id) AS memory_count
               FROM companion_bindings b JOIN souls s
                 ON s.realm_id=b.realm_id AND s.bot_guid=b.bot_guid
               LEFT JOIN memories m ON m.realm_id=s.realm_id AND m.bot_guid=s.bot_guid
               WHERE b.world_id=? GROUP BY b.world_id,b.bot_guid ORDER BY b.party_position""",
            (world["id"],),
        ).fetchall()
        self.store.close(connection)
        return [dict(row) for row in rows]

    def promote_companion(self, guid: str, name: str, role: str = "dps") -> dict[str, Any]:
        world = self.active_world()
        if not world:
            raise ValueError("forge a world before promoting companions")
        if not re.fullmatch(r"[1-9][0-9]{0,19}", guid) or not 1 <= len(name) <= 24:
            raise ValueError("invalid companion identity")
        if role not in {"tank", "healer", "dps"}:
            raise ValueError("invalid companion role")
        connection = self.store.connect()
        position = connection.execute(
            "SELECT COALESCE(MAX(party_position),0)+1 AS position FROM companion_bindings WHERE world_id=?",
            (world["id"],),
        ).fetchone()["position"]
        connection.execute(
            """INSERT OR IGNORE INTO companion_bindings
               (world_id,realm_id,bot_guid,role,party_position,created_at) VALUES(?,?,?,?,?,?)""",
            (world["id"], REALM_ID, guid, role, position, utc_now()),
        )
        connection.commit()
        self.store.close(connection)
        self.store.seed_soul(REALM_ID, guid, name)
        return next(item for item in self.companions() if item["bot_guid"] == guid)

    def record_presence(self, humans_online: int, elapsed_seconds: int = 0) -> None:
        world = self.active_world()
        if not world:
            return
        elapsed = min(max(int(elapsed_seconds), 0), 120) if humans_online > 0 else 0
        connection = self.store.connect()
        session = connection.execute(
            "SELECT * FROM world_sessions WHERE world_id=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (world["id"],),
        ).fetchone()
        now = utc_now()
        if humans_online > 0:
            if not session:
                session_id = str(uuid4())
                connection.execute(
                    "INSERT INTO world_sessions(id,world_id,started_at) VALUES(?,?,?)",
                    (session_id, world["id"], now),
                )
            else:
                session_id = session["id"]
            if elapsed:
                connection.execute(
                    "UPDATE world_sessions SET played_seconds=played_seconds+? WHERE id=?",
                    (elapsed, session_id),
                )
                connection.execute(
                    "UPDATE worlds SET played_seconds=played_seconds+?,status='live',updated_at=? WHERE id=?",
                    (elapsed, now, world["id"]),
                )
        elif session:
            connection.execute("UPDATE world_sessions SET ended_at=? WHERE id=?", (now, session["id"]))
            connection.execute("UPDATE worlds SET status='paused',updated_at=? WHERE id=?", (now, world["id"]))
        connection.commit()
        self.store.close(connection)

    def providers(self) -> list[dict[str, Any]]:
        connection = self.store.connect()
        rows = connection.execute(
            """SELECT id,name,kind,base_url,enabled,has_secret,input_cost_micros,
                      cached_input_cost_micros,output_cost_micros,verified_at,created_at,updated_at
               FROM provider_profiles ORDER BY name"""
        ).fetchall()
        self.store.close(connection)
        return [{**dict(row), "enabled": bool(row["enabled"]),
                 "has_secret": bool(row["has_secret"])} for row in rows]

    def provider(self, provider_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
        connection = self.store.connect()
        row = connection.execute("SELECT * FROM provider_profiles WHERE id=?", (provider_id,)).fetchone()
        self.store.close(connection)
        if not row:
            return None
        value = dict(row)
        if not include_secret:
            value.pop("secret_ciphertext", None)
        return value

    def save_provider(self, payload: dict[str, Any], secret_ciphertext: str = "") -> dict[str, Any]:
        provider_id = str(payload.get("id") or uuid4())
        name, kind = str(payload.get("name", "")).strip(), str(payload.get("kind", "")).strip()
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", provider_id):
            raise ValueError("invalid provider id")
        if not 1 <= len(name) <= 80 or kind not in PROVIDER_KINDS:
            raise ValueError("invalid provider name or kind")
        if not re.fullmatch(r"https?://[^\s]{3,500}", base_url):
            raise ValueError("provider base_url must be an http or https URL")
        if kind not in {"ollama", "openai_compatible"} and not secret_ciphertext:
            existing = self.provider(provider_id, include_secret=True)
            if not existing or not existing.get("secret_ciphertext"):
                raise ValueError("this provider requires an API key")
        costs = []
        for key in ("input_cost_micros", "cached_input_cost_micros", "output_cost_micros"):
            value = int(payload.get(key, 0))
            if not 0 <= value <= 10_000_000_000:
                raise ValueError(f"invalid {key}")
            costs.append(value)
        now = utc_now()
        connection = self.store.connect()
        prior = connection.execute("SELECT secret_ciphertext FROM provider_profiles WHERE id=?", (provider_id,)).fetchone()
        encrypted = secret_ciphertext or (prior["secret_ciphertext"] if prior else "")
        connection.execute(
            """INSERT INTO provider_profiles
               (id,name,kind,base_url,secret_ciphertext,enabled,has_secret,input_cost_micros,
                cached_input_cost_micros,output_cost_micros,verified_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,
                 base_url=excluded.base_url,secret_ciphertext=excluded.secret_ciphertext,
                 enabled=excluded.enabled,has_secret=excluded.has_secret,
                 input_cost_micros=excluded.input_cost_micros,
                 cached_input_cost_micros=excluded.cached_input_cost_micros,
                 output_cost_micros=excluded.output_cost_micros,
                 verified_at=excluded.verified_at,updated_at=excluded.updated_at""",
            (provider_id, name, kind, base_url, encrypted, 1 if payload.get("enabled", True) else 0,
             1 if encrypted else 0, *costs, payload.get("verified_at"),
             now, now),
        )
        connection.commit()
        self.store.close(connection)
        return self.provider(provider_id) or {}

    def routes(self) -> dict[str, dict[str, Any]]:
        connection = self.store.connect()
        rows = connection.execute("SELECT * FROM ai_routes ORDER BY purpose").fetchall()
        self.store.close(connection)
        return {row["purpose"]: dict(row) for row in rows}

    def save_routes(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        connection = self.store.connect()
        for purpose in ("director", "dialogue", "ambient"):
            if purpose not in payload:
                continue
            route = payload[purpose]
            provider_id, model = str(route.get("provider_id", "")), str(route.get("model", "")).strip()
            if not self.provider(provider_id) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
                raise ValueError(f"invalid {purpose} provider or model")
            temperature, max_tokens = float(route.get("temperature", 0.7)), int(route.get("max_tokens", 180))
            if not 0 <= temperature <= 2 or not 32 <= max_tokens <= 4096:
                raise ValueError(f"invalid {purpose} generation limits")
            connection.execute(
                """UPDATE ai_routes SET provider_id=?,model=?,temperature=?,max_tokens=?,updated_at=?
                   WHERE purpose=?""",
                (provider_id, model, temperature, max_tokens, utc_now(), purpose),
            )
        connection.commit()
        self.store.close(connection)
        return self.routes()

    def ai_state(self) -> dict[str, Any]:
        settings = self.store.get_settings()
        return {
            "enabled": settings.get("ai_enabled", settings.get("souls_enabled", "true")) == "true",
            "monthly_cap_micros": int(settings.get("monthly_cap_micros", "0")),
            "auto_stop_minutes": int(settings.get("auto_stop_minutes", "10")),
            "ambient_enabled": settings.get("ambient_enabled", "true") == "true",
            "ambient_reply_percent": int(settings.get("ambient_reply_percent", "5")),
            "ambient_cooldown_seconds": int(settings.get("ambient_cooldown_seconds", "30")),
        }

    def save_ai_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.ai_state()
        enabled = payload.get("enabled", current["enabled"])
        cap = payload.get("monthly_cap_micros", current["monthly_cap_micros"])
        auto_stop = payload.get("auto_stop_minutes", current["auto_stop_minutes"])
        ambient_enabled = payload.get("ambient_enabled", current["ambient_enabled"])
        ambient_percent = payload.get("ambient_reply_percent", current["ambient_reply_percent"])
        ambient_cooldown = payload.get("ambient_cooldown_seconds", current["ambient_cooldown_seconds"])
        if not isinstance(enabled, bool) or isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
            raise ValueError("invalid AI state")
        if isinstance(auto_stop, bool) or not isinstance(auto_stop, int) or not 0 <= auto_stop <= 120:
            raise ValueError("auto_stop_minutes must be between 0 and 120")
        if not isinstance(ambient_enabled, bool):
            raise ValueError("ambient_enabled must be boolean")
        if isinstance(ambient_percent, bool) or not isinstance(ambient_percent, int) or not 0 <= ambient_percent <= 25:
            raise ValueError("ambient_reply_percent must be between 0 and 25")
        if isinstance(ambient_cooldown, bool) or not isinstance(ambient_cooldown, int) or not 5 <= ambient_cooldown <= 600:
            raise ValueError("ambient_cooldown_seconds must be between 5 and 600")
        self.store.set_settings({
            "ai_enabled": "true" if enabled else "false",
            "souls_enabled": "true" if enabled else "false",
            "monthly_cap_micros": str(cap),
            "auto_stop_minutes": str(auto_stop),
            "ambient_enabled": "true" if ambient_enabled else "false",
            "ambient_reply_percent": str(ambient_percent),
            "ambient_cooldown_seconds": str(ambient_cooldown),
        })
        return self.ai_state()

    def record_usage(self, purpose: str, profile: dict[str, Any], model: str,
                     usage: dict[str, int], latency_ms: int, success: bool,
                     error_code: str | None = None) -> dict[str, int]:
        ordinary_input = max(usage.get("input_tokens", 0) - usage.get("cached_input_tokens", 0), 0)
        cost = (
            ordinary_input * profile.get("input_cost_micros", 0)
            + usage.get("cached_input_tokens", 0) * profile.get("cached_input_cost_micros", 0)
            + (usage.get("output_tokens", 0) + usage.get("reasoning_tokens", 0))
            * profile.get("output_cost_micros", 0)
        ) // 1_000_000
        connection = self.store.connect()
        connection.execute(
            """INSERT INTO ai_usage
               (purpose,provider_id,model,input_tokens,cached_input_tokens,reasoning_tokens,
                output_tokens,total_tokens,estimated_cost_micros,latency_ms,success,error_code,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (purpose, profile["id"], model, usage.get("input_tokens", 0),
             usage.get("cached_input_tokens", 0), usage.get("reasoning_tokens", 0),
             usage.get("output_tokens", 0), usage.get("total_tokens", 0), cost,
             latency_ms, 1 if success else 0, error_code, utc_now()),
        )
        connection.commit()
        self.store.close(connection)
        return {"estimated_cost_micros": cost}

    def usage_summary(self) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00Z")
        current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        series_start = current_hour - timedelta(hours=23)
        connection = self.store.connect()
        row = connection.execute(
            """SELECT COALESCE(SUM(input_tokens),0) AS input_tokens,
                      COALESCE(SUM(cached_input_tokens),0) AS cached_input_tokens,
                      COALESCE(SUM(reasoning_tokens),0) AS reasoning_tokens,
                      COALESCE(SUM(output_tokens),0) AS output_tokens,
                      COALESCE(SUM(total_tokens),0) AS total_tokens,
                      COALESCE(SUM(estimated_cost_micros),0) AS estimated_cost_micros,
                      COUNT(*) AS requests
               FROM ai_usage WHERE created_at>=?""",
            (month,),
        ).fetchone()
        hourly_rows = connection.execute(
            """SELECT substr(created_at,1,13) || ':00:00Z' AS bucket,
                      COALESCE(SUM(input_tokens),0) AS input_tokens,
                      COALESCE(SUM(output_tokens),0) AS output_tokens,
                      COALESCE(SUM(reasoning_tokens),0) AS reasoning_tokens,
                      COUNT(*) AS requests
               FROM ai_usage WHERE created_at>=?
               GROUP BY substr(created_at,1,13) ORDER BY bucket""",
            (series_start.isoformat().replace("+00:00", "Z"),),
        ).fetchall()
        self.store.close(connection)
        by_bucket = {item["bucket"]: dict(item) for item in hourly_rows}
        series = []
        for offset in range(24):
            bucket = (series_start + timedelta(hours=offset)).isoformat().replace("+00:00", "Z")
            series.append(by_bucket.get(bucket, {
                "bucket": bucket, "input_tokens": 0, "output_tokens": 0,
                "reasoning_tokens": 0, "requests": 0,
            }))
        return {**dict(row), "period_start": month, "series": series, **self.ai_state()}

    def paid_budget_available(self, profile: dict[str, Any]) -> bool:
        cap = self.ai_state()["monthly_cap_micros"]
        if not cap or profile["kind"] == "ollama":
            return True
        return self.usage_summary()["estimated_cost_micros"] < cap


def companion_roles(player_role: str) -> list[str]:
    if player_role == "tank":
        return ["healer", "dps", "dps", "dps"]
    if player_role == "healer":
        return ["tank", "dps", "dps", "dps"]
    return ["tank", "healer", "dps", "dps"]


def select_dungeon_group(candidates: list[dict[str, Any]], faction: str,
                         player_role: str) -> list[dict[str, Any]]:
    eligible = [bot for bot in candidates if int(bot.get("race", 0)) in FACTION_RACES[faction]]
    selected: list[dict[str, Any]] = []
    for role in companion_roles(player_role):
        pool = [bot for bot in eligible if bot not in selected and _supports_role(int(bot.get("class", 0)), role)]
        if not pool:
            raise ValueError(f"Playerbots has not generated an eligible {faction} {role} companion yet")
        selected.append(sorted(pool, key=lambda bot: (not bot.get("player_added", False), int(bot.get("level", 1)), str(bot.get("name"))))[0])
    return selected


def _supports_role(character_class: int, role: str) -> bool:
    if role == "tank":
        return character_class in TANK_CLASSES
    if role == "healer":
        return character_class in HEALER_CLASSES
    return character_class not in {0}

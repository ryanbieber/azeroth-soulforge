"""Internal, allowlisted host control boundary for Soulforge administration."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


MAX_BODY = 16 * 1024
PROJECT = "azeroth-soulforge"
CONFIG_DIR = Path("/config")
SETTING_KEYS = {
    "random_bots": ("modules/playerbots.conf", ("AiPlayerbot.MinRandomBots", "AiPlayerbot.MaxRandomBots"), 0, 2000),
    "max_added_bots": ("modules/playerbots.conf", ("AiPlayerbot.MaxAddedBots",), 1, 80),
    "player_limit": ("worldserver.conf", ("PlayerLimit",), 1, 1000),
    "new_character_level": ("worldserver.conf", ("StartPlayerLevel", "StartHeroicPlayerLevel"), 1, 80),
}
RATE_SETTING_KEYS = {
    "xp_rate": (
        "worldserver.conf",
        (
            "Rate.XP.Kill", "Rate.XP.Quest", "Rate.XP.Quest.DF", "Rate.XP.Explore", "Rate.XP.Pet",
            "Rate.XP.BattlegroundKillAV", "Rate.XP.BattlegroundKillWSG",
            "Rate.XP.BattlegroundKillAB", "Rate.XP.BattlegroundKillEOTS",
            "Rate.XP.BattlegroundKillSOTA", "Rate.XP.BattlegroundKillIC",
            "Rate.XP.BattlegroundBonus",
        ),
        0.1, 10.0, 1.0,
    ),
    "reputation_rate": ("worldserver.conf", ("Rate.Reputation.Gain",), 0.1, 10.0, 1.0),
    "loot_rate": (
        "worldserver.conf",
        (
            "Rate.Drop.Item.Poor", "Rate.Drop.Item.Normal", "Rate.Drop.Item.Uncommon",
            "Rate.Drop.Item.Rare", "Rate.Drop.Item.Epic", "Rate.Drop.Item.Legendary",
            "Rate.Drop.Item.Artifact", "Rate.Drop.Item.Referenced",
        ),
        0.1, 10.0, 1.0,
    ),
    "money_rate": ("worldserver.conf", ("Rate.Drop.Money",), 0.1, 10.0, 1.0),
    "honor_rate": ("worldserver.conf", ("Rate.Honor",), 0.1, 10.0, 1.0),
    "profession_skill_rate": (
        "worldserver.conf", ("SkillGain.Crafting", "SkillGain.Gathering"), 1, 10, 1,
    ),
}
REALM_TYPES = {
    "normal": 0,
    "pvp": 1,
    "rp": 6,
    "rp_pvp": 8,
}
AHBOT_CONFIG = "modules/mod_ahbot.conf"


def run(command: list[str], *, input_text: str | None = None, timeout: int = 45) -> str:
    completed = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise RuntimeError(detail or f"command failed with status {completed.returncode}")
    return completed.stdout


def container_id(service: str) -> str:
    output = run([
        "docker", "ps", "--all", "--quiet",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={service}",
    ])
    identifiers = output.split()
    if not identifiers:
        raise RuntimeError(f"{service} container has not been created; run make up once")
    return identifiers[0]


def service_state(service: str) -> dict[str, Any]:
    try:
        identifier = container_id(service)
        raw = run([
            "docker", "inspect", identifier, "--format",
            "{{json .State}}",
        ])
        state = json.loads(raw)
        return {
            "service": service,
            "status": state.get("Status", "unknown"),
            "running": bool(state.get("Running")),
            "health": (state.get("Health") or {}).get("Status"),
            "started_at": state.get("StartedAt"),
        }
    except RuntimeError as error:
        return {"service": service, "status": "missing", "running": False, "detail": str(error)}


def read_config_value(filename: str, key: str, default: int | float) -> int | float:
    path = CONFIG_DIR / filename
    if not path.exists():
        return default
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(\d+(?:\.\d+)?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            value = float(match.group(1))
            return int(value) if isinstance(default, int) else value
    return default


def write_config_value(filename: str, key: str, value: int | float) -> None:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise RuntimeError(f"{filename} is unavailable; run make up once")
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replacement = f"{key} = {value:g}"
    updated = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = replacement
            updated = True
            break
    if not updated:
        lines.append(replacement)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.chmod(path.stat().st_mode)
    temporary.replace(path)


def mysql(sql: str, database: str | None = None) -> str:
    database_container = container_id("ac-database")
    command = [
        "docker", "exec", "-i", "-e",
        f"MYSQL_PWD={os.environ['SOULFORGE_DB_ROOT_PASSWORD']}",
        database_container, "mysql", "--batch", "--skip-column-names", "--raw", "--user=root",
    ]
    if database:
        command.append(database)
    return run(command, input_text=sql, timeout=30)


def realm_name() -> str:
    try:
        return mysql("SELECT name FROM realmlist WHERE id=1;", "acore_auth").strip() or "Azeroth Soulforge"
    except RuntimeError:
        return "Azeroth Soulforge"


def update_realm_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9 ._'!-]{1,32}", value):
        raise ValueError("realm_name must be 1-32 simple display characters")
    escaped = value.replace("'", "''")
    mysql(f"UPDATE realmlist SET name='{escaped}' WHERE id=1;", "acore_auth")


def realm_type() -> str:
    value = read_config_value("worldserver.conf", "GameType", 0)
    return next((name for name, number in REALM_TYPES.items() if number == value), "normal")


def update_realm_type(value: str) -> None:
    if value not in REALM_TYPES:
        raise ValueError(f"realm_type must be one of: {', '.join(REALM_TYPES)}")
    number = REALM_TYPES[value]
    write_config_value("worldserver.conf", "GameType", number)
    mysql(f"UPDATE realmlist SET icon={number} WHERE id=1;", "acore_auth")


def update_rate_setting(name: str, value: Any) -> None:
    filename, keys, minimum, maximum, _ = RATE_SETTING_KEYS[name]
    invalid_integer = isinstance(minimum, int) and not isinstance(value, int)
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or invalid_integer
            or not minimum <= value <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    normalized = int(value) if isinstance(minimum, int) else float(value)
    for key in keys:
        write_config_value(filename, key, normalized)


def update_setting(name: str, value: Any) -> None:
    filename, keys, minimum, maximum = SETTING_KEYS[name]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    for key in keys:
        write_config_value(filename, key, value)


def auction_house_characters() -> list[dict[str, Any]]:
    query = """
SELECT c.guid,c.name,c.account,a.username,c.online
FROM acore_characters.characters c
JOIN acore_auth.account a ON a.id=c.account
WHERE LOWER(a.username) NOT LIKE 'rndbot%'
  AND LOWER(a.username) NOT LIKE 'addclass%'
ORDER BY a.username,c.name;
"""
    characters = []
    for line in mysql(query).splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        guid, name, account, username, online = fields
        characters.append({
            "guid": guid, "name": name, "account_id": int(account),
            "account": username, "online": online == "1",
        })
    return characters


def auction_house_settings() -> dict[str, Any]:
    return {
        "auction_house_character_guid": str(read_config_value(AHBOT_CONFIG, "AuctionHouseBot.GUID", 0)),
        "auction_house_seller": bool(read_config_value(AHBOT_CONFIG, "AuctionHouseBot.EnableSeller", 0)),
        "auction_house_buyer": bool(read_config_value(AHBOT_CONFIG, "AuctionHouseBot.EnableBuyer", 0)),
        "auction_house_items_per_cycle": read_config_value(AHBOT_CONFIG, "AuctionHouseBot.ItemsPerCycle", 200),
    }


def update_auction_house_settings(payload: dict[str, Any]) -> bool:
    names = {
        "auction_house_character_guid", "auction_house_seller", "auction_house_buyer",
        "auction_house_items_per_cycle",
    }
    if not names.intersection(payload):
        return False

    current = auction_house_settings()
    guid_text = str(payload.get("auction_house_character_guid", current["auction_house_character_guid"]))
    if not re.fullmatch(r"0|[1-9][0-9]{0,9}", guid_text):
        raise ValueError("auction_house_character_guid must identify an available character")
    guid = int(guid_text)
    seller = payload.get("auction_house_seller", current["auction_house_seller"])
    buyer = payload.get("auction_house_buyer", current["auction_house_buyer"])
    items = payload.get("auction_house_items_per_cycle", current["auction_house_items_per_cycle"])
    if not isinstance(seller, bool) or not isinstance(buyer, bool):
        raise ValueError("auction house seller and buyer settings must be boolean")
    if isinstance(items, bool) or not isinstance(items, int) or not 1 <= items <= 1000:
        raise ValueError("auction_house_items_per_cycle must be between 1 and 1000")
    if (seller or buyer) and guid == 0:
        raise ValueError("choose a dedicated auction-house character before enabling the bot")

    account = 0
    if guid:
        rows = [entry for entry in auction_house_characters() if entry["guid"] == guid_text]
        if not rows:
            raise ValueError("the selected auction-house character is unavailable")
        if (seller or buyer) and rows[0]["online"]:
            raise ValueError("log out the dedicated auction-house character before enabling the bot")
        account = rows[0]["account_id"]

    write_config_value(AHBOT_CONFIG, "AuctionHouseBot.Account", account)
    write_config_value(AHBOT_CONFIG, "AuctionHouseBot.GUID", guid)
    write_config_value(AHBOT_CONFIG, "AuctionHouseBot.EnableSeller", int(seller))
    write_config_value(AHBOT_CONFIG, "AuctionHouseBot.EnableBuyer", int(buyer))
    write_config_value(AHBOT_CONFIG, "AuctionHouseBot.ItemsPerCycle", items)
    return True


def list_bots() -> list[dict[str, Any]]:
    query = """
SELECT c.guid,c.name,c.level,c.race,c.class,c.online,a.username,
       CASE WHEN LOWER(a.username) LIKE 'rndbot%' THEN 0 ELSE 1 END AS player_added
FROM acore_characters.characters c
JOIN acore_auth.account a ON a.id=c.account
WHERE LOWER(a.username) NOT LIKE 'addclass%'
ORDER BY player_added DESC,c.name;
"""
    rows = []
    try:
        output = mysql(query)
    except RuntimeError:
        return rows
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 8:
            continue
        guid, name, level, race, character_class, online, account, player_added = fields
        rows.append({
            "guid": guid,
            "name": name,
            "level": int(level),
            "race": int(race),
            "class": int(character_class),
            "online": online == "1",
            "account": account,
            "player_added": player_added == "1",
        })
    return rows


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "SoulforgeControl/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if not self._authorized():
            return
        if self.path == "/v1/status":
            services = [service_state(name) for name in (
                "ac-database", "ac-authserver", "ac-worldserver", "ollama", "soul-service"
            )]
            self._json(HTTPStatus.OK, {"services": services})
        elif self.path == "/v1/settings":
            settings: dict[str, Any] = {"realm_name": realm_name(), "realm_type": realm_type()}
            for name, (filename, keys, minimum, _) in SETTING_KEYS.items():
                settings[name] = read_config_value(filename, keys[0], minimum)
            for name, (filename, keys, _, _, default) in RATE_SETTING_KEYS.items():
                settings[name] = read_config_value(filename, keys[0], default)
            settings.update(auction_house_settings())
            self._json(HTTPStatus.OK, settings)
        elif self.path == "/v1/bots":
            self._json(HTTPStatus.OK, {"bots": list_bots()})
        elif self.path == "/v1/auction-house/characters":
            self._json(HTTPStatus.OK, {"characters": auction_house_characters()})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        try:
            payload = self._body()
            if self.path.startswith("/v1/actions/"):
                action = self.path.rsplit("/", 1)[-1]
                if action not in {"start", "stop", "restart"}:
                    raise ValueError("unsupported action")
                command = "restart" if action == "restart" else action
                for service in ("ac-authserver", "ac-worldserver"):
                    run(["docker", command, container_id(service)], timeout=90)
                self._json(HTTPStatus.OK, {"status": "accepted", "action": action})
            elif self.path == "/v1/settings":
                changed = False
                for name in SETTING_KEYS:
                    if name not in payload:
                        continue
                    update_setting(name, payload[name])
                    changed = True
                for name in RATE_SETTING_KEYS:
                    if name not in payload:
                        continue
                    update_rate_setting(name, payload[name])
                    changed = True
                if update_auction_house_settings(payload):
                    changed = True
                if "realm_name" in payload:
                    update_realm_name(str(payload["realm_name"]).strip())
                if "realm_type" in payload:
                    update_realm_type(str(payload["realm_type"]))
                    changed = True
                restarted = False
                if changed:
                    world = service_state("ac-worldserver")
                    if world["running"]:
                        run(["docker", "restart", container_id("ac-worldserver")], timeout=120)
                        restarted = True
                self._json(HTTPStatus.OK, {
                    "status": "applied",
                    "world_restarted": restarted,
                })
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "operation_failed", "detail": str(error)})

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = os.environ.get("SOULFORGE_CONTROL_SECRET", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False
        return True

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise ValueError("request body is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    if not os.environ.get("SOULFORGE_CONTROL_SECRET"):
        raise SystemExit("SOULFORGE_CONTROL_SECRET must be set")
    server = build_server("0.0.0.0", 8770)
    server.daemon_threads = True
    print("Soulforge control agent listening internally on port 8770", flush=True)
    server.serve_forever()


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ControlHandler)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    main()

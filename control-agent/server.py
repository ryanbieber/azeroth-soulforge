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
    "random_bots": ("modules/playerbots.conf", ("AiPlayerbot.MinRandomBots", "AiPlayerbot.MaxRandomBots"), 0, 200),
    "max_added_bots": ("modules/playerbots.conf", ("AiPlayerbot.MaxAddedBots",), 1, 80),
    "player_limit": ("worldserver.conf", ("PlayerLimit",), 1, 1000),
}


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


def read_config_value(filename: str, key: str, default: int) -> int:
    path = CONFIG_DIR / filename
    if not path.exists():
        return default
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(\d+)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1))
    return default


def write_config_value(filename: str, key: str, value: int) -> None:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise RuntimeError(f"{filename} is unavailable; run make up once")
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replacement = f"{key} = {value}"
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


def list_bots() -> list[dict[str, Any]]:
    query = """
SELECT c.guid,c.name,c.level,c.race,c.class,c.online,a.username
FROM acore_characters.characters c
JOIN acore_auth.account a ON a.id=c.account
WHERE LOWER(a.username) LIKE 'rndbot%'
ORDER BY c.name;
"""
    rows = []
    try:
        output = mysql(query)
    except RuntimeError:
        return rows
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        guid, name, level, race, character_class, online, account = fields
        rows.append({
            "guid": guid,
            "name": name,
            "level": int(level),
            "race": int(race),
            "class": int(character_class),
            "online": online == "1",
            "account": account,
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
            settings: dict[str, Any] = {"realm_name": realm_name()}
            for name, (filename, keys, minimum, _) in SETTING_KEYS.items():
                settings[name] = read_config_value(filename, keys[0], minimum)
            self._json(HTTPStatus.OK, settings)
        elif self.path == "/v1/bots":
            self._json(HTTPStatus.OK, {"bots": list_bots()})
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
                for name, (filename, keys, minimum, maximum) in SETTING_KEYS.items():
                    if name not in payload:
                        continue
                    value = payload[name]
                    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                        raise ValueError(f"{name} must be between {minimum} and {maximum}")
                    for key in keys:
                        write_config_value(filename, key, value)
                    changed = True
                if "realm_name" in payload:
                    update_realm_name(str(payload["realm_name"]).strip())
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

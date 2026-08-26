"""Minimal scaffold health server used by the local Compose stack.

This is intentionally not the planned FastAPI bridge implementation. It makes
the development stack observable while API and persistence milestones are
built without pretending unimplemented endpoints exist.
"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Any


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "SoulforgeScaffold/0.1"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/health":
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._json_response(
            HTTPStatus.OK,
            {
                "status": "ok",
                "stage": "scaffold",
                "ollama_url": os.environ.get(
                    "SOULFORGE_OLLAMA_URL", "http://127.0.0.1:11434"
                ),
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _json_response(self, status: HTTPStatus, payload: dict[str, str]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), HealthHandler)


def main() -> None:
    host = os.environ.get("SOULFORGE_HOST", "127.0.0.1")
    port = int(os.environ.get("SOULFORGE_PORT", "8765"))
    server = build_server(host, port)
    print(f"Soulforge scaffold listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

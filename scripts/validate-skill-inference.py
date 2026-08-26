#!/usr/bin/env python3
"""Run one signed event through Soul Service and prove SKILL.md reaches Ollama."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
from urllib.request import Request, urlopen
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "soul-service" / "src"))

from soulforge.server import build_server  # noqa: E402


def owner_section(document: str) -> str:
    marker = "## Character skill (owner editable)"
    end = "<!-- soulforge:memories:start -->"
    if marker not in document or end not in document:
        raise SystemExit("example SKILL.md is missing its managed section markers")
    return document.split(marker, 1)[1].split(end, 1)[0].strip()


def main() -> None:
    ollama_url = os.environ.get("SOULFORGE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("SOULFORGE_CHAT_MODEL", "qwen3.5:4b")
    with urlopen(f"{ollama_url}/api/tags", timeout=5) as response:
        installed = {item["name"] for item in json.load(response).get("models", [])}
    if model not in installed:
        raise SystemExit(f"{model} is not installed in Ollama")

    source = (REPO_ROOT / "examples" / "profiles" / "Thorn" / "SKILL.md").read_text(encoding="utf-8")
    secret = "local-skill-validation-secret"
    with tempfile.TemporaryDirectory() as directory:
        os.environ["SOULFORGE_OLLAMA_URL"] = ollama_url
        os.environ["SOULFORGE_CHAT_MODEL"] = model
        server = build_server(
            "127.0.0.1", 0, str(Path(directory) / "soulforge.sqlite3"), secret,
            "local-validation-admin", start_worker=True,
        )
        server.store.seed_soul("skill-validation", "1842", "Thorn")
        server.store.update_soul("skill-validation", "1842", {
            "archetype": "weathered road warden",
            "voice": "dry, observant, quietly protective",
            "values_text": "loyalty, patience, keeping one's word",
            "enabled": True,
        })
        server.store.update_skill_document("skill-validation", "1842", owner_section(source))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            event = {
                "schema_version": "1.0",
                "event_id": str(uuid4()),
                "realm_id": "skill-validation",
                "event_type": "chat.whisper",
                "occurred_at": "2026-08-26T00:00:00Z",
                "actor": {"guid": "1", "kind": "human", "name": "Guildmaster"},
                "participants": [{"guid": "1842", "kind": "soul", "name": "Thorn"}],
                "channel": "whisper",
                "text": "What exact keepsake did you hide beneath the Northshire bridge? Answer with only its name.",
                "context": {},
                "trace": {"trace_id": str(uuid4()), "origin": "human", "hop_count": 0},
            }
            body = json.dumps(event, separators=(",", ":")).encode()
            timestamp, nonce = str(int(time.time())), str(uuid4())
            canonical = b"POST\n/v1/events\n" + timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
            signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
            request = Request(
                f"http://127.0.0.1:{server.server_port}/v1/events", data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Soulforge-Timestamp": timestamp,
                    "X-Soulforge-Nonce": nonce,
                    "X-Soulforge-Signature": signature,
                },
            )
            with urlopen(request, timeout=5) as response:
                accepted = json.load(response)
            deadline = time.time() + 180
            replies = []
            while time.time() < deadline:
                replies = server.store.pending("skill-validation", 10)
                if replies:
                    break
                time.sleep(0.5)
            if not replies:
                raise SystemExit("Ollama did not return a Soulforge reply within 180 seconds")
            reply = replies[0]["text"]
            if "silver" not in reply.lower() or "acorn" not in reply.lower():
                raise SystemExit(f"model reply did not use Thorn's SKILL.md detail: {reply!r}")
            print(f"event={accepted['status']} model={model}")
            print(f"reply={reply}")
            print("SKILL.md inference validation passed: the reply used Thorn's silver acorn detail.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()

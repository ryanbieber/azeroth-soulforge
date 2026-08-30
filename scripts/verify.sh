#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

required=(
  AGENTS.md README.md LICENSE Makefile compose.yaml .env.example .dockerignore docs/PROJECT.md
  docs/LAN_SETUP.md scripts/setup-source.sh scripts/configure-realm.sh
  scripts/create-account.sh scripts/configure-firewall.sh
  scripts/install-module-sql.sh
  contracts/openapi.yaml contracts/admin-openapi.yaml contracts/events.schema.json
  contracts/soul-export.schema.json soul-service/pyproject.toml
  soul-service/src/soulforge/providers.py soul-service/src/soulforge/world.py
  soul-service/README.md mod-soulbridge/CMakeLists.txt
  mod-soulbridge/README.md mod-soulbridge/include.sh
  control-agent/Dockerfile control-agent/server.py dashboard/package-lock.json
  dashboard/src/main.jsx config/nginx-soulforge.conf config/upstreams.lock.yaml
  examples/profiles/README.md examples/profiles/Thorn/SKILL.md
  scripts/validate-skill-inference.py
  docs/GETTING_STARTED.md docs/PLAYERBOT_HOTKEYS.md site/index.html site/assets/styles.css
  site/assets/app.js site/.nojekyll .github/workflows/pages.yml
  scripts/validate-pages.py
  addons/SoulforgeCommander/SoulforgeCommander.toc
  addons/SoulforgeCommander/SoulforgeCommander.lua
  addons/SoulforgeCommander/Bindings.xml
)
for path in "${required[@]}"; do
  test -f "$path" || { echo "missing required file: $path" >&2; exit 1; }
done

python3 - <<'PY'
import json
from pathlib import Path

for path in Path("contracts").glob("*.json"):
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SystemExit(f"{path}: unsupported or missing JSON Schema dialect")

openapi = Path("contracts/openapi.yaml").read_text(encoding="utf-8")
for marker in ("openapi: 3.1.0", "/v1/events:", "/v1/outbox:", "components:"):
    if marker not in openapi:
        raise SystemExit(f"contracts/openapi.yaml: missing {marker!r}")

admin = Path("contracts/admin-openapi.yaml").read_text(encoding="utf-8")
for marker in ("openapi: 3.1.0", "/session:", "/world/forge:", "/ai/providers:", "/addon/download:", "/server/settings:", "/models/pull:", "/skill:"):
    if marker not in admin:
        raise SystemExit(f"contracts/admin-openapi.yaml: missing {marker!r}")
PY

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=soul-service/src \
  python3 -m unittest discover -s soul-service/tests -v

PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s control-agent/tests -v

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  scripts/validate-skill-inference.py

python3 scripts/validate-pages.py

npm --prefix dashboard ci --ignore-scripts
npm --prefix dashboard run build
npm --prefix dashboard exec -- luaparse --file addons/SoulforgeCommander/SoulforgeCommander.lua --quiet

docker compose --env-file .env.example -f compose.yaml config --quiet

for script in scripts/*.sh; do
  bash -n "$script"
done

VERIFY_TMP=$(mktemp -d)
trap 'rm -rf "$VERIFY_TMP"' EXIT
cmake -S mod-soulbridge -B "$VERIFY_TMP/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$VERIFY_TMP/build" --parallel 2
ctest --test-dir "$VERIFY_TMP/build" --output-on-failure

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
  tracked=$(git ls-files)
  if printf '%s\n' "$tracked" | grep -E '\.(db|sqlite|sqlite3|gguf|mpq|pem|key)$' >/dev/null; then
    echo "forbidden runtime, model, game, or secret file is tracked" >&2
    exit 1
  fi
fi

if rg -n --hidden -g '!.git/**' \
  '(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----)' .; then
  echo "possible committed secret detected" >&2
  exit 1
fi

echo "Azeroth Soulforge verification passed."

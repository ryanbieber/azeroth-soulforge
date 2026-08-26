#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
set -a; . ./.env; set +a

MARKER="$REPO_ROOT/.run/server-settings-initialized"
if test -f "$MARKER"; then
  exit 0
fi

set_config() {
  local file=$1 key=$2 value=$3
  test -f "$file" || { echo "missing generated configuration: $file" >&2; exit 1; }
  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import re
import sys

path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
for index, line in enumerate(lines):
    if pattern.match(line):
        lines[index] = f"{key} = {value}"
        break
else:
    lines.append(f"{key} = {value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

set_config runtime/azerothcore/etc/playerbots.conf AiPlayerbot.MinRandomBots "${SOULFORGE_RANDOM_BOTS:-50}"
set_config runtime/azerothcore/etc/playerbots.conf AiPlayerbot.MaxRandomBots "${SOULFORGE_RANDOM_BOTS:-50}"
set_config runtime/azerothcore/etc/playerbots.conf AiPlayerbot.MaxAddedBots "${SOULFORGE_MAX_ADDED_BOTS:-40}"
set_config runtime/azerothcore/etc/worldserver.conf PlayerLimit "${SOULFORGE_PLAYER_LIMIT:-100}"
mkdir -p "$REPO_ROOT/.run"
touch "$MARKER"

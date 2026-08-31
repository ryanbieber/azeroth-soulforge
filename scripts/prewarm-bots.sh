#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}
set -a; . ./.env; set +a

TARGET=${SOULFORGE_RANDOM_BOTS:-500}
TIMEOUT=${SOULFORGE_BOT_PREWARM_TIMEOUT:-3600}
MARKER="$REPO_ROOT/.run/bots-prewarmed"
CONFIG="$REPO_ROOT/runtime/azerothcore/etc/modules/playerbots.conf"

if (( TARGET < 0 || TARGET > 2000 )); then
  echo "SOULFORGE_RANDOM_BOTS must be between 0 and 2000" >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/.run"
PREPARED=0
if test -f "$MARKER"; then
  read -r PREPARED < "$MARKER" || PREPARED=0
fi
if [[ ! "$PREPARED" =~ ^[0-9]+$ ]]; then
  PREPARED=0
fi

BOT_ACCOUNTS=$($COMPOSE exec -T ac-database mysql \
  --user=root --password="$SOULFORGE_DB_ROOT_PASSWORD" \
  --database=acore_auth --batch --skip-column-names \
  --execute="SELECT COUNT(*) FROM account WHERE username LIKE 'RNDBOT%';" 2>/dev/null || echo 0)
if [[ ! "$BOT_ACCOUNTS" =~ ^[0-9]+$ ]] || (( BOT_ACCOUNTS == 0 )); then
  PREPARED=0
fi

if (( PREPARED >= TARGET )); then
  echo "Bot preparation already covers ${PREPARED} bots."
  exit 0
fi

if $COMPOSE ps --status running --services | grep -Eq '^(ac-worldserver|ac-authserver)$'; then
  if [[ "${SOULFORGE_EXPLICIT_BOT_BUILD:-0}" == "1" ]]; then
    echo "make bots requires the game services to be stopped; run 'make down' first" >&2
    exit 1
  fi
  printf '%s\n' "$TARGET" > "$MARKER"
  echo "Existing running realm detected; preserving it and adopting its prepared bot state."
  exit 0
fi

test -f "$CONFIG" || { echo "missing Playerbots configuration: $CONFIG" >&2; exit 1; }

set_config() {
  local key=$1 value=$2
  python3 - "$CONFIG" "$key" "$value" <<'PY'
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

restore_config() {
  set_config AiPlayerbot.ReactDelay 250
  set_config AiPlayerbot.RandomBotUpdateInterval 30
  set_config AiPlayerbot.RandomBotsPerInterval 25
  set_config AiPlayerbot.DisabledWithoutRealPlayer 1
  set_config AiPlayerbot.DisabledWithoutRealPlayerLoginDelay 30
}

cleanup() {
  restore_config
  if (( ${PREWARM_COMPLETE:-0} == 0 )); then
    $COMPOSE stop --timeout 180 ac-worldserver >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if (( TARGET == 0 )); then
  printf '0\n' > "$MARKER"
  PREWARM_COMPLETE=1
  echo "Random bots are disabled; no preparation is needed."
  exit 0
fi

echo "First-run bot preparation is starting for ${TARGET} bots."
echo "This can take several minutes; the normal login server is not started during preparation."
set_config AiPlayerbot.MinRandomBots "$TARGET"
set_config AiPlayerbot.MaxRandomBots "$TARGET"
set_config AiPlayerbot.DisabledWithoutRealPlayer 0
set_config AiPlayerbot.RandomBotUpdateInterval 20
set_config AiPlayerbot.RandomBotsPerInterval 60

STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
$COMPOSE up --detach --build ac-worldserver

DEADLINE=$((SECONDS + TIMEOUT))
LAST_COUNT=0
while (( SECONDS < DEADLINE )); do
  STATUS=$($COMPOSE ps --status running --services)
  if ! grep -qx 'ac-worldserver' <<<"$STATUS"; then
    echo "worldserver stopped during bot preparation" >&2
    exit 1
  fi

  COUNT=$($COMPOSE logs --no-color --since "$STARTED_AT" ac-worldserver 2>/dev/null \
    | rg -o "[0-9]+/${TARGET} Bot" \
    | tail -1 \
    | cut -d/ -f1 || true)
  COUNT=${COUNT:-0}
  if [[ "$COUNT" =~ ^[0-9]+$ ]] && (( COUNT > LAST_COUNT )); then
    LAST_COUNT=$COUNT
    echo "Prepared ${LAST_COUNT}/${TARGET} bots..."
  fi
  if (( LAST_COUNT >= TARGET )); then
    break
  fi
  sleep 5
done

if (( LAST_COUNT < TARGET )); then
  echo "bot preparation timed out at ${LAST_COUNT}/${TARGET}" >&2
  exit 1
fi

echo "Flushing prepared bot state to the database..."
$COMPOSE stop --timeout 180 ac-worldserver
restore_config
printf '%s\n' "$TARGET" > "$MARKER"
PREWARM_COMPLETE=1
trap - EXIT INT TERM
echo "Prepared ${TARGET}/${TARGET} bots. Normal starts will reuse this state."

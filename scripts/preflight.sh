#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
fail() { echo "preflight: $*" >&2; exit 1; }

command -v docker >/dev/null || fail "Docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose is required"
docker info >/dev/null 2>&1 || fail "Docker is not running or this user cannot access it"
test -f .env || fail "run: cp .env.example .env, then replace the private values"

set -a
. ./.env
set +a
for key in SOULFORGE_DB_ROOT_PASSWORD SOULFORGE_BRIDGE_SECRET SOULFORGE_GAME_USERNAME SOULFORGE_GAME_PASSWORD SOULFORGE_LAN_IP; do
  value=${!key:-}
  case "$value" in ""|replace-*|YOURACCOUNT) fail "replace $key in .env" ;; esac
done
[[ $SOULFORGE_GAME_USERNAME =~ ^[A-Za-z0-9]{1,17}$ ]] || fail "game username must be 1-17 letters/numbers"
[[ $SOULFORGE_GAME_PASSWORD =~ ^[A-Za-z0-9]{8,16}$ ]] || fail "game password must be 8-16 letters/numbers"
[[ $SOULFORGE_LAN_IP =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || fail "SOULFORGE_LAN_IP must be an IPv4 address"

test -d runtime/source/azerothcore/.git || fail "upstream source missing; run make setup"
test -f runtime/source/azerothcore/modules/mod-soulbridge/include.sh || fail "Soulbridge is not synced; run make setup"
mkdir -p runtime/azerothcore/etc runtime/azerothcore/logs backups
docker compose config --quiet
echo "preflight: complete"

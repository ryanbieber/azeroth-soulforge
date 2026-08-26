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
for key in SOULFORGE_DB_ROOT_PASSWORD SOULFORGE_BRIDGE_SECRET SOULFORGE_CONTROL_SECRET SOULFORGE_ADMIN_PASSWORD SOULFORGE_GAME_USERNAME SOULFORGE_GAME_PASSWORD SOULFORGE_LAN_IP SOULFORGE_LAN_CIDR; do
  value=${!key:-}
  case "$value" in ""|replace-*|YOURACCOUNT) fail "replace $key in .env" ;; esac
done
[[ $SOULFORGE_GAME_USERNAME =~ ^[A-Za-z0-9]{1,17}$ ]] || fail "game username must be 1-17 letters/numbers"
[[ $SOULFORGE_GAME_PASSWORD =~ ^[A-Za-z0-9]{8,16}$ ]] || fail "game password must be 8-16 letters/numbers"
(( ${#SOULFORGE_ADMIN_PASSWORD} >= 12 )) || fail "dashboard admin password must be at least 12 characters"
(( ${#SOULFORGE_CONTROL_SECRET} >= 32 )) || fail "control secret must be at least 32 characters"
[[ $SOULFORGE_ADMIN_PASSWORD != "$SOULFORGE_BRIDGE_SECRET" ]] || fail "dashboard and bridge secrets must be different"
[[ $SOULFORGE_CONTROL_SECRET != "$SOULFORGE_BRIDGE_SECRET" ]] || fail "control and bridge secrets must be different"
[[ $SOULFORGE_LAN_IP =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || fail "SOULFORGE_LAN_IP must be an IPv4 address"
[[ $SOULFORGE_LAN_CIDR =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] || fail "SOULFORGE_LAN_CIDR must be an IPv4 CIDR"
ip -4 address show | grep -Fq "${SOULFORGE_LAN_IP}/" || fail "SOULFORGE_LAN_IP is not assigned to this host"
[[ ${SOULFORGE_BIND_ADDRESS:-} == "$SOULFORGE_LAN_IP" ]] || fail "SOULFORGE_BIND_ADDRESS must match SOULFORGE_LAN_IP for trusted-LAN mode"

test -d runtime/source/azerothcore/.git || fail "upstream source missing; run make setup"
test -f runtime/source/azerothcore/modules/mod-soulbridge/include.sh || fail "Soulbridge is not synced; run make setup"
mkdir -p runtime/azerothcore/etc runtime/azerothcore/logs backups
docker compose config --quiet
echo "preflight: complete"

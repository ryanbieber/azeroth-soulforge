#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}

./scripts/setup-source.sh
./scripts/preflight.sh
set -a; . ./.env; set +a

cleanup_on_error() {
  echo "startup failed; stopping only the Azeroth Soulforge stack" >&2
  $COMPOSE down
}
trap cleanup_on_error ERR

$COMPOSE up --detach --build ac-database ac-db-import
$COMPOSE wait ac-db-import
./scripts/configure-realm.sh
./scripts/create-account.sh

$COMPOSE up --detach ollama
$COMPOSE exec -T ollama ollama pull "${SOULFORGE_CHAT_MODEL:-qwen3.5:4b}"
$COMPOSE up --detach --build --wait --wait-timeout 900

trap - ERR
$COMPOSE ps
echo
echo "Azeroth Soulforge is ready."
echo "Client realmlist: set realmlist ${SOULFORGE_LAN_IP}"
echo "Soul dashboard: http://127.0.0.1:${SOULFORGE_DASHBOARD_PORT:-8765}"

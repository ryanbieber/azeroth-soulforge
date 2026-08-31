#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}
MODE=${1:-up}

if [[ "$MODE" != "up" && "$MODE" != "--bots-only" ]]; then
  echo "usage: $0 [--bots-only]" >&2
  exit 2
fi

./scripts/check-host.sh
./scripts/setup-source.sh
./scripts/preflight.sh
set -a; . ./.env; set +a
./scripts/generate-dashboard-cert.sh

cleanup_on_error() {
  echo "startup failed; stopping only the Azeroth Soulforge stack" >&2
  $COMPOSE down
}
trap cleanup_on_error ERR

$COMPOSE up --detach --build ac-database ac-db-import
$COMPOSE wait ac-db-import
./scripts/configure-realm.sh
./scripts/install-module-sql.sh
./scripts/configure-server-settings.sh
./scripts/create-account.sh

$COMPOSE up --detach ollama
if [[ -n "${SOULFORGE_OPENAI_API_KEY:-}" ]]; then
  echo "OpenAI API key detected; skipping local Ollama model download."
else
  $COMPOSE exec -T ollama ollama pull "${SOULFORGE_CHAT_MODEL:-qwen3.5:4b}"
fi

if [[ "$MODE" == "--bots-only" ]]; then
  SOULFORGE_EXPLICIT_BOT_BUILD=1 ./scripts/prewarm-bots.sh
else
  ./scripts/prewarm-bots.sh
fi

if [[ "$MODE" == "--bots-only" ]]; then
  $COMPOSE down
  trap - ERR
  echo "Bot preparation is complete. Run 'make up' when you are ready to play."
  exit 0
fi

$COMPOSE up --detach --build --wait --wait-timeout 900

trap - ERR
$COMPOSE ps
echo
echo "Azeroth Soulforge is ready."
echo "Client realmlist: set realmlist ${SOULFORGE_LAN_IP}"
echo "Soulforge control plane: https://${SOULFORGE_LAN_IP}:${SOULFORGE_DASHBOARD_PORT:-8765}"

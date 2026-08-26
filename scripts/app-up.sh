#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}

./scripts/preflight.sh
$COMPOSE up --detach --build mariadb ollama soul-service

if ! ./scripts/game-up.sh; then
  echo "game servers failed; stopping infrastructure to avoid a partial app" >&2
  $COMPOSE down
  exit 1
fi

$COMPOSE ps
echo "Azeroth Soulforge is up. Soul Service: http://127.0.0.1:${SOULFORGE_PORT:-8765}/health"

#!/usr/bin/env bash
set -u

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}
status=0

./scripts/game-down.sh || status=1
if test -f .env; then
  $COMPOSE down || status=1
else
  $COMPOSE --env-file .env.example down || status=1
fi
exit "$status"

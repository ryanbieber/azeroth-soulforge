#!/usr/bin/env bash
set -u

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}
status=0

./scripts/game-down.sh || status=1
$COMPOSE down || status=1
exit "$status"

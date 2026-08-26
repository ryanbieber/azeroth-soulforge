#!/usr/bin/env bash
set -u

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}

if test -f .env; then
  $COMPOSE down
else
  $COMPOSE --env-file .env.example down
fi

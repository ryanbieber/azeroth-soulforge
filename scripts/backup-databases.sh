#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
test -f .env || { echo "missing .env" >&2; exit 1; }
set -a; . ./.env; set +a
mkdir -p backups
destination="backups/azeroth-soulforge-$(date -u +%Y%m%dT%H%M%SZ).sql"
docker compose exec -T ac-database mysqldump --user=root --password="$SOULFORGE_DB_ROOT_PASSWORD" \
  --single-transaction --routines --events --all-databases > "$destination"
echo "backup: $destination"

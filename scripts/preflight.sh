#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

fail() { echo "preflight: $*" >&2; exit 1; }

command -v docker >/dev/null || fail "docker is required"
docker compose version >/dev/null 2>&1 || fail "docker compose is required"
test -f .env || fail "copy .env.example to .env and replace both database passwords"

set -a
# The file is operator-owned and intentionally uses shell-compatible KEY=VALUE lines.
. ./.env
set +a

case "${SOULFORGE_DB_ROOT_PASSWORD:-}" in
  ""|replace-*) fail "replace SOULFORGE_DB_ROOT_PASSWORD in .env" ;;
esac
case "${SOULFORGE_DB_PASSWORD:-}" in
  ""|replace-*) fail "replace SOULFORGE_DB_PASSWORD in .env" ;;
esac

RUNTIME=${AZEROTHCORE_RUNTIME_DIR:-runtime/azerothcore}
for path in \
  "$RUNTIME/bin/authserver" \
  "$RUNTIME/bin/worldserver" \
  "$RUNTIME/etc/authserver.conf" \
  "$RUNTIME/etc/worldserver.conf" \
  "$RUNTIME/etc/modules/playerbots.conf" \
  "$RUNTIME/etc/modules/soulbridge.conf"; do
  test -f "$path" || fail "missing required runtime file: $path"
done

test -x "$RUNTIME/bin/authserver" || fail "authserver is not executable"
test -x "$RUNTIME/bin/worldserver" || fail "worldserver is not executable"
for directory in dbc maps vmaps mmaps; do
  test -d "$RUNTIME/data/$directory" || fail "missing extracted data directory: $RUNTIME/data/$directory"
done

docker compose config --quiet
echo "preflight: complete"

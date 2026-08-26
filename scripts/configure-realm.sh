#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
set -a; . ./.env; set +a

docker compose exec -T ac-database mysql --user=root --password="$SOULFORGE_DB_ROOT_PASSWORD" acore_auth \
  --execute="UPDATE realmlist SET name='Azeroth Soulforge', address='${SOULFORGE_LAN_IP}', localAddress='${SOULFORGE_LAN_IP}', localSubnetMask='255.255.255.0', port=8085 WHERE id=1;"
echo "realm: Azeroth Soulforge advertised at ${SOULFORGE_LAN_IP}:8085"

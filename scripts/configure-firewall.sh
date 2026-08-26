#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
test -f .env || { echo "copy .env.example to .env first" >&2; exit 1; }
set -a; . ./.env; set +a

if ! command -v ufw >/dev/null; then
  echo "ufw is not installed; no firewall change was needed"
  exit 0
fi
echo "This one-time step asks for your Linux password locally. It is never stored."
sudo ufw allow from "$SOULFORGE_LAN_CIDR" to any port 3724 proto tcp comment 'Azeroth Soulforge auth'
sudo ufw allow from "$SOULFORGE_LAN_CIDR" to any port 8085 proto tcp comment 'Azeroth Soulforge world'
sudo ufw allow from "$SOULFORGE_LAN_CIDR" to any port "${SOULFORGE_DASHBOARD_PORT:-8765}" proto tcp comment 'Azeroth Soulforge dashboard'
sudo ufw status

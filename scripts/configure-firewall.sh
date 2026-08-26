#!/usr/bin/env bash
set -euo pipefail

if ! command -v ufw >/dev/null; then
  echo "ufw is not installed; no firewall change was needed"
  exit 0
fi
echo "This one-time step asks for your Linux password locally. It is never stored."
sudo ufw allow from 192.168.86.0/24 to any port 3724 proto tcp comment 'Azeroth Soulforge auth'
sudo ufw allow from 192.168.86.0/24 to any port 8085 proto tcp comment 'Azeroth Soulforge world'
sudo ufw status

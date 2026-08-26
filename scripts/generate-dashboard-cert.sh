#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
set -a; . ./.env; set +a

TLS_DIR="$REPO_ROOT/.run/tls"
CERT="$TLS_DIR/dashboard.crt"
KEY="$TLS_DIR/dashboard.key"
mkdir -p "$TLS_DIR"

if test -s "$CERT" && test -s "$KEY" && \
   openssl x509 -in "$CERT" -noout -checkend 604800 >/dev/null 2>&1 && \
   openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:${SOULFORGE_LAN_IP}"; then
  exit 0
fi

openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
  -keyout "$KEY" -out "$CERT" \
  -subj "/CN=Azeroth Soulforge" \
  -addext "subjectAltName=IP:${SOULFORGE_LAN_IP},DNS:azeroth-soulforge.local,DNS:localhost,IP:127.0.0.1" \
  >/dev/null 2>&1
chmod 600 "$KEY"
chmod 644 "$CERT"
echo "Generated a private HTTPS certificate for ${SOULFORGE_LAN_IP}."

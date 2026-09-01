#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

TARGET_DIR=runtime/client-addons
mkdir -p "$TARGET_DIR"

download_verified() {
  local name=$1 url=$2 expected_sha=$3 target=$4 validator=$5
  if test -f "$target" && printf '%s  %s\n' "$expected_sha" "$target" | sha256sum --check --status; then
    chmod 0644 "$target"
    python3 "$validator" "$target" >/dev/null
    echo "client downloads: ${name} already verified"
    return
  fi

  local temporary
  temporary=$(mktemp "${TARGET_DIR}/.${name}.XXXXXX")
  curl --fail --location --retry 3 --output "$temporary" "$url"
  if ! printf '%s  %s\n' "$expected_sha" "$temporary" | sha256sum --check --status; then
    rm -f "$temporary"
    echo "${name} checksum mismatch" >&2
    exit 1
  fi
  if ! python3 "$validator" "$temporary" >/dev/null; then
    rm -f "$temporary"
    exit 1
  fi
  mv "$temporary" "$target"
  chmod 0644 "$target"
  echo "client downloads: downloaded and verified ${name}"
}

download_verified \
  "ConsolePortLK-1.5.0-rc2" \
  "https://github.com/leoaviana/ConsolePortLK/releases/download/1.5.0-rc2/ConsolePortLK-1.5.0-rc2.zip" \
  "9ee20bb1f3c5c5b8d45fcc5980a07bb90d49a707e120613453177c05fea6497f" \
  "${TARGET_DIR}/ConsolePortLK-1.5.0-rc2.zip" \
  scripts/validate-consoleport-archive.py

download_verified \
  "WoWmapperX-1.1.0-x86-aot" \
  "https://github.com/leoaviana/WoWmapperX/releases/download/1.1.0/wowmapperx-x86-aot.zip" \
  "a7b60153416584fd52ff2d465cdf35f13c13554bf197e7f0edb7a1542fe676ef" \
  "${TARGET_DIR}/WoWmapperX-1.1.0-x86-aot.zip" \
  scripts/validate-wowmapperx-archive.py

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

VERSION=1.5.0-rc2
EXPECTED_SHA=9ee20bb1f3c5c5b8d45fcc5980a07bb90d49a707e120613453177c05fea6497f
URL="https://github.com/leoaviana/ConsolePortLK/releases/download/${VERSION}/ConsolePortLK-${VERSION}.zip"
TARGET_DIR=runtime/client-addons
TARGET="${TARGET_DIR}/ConsolePortLK-${VERSION}.zip"

mkdir -p "$TARGET_DIR"
if test -f "$TARGET" && printf '%s  %s\n' "$EXPECTED_SHA" "$TARGET" | sha256sum --check --status; then
  chmod 0644 "$TARGET"
  python3 scripts/validate-consoleport-archive.py "$TARGET" >/dev/null
  echo "client addons: ConsolePortLK ${VERSION} already verified"
  exit 0
fi

TEMP=$(mktemp "${TARGET_DIR}/.ConsolePortLK-${VERSION}.XXXXXX")
trap 'rm -f "$TEMP"' EXIT
curl --fail --location --retry 3 --output "$TEMP" "$URL"
printf '%s  %s\n' "$EXPECTED_SHA" "$TEMP" | sha256sum --check --status || {
  echo "ConsolePortLK ${VERSION} checksum mismatch" >&2
  exit 1
}
python3 scripts/validate-consoleport-archive.py "$TEMP" >/dev/null
mv "$TEMP" "$TARGET"
chmod 0644 "$TARGET"
trap - EXIT
echo "client addons: downloaded and verified ConsolePortLK ${VERSION}"

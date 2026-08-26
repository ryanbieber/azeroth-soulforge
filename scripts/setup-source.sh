#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
SOURCE_DIR=runtime/source/azerothcore
CORE_SHA=9fb906bb7296212ff42fc95ff73a92aaf8554f0d
PLAYERBOTS_SHA=2f7d9f774987d0157c6a0d0cc08c40bec3db3945
PROGRESSION_SHA=84a25e6df8497d83432e61aa38557a92c156e77d

mkdir -p runtime/source runtime/azerothcore/etc runtime/azerothcore/logs backups
if ! test -d "$SOURCE_DIR/.git"; then
  git clone --branch Playerbot https://github.com/mod-playerbots/azerothcore-wotlk.git "$SOURCE_DIR"
  git -C "$SOURCE_DIR" checkout --detach "$CORE_SHA"
fi
test "$(git -C "$SOURCE_DIR" rev-parse HEAD)" = "$CORE_SHA" || {
  echo "unexpected AzerothCore revision in $SOURCE_DIR; expected $CORE_SHA" >&2; exit 1;
}

clone_module() {
  local url=$1 target=$2 revision=$3
  if ! test -d "$target/.git"; then
    git clone "$url" "$target"
    git -C "$target" checkout --detach "$revision"
  fi
  test "$(git -C "$target" rev-parse HEAD)" = "$revision" || {
    echo "unexpected module revision in $target; expected $revision" >&2; exit 1;
  }
}
clone_module https://github.com/mod-playerbots/mod-playerbots.git "$SOURCE_DIR/modules/mod-playerbots" "$PLAYERBOTS_SHA"
clone_module https://github.com/azerothcore/mod-progression-system.git "$SOURCE_DIR/modules/mod-progression-system" "$PROGRESSION_SHA"

TARGET="$SOURCE_DIR/modules/mod-soulbridge"
test "$TARGET" = "runtime/source/azerothcore/modules/mod-soulbridge"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a mod-soulbridge/. "$TARGET/"
echo "source: pinned upstreams verified and Soulbridge synced"

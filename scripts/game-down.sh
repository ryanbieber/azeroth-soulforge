#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

stop_server() {
  local name=$1
  local pid_file="$REPO_ROOT/.run/$name.pid"
  test -f "$pid_file" || { echo "$name is not running"; return; }

  local pid
  pid=$(cat "$pid_file")
  case "$pid" in
    ""|*[!0-9]*) echo "invalid PID file for $name; remove $pid_file manually" >&2; return 1 ;;
  esac

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "$name was already stopped"
    return
  fi

  local command
  command=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)
  case "$command" in
    *"$name"*) ;;
    *) echo "refusing to stop PID $pid: it does not look like $name" >&2; return 1 ;;
  esac

  kill -TERM "$pid"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name did not stop after 5 seconds; leaving PID $pid for manual review" >&2
    return 1
  fi
  rm -f "$pid_file"
  echo "$name stopped"
}

stop_server worldserver
stop_server authserver

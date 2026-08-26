#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
set -a
. ./.env
set +a

RUNTIME=${AZEROTHCORE_RUNTIME_DIR:-runtime/azerothcore}
RUN_DIR="$REPO_ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$LOG_DIR"

is_running() {
  local pid_file=$1
  test -f "$pid_file" || return 1
  local pid
  pid=$(cat "$pid_file")
  kill -0 "$pid" 2>/dev/null
}

start_server() {
  local name=$1
  local binary=$2
  local config=$3
  local pid_file="$RUN_DIR/$name.pid"
  if is_running "$pid_file"; then
    echo "$name is already running (PID $(cat "$pid_file"))"
    return
  fi

  (
    cd "$RUNTIME"
    nohup "$binary" -c "$config" >"$LOG_DIR/$name.log" 2>&1 &
    echo $! >"$pid_file"
  )
  sleep 1
  is_running "$pid_file" || {
    echo "$name failed to stay running; inspect $LOG_DIR/$name.log" >&2
    return 1
  }
  echo "$name started (PID $(cat "$pid_file"))"
}

start_server authserver ./bin/authserver ./etc/authserver.conf
start_server worldserver ./bin/worldserver ./etc/worldserver.conf

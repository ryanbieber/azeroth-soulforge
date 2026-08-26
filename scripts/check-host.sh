#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fail() { echo "host check: $*" >&2; exit 1; }
missing=()
for command in git make openssl curl docker ip python3; do
  command -v "$command" >/dev/null 2>&1 || missing+=("$command")
done
if ((${#missing[@]})); then
  echo "host check: missing required tools: ${missing[*]}" >&2
  echo "Ubuntu/Debian basics: sudo apt install git make openssl curl python3 iproute2" >&2
  echo "Install Docker Engine + Compose from https://docs.docker.com/engine/install/" >&2
  exit 1
fi

[[ $(uname -s) == Linux ]] || fail "Linux is required for this Docker deployment"
case $(uname -m) in x86_64|aarch64) ;; *) fail "supported CPU architectures are x86_64 and aarch64" ;; esac
docker info >/dev/null 2>&1 || fail "Docker is not running or this user cannot access /var/run/docker.sock"
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' || fail "Python 3.8 or newer is required for host setup scripts"
compose_version=$(docker compose version --short 2>/dev/null) || fail "Docker Compose v2 is required"
compose_major=${compose_version%%.*}
[[ $compose_major =~ ^[0-9]+$ ]] && ((compose_major >= 2)) || fail "Docker Compose v2 or newer is required"

memory_kib=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
disk_kib=$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')
((memory_kib >= 6 * 1024 * 1024)) || fail "at least 6 GiB RAM is required; 12 GiB or more is recommended"
((disk_kib >= 15 * 1024 * 1024)) || fail "at least 15 GiB free disk is required; 40 GiB or more is recommended"

echo "host check: Linux $(uname -m), Docker Compose ${compose_version}, $((memory_kib / 1024 / 1024)) GiB RAM, $((disk_kib / 1024 / 1024)) GiB free"
echo "host check: application compilers and libraries are provided by pinned containers"

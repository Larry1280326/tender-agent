#!/usr/bin/env bash
# stop.sh — stop the tender-agent stack (FastAPI backend + Next.js frontend).
#
# Usage:
#   ./scripts/stop.sh               # stop backend + frontend
#   ./scripts/stop.sh backend       # stop only the backend
#   ./scripts/stop.sh frontend      # stop only the frontend

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

log() { printf '%s\n' "$*"; }

# Kill the process group headed by $pid (uv/npm spawn children: uvicorn, next).
kill_group() {
  local pid="$1" sig="$2"
  kill "-$sig" -- "-$pid" 2>/dev/null || kill "-$sig" "$pid" 2>/dev/null || true
  # Belt-and-braces for the non-setsid fallback: signal direct children too.
  pkill "-$sig" -P "$pid" 2>/dev/null || true
}

stop_service() {
  local name="$1" pid_file="$2" port="$3"
  local stopped=0

  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log "▶ Stopping ${name} (pid ${pid}) ..."
      kill_group "$pid" TERM
      # Wait up to 10s for a graceful shutdown before force-killing.
      local i=0
      while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 10 ]; do
        sleep 1
        i=$((i + 1))
      done
      if kill -0 "$pid" 2>/dev/null; then
        log "  ${name} did not stop gracefully — force killing"
        kill_group "$pid" KILL
      fi
      log "  ✓ ${name} stopped"
      stopped=1
    else
      log "${name}: pid file present but process ${pid:-?} not running"
    fi
    rm -f "$pid_file"
  fi

  # Fallback for processes started by hand (no pid file): clear the known port.
  if [ "$stopped" = "0" ] && command -v fuser >/dev/null 2>&1; then
    log "${name}: no live pid — cleaning up anything on :${port} ..."
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
}

case "${1:-all}" in
  all)      stop_service "backend"  "$BACKEND_PID_FILE"  "$BACKEND_PORT"
            stop_service "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PORT" ;;
  backend)  stop_service "backend"  "$BACKEND_PID_FILE"  "$BACKEND_PORT" ;;
  frontend) stop_service "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PORT" ;;
  *)        log "usage: $0 [backend|frontend]"; exit 1 ;;
esac

log "Done."

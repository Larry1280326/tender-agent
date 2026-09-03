#!/usr/bin/env bash
# start.sh — start the tender-agent stack (FastAPI backend + Next.js frontend).
#
# Usage:
#   ./scripts/start.sh               # start backend + frontend
#   ./scripts/start.sh backend       # start only the backend
#   ./scripts/start.sh frontend      # start only the frontend
#
# Environment overrides:
#   HOST=0.0.0.0 BACKEND_PORT=8000 FRONTEND_PORT=3000 PROD=1 ./scripts/start.sh
#
# Runtime state (pid files + logs) lives under <repo>/.run/ (gitignored).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
PROD="${PROD:-0}"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

log() { printf '%s\n' "$*"; }

is_running() {
  local pid
  pid="$(cat "$1" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Wait until something answers on the port. curl exits 0 on any HTTP response
# (including 404), so this means "server is listening" rather than "200 OK".
wait_for_port() {
  local port="$1" name="$2" attempts="${3:-40}"
  local i=0
  while [ "$i" -lt "$attempts" ]; do
    if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${port}/" 2>/dev/null; then
      log "  ✓ ${name} ready on http://localhost:${port}"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  log "  ⚠ ${name} did not respond on :${port} within ${attempts}s — see ${LOG_DIR}/${name}.log"
  return 1
}

start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    log "backend already running (pid $(cat "$BACKEND_PID_FILE"))"
    return 0
  fi

  log "▶ Starting backend on http://localhost:${BACKEND_PORT} ..."
  local args=(run uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT")
  if [ "$PROD" != "1" ]; then
    args+=(--reload)
  fi

  cd "$ROOT_DIR/backend"
  # setsid puts the process in its own group so stop.sh can kill uvicorn + any
  # reload worker with a single "kill -- -PID".
  setsid uv "${args[@]}" > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$BACKEND_PID_FILE"
  log "  backend pid $(cat "$BACKEND_PID_FILE")"
  wait_for_port "$BACKEND_PORT" "backend" || true
}

start_frontend() {
  if is_running "$FRONTEND_PID_FILE"; then
    log "frontend already running (pid $(cat "$FRONTEND_PID_FILE"))"
    return 0
  fi

  log "▶ Starting frontend on http://localhost:${FRONTEND_PORT} ..."
  local args=()
  if [ "$PROD" = "1" ]; then
    log "  (PROD mode: assuming 'npm run build' has already been run)"
    args=(run start -- -p "$FRONTEND_PORT")
  else
    args=(run dev -- -p "$FRONTEND_PORT")
  fi

  cd "$ROOT_DIR/frontend"
  setsid npm "${args[@]}" > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$FRONTEND_PID_FILE"
  log "  frontend pid $(cat "$FRONTEND_PID_FILE")"
  wait_for_port "$FRONTEND_PORT" "frontend" || true
}

case "${1:-all}" in
  all)      start_backend; start_frontend ;;
  backend)  start_backend ;;
  frontend) start_frontend ;;
  *)        log "usage: $0 [backend|frontend]"; exit 1 ;;
esac

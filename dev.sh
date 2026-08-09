#!/usr/bin/env bash
# Start Postgres/Redis (Docker), Django API, Celery worker, and Vite frontend.
# Usage (from repo root):  ./dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BACKEND_PORT=8000
FRONTEND_PORT=5173

BACKEND_PID=""
CELERY_PID=""
FRONTEND_PID=""

# Free a TCP listen port (macOS / Linux). Kills whatever is bound to it.
free_port() {
  local port="$1"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    # Linux fallback
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return 0
  else
    echo "Warning: cannot free port $port (no lsof/fuser)."
    return 0
  fi

  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Port $port in use — stopping PID(s): $(echo "$pids" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.4
  # Force if still listening
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.2
  fi
}

cleanup() {
  echo ""
  echo "Stopping…"
  for pid in "$FRONTEND_PID" "$CELERY_PID" "$BACKEND_PID"; do
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  echo "Done."
}
trap cleanup EXIT INT TERM

if [[ ! -d "$ROOT/backend/.venv" ]]; then
  echo "Missing backend/.venv — create it first:"
  echo "  cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "$ROOT/backend/.env" ]]; then
  echo "Missing backend/.env — copy from example and edit:"
  echo "  cp backend/.env.example backend/.env"
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies…"
  (cd "$ROOT/frontend" && npm install)
fi

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Warning: docker not found — ensure Postgres/Redis are already running."
    return 0
  fi

  if docker info >/dev/null 2>&1; then
    return 0
  fi

  # Common on macOS: Docker CLI points at Colima, but Colima is stopped.
  if command -v colima >/dev/null 2>&1; then
    echo "Docker daemon not running — starting Colima…"
    colima start
    return 0
  fi

  echo "Docker daemon is not running."
  echo "Start Docker Desktop, or Colima:  colima start"
  echo "Then re-run:  ./dev.sh"
  exit 1
}

ensure_docker

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Starting Postgres + Redis…"
  docker compose up -d
fi

# shellcheck disable=SC1091
source "$ROOT/backend/.venv/bin/activate"

echo "Running migrations…"
(cd "$ROOT/backend" && python manage.py migrate --noinput)

echo "Freeing ports ${BACKEND_PORT} and ${FRONTEND_PORT} if needed…"
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

echo "Starting Django → http://127.0.0.1:${BACKEND_PORT}"
(cd "$ROOT/backend" && python manage.py runserver "127.0.0.1:${BACKEND_PORT}") &
BACKEND_PID=$!

echo "Starting Celery worker…"
(
  cd "$ROOT/backend"
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
  celery -A config worker -l info --pool=solo
) &
CELERY_PID=$!

echo "Starting frontend → http://127.0.0.1:${FRONTEND_PORT}"
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT") &
FRONTEND_PID=$!

echo ""
echo "All services running. Press Ctrl+C to stop."
echo "  App:     http://127.0.0.1:${FRONTEND_PORT}/"
echo "  API docs: http://127.0.0.1:${BACKEND_PORT}/api/docs/"
echo ""

wait

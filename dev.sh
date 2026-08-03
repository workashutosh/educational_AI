#!/usr/bin/env bash
# Start Postgres/Redis (Docker), Django API, Celery worker, and Vite frontend.
# Usage (from repo root):  ./dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BACKEND_PID=""
CELERY_PID=""
FRONTEND_PID=""

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

echo "Starting Django → http://127.0.0.1:8000"
(cd "$ROOT/backend" && python manage.py runserver) &
BACKEND_PID=$!

echo "Starting Celery worker…"
(
  cd "$ROOT/backend"
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
  celery -A config worker -l info --pool=solo
) &
CELERY_PID=$!

echo "Starting frontend → http://127.0.0.1:5173"
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port 5173) &
FRONTEND_PID=$!

echo ""
echo "All services running. Press Ctrl+C to stop."
echo "  App:     http://127.0.0.1:5173/"
echo "  API docs: http://127.0.0.1:8000/api/docs/"
echo ""

wait

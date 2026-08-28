#!/usr/bin/env bash
#
# Start RetailIQ (API + web) and keep both in the foreground.
#
# Run this in its own terminal tab and leave it open. Ctrl-C stops both cleanly.
# Foreground on purpose: a backgrounded server dies with whatever shell launched
# it, which is exactly the wrong surprise five minutes before a demo.
#
#   ./run.sh              start both
#   ./run.sh --backend    API only
#   ./run.sh --frontend   web only
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT=8000
WEB_PORT=5173

bold()  { printf "\033[1m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
dim()   { printf "\033[2m%s\033[0m\n" "$1"; }

WANT_BACKEND=1
WANT_FRONTEND=1
case "${1:-}" in
  --backend)  WANT_FRONTEND=0 ;;
  --frontend) WANT_BACKEND=0 ;;
  "") ;;
  *) red "Unknown option: $1"; exit 2 ;;
esac

# ── preflight ────────────────────────────────────────────────────────────────
if [[ $WANT_BACKEND == 1 && ! -x "$BACKEND/.venv/bin/python" ]]; then
  red "Backend virtualenv missing."
  dim  "  cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev,trends]'"
  exit 1
fi
if [[ $WANT_FRONTEND == 1 && ! -d "$FRONTEND/node_modules" ]]; then
  red "Frontend dependencies missing."
  dim  "  cd frontend && npm install"
  exit 1
fi

free_port() {
  local port=$1
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    dim "Port $port is busy; stopping $(echo "$pids" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 2
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    # shellcheck disable=SC2086
    [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
  fi
}

PIDS=()
cleanup() {
  echo
  dim "Stopping…"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  green "Stopped."
}
trap cleanup EXIT INT TERM

echo
bold "RetailIQ"
dim  "$ROOT"
echo

# ── backend ──────────────────────────────────────────────────────────────────
if [[ $WANT_BACKEND == 1 ]]; then
  free_port "$API_PORT"
  dim "Starting API on :$API_PORT …"
  (
    cd "$BACKEND"
    exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
  ) &
  PIDS+=($!)

  # Model weights load lazily, so the API answers /health quickly even on a cold
  # cache. Thirty seconds is generous for the import graph alone.
  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$API_PORT/health" 2>/dev/null; then
      green "  API ready  →  http://localhost:$API_PORT/docs"
      break
    fi
    if [[ $i == 30 ]]; then
      red "  API failed to start. Scroll up for the traceback."
      exit 1
    fi
    sleep 1
  done
fi

# ── frontend ─────────────────────────────────────────────────────────────────
if [[ $WANT_FRONTEND == 1 ]]; then
  free_port "$WEB_PORT"
  dim "Starting web on :$WEB_PORT …"
  (
    cd "$FRONTEND"
    exec npm run dev -- --port "$WEB_PORT" --strictPort
  ) &
  PIDS+=($!)

  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT" 2>/dev/null; then
      green "  Web ready  →  http://localhost:$WEB_PORT"
      break
    fi
    [[ $i == 30 ]] && red "  Web failed to start."
    sleep 1
  done
fi

echo
bold "Open  →  http://localhost:$WEB_PORT"
dim  "Ctrl-C to stop both."
echo

wait

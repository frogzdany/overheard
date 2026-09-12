#!/usr/bin/env bash
# Start the Python engine (app.py with FastAPI on :8765) and the Next.js web
# dev server together. Ctrl-C stops both cleanly.
#
# Flags:
#   --port=NNNN       engine port (default 8765)
#   --web-pm=pnpm     web package manager (default npm)
#
# Logs are tee'd to ./.dev-logs/ for tailing.

set -euo pipefail
cd "$(dirname "$0")"

ENGINE_PORT=8765
WEB_PM="npm"

for arg in "$@"; do
  case "$arg" in
    --headless|--no-window) ;;   # accepted + ignored: the engine is always headless
    --port=*) ENGINE_PORT="${arg#*=}" ;;
    --web-pm=*) WEB_PM="${arg#*=}" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v "$WEB_PM" >/dev/null 2>&1; then
  echo "$WEB_PM not found, falling back to npm" >&2
  WEB_PM="npm"
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "error: .venv/bin/python not found. Activate or create the venv first." >&2
  exit 1
fi

if [ ! -d "web/node_modules" ]; then
  echo "web/node_modules missing — installing…" >&2
  (cd web && "$WEB_PM" install)
fi

mkdir -p .dev-logs
ENGINE_LOG=".dev-logs/engine.log"
WEB_LOG=".dev-logs/web.log"

ENGINE_PID=""
WEB_PID=""

cleanup() {
  echo
  echo "stopping…"
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
  [ -n "$ENGINE_PID" ] && kill "$ENGINE_PID" 2>/dev/null || true
  wait 2>/dev/null
  echo "done."
}
trap cleanup INT TERM EXIT

# Engine — always headless; the UI is the Next.js app on :3000.
ENGINE_ARGS=("app.py" "--no-window" "--port=$ENGINE_PORT")

echo "▲ engine  → http://127.0.0.1:$ENGINE_PORT  (log: $ENGINE_LOG)"
.venv/bin/python "${ENGINE_ARGS[@]}" 2>&1 | tee "$ENGINE_LOG" &
ENGINE_PID=$!

# Wait for engine to answer /health (up to 15s) before starting web. Fail
# loudly if it never comes up — otherwise we'd point the web UI at a dead
# engine and the user would chase phantom "cannot reach engine" errors.
HEALTHY=0
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$ENGINE_PORT/health" >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  # The engine pipeline is backgrounded; if it already died, stop waiting.
  if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

if [ "$HEALTHY" -ne 1 ]; then
  echo "error: engine did not answer /health on :$ENGINE_PORT within 15s." >&2
  echo "       check $ENGINE_LOG (port in use? missing API keys? import error)" >&2
  exit 1
fi

# Web
echo "▲ web     → http://localhost:3000  (log: $WEB_LOG)"
(cd web && "$WEB_PM" run dev) 2>&1 | tee "$WEB_LOG" &
WEB_PID=$!

echo
echo "Both running. Ctrl-C to stop."
wait

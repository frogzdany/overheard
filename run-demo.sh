#!/usr/bin/env bash
# Start the full Overheard demo stack: hands, optionally the Trigger.dev dev
# worker, the Python engine, and the Next.js web app — in that order, each
# waited on for health before the next one starts. Ctrl-C stops everything.
#
# The root .env is loaded into this script's environment first, so EXECUTOR,
# HANDS_URL, HANDS_PORT, and every key in it apply to every child process;
# command-line flags override whatever .env set.
#
# Logs are tee'd to ./.dev-logs/ for tailing.
#
# Run ./run-demo.sh --help for the full flag list.

set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(pwd)"

usage() {
  cat <<'EOF'
Usage: ./run-demo.sh [options]

Starts, in order: hands, the Trigger.dev dev worker (only with
--executor=trigger), the engine, then the web app — waiting for each one's
health before starting the next. Loads the root .env first; flags override it.

Replay mode (mutually exclusive; default: --transcript):
  --transcript[=PATH]  Replay a scripted JSONL transcript through the engine.
                        Default PATH: fixtures/meeting-transcript.jsonl
  --file[=PATH]        Stream a WAV file through the engine (real STT key
                        required — not compatible with --mock).
                        Default PATH: fixtures/meeting-clip.wav
  --live                Real live capture (mic + system audio). Needs the
                        audio helper built and Screen Recording permission.

Options:
  --executor=local|trigger  Override EXECUTOR for hands + engine (default:
                            whatever .env sets, else "local"). "trigger" also
                            starts the Trigger.dev dev worker.
  --speed=N                 Set REPLAY_SPEED (0 = no waiting, replay fixture
                            timestamps as fast as possible).
  --port=N                   Engine port (default 8765). Also sets
                            NEXT_PUBLIC_ENGINE_URL and the hands ENGINE_URL.
  --hands-port=N             Hands port (default 8790). Also sets HANDS_URL
                            for the engine.
  --mock                     LLM_PROVIDER=mock and empty AMBIGUOUS_API_KEY /
                            EXA_API_KEY for hands — the whole loop runs
                            keyless.
  --no-web                   Don't start the Next.js web app.
  --no-dev                   Don't set ENGINE_DEV=1 (dev-only routes off).
  -h, --help                  Show this help and exit.

Logs: ./.dev-logs/{hands,trigger,engine,web}.log
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
done

# ---------------------------------------------------------------------------
# Defaults, then load .env, then apply flag overrides on top.
# ---------------------------------------------------------------------------
ENGINE_PORT=8765
TRANSCRIPT_PATH="fixtures/meeting-transcript.jsonl"
FILE_PATH="fixtures/meeting-clip.wav"
REPLAY_MODE="transcript"
MODE_FLAG_COUNT=0
MOCK=0
NO_WEB=0
NO_DEV=0

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  echo "loaded .env"
else
  echo "no .env found in $REPO_ROOT — using defaults/flags only" >&2
fi

# Safe defaults for anything .env didn't set (nounset-safe: ${VAR:=default}
# only triggers on unset-or-empty, never errors under `set -u`).
: "${EXECUTOR:=local}"
: "${HANDS_PORT:=8790}"
: "${REPLAY_SPEED:=1.0}"
: "${LLM_PROVIDER:=}"
: "${AMBIGUOUS_API_KEY:=}"
: "${EXA_API_KEY:=}"
: "${OPENAI_API_KEY:=}"
: "${OPENROUTER_API_KEY:=}"
: "${DEEPGRAM_API_KEY:=}"
: "${TRIGGER_SECRET_KEY:=}"
: "${TRIGGER_PROJECT_REF:=}"
: "${ENGINE_TOKEN:=}"

for arg in "$@"; do
  case "$arg" in
    --transcript)
      REPLAY_MODE="transcript"; MODE_FLAG_COUNT=$((MODE_FLAG_COUNT + 1)) ;;
    --transcript=*)
      REPLAY_MODE="transcript"; TRANSCRIPT_PATH="${arg#*=}"
      MODE_FLAG_COUNT=$((MODE_FLAG_COUNT + 1)) ;;
    --file)
      REPLAY_MODE="file"; MODE_FLAG_COUNT=$((MODE_FLAG_COUNT + 1)) ;;
    --file=*)
      REPLAY_MODE="file"; FILE_PATH="${arg#*=}"
      MODE_FLAG_COUNT=$((MODE_FLAG_COUNT + 1)) ;;
    --live)
      REPLAY_MODE="live"; MODE_FLAG_COUNT=$((MODE_FLAG_COUNT + 1)) ;;
    --executor=*) EXECUTOR="${arg#*=}" ;;
    --speed=*) REPLAY_SPEED="${arg#*=}" ;;
    --port=*) ENGINE_PORT="${arg#*=}" ;;
    --hands-port=*) HANDS_PORT="${arg#*=}" ;;
    --mock) MOCK=1 ;;
    --no-web) NO_WEB=1 ;;
    --no-dev) NO_DEV=1 ;;
    -h|--help) ;; # handled above
    *)
      echo "run-demo.sh: unknown argument: $arg" >&2
      usage >&2
      exit 2 ;;
  esac
done

if [ "$MODE_FLAG_COUNT" -gt 1 ]; then
  echo "run-demo.sh: pass only one of --transcript / --file / --live" >&2
  exit 2
fi

case "$EXECUTOR" in
  local|trigger) ;;
  *) echo "run-demo.sh: --executor must be local or trigger (got: $EXECUTOR)" >&2; exit 2 ;;
esac
case "$ENGINE_PORT" in
  ''|*[!0-9]*) echo "run-demo.sh: --port must be numeric (got: $ENGINE_PORT)" >&2; exit 2 ;;
esac
case "$HANDS_PORT" in
  ''|*[!0-9]*) echo "run-demo.sh: --hands-port must be numeric (got: $HANDS_PORT)" >&2; exit 2 ;;
esac

if [ "$MOCK" -eq 1 ]; then
  LLM_PROVIDER="mock"
  AMBIGUOUS_API_KEY=""
  EXA_API_KEY=""
fi

if [ "$NO_DEV" -eq 1 ]; then
  ENGINE_DEV=0
else
  ENGINE_DEV=1
fi

HANDS_URL="http://127.0.0.1:${HANDS_PORT}"
ENGINE_URL="http://127.0.0.1:${ENGINE_PORT}"
NEXT_PUBLIC_ENGINE_URL="$ENGINE_URL"

export EXECUTOR HANDS_PORT REPLAY_SPEED LLM_PROVIDER AMBIGUOUS_API_KEY EXA_API_KEY \
       ENGINE_DEV HANDS_URL ENGINE_URL NEXT_PUBLIC_ENGINE_URL

# Never print key values — only the names of the ones that are non-empty.
KEY_VARS="OPENAI_API_KEY OPENROUTER_API_KEY DEEPGRAM_API_KEY AMBIGUOUS_API_KEY EXA_API_KEY TRIGGER_SECRET_KEY ENGINE_TOKEN"
SET_KEYS=""
for k in $KEY_VARS; do
  v="${!k}"
  [ -n "$v" ] && SET_KEYS="$SET_KEYS $k"
done
echo "keys:${SET_KEYS}"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
echo "== preflight =="

if [ ! -x ".venv/bin/python" ]; then
  echo "error: .venv/bin/python not found. Create it first:" >&2
  echo "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [ ! -d "hands/node_modules" ]; then
  echo "hands/node_modules missing — installing…" >&2
  (cd hands && npm install)
fi

if [ "$NO_WEB" -eq 0 ] && [ ! -d "web/node_modules" ]; then
  echo "web/node_modules missing — installing…" >&2
  (cd web && npm install)
fi

if [ "$REPLAY_MODE" = "live" ] && [ ! -x "audio-helper/.build/release/MeetAudioHelper" ]; then
  echo "audio helper missing — building…" >&2
  ./build-audio-helper.sh
fi

check_port_free() {
  port="$1"; label="$2"
  if lsof -i ":$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "error: port $port ($label) is already in use:" >&2
    lsof -i ":$port" -sTCP:LISTEN >&2 || true
    exit 1
  fi
}
check_port_free "$ENGINE_PORT" "engine"
check_port_free "$HANDS_PORT" "hands"
[ "$NO_WEB" -eq 0 ] && check_port_free 3000 "web"

if [ "$EXECUTOR" = "trigger" ]; then
  if [ -z "$TRIGGER_SECRET_KEY" ] || [ -z "$TRIGGER_PROJECT_REF" ]; then
    echo "error: --executor=trigger requires TRIGGER_SECRET_KEY and TRIGGER_PROJECT_REF" >&2
    echo "       (set them in .env or export them before running)" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
mkdir -p .dev-logs
HANDS_LOG=".dev-logs/hands.log"
TRIGGER_LOG=".dev-logs/trigger.log"
ENGINE_LOG=".dev-logs/engine.log"
WEB_LOG=".dev-logs/web.log"

HANDS_PID=""
TRIGGER_PID=""
ENGINE_PID=""
WEB_PID=""
CHILD_PIDS=""

# Job control gives each backgrounded pipeline its own process group (its
# PGID becomes resolvable via `ps -o pgid=` off any member's PID), which lets
# cleanup() kill a whole pipeline — including any grandchildren npx/tsx/next
# spawn — via `kill -- -$PGID` instead of just the tracked PID.
set -m

kill_by_cwd_pattern() {
  # Sweep any process matching a name pattern, but only if its cwd is under
  # this repo — so we never touch an unrelated process on the machine.
  pattern="$1"
  for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/{print substr($0,2); exit}')
    case "$cwd" in
      "$REPO_ROOT"|"$REPO_ROOT"/*) kill "$pid" 2>/dev/null || true ;;
    esac
  done
}

report_port_stopped() {
  name="$1"; port="$2"; i=0
  while [ "$i" -lt 6 ]; do
    lsof -i ":$port" -sTCP:LISTEN >/dev/null 2>&1 || { echo "  $name: stopped (port $port free)"; return; }
    sleep 0.5
    i=$((i + 1))
  done
  echo "  $name: still holding port $port"
}

report_pid_stopped() {
  name="$1"; pid="$2"; i=0
  while [ "$i" -lt 6 ]; do
    kill -0 "$pid" 2>/dev/null || { echo "  $name: stopped"; return; }
    sleep 0.5
    i=$((i + 1))
  done
  echo "  $name: still running (pid $pid)"
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "stopping…"

  for pid in $CHILD_PIDS; do
    pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$pgid" ] && kill -TERM -- "-$pgid" 2>/dev/null || true
  done
  for pid in $CHILD_PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  sleep 1

  # Belt-and-suspenders: catch anything that escaped its process group
  # (e.g. a detached grandchild spawned by npx), scoped to this repo.
  kill_by_cwd_pattern "tsx src/server.ts"
  kill_by_cwd_pattern "trigger.dev"
  kill_by_cwd_pattern "app.py --no-window"
  kill_by_cwd_pattern "next dev"

  wait 2>/dev/null || true

  echo "status:"
  [ -n "$HANDS_PID" ] && report_port_stopped "hands" "$HANDS_PORT"
  [ -n "$TRIGGER_PID" ] && report_pid_stopped "trigger" "$TRIGGER_PID"
  [ -n "$ENGINE_PID" ] && report_port_stopped "engine" "$ENGINE_PORT"
  [ -n "$WEB_PID" ] && report_port_stopped "web" 3000
  echo "done."
}
trap cleanup INT TERM EXIT

wait_for_http() {
  # $1 url  $2 pid-to-watch  $3 label  $4 log  $5 timeout-seconds
  url="$1"; pid="$2"; label="$3"; log="$4"; timeout="${5:-30}"
  i=0; max=$((timeout * 2))
  while [ "$i" -lt "$max" ]; do
    curl -s -o /dev/null "$url" 2>/dev/null && return 0
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "error: $label exited before answering $url — see $log" >&2
      exit 1
    fi
    sleep 0.5
    i=$((i + 1))
  done
  echo "error: $label did not answer $url within ${timeout}s — see $log" >&2
  exit 1
}

wait_for_trigger_ready() {
  log="$1"; timeout="${2:-25}"
  i=0; max=$((timeout * 2))
  while [ "$i" -lt "$max" ]; do
    grep -qi "ready" "$log" 2>/dev/null && return 0
    sleep 0.5
    i=$((i + 1))
  done
  echo "warning: trigger.dev dev worker did not log \"ready\" within ${timeout}s — continuing (see $log)" >&2
}

echo "== starting services =="

echo "-> hands    ${HANDS_URL}  (log: $HANDS_LOG)"
(cd hands && npx tsx src/server.ts) 2>&1 | tee "$HANDS_LOG" &
HANDS_PID=$!
CHILD_PIDS="$CHILD_PIDS $HANDS_PID"
wait_for_http "${HANDS_URL}/health" "$HANDS_PID" "hands" "$HANDS_LOG" 30

if [ "$EXECUTOR" = "trigger" ]; then
  echo "-> trigger  npx trigger.dev@latest dev  (log: $TRIGGER_LOG)"
  (cd hands && npx trigger.dev@latest dev) 2>&1 | tee "$TRIGGER_LOG" &
  TRIGGER_PID=$!
  CHILD_PIDS="$CHILD_PIDS $TRIGGER_PID"
  wait_for_trigger_ready "$TRIGGER_LOG" 25
fi

ENGINE_ARGS=(".venv/bin/python" "app.py" "--no-window" "--port=${ENGINE_PORT}")
case "$REPLAY_MODE" in
  transcript) ENGINE_ARGS+=("--from-transcript" "$TRANSCRIPT_PATH") ;;
  file) ENGINE_ARGS+=("--from-file" "$FILE_PATH") ;;
  live) : ;; # no replay flag — real live capture
esac
echo "-> engine   ${ENGINE_URL}  mode=$REPLAY_MODE  (log: $ENGINE_LOG)"
("${ENGINE_ARGS[@]}") 2>&1 | tee "$ENGINE_LOG" &
ENGINE_PID=$!
CHILD_PIDS="$CHILD_PIDS $ENGINE_PID"
wait_for_http "${ENGINE_URL}/health" "$ENGINE_PID" "engine" "$ENGINE_LOG" 30

if [ "$NO_WEB" -eq 0 ]; then
  echo "-> web      http://localhost:3000  (log: $WEB_LOG)"
  (cd web && npm run dev) 2>&1 | tee "$WEB_LOG" &
  WEB_PID=$!
  CHILD_PIDS="$CHILD_PIDS $WEB_PID"
  wait_for_http "http://localhost:3000" "$WEB_PID" "web" "$WEB_LOG" 30
fi

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
REPLAY_DESC="$REPLAY_MODE"
case "$REPLAY_MODE" in
  transcript) REPLAY_DESC="transcript ($TRANSCRIPT_PATH, speed=$REPLAY_SPEED)" ;;
  file) REPLAY_DESC="file ($FILE_PATH)" ;;
  live) REPLAY_DESC="live capture" ;;
esac

echo
echo "================================================================"
echo " overheard demo is up"
echo "================================================================"
[ "$NO_WEB" -eq 0 ] && echo "  web       http://localhost:3000"
echo "  engine    ${ENGINE_URL}/health"
echo "  hands     ${HANDS_URL}/health"
if [ "$EXECUTOR" = "trigger" ]; then
  echo "  trigger   https://cloud.trigger.dev/projects/v3/${TRIGGER_PROJECT_REF}"
fi
echo "  replay    $REPLAY_DESC"
echo "  executor  $EXECUTOR"
echo
echo "Ctrl-C stops everything."
echo

wait

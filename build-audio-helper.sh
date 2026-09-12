#!/usr/bin/env bash
# Build + ad-hoc sign the Swift ScreenCaptureKit audio helper.
#
# Usage:
#   ./build-audio-helper.sh              # release build (default)
#   ./build-audio-helper.sh --debug      # debug build (faster, includes symbols)
#   ./build-audio-helper.sh --clean      # wipe build artifacts first
#   ./build-audio-helper.sh --test       # build, sign, then run a 3s capture smoke test
#
# Ad-hoc signing (`codesign --sign -`) gives the binary a stable hash so macOS
# remembers the Screen Recording permission grant across rebuilds. Costs nothing.

set -euo pipefail
cd "$(dirname "$0")/audio-helper"

CONFIG="release"
CLEAN=0
RUN_TEST=0

for arg in "$@"; do
  case "$arg" in
    --debug) CONFIG="debug" ;;
    --release) CONFIG="release" ;;
    --clean) CLEAN=1 ;;
    --test) RUN_TEST=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if ! command -v swift >/dev/null 2>&1; then
  echo "error: swift not found on PATH. Install Xcode or Command Line Tools." >&2
  exit 1
fi

if [ "$CLEAN" -eq 1 ]; then
  echo "▶ swift package clean"
  swift package clean
  rm -rf .build
fi

echo "▶ swift build -c $CONFIG"
swift build -c "$CONFIG"

BIN=".build/$CONFIG/MeetAudioHelper"
if [ ! -x "$BIN" ]; then
  echo "error: build produced no binary at $BIN" >&2
  exit 1
fi

echo "▶ ad-hoc signing $BIN"
codesign --force --sign - --entitlements entitlements.plist "$BIN"

echo "▶ verifying signature"
codesign -dv "$BIN" 2>&1 | sed 's/^/  /'

# Resolve into the absolute path the Python wrapper expects (release symlink
# may differ from the Swift Package Manager arch-specific path).
REAL=$(readlink -f "$BIN" 2>/dev/null || python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$BIN")
echo
echo "✔ built: $REAL"
echo
echo "Next: grant Screen Recording permission on first capture, then:"
echo "  .venv/bin/python -m engine.swift_audio --seconds 3 --out test.wav"

if [ "$RUN_TEST" -eq 1 ]; then
  echo
  echo "▶ running 3s capture smoke test"
  cd ..
  if [ ! -x ".venv/bin/python" ]; then
    echo "error: .venv/bin/python not found; cannot run smoke test." >&2
    exit 1
  fi
  .venv/bin/python -m engine.swift_audio --seconds 3 --out test.wav
fi

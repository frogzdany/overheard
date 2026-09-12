#!/bin/bash
# make-clip.sh — synthesize fixtures/meeting-clip.wav from meeting-transcript.jsonl
# using the macOS built-in `say` command, so the Overheard demo does not depend
# on live audio or a real recording.
#
# Requires macOS (`say`, `afconvert`, `afinfo`). Prefers `ffmpeg` for
# concatenating the per-utterance clips with silence gaps; falls back to
# `sox`, then to a small pure stdlib (wave module) Python concatenator if
# neither is installed.
#
# Usage:
#   ./make-clip.sh
#   VOICE_ANA="Samantha" VOICE_DANIEL="Daniel" ./make-clip.sh   # override voices
#
# Output: fixtures/meeting-clip.wav — 16 kHz mono 16-bit PCM WAV, ~3 minutes.
# This file is gitignored (`*.wav` in the repo root .gitignore); only this
# script ships.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

TRANSCRIPT="meeting-transcript.jsonl"
SPEAKERS="speakers.json"
OUT="meeting-clip.wav"

# Voices, chosen from `say -v '?'` on this machine: one female-sounding, one
# male-sounding English voice. Ana -> Samantha (en_US, female). Daniel -> the
# "Daniel" voice (en_GB, male) — a happy coincidence that the voice name
# matches the character's name.
VOICE_ANA="${VOICE_ANA:-Samantha}"
VOICE_DANIEL="${VOICE_DANIEL:-Daniel}"

for bin in say afconvert afinfo python3; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "error: required tool '$bin' not found (this script is macOS-only)" >&2
    exit 1
  }
done

for v in "$VOICE_ANA" "$VOICE_DANIEL"; do
  if ! say -v '?' | awk '{print $1}' | grep -qx "$v"; then
    echo "error: voice '$v' is not installed. Run: say -v '?'  and pick two installed English voices." >&2
    exit 1
  fi
done

if command -v ffmpeg >/dev/null 2>&1; then
  CONCAT_TOOL="ffmpeg"
elif command -v sox >/dev/null 2>&1; then
  CONCAT_TOOL="sox"
else
  CONCAT_TOOL="python"
  echo "note: neither ffmpeg nor sox found; falling back to a pure-Python (wave module) concatenator" >&2
fi

echo "Using voices: Ana=$VOICE_ANA, Daniel=$VOICE_DANIEL"
echo "Using concat tool: $CONCAT_TOOL"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/overheard-clip.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

TRANSCRIPT="$TRANSCRIPT" SPEAKERS="$SPEAKERS" VOICE_ANA="$VOICE_ANA" \
VOICE_DANIEL="$VOICE_DANIEL" WORKDIR="$WORKDIR" OUT="$OUT" CONCAT_TOOL="$CONCAT_TOOL" \
python3 - <<'PYEOF'
import json
import os
import shutil
import subprocess
import sys
import wave

TRANSCRIPT = os.environ["TRANSCRIPT"]
SPEAKERS_PATH = os.environ["SPEAKERS"]
VOICE_ANA = os.environ["VOICE_ANA"]
VOICE_DANIEL = os.environ["VOICE_DANIEL"]
WORKDIR = os.environ["WORKDIR"]
OUT = os.environ["OUT"]
CONCAT_TOOL = os.environ["CONCAT_TOOL"]

SR = 16000
MIN_GAP = 0.35  # seconds, floor for a natural pause between speaker turns
TAIL_SILENCE = 0.6  # seconds of silence appended at the very end

speakers = json.load(open(SPEAKERS_PATH))
lines = [json.loads(l) for l in open(TRANSCRIPT) if l.strip()]


def voice_for(speaker_label: str) -> str:
    name = speakers.get(speaker_label, speaker_label)
    if name == "Ana":
        return VOICE_ANA
    if name == "Daniel":
        return VOICE_DANIEL
    return VOICE_ANA


def afinfo_duration(path: str) -> float:
    res = subprocess.run(["afinfo", path], capture_output=True, text=True, check=True)
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("estimated duration:"):
            return float(line.split(":", 1)[1].strip().split()[0])
    raise RuntimeError(f"could not parse afinfo duration for {path}")


def make_silence(path: str, dur: float) -> None:
    dur = max(dur, 0.01)
    if CONCAT_TOOL == "ffmpeg":
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
                "-t", f"{dur:.3f}",
                "-c:a", "pcm_s16le",
                path,
            ],
            check=True,
        )
    elif CONCAT_TOOL == "sox":
        subprocess.run(
            ["sox", "-n", "-r", str(SR), "-c", "1", "-b", "16", path,
             "synth", f"{dur:.3f}", "sine", "0", "vol", "0"],
            check=True,
        )
    else:
        n_frames = int(dur * SR)
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(b"\x00\x00" * n_frames)


def concat_wavs(paths, out_path: str) -> None:
    if CONCAT_TOOL == "ffmpeg":
        list_path = os.path.join(WORKDIR, "concat.txt")
        with open(list_path, "w") as f:
            for p in paths:
                f.write(f"file '{os.path.abspath(p)}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", out_path],
            check=True,
        )
    elif CONCAT_TOOL == "sox":
        subprocess.run(["sox"] + list(paths) + [out_path], check=True)
    else:
        with wave.open(out_path, "w") as out_w:
            out_w.setnchannels(1)
            out_w.setsampwidth(2)
            out_w.setframerate(SR)
            for p in paths:
                with wave.open(p, "r") as in_w:
                    out_w.writeframes(in_w.readframes(in_w.getnframes()))


print(f"Synthesizing {len(lines)} utterances with `say`...")

segments = []  # ordered list of wav paths (speech + silence) to concatenate
elapsed = 0.0

for i, obj in enumerate(lines):
    text = obj["text"]
    target_t = float(obj["t"])
    voice = voice_for(obj["speaker"])

    aiff_path = os.path.join(WORKDIR, f"line_{i:03d}.aiff")
    wav_path = os.path.join(WORKDIR, f"line_{i:03d}.wav")

    subprocess.run(["say", "-v", voice, "-o", aiff_path, text], check=True)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", aiff_path, wav_path],
        check=True,
    )
    dur = afinfo_duration(wav_path)

    if i > 0:
        # Insert a silence gap so this line starts roughly at its scripted
        # timestamp (falling back to a minimum natural pause if the
        # synthesized speech already ran past that point).
        gap = max(target_t - elapsed, MIN_GAP)
        gap_path = os.path.join(WORKDIR, f"gap_{i:03d}.wav")
        make_silence(gap_path, gap)
        segments.append(gap_path)
        elapsed += gap

    segments.append(wav_path)
    elapsed += dur

tail_path = os.path.join(WORKDIR, "gap_tail.wav")
make_silence(tail_path, TAIL_SILENCE)
segments.append(tail_path)

combined_path = os.path.join(WORKDIR, "combined.wav")
concat_wavs(segments, combined_path)

# Final normalization pass to guarantee 16 kHz mono 16-bit PCM, per the
# format afconvert produces natively.
subprocess.run(
    ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", combined_path, OUT],
    check=True,
)

print(f"Wrote {OUT}")
PYEOF

echo
echo "Done. Verifying output:"
ls -lh "$OUT"
afinfo "$OUT"

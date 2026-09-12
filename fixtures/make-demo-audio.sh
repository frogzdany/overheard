#!/bin/bash
# make-demo-audio.sh — synthesize fixtures/demo-meeting.{mp3,wav} from
# meeting-transcript.jsonl using the ElevenLabs CLI (text-to-dialogue), so the
# Overheard demo has a natural-sounding two-speaker recording to play through
# a real meeting app (mp3) and to feed the engine directly via --from-file
# (16 kHz mono 16-bit PCM wav).
#
# Unlike make-clip.sh (macOS `say`, used for fast keyless iteration), this
# script calls the ElevenLabs API and therefore costs credits and requires
# `npx --yes @elevenlabs/cli@latest` to already be logged in
# (`... auth status`).
#
# The spoken text is copied verbatim from meeting-transcript.jsonl — no words
# added, no audio tags — because expected-actions.json quotes it exactly and
# the suggestion brain is tuned against that wording.
#
# Usage:
#   ./make-demo-audio.sh
#   ANA_VOICE_ID="..." DANIEL_VOICE_ID="..." ./make-demo-audio.sh   # override voices
#
# Outputs (both overwritten idempotently on every run):
#   fixtures/demo-meeting.mp3 — full quality (mp3_44100_128), for playing in a
#     meeting app (QuickTime/Chrome) during a screen recording.
#   fixtures/demo-meeting.wav — 16 kHz mono 16-bit PCM, for
#     --from-file fixtures/demo-meeting.wav.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

TRANSCRIPT="meeting-transcript.jsonl"
OUT_MP3="demo-meeting.mp3"
OUT_WAV="demo-meeting.wav"

CLI=(npx --yes @elevenlabs/cli@latest)

# Voices picked from `... voices search --format json` — premade/professional
# English voices with a conversational description. See fixtures/README.md
# for the full picks and rationale.
ANA_VOICE_ID="${ANA_VOICE_ID:-kdmDKE6EkgrWrrykO9Qt}"       # Alexandra - Conversational and Real
DANIEL_VOICE_ID="${DANIEL_VOICE_ID:-cjVigY5qzO86Huf0OWal}" # Eric - Smooth, Trustworthy

MODEL_ID="${MODEL_ID:-eleven_v3}"
CHAR_LIMIT="${CHAR_LIMIT:-1800}" # stay safely under text-to-dialogue's ~2000 char/request cap

for bin in ffmpeg afinfo python3; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "error: required tool '$bin' not found" >&2
    exit 1
  }
done

echo "Checking ElevenLabs CLI auth..."
"${CLI[@]}" auth status >/dev/null || {
  echo "error: elevenlabs CLI is not logged in. Run: npx --yes @elevenlabs/cli@latest auth login" >&2
  exit 1
}

echo "Using voices: Ana=$ANA_VOICE_ID, Daniel=$DANIEL_VOICE_ID, model=$MODEL_ID"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/overheard-demo-audio.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

# 1) Split the 38 transcript lines into consecutive chunks that stay under
#    CHAR_LIMIT total characters, and write each chunk as a text-to-dialogue
#    request body JSON file (inputs: [{text, voice_id}, ...], model_id).
echo "Chunking $TRANSCRIPT (limit ${CHAR_LIMIT} chars/request)..."
NUM_CHUNKS=$(
  TRANSCRIPT="$TRANSCRIPT" WORKDIR="$WORKDIR" CHAR_LIMIT="$CHAR_LIMIT" \
  ANA_VOICE_ID="$ANA_VOICE_ID" DANIEL_VOICE_ID="$DANIEL_VOICE_ID" MODEL_ID="$MODEL_ID" \
  python3 - <<'PYEOF'
import json
import os

transcript = os.environ["TRANSCRIPT"]
workdir = os.environ["WORKDIR"]
limit = int(os.environ["CHAR_LIMIT"])
ana_id = os.environ["ANA_VOICE_ID"]
daniel_id = os.environ["DANIEL_VOICE_ID"]
model_id = os.environ["MODEL_ID"]

speakers = json.load(open("speakers.json"))

def voice_for(label):
    name = speakers.get(label, label)
    if name == "Daniel":
        return daniel_id
    return ana_id  # Ana, or fall back to Ana's voice for any other label

lines = [json.loads(l) for l in open(transcript) if l.strip()]

chunks = []
cur = []
cur_chars = 0
for line in lines:
    tlen = len(line["text"])
    if cur and cur_chars + tlen > limit:
        chunks.append(cur)
        cur = []
        cur_chars = 0
    cur.append(line)
    cur_chars += tlen
if cur:
    chunks.append(cur)

for i, chunk in enumerate(chunks):
    body = {
        "inputs": [
            {"text": line["text"], "voice_id": voice_for(line["speaker"])}
            for line in chunk
        ],
        "model_id": model_id,
    }
    path = os.path.join(workdir, f"chunk_{i:02d}.json")
    with open(path, "w") as f:
        json.dump(body, f)

print(len(chunks))
PYEOF
)

echo "Split into $NUM_CHUNKS chunk(s)."

# 2) Render each chunk with text-to-dialogue convert.
CHUNK_MP3S=()
for i in $(seq 0 $((NUM_CHUNKS - 1))); do
  n=$(printf "%02d" "$i")
  json_path="$WORKDIR/chunk_${n}.json"
  mp3_path="$WORKDIR/chunk_${n}.mp3"
  echo "Rendering chunk $n via text-to-dialogue convert..."
  "${CLI[@]}" text-to-dialogue convert \
    --json "$(cat "$json_path")" \
    --output-format mp3_44100_128 \
    -o "$mp3_path" \
    -q
  CHUNK_MP3S+=("$mp3_path")
done

# 3) Concatenate chunks in order with ffmpeg (stream copy, same codec/params
#    across chunks so this is lossless).
CONCAT_LIST="$WORKDIR/concat.txt"
: > "$CONCAT_LIST"
for f in "${CHUNK_MP3S[@]}"; do
  echo "file '$f'" >> "$CONCAT_LIST"
done

echo "Concatenating ${#CHUNK_MP3S[@]} chunk(s) into $OUT_MP3..."
ffmpeg -y -v error -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$OUT_MP3"

# 4) Downmix/convert to 16 kHz mono 16-bit PCM WAV for --from-file.
echo "Converting to 16 kHz mono 16-bit PCM WAV ($OUT_WAV)..."
ffmpeg -y -v error -i "$OUT_MP3" -ar 16000 -ac 1 -sample_fmt s16 -c:a pcm_s16le "$OUT_WAV"

echo
echo "Done. Verifying output:"
ls -lh "$OUT_MP3" "$OUT_WAV"
echo "--- $OUT_MP3 ---"
afinfo "$OUT_MP3"
echo "--- $OUT_WAV ---"
afinfo "$OUT_WAV"

echo
echo "ElevenLabs usage (character_count / character_limit):"
"${CLI[@]}" user subscription get --format json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  {d.get(\"character_count\")} / {d.get(\"character_limit\")}')" \
  || echo "  (could not fetch usage)"

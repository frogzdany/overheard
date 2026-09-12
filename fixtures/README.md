# Overheard demo fixtures

Scripted, repeatable 3-minute "meeting" used to tune and demo Overheard's
suggestion brain without needing live audio or a real recording. Two
fictional speakers — **Ana** (product lead) and **Daniel** (engineer), both
at the fictional company **Atlas Labs** — discuss launching **Project
Atlas** next quarter. The only outside company mentioned is the fictional
vendor **Acme Corp**. Five, and only five, obvious commitments are scripted
in, one per Overheard action kind (`create_task`, `schedule_followup`,
`draft_message`, `create_doc`, `lookup`); everything else is realistic
filler with nothing actionable in it.

## Files

- **`meeting-script.md`** — the human-readable script: full dialogue with
  timestamps, speaker names, and the five commitment moments called out
  inline. Read this first to understand what the meeting is about and where
  the five moments live.

- **`meeting-transcript.jsonl`** — the machine-readable transcript, one JSON
  object per spoken line:
  `{"t": <seconds_float>, "speaker": "Speaker 0"|"Speaker 1", "text": "..."}`.
  38 lines, timestamps span 0.0–188.95s (consistent with the ~3-minute clip).
  `Speaker 0` = Ana, `Speaker 1` = Daniel.

- **`speakers.json`** — maps diarization labels to names:
  `{"Speaker 0": "Ana", "Speaker 1": "Daniel"}`.

- **`expected-actions.json`** — the five actions Overheard's suggestion
  brain is expected to produce from this meeting, in the engine's action
  contract shape:
  ```json
  { "kind": "...", "title": "...", "evidence": ["<verbatim quote from the transcript>", ...], "args": { ... } }
  ```
  `args` shape per kind: `create_task {title, assignee, due}`,
  `schedule_followup {title, when, attendees}` (ISO `when`, next Tuesday
  relative to 2026-09-12 at 10:00 local — `2026-09-15T10:00:00`),
  `draft_message {to, body}`, `create_doc {title, body}`,
  `lookup {query}`. Every `evidence` entry is copied verbatim from
  `meeting-transcript.jsonl` so it can be matched exactly. **This file is
  the tuning target for the brain** — run the brain against the transcript
  and diff its output against this file.

- **`make-clip.sh`** — macOS script that synthesizes `meeting-clip.wav` from
  `meeting-transcript.jsonl` using the built-in `say` command (voices:
  Samantha for Ana, Daniel for Daniel — see "Regenerating the clip" below).
  This is what ships; the WAV itself is not committed (see below).

- **`meeting-clip.wav`** (generated, gitignored) — the synthesized audio,
  16 kHz mono 16-bit PCM, ~3:12 long. Matches the root `.gitignore`'s
  `*.wav` rule, so it is never committed — regenerate it locally with
  `make-clip.sh` whenever you need it.

- **`make-demo-audio.sh`** — script that synthesizes `demo-meeting.mp3` and
  `demo-meeting.wav` from `meeting-transcript.jsonl` using the ElevenLabs CLI
  (`npx --yes @elevenlabs/cli@latest`, logged in via `... auth status`) and
  its `text-to-dialogue convert` endpoint — natural, higher-quality
  multi-speaker TTS than `make-clip.sh`'s `say`-based clip, at the cost of
  ElevenLabs credits. See "Regenerating the ElevenLabs demo audio" below.

- **`demo-meeting.mp3`** (generated, not committed) — full-quality
  (`mp3_44100_128`) rendering of the same 38-line transcript, ~2:51 long.
  Meant to be *played back* through a real meeting app (QuickTime, Chrome
  tab, etc.) while screen-recording a live Overheard capture — see "Intended
  usage" below. Note: the root `.gitignore` only excludes `*.wav`, not
  `*.mp3` — this file is a generated artifact and should not be committed by
  hand.

- **`demo-meeting.wav`** (generated, gitignored via the root `*.wav` rule) —
  the same audio downmixed to 16 kHz mono 16-bit PCM for
  `--from-file fixtures/demo-meeting.wav`, matching the format
  `engine/file_audio.py::FileAudioSource` expects. Regenerate locally with
  `make-demo-audio.sh`.

## Regenerating the clip

```sh
cd fixtures
./make-clip.sh
```

This picks two installed macOS voices — one female-sounding (`Samantha`,
en_US) for Ana, one male-sounding (`Daniel`, en_GB) for Daniel — synthesizes
each line of `meeting-transcript.jsonl` individually with `say -o` to AIFF,
converts each to 16 kHz mono 16-bit PCM with `afconvert`, concatenates them
in order with silence gaps sized to land each line close to its scripted
timestamp (via `ffmpeg`, falling back to `sox`, falling back to a pure
stdlib `wave`-module concatenator if neither is installed), and writes
`fixtures/meeting-clip.wav`. It prints `afinfo` on the result so you can
confirm the format and duration.

Override the voices if needed (e.g. if this repo moves to a machine without
`Samantha`/`Daniel` installed — check with `say -v '?'`):

```sh
VOICE_ANA="Kathy" VOICE_DANIEL="Fred" ./make-clip.sh
```

Last generated locally: 191.78s (~3:12), 16000 Hz, 1 channel, Int16 PCM WAV.

## Regenerating the ElevenLabs demo audio

```sh
cd fixtures
./make-demo-audio.sh
```

Requires the ElevenLabs CLI logged in (`npx --yes @elevenlabs/cli@latest auth
status`). The script reads `meeting-transcript.jsonl` and `speakers.json`,
splits the 38 lines into consecutive chunks that stay under
`text-to-dialogue`'s ~2,000-character-per-request limit (2 chunks for this
transcript), renders each chunk with `text-to-dialogue convert` (model
`eleven_v3`, one `{text, voice_id}` input per transcript line — the spoken
text is copied verbatim, no words added and no audio tags, since
`expected-actions.json` quotes the transcript exactly), concatenates the
chunks in order with `ffmpeg -f concat` into `demo-meeting.mp3`, then
downmixes to 16 kHz mono 16-bit PCM with `ffmpeg -ar 16000 -ac 1
-sample_fmt s16` into `demo-meeting.wav`. It prints `afinfo` on both outputs
and the account's `character_count`/`character_limit` from
`... user subscription get` (no other account details).

**Voices chosen** (from `... voices search --format json`, premade/professional
English voices with a conversational description — see step 1 of the task
for the selection criteria):

| Role | Voice | Voice ID | Notes |
|---|---|---|---|
| Ana | Alexandra — Conversational and Real | `kdmDKE6EkgrWrrykO9Qt` | professional category, American, female, "conversational" use-case, described as youthful/authentic/down-to-earth |
| Daniel | Eric — Smooth, Trustworthy | `cjVigY5qzO86Huf0OWal` | premade category, American, male, "conversational" use-case, smooth 40s tenor, "perfect for agentic use cases" |

Override the voices if needed (e.g. if these voice IDs are ever removed from
the account, or to try alternates):

```sh
ANA_VOICE_ID="..." DANIEL_VOICE_ID="..." ./make-demo-audio.sh
```

Last generated locally: 170.66s (~2:51), full-quality mp3 (44.1 kHz mono,
128 kbps) plus a 16 kHz mono 16-bit PCM wav of the same length. Total
ElevenLabs usage for the transcript's ~2,394 characters of spoken text was
~2,400 characters against a 10,000-character pay-as-you-go allowance (see
`... user subscription get --format json` for current usage; no other
account details are printed).

## Intended usage

These fixtures exist so the suggestion brain (and the demo) don't depend on
live audio or a microphone:

- **`fixtures/demo-meeting.mp3`** (ElevenLabs, natural-sounding) — for a
  real, screen-recorded demo of the live capture path: open it in QuickTime
  Player or a Chrome tab and, in Overheard's session-start dialog, pick that
  app (QuickTime/Chrome) as the audio source, then hit play in the other app
  while recording. This exercises the actual system-audio capture path, not
  a file replay, so it's the closest thing to a real meeting without one.

- **`--from-file fixtures/demo-meeting.wav`** (ElevenLabs, natural-sounding)
  or **`--from-file fixtures/meeting-clip.wav`** (macOS `say`, keyless/fast)
  stream the synthesized clip through the real speech-to-text path, exactly
  as a live meeting would be ingested — useful for testing the full audio →
  transcript → suggestions pipeline end to end without opening another app.
  The WAV is read by `engine/file_audio.py::FileAudioSource`, which presents
  the same surface to the STT worker as the Swift helper does and paces
  50 ms 16 kHz linear16 chunks in wall-clock time. System stream only — no
  mic is opened. Needs a real STT key (`DEEPGRAM_API_KEY` or, with
  `STT_PROVIDER=openai`, `OPENAI_API_KEY`); without one the engine prints why
  and exits 2.

- **`--from-transcript fixtures/meeting-transcript.jsonl`** (implemented)
  replays the scripted lines directly (with their timestamps) without going
  through STT — useful for fast iteration on the suggestion brain itself, and
  for a demo that can't risk a flaky STT pass. It opens a `transcriptOnly`
  session and pushes each line through the same entry point as
  `POST /sessions/{id}/transcript/inject`, paced by `t` divided by
  `REPLAY_SPEED` (env, default `1.0`; `0` replays instantly). After the last
  line it forces one actions tick, then leaves the session open so the normal
  45 s timer keeps running and the web UI can attach.

The suggestions produced from either path should match
`expected-actions.json` (five actions, one per kind, matching
kind/args/evidence). A fast, keyless loop for checking that:

```sh
ENGINE_DEV=1 LLM_PROVIDER=mock REPLAY_SPEED=0 \
  .venv/bin/python app.py --no-window --port=8766 \
  --from-transcript fixtures/meeting-transcript.jsonl
curl -s localhost:8766/sessions/<id>/actions
```

`LLM_PROVIDER=mock` returns canned suggestions (it exercises the pipeline, not
the brain). Swap in `LLM_PROVIDER=openai` with `OPENAI_API_KEY` set to score the
real brain against `expected-actions.json`.

## ElevenLabs audio quality check

`demo-meeting.wav` was validated end to end through the real STT path:

```sh
STT_PROVIDER=openai ENGINE_DEV=1 LLM_PROVIDER=mock \
  OVERHEARD_DATA_DIR=/tmp/overheard-audio-check \
  .venv/bin/python app.py --no-window --port=8768 \
  --from-file fixtures/demo-meeting.wav
```

run from the repo root (root `.env` has the OpenAI key) for the first ~86s
of playback, then diffing the session's `dg_final` transcript lines in the
data dir's `logs/session-*.jsonl` against `meeting-transcript.jsonl`. Result:
word accuracy over the first 8 scripted lines (spanning the `create_task`
moment) was effectively 100% — every word was transcribed correctly, no
lines were garbled or dropped. The only differences were cosmetic sentence
segmentation: OpenAI's STT sometimes splits one transcript line into two
`dg_final` events, or renders a mid-sentence comma as a period + capital
letter (e.g. "Sounds good, solid progress..." → "Sounds good. Solid
progress..."), and lowercased one proper noun ("Project Atlas" →
"project Atlas"). Note: `STT_PROVIDER=openai` does not diarize, so all lines
in this run were attributed to "Speaker 0" — a known engine/provider
limitation, unrelated to the audio itself.

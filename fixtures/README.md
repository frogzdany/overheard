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

## Intended usage

These fixtures exist so the suggestion brain (and the demo) don't depend on
live audio or a microphone:

- **`--from-file fixtures/meeting-clip.wav`** (implemented) streams the
  synthesized clip through the real speech-to-text path, exactly as a live
  meeting would be ingested — useful for testing the full audio → transcript →
  suggestions pipeline end to end. The WAV is read by
  `engine/file_audio.py::FileAudioSource`, which presents the same surface to
  the Deepgram worker as the Swift helper does and paces 50 ms 16 kHz linear16
  chunks in wall-clock time. System stream only — no mic is opened. Needs a
  real `DEEPGRAM_API_KEY`; without one the engine prints why and exits 2.

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

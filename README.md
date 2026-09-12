# Overheard

Overheard is a macOS agent that sits inside a live meeting instead of a separate chat
window. It listens to the meeting's audio, transcribes it with speakers, and every 45
seconds proposes concrete actions it heard: create a task, schedule a follow-up, draft a
message, create a doc, or look something up, each with a rationale and the exact quote it
came from. You edit, approve, or reject each card. Approved actions run as durable
background jobs and land as real, attributed items in a shared workspace under the
Overheard coworker identity.

## What it does

1. Sign in and start a session by picking the app or window to capture. macOS asks for
   Screen Recording permission the first time.
2. Overheard listens to two live audio streams, system audio and your microphone, and
   transcribes both with speaker labels in real time.
3. Every 45 seconds it looks at the recent transcript and proposes actions it heard:
   create a task, schedule a follow-up, draft a message, create a doc, or look something
   up, each with a rationale and the verbatim quote it came from.
4. Each proposal shows up as a card, in the dashboard's Actions tab or inline in the
   CopilotKit sidebar. You edit any field, then approve or reject it; nothing runs without
   an explicit yes.
5. An approved action becomes a durable background job: it dispatches to hands, lands as a
   real item in the workspace authored by the Overheard coworker (or comes back as an
   Exa-sourced answer for a lookup), and the card updates from running to succeeded or
   failed.

## Architecture

```
+--------------------------+
| ears                     |
| Swift ScreenCaptureKit   |
| system audio             |
| sounddevice (microphone) |
+--------------------------+
             |
             | WS: transcript events
             v
+------------------------------+
| brain + UI                    |
| Python engine (FastAPI)       |
|  bus, session store, DB       |
|  Deepgram / OpenAI STT        |
|  llm.py (any-llm) actions     |
|  worker, every 45s            |
|                                |
| Next.js dashboard             |
|  transcript, ActionsTab       |
|  CopilotKit sidebar           |
+------------------------------+
             |
             | HTTP (HANDS_URL): prepare / execute / approve / cancel
             v
+--------------------------+
| hands                    |
| Node service             |
|  EXECUTOR=local|trigger  |
|  /execute   /prepare     |
|  /runs/{id}/approve      |
|  /runs/{id}/cancel       |
+--------------------------+
             |
             | HTTP (ENGINE_URL): PATCH .../actions/{id}/status
             ^  (running, then succeeded or failed; flows back to brain + UI)
             |
        +----+----+
        |         |
        v         v
  Ambiguous MCP   Exa
  tasks, calendar answer()
  chat, docs      (lookup, cited)
```

The engine is the ears and most of the brain: it captures or replays audio, transcribes
it, runs the suggestion brain, and serves the dashboard over REST and a per-session
WebSocket. The dashboard (the rest of the brain, plus the UI) reads and writes that same
engine API. Hands is a separate Node service the engine calls over HTTP: with
`EXECUTOR=local` (the default) the engine only calls hands on approval, `POST
${HANDS_URL}/execute`; with `EXECUTOR=trigger` the engine calls `POST
${HANDS_URL}/prepare` as soon as an action is suggested, and approval or rejection
completes a Trigger.dev waitpoint instead. Either way hands reports status back to the
engine, and dispatches the approved action to Ambiguous (tasks, calendar events, chat
messages, docs) or to Exa for a lookup, then writes the answer into an Ambiguous doc.

Every action is one JSON object, carried unchanged from the engine's suggestion through
approval to the finished result:

```jsonc
{
  "id": "a7f3",
  "sessionId": "s1",
  "kind": "create_task" | "schedule_followup" | "draft_message" | "create_doc" | "lookup",
  "title": "Send Ana the Q3 architecture diagram",
  "rationale": "Ana asked for it and you said you'd send it today",
  "evidence": ["...verbatim transcript quote..."],
  "confidence": 0.82,
  "tool": "ambiguous.tasks.create",
  "args": { "title": "...", "assignee": "Ana", "due": "2026-09-15" },
  "status": "suggested",
  "approvedBy": null,
  "runId": null,
  "resultUrl": null
}
```

`status` moves through `suggested`, `approved`, `running`, and ends at `succeeded`,
`failed`, `rejected`, or `expired` (an unactioned suggestion expires after 30 minutes).

## Sponsor technologies

| Sponsor | What it does in Overheard | Where in the code | How to turn it on |
|---|---|---|---|
| OpenAI | Runs the suggestion brain's structured output; optional live transcription | `engine/llm.py`, `engine/workers/openai_stt.py` | Default: set `OPENAI_API_KEY` (`LLM_PROVIDER=openai`). Realtime STT: `STT_PROVIDER=openai` |
| CopilotKit | Sidebar chat, shared readable state (transcript, actions), one `renderAndWaitForResponse` approval card per action kind, served over its AG-UI runtime route | `web/src/components/sessions/CopilotBridge.tsx`, `web/src/app/api/copilotkit/route.ts`, `web/src/app/layout.tsx` | Set `OPENAI_API_KEY` in `web/.env.local`; the sidebar renders regardless but errors on send without it |
| Ambiguous AI | MCP connector approved actions dispatch to; Overheard runs as its own coworker identity, so every item is attributed to it | `hands/src/connectors/ambiguous.ts` | `npx ambiguous auth signup --name "Overheard"`, then set `AMBIGUOUS_API_KEY` |
| Trigger.dev | `execute-action` task; a waitpoint holds each run at "awaiting approval" until the engine completes it | `hands/src/trigger/execute-action.ts`, `hands/src/server.ts` | Set `EXECUTOR=trigger` on both engine and hands, plus `TRIGGER_SECRET_KEY` and `TRIGGER_PROJECT_REF`; run `npx trigger.dev@latest dev` |
| Auth0 | SPA login; every approval is stamped with the signed-in user as `approvedBy` | `web/src/lib/auth.ts`, `engine/server.py` (approve route) | Set `NEXT_PUBLIC_AUTH0_DOMAIN`, `NEXT_PUBLIC_AUTH0_CLIENT_ID`, `NEXT_PUBLIC_AUTH0_AUDIENCE` |
| Exa | Answers a `lookup` action with a cited answer, written into an Ambiguous doc | `hands/src/connectors/exa.ts` | Set `EXA_API_KEY`; without it lookups return a mock answer |
| Mozilla.ai | `any-llm` is the provider-agnostic client the brain runs on; `any-guardrail` screens drafted text for prompt injection | `engine/llm.py`, `engine/guardrail.py` | `any-llm` is always on; guardrail needs `GUARDRAIL=on` plus the `any-guardrail[huggingface]` extra |
| OpenRouter | Fallback LLM provider behind the same `any-llm` interface | `engine/llm.py` | Set `LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY` |

## What existed before the hackathon and what was built today

Before today:

- The Swift ScreenCaptureKit helper that captures system audio.
- The Deepgram dual-stream worker (system audio plus microphone, each its own WebSocket)
  with a reconnect watchdog.
- The Python engine's session lifecycle, event bus, per-session WebSocket, and SQLite
  session index.
- The Next.js dashboard's transcript view.
- Auth0 SPA login.
- The "questions asked to me" dedupe-and-refine gate that the actions worker reuses.

Built today:

- The actions worker and its per-kind action schema.
- `engine/llm.py`, the `any-llm` wrapper the brain, summary, insight, and titler workers
  all now call, with OpenAI as the default provider and OpenRouter as a fallback.
- The action routes and the `suggested_actions` table: approve, reject, status callback,
  and chat-initiated action creation.
- `ActionCard` and `ActionsTab` in the dashboard.
- The CopilotKit sidebar: shared readable state and one generative approval card per
  action kind.
- The hands service itself: local and Trigger.dev execution, the Ambiguous MCP connector,
  and the Exa connector.
- The replay flags (`--from-transcript`, `--from-file`) and the `fixtures/` demo meeting.
- The OpenAI Realtime STT worker, behind `STT_PROVIDER=openai`.
- The any-guardrail prompt-injection screen for drafted text.

## Run it

Prerequisites:

- macOS 13 (Ventura) or later
- Xcode Command Line Tools (`xcode-select --install`), needed for `swift`
- Python 3.12
- Node 22
- Screen Recording permission for live capture (macOS prompts on first use)

### One-command demo

`run-demo.sh` starts hands, the engine, and the web app together (in that order, waiting
for each one's health before starting the next), loading the root `.env` first and
tearing everything down cleanly on Ctrl-C. It's the fastest way to reproduce the keyless
path below or switch into `--live` / `--executor=trigger` for the real path:

```bash
./run-demo.sh --mock --transcript --speed=0   # keyless demo, replayed as fast as possible
./run-demo.sh                                 # real keys from .env, scripted transcript replay
./run-demo.sh --live                          # real live capture (needs the audio helper built)
./run-demo.sh --executor=trigger              # also starts the Trigger.dev dev worker
```

Run `./run-demo.sh --help` for the full flag list (`--file`, `--port`, `--hands-port`,
`--no-web`, `--no-dev`, …). Logs are tee'd to `.dev-logs/`.

### Keyless demo path

No API keys, no microphone, no real workspace. Runs the whole loop against fixtures and
mock connectors. (`./run-demo.sh --mock --transcript --speed=0` does this in one step —
see above.)

```bash
# Engine, replaying the scripted fixture meeting instead of live audio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
ENGINE_DEV=1 LLM_PROVIDER=mock REPLAY_SPEED=0 \
  .venv/bin/python app.py --no-window --port=8765 \
  --from-transcript fixtures/meeting-transcript.jsonl

# Hands, local mode with no connector keys set: mock Ambiguous and Exa results
cd hands && npm install && npm run dev

# Web, with the Auth0 vars left blank in web/.env.local: no sign-in gate
cd web && npm install && cp .env.example .env.local && npm run dev
```

Open `http://localhost:3000`, open the session, and watch the five scripted commitments
turn into action cards on the Actions tab.

### Real path

Fill in real keys and run against a live meeting and a real workspace.

```bash
# Engine: DEEPGRAM_API_KEY and OPENAI_API_KEY (or OPENROUTER_API_KEY) in .env
# Hands: AMBIGUOUS_API_KEY and EXA_API_KEY in hands/.env
npx ambiguous auth signup --name "Overheard"     # provisions the coworker identity

# Optional: Trigger.dev waitpoint flow instead of approve-then-run
#   set EXECUTOR=trigger, TRIGGER_SECRET_KEY, TRIGGER_PROJECT_REF on engine and hands
(cd hands && npx trigger.dev@latest dev)
(cd hands && EXECUTOR=trigger npm run dev)

# Web: fill NEXT_PUBLIC_AUTH0_* in web/.env.local for real login

# Build the audio helper once, then run everything (engine on :8765, web on :3000)
./build-audio-helper.sh
./run-dev.sh
# or, to also start hands (and the Trigger.dev worker in trigger mode) in one command:
./run-demo.sh --live [--executor=trigger]
```

> **One ScreenCaptureKit client per code identity.** Build the audio helper once and do
> not run two copies of it. macOS ties the Screen Recording grant to the binary's code
> signature, and a second client under the same identity fights the first for the capture
> stream: you get silence, not an error.

## Known limitations

- The any-guardrail prompt-injection screen has false positives; it is advisory only (a
  flagged action still publishes, with a lowered confidence and a warning) and off by
  default.
- The OpenAI Realtime STT path is verified live against `fixtures/meeting-clip.wav`
  (`STT_PROVIDER=openai ... --from-file`), not yet against a live meeting. It speaks the
  GA Realtime shape — `session.update` with a `type: "transcription"` session and
  everything under `audio.input`; the old beta shape (`transcription_session.update`
  behind `OpenAI-Beta: realtime=v1`) is switched off server-side and now closes the
  socket with `invalid_request_error.beta_api_shape_disabled`. The 16 kHz capture is
  upsampled to 24 kHz because `audio.input.format` accepts nothing else.
- `OPENAI_STT_MODEL` defaults to `gpt-live-transcribe`, which rejects `turn_detection`
  and therefore never closes an item: it streams deltas and emits no final. The worker
  substitutes `gpt-transcribe` (and says so in the status line) for that model and for
  `gpt-realtime-whisper`; set `OPENAI_STT_MODEL` to any VAD-capable Realtime
  transcription model to override.
- Realtime line breaks come from server VAD alone, so `silence_duration_ms` is what sets
  transcript line length. The synthesized fixture clip leaves almost no silence between
  lines: at 500 ms the first 95 s came back as 8 finals, one of them 63 words spanning
  six speaker turns; at the 250 ms this worker now sends, the same stretch is 12 finals,
  one per scripted line, word-for-word against `meeting-transcript.jsonl` apart from
  punctuation and casing. Real meetings pause longer, so expect longer lines there. One
  observed word slip so far: "before lunch" for "before launch".
- `--from-file` still refuses to start without a non-empty `DEEPGRAM_API_KEY`, even when
  `STT_PROVIDER=openai` makes the Deepgram path unreachable. Set the variable to any
  placeholder to replay a WAV through OpenAI.
- The Trigger.dev waitpoint flow has not been exercised against the real Trigger.dev
  cloud, only locally with `npx trigger.dev dev`.
- The OpenAI Realtime STT path does not diarize: all system audio comes through as a
  single speaker.
- The suggestion brain is verified live against `fixtures/expected-actions.json` with
  `LLM_PROVIDER=openai`: all five expected actions, one per kind, no false positives,
  verbatim evidence and schema-correct args, in ~14 s per tick on `gpt-5.5`. A later
  correction ("make that diagram due Monday instead") refines the existing action in
  place rather than duplicating it.
- The engine never resolves speaker labels — `Speaker 0` / `Speaker 1` are what reach
  the LLM — so an `assignee` or `attendees` entry is a real name only when the
  transcript itself says it. In the fixture, Daniel is addressed by name and Ana never
  is, so she stays `Speaker 0`.
- `LLM_MODEL` unset means the newest `gpt-5*` id the account can list wins, which is a
  dated snapshot (`gpt-5.5-2026-04-23`) rather than the rolling alias. The hardcoded
  fallback if that listing call fails is `gpt-5.6`, which not every account has — pin
  `LLM_MODEL` for a reproducible demo.
- The gpt-5 models reject `temperature` and spend hidden reasoning tokens against the
  same budget as the answer; `engine/llm.py` drops the temperature after the API
  refuses it once and adds reasoning headroom to every caller's `max_tokens`. Only the
  actions worker has been re-checked live since — the summary, insight and titler
  prompts have not.
- Ambiguous MCP tool names are resolved at runtime from `listTools()`, not hardcoded, so
  a workspace whose server exposes differently named tools may need an
  `AMBIGUOUS_TOOL_*` override.
- `mail.send` is deliberately out of scope: Overheard never sends email on your behalf.

## Team docs

- [docs/TEAM-BRIEF.md](docs/TEAM-BRIEF.md) — the original hackathon brief: idea, architecture, sponsor map, work split.
- [docs/MILESTONES.md](docs/MILESTONES.md) — the execution plan and, at the top, where things stand now.
- [docs/SUBMISSION.md](docs/SUBMISSION.md) — the draft submission package: title, description, video, social posts.
- [docs/EVENT.md](docs/EVENT.md) — the hackathon rules: timeline, submission checklist, judging, prizes.
- [docs/SPONSOR-RESEARCH.md](docs/SPONSOR-RESEARCH.md) — background research behind the sponsor-technology choices.

## Repository layout

```
app.py                 engine entry point (headless Qt event loop + FastAPI thread)
engine/                bus, config, settings, secrets, SQLite index, LLM, guardrail, server
engine/workers/         deepgram, openai_stt, insight, actions, summary, titler
audio-helper/          Swift ScreenCaptureKit system-audio helper
fixtures/              scripted 3-minute demo meeting (transcript, clip, expected actions)
hands/                 Node service: execution, Trigger.dev task, Ambiguous + Exa connectors
web/                   Next.js dashboard: transcript, ActionsTab, CopilotKit sidebar, Auth0
requirements.txt       Python engine dependencies
run-dev.sh             starts the engine (:8765) and the web app (:3000) together
build-audio-helper.sh  builds and ad-hoc signs the Swift helper
```

## License

MIT.

The capture engine (ears) is a subset of the author's private meeting-assistant project,
carved out for this hackathon.

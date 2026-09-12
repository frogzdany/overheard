# Overheard: hackathon execution plan

Overheard listens to a live meeting, transcribes it, and every minute proposes concrete actions
it heard (create a task, schedule a follow-up, draft a message, create a doc, look something up).
A human approves a card, and a background agent does the real work in tools the team already
uses, attributed and auditable. This document is the execution plan for the build window: it
carves the author's private meeting assistant into a public repo (`overheard/`), replaces the private
LLM stack with sponsor SDKs, and lands a demoable path from "heard it" to "done it" by the 14:00
integration checkpoint, with polish and stretch on top if time allows. Build window 11:15 to
15:30, freeze at 15:00, submit by 15:45.

## Where we are (2026-09-12)

M0 through M5 below are done. Verified keyless end to end: transcript replay
(`--from-transcript` / `--from-file`), the mock LLM path, mocked hands connectors, and the
cards flow from approve through running to succeeded.

Open, in that order of priority:

- Tune the brain prompt with a real OpenAI key against `fixtures/expected-actions.json`.
- Run Ambiguous with a real key against a real workspace.
- Run Trigger.dev live with `EXECUTOR=trigger` (only exercised locally with `npx trigger.dev dev`
  so far).
- Run the OpenAI STT worker (`openai_stt.py`) live, not just against replay fixtures.
- Record the two-minute video and fill out the submission form.

Proposed split for teammates picking this up:

- **Stream B** — tune the brain prompt with a real key against `fixtures/expected-actions.json`.
- **Stream C** — polish the ActionCard/ActionsTab and the CopilotKit sidebar with a key.
- **Stream D** — Ambiguous against a real workspace, and Trigger.dev live (`EXECUTOR=trigger`).
- **Daniel** — live capture, the video, and the submission form.

## Replacement table

| Private project tech | Sponsor tech | Where in the code | Tier |
|---|---|---|---|
| Groq (`engine/groq_retry.py`, `openai/gpt-oss-120b`) | Mozilla.ai `any-llm` (`any-llm-sdk[openai,openrouter]`), provider OpenAI | `engine/llm.py`, `complete_json(system, user, schema)` helper | 1 (OpenAI provider) / 2 (any-llm abstraction) |
| `claude` CLI subprocess in `summary.py` | Same `complete_json` helper, no subprocess | `engine/workers/summary.py`, `insight.py`, `titler.py` | 1 / 2 |
| No action-suggestion worker | New actions worker, OpenAI structured output | `engine/workers/actions.py` (cloned from `insight.py`) | 1 |
| No durable execution layer | Trigger.dev v4, `wait.forToken` waitpoint | `hands/src/trigger/execute-action.ts` | 1 |
| No execution target | Ambiguous MCP (`tasks.create`, `docs.create`, `calendar.createEvent`, `chat.sendMessage`) | `hands/src/connectors/ambiguous.ts` | 1 |
| No research tool | Exa `answer()` for the `lookup` kind | `hands/src/connectors/exa.ts` | 2 |
| `QuestionsTab` only | `ActionCard` + `ActionsTab`, engine-driven | `web/src/components/sessions/{ActionCard,ActionsTab}.tsx` | 1 |
| Chat-only assistant surface | CopilotKit sidebar, shared readable state, `renderAndWaitForResponse` | `web/src/app/api/copilotkit/route.ts`, layout provider | 1 |
| Deepgram only | Deepgram default, OpenAI Realtime `gpt-live-transcribe` behind a flag | `engine/workers/openai_stt.py` (new, mirrors `deepgram.py`) | 2 |
| No provider fallback | OpenRouter fallback for `any-llm` | `engine/llm.py`, `LLM_PROVIDER=openrouter` | 3 |
| No content screening | Mozilla.ai `any-guardrail` on `draft_message`/`create_doc` | `engine/workers/actions.py`, pre-publish check | 2 |
| Auth0 SPA login (unchanged) | Same, plus every approval stamped with the Auth0 `sub` | `web/src/lib/auth.ts` (existing), engine approve route | 1 (login) / 3 (CIBA stretch) |
| Live capture only | `--from-file` / `--from-transcript` replay flags | `app.py` / `engine/runtime.py`, new `fixtures/` | dev/demo tooling, all tiers |
| No prefilter | Mozilla.ai `mcpd` / `encoderfile` (mentioned honestly, not built) | not built | 3 (stretch) |

## Milestones

### M0: carve-out baseline runs

Status: done (2026-09-12)

Goal: a runnable public baseline (ears + web) exists before any new feature work starts.

Files: `overheard/` in full, per `CARVE-OUT-SPEC.md` stream A (engine + Swift helper) and stream B
(`web/**`).

Steps:
- Stream A copies and trims `app.py`, `engine/*`, `engine/workers/{deepgram,insight,summary,titler}.py`, the Swift audio helper, per the spec's copy/drop lists.
- Stream B copies and trims `web/src/{app,components,lib,types}` per the spec, drops Tauri/mobile/cloud.
- `summary.py` loses the `claude` CLI subprocess call in favor of the existing Groq client for now (the `any-llm` swap happens in M1, not here).
- Both streams write `.env.example` files with placeholders only.
- Run the privacy grep from `CARVE-OUT-SPEC.md` rule 3 in the target repo; it must return nothing.
- `git init`, one squashed commit, never a fork of the private repo.

Acceptance test: `DEEPGRAM_API_KEY=x GROQ_API_KEY=x .venv/bin/python app.py --no-window --port=8765` then `curl -s localhost:8765/health` returns 200 JSON; `cd web && npm install && npm run build` succeeds; the privacy grep returns nothing.

Executor: two carve-out agents already running (stream A engine, stream B web).
Estimated minutes: 45 to 60 (already in flight at 11:15).
Depends on: nothing.
Unblocks: everything (M1 through M6).

### M1: schema + engine LLM swap + actions worker + routes + DB

Status: done (2026-09-12)

Goal: land the action schema end to end in the Python engine so UI and hands can build against a real contract.

Files to create or change:
- `engine/llm.py` (new)
- `engine/workers/actions.py` (new, cloned from `insight.py`)
- `engine/workers/{insight,summary,titler}.py` (edit)
- `engine/runtime.py` (edit)
- `engine/db.py` (edit)
- `engine/server.py` (edit)
- `engine/bus.py` (edit if needed for new topics)
- `engine/config.py`, `engine/secrets.py` (edit)
- `requirements.txt`, `.env.example` (edit)

Steps:
- Write `engine/llm.py`: an `any-llm` wrapper with one `complete_json(system, user, schema)` helper doing structured output; `LLM_PROVIDER=openai` default, `openrouter` behind a flag.
- Delete `engine/groq_retry.py` usage; port `insight.py`, `summary.py`, `titler.py` to call `complete_json` instead.
- Clone `insight.py`'s timer and `ALREADY_KNOWN` suppression pattern into `engine/workers/actions.py`, emitting typed actions per the schema below.
- Reuse `_merge_question_for_me` verbatim (difflib ratio >= 0.8) as the dedupe/refinement gate for actions, keyed by stable id.
- Add a `suggested_actions` table to `db.py` with columns matching the schema, migrations that initialize cleanly on a fresh DB.
- Add routes to `server.py`: `GET /sessions/{id}/actions`, `POST /sessions/{id}/actions/{aid}/approve` (body: edited args, `approvedBy`), `POST .../reject`, `PATCH .../status` (callback target for hands).
- Emit `action.suggested` and `action.updated` bus events through the existing WS `/sessions/{id}/events`.
- Implement the 30-minute suggestion expiry and durable rejection suppression (rejected ids never resuggest).
- Update `requirements.txt` (drop `groq`, add `any-llm-sdk[openai,openrouter]`) and `.env.example`.
- Codex review pass once the above is wired.

The contract (action schema):
```jsonc
{
  "id": "a7f3",
  "kind": "create_task" | "schedule_followup" | "draft_message" | "create_doc" | "lookup",
  "title": "Send Ana the Q3 architecture diagram",
  "rationale": "Ana asked for it at 14:02 and you said you'd send it today",
  "evidence": ["...verbatim transcript quote..."],
  "confidence": 0.82,
  "tool": "ambiguous.tasks.create",
  "args": { "title": "...", "assignee": "...", "due": "2026-09-15" },
  "status": "suggested" | "approved" | "running" | "succeeded" | "failed" | "rejected" | "expired",
  "approvedBy": "auth0|...",
  "runId": "run_...",
  "resultUrl": "https://..."
}
```

Acceptance test: `curl -s localhost:8765/health` returns 200; feeding a scripted transcript line implying a commitment produces, within one suggestion cycle, `curl localhost:8765/sessions/{id}/actions` returning a JSON array with one action matching the schema; a rephrased repeat of the same commitment updates the same id instead of creating a second one; `curl -X POST .../actions/{aid}/approve -d '{"approvedBy":"auth0|test"}'` flips status to `approved`; `grep -rn groq --include=*.py engine/` returns nothing.

Executor: Codex, high reasoning (Python engine).
Estimated minutes: 75.
Depends on: M0.
Unblocks: M2, M3, M4.

### M2: replay from file and transcript, test clip

Status: done (2026-09-12)

Goal: tune and demo the brain without live capture, and produce the scripted meeting clip deliverable.

Files:
- `app.py` / `engine/runtime.py` (edit: add `--from-file` and `--from-transcript` flags)
- `engine/workers/deepgram.py` (edit or wrap: accept WAV bytes at real-time pace as an alternate PCM source)
- `fixtures/meeting-clip.wav` (new)
- `fixtures/meeting-clip.jsonl` (new)

Steps:
- Add `--from-file path.wav`: stream the WAV into the existing Deepgram PCM-in path at real-time pace instead of ScreenCaptureKit.
- Add `--from-transcript path.jsonl`: bypass STT entirely, replay transcript lines onto the bus at real-time (or accelerated) pace so downstream workers run for free.
- Script and record (or synthesize) a 3-minute meeting clip with 5 unambiguous commitments, one per action kind.
- Generate the matching `.jsonl` transcript for the fast replay path.
- Run both replay paths against M1's actions worker and confirm 5 actions, one per kind, are produced.
- Note replay usage in the README skeleton.

Acceptance test: `python app.py --no-window --port=8765 --from-transcript fixtures/meeting-clip.jsonl` needs no STT key and yields 5 suggested actions across all 5 kinds via `curl localhost:8765/sessions/{id}/actions`; `python app.py --no-window --port=8765 --from-file fixtures/meeting-clip.wav` reproduces the same 5 actions through Deepgram at real-time pace; `/health` stays 200 throughout.

Executor: Claude Sonnet.
Estimated minutes: 40.
Depends on: M1.
Unblocks: M3 (real data instead of mocks), M5 (video script material).

### M3: web ActionsTab, ActionCard, CopilotKit wiring

Status: done (2026-09-12)

Goal: the human approval surface, both as an engine-driven tab and as a CopilotKit generative-UI sidebar.

Files:
- `web/src/components/sessions/{ActionCard,ActionsTab}.tsx` (new, modeled on `QuestionsTab.tsx`)
- `web/src/lib/useSessionStream.ts`, `web/src/types/session.ts` (edit: actions state, `action.suggested`/`action.updated` reducer branches, `Action` type)
- `web/src/app/session/**` (edit: add the Actions tab)
- `web/src/app/api/copilotkit/route.ts` (new: `CopilotRuntime` + `OpenAIAdapter`)
- `web/src/app/layout.tsx` (edit: CopilotKit provider)
- `web/next.config.*` (edit: drop `output: "export"`, required for the API route)
- `web/package.json` (edit: `@copilotkit/react-core`, `react-ui`, `runtime`)

Steps (M3a, cards/ActionsTab):
- Build `ActionCard.tsx`: Approve, inline Edit, Reject, evidence quote, confidence, status badge.
- Build `ActionsTab.tsx`: render the list from `useSessionStream`'s actions state, call the engine's approve/reject routes.
- Extend `useSessionStream.ts` and `types/session.ts` with the `Action` type and WS event handling.
- Wire `ActionsTab` into the session page next to Transcript/Summary/Questions.
- Develop against a mocked `actions.json` fixture until M1's routes are live.

Steps (M3b, CopilotKit wiring):
- Remove `output: "export"` from `next.config`, add CopilotKit deps, scaffold `app/api/copilotkit/route.ts`.
- Add the CopilotKit provider to layout/session page; `useCopilotReadable` exposing transcript and actions.
- One `useCopilotAction` per kind using `renderAndWaitForResponse`, rendering the same `ActionCard`.
- Verify a chat command ("create a task for the diagram") produces an in-place `ActionCard` approvable from the sidebar.

Acceptance test: `npx tsc --noEmit` clean; `npm run build` succeeds with the API route present; a session with mocked actions renders one `ActionCard` per action; Approve calls the engine route and the card flips to approved then updates on the next `action.updated` event; the CopilotKit sidebar renders an approvable card from a natural-language command; privacy grep over `web/` returns nothing.

Executor: M3a Claude Opus (cards/ActionsTab); M3b Grok (CopilotKit wiring).
Estimated minutes: 55 each, run in parallel (wall time about 60).
Depends on: M1 (schema; can start earlier against mocked JSON).
Unblocks: 14:00 integration checkpoint.

### M4: hands, Trigger.dev, Ambiguous, Exa, local executor

Status: done (2026-09-12)

Goal: an approved action actually executes against Ambiguous and Exa, and reports status back to the engine.

Files:
- `hands/` (new Trigger.dev v4 project: `package.json`, `trigger.config.ts`, `src/trigger/execute-action.ts`)
- `hands/src/connectors/{ambiguous,exa}.ts` (new)
- `hands/.env.example` (new)
- `web/src/app/api/execute/route.ts` (new, `EXECUTOR=local` in-process fallback)
- `web/src/components/sessions/ActionCard.tsx` (edit: `useRealtimeRun` status when `EXECUTOR=trigger`)

Steps:
- `npx trigger.dev init` in `hands/`; scaffold `execute-action` task with `@trigger.dev/sdk` v4.
- Provision the coworker: `npx ambiguous auth signup --name "Overheard"`, store the Bearer key.
- Build `ambiguous.ts`: an MCP client (`@modelcontextprotocol/sdk`) to `https://app.ambiguous.ai/mcp` wrapping `tasks.create`, `docs.create`, `calendar.createEvent`, `chat.sendMessage` (`mail.send` stays out of the default path, stretch-only).
- Build `exa.ts`: `exa-js` `answer()` for `lookup`, result written into an Ambiguous doc via `docs.create`.
- In `execute-action`: `wait.createToken()` at suggestion or approval time, `wait.forToken()`, dispatch by `action.tool`, then `PATCH` the engine's `/sessions/{id}/actions/{aid}/status`.
- Build `web/src/app/api/execute/route.ts` running the same connector logic in-process, so the demo survives Trigger.dev being down.
- Read `EXECUTOR=local|trigger` to pick which path completes the approval.
- Wire `useRealtimeRun` in `ActionCard` for live status under `EXECUTOR=trigger`.
- Codex review pass once wired; privacy audit before push (no real workspace names or keys committed).

Acceptance test: with `EXECUTOR=local`, `curl -X POST localhost:3000/api/execute -d '{"actionId":"a7f3"}'` creates a real item in the Ambiguous workspace and the engine action flips to `succeeded` via the status callback; with `EXECUTOR=trigger` and `npx trigger.dev dev` running, approving a card shows the Trigger.dev dashboard run parked at "waiting for token" then completing, and the card updates live; a `lookup` action produces an Ambiguous doc with the Exa answer and citations; privacy grep over `hands/` returns nothing.

Executor: Codex, high reasoning (TypeScript).
Estimated minutes: 70.
Depends on: M1 (schema, status callback route).
Unblocks: 14:00 integration checkpoint.

M3 and M4 run in parallel. Integration checkpoint at 14:00: approve a card, the run wakes, the item appears in Ambiguous, the card flips to succeeded.

### M5: sponsor polish

Status: done (2026-09-12)

Goal: fill in the remaining tier-2/3 sponsor surface and produce the submission materials.

Files:
- `engine/llm.py` (edit: verify OpenRouter fallback path)
- `engine/workers/actions.py` (edit: `any-guardrail` check before publishing `draft_message`/`create_doc`)
- `engine/workers/openai_stt.py` (new, mirrors `deepgram.py`, behind `STT_PROVIDER=openai`)
- `README.md` (edit: sponsor map, before/today section, AG-UI and generative-UI wording)
- `.env.example`, `web/.env.example`, `hands/.env.example` (edit: complete, consistent)
- video script (in `README.md` or a short standalone file)

Steps:
- (Claude Sonnet) Wire `any-guardrail` in `actions.py`: screen `draft_message`/`create_doc` text before it is shown as `suggested`; keep one blocked example for the README.
- (Claude Sonnet) Verify the OpenRouter fallback: flip `LLM_PROVIDER=openrouter`, confirm `complete_json` still returns valid structured output against the replay clip.
- (Codex, medium reasoning) Build `openai_stt.py`: `gpt-live-transcribe` over the Realtime API, same PCM-in/transcript-events-out shape as `deepgram.py`, gated by `STT_PROVIDER=openai`.
- (Claude Haiku draft, then Sonnet edit) Write the README: architecture diagram (ears, brain, hands), sponsor table with tiers, an honest "what existed before today vs built today" section, AG-UI / generative UI wording for CopilotKit.
- Fill every `.env.example` completely, placeholders only, across engine/web/hands.
- Write the 2-minute video script (problem, login and live transcript, cards appearing, Trigger.dev and Ambiguous payoff, architecture slide, close).
- Re-run the privacy grep across the whole repo before the final push.
- Smoke-test that flipping `STT_PROVIDER` and `LLM_PROVIDER` never breaks the default demo path.

Acceptance test: a drafted message with a blocked pattern is caught by `any-guardrail` before reaching `status: suggested`; `LLM_PROVIDER=openrouter` still produces valid actions from the M2 replay clip; `STT_PROVIDER=openai` streams the same clip and produces transcript events on the same bus topic as `deepgram.py`; the full-repo privacy grep returns nothing; the README renders the sponsor table, the before/today section, and the video script.

Executor: guardrail + OpenRouter, Claude Sonnet; OpenAI STT worker, Codex medium reasoning; README, Claude Haiku draft then Sonnet edit.
Estimated minutes: 60 (parallel tracks).
Depends on: M1, M2, M4.
Unblocks: M6, submission.

### M6: stretch

Goal: extra sponsor depth if Tier 2 finished with time to spare before the 15:00 freeze.

Files:
- `hands/src/connectors/ambiguous.ts` (edit: `mail.send` behind an Auth0 CIBA gate)
- `hands/src/trigger/execute-action.ts` (edit: optional `@openai/agents` `Agent` with `needsApproval` inside the executor)
- `mcpd` config, `encoderfile` prefilter (stretch, mention honestly if not built)

Steps:
- If time remains: gate `mail.send` behind Auth0 CIBA (`/bc-authorize`, poll `/token`, Guardian push) ahead of execution.
- Optional: add `@openai/agents` `needsApproval` semantics inside the executor as an additive, non-breaking path.
- Optional: `mcpd` for declarative MCP server management; `encoderfile` as a compiled actionability prefilter.
- Whoever is free takes the single highest-impact item first.
- Anything unfinished stays fully disabled behind its flag; no half-wired path is reachable from the default demo.

Acceptance test: each attempted item is either fully working end to end or completely disabled by its flag, with no partially-wired code path exposed in the default demo run.

Executor: whoever is free.
Estimated minutes: remaining time only, opportunistic.
Depends on: M4, M5.
Unblocks: nothing (terminal).

## Timeline

| Time | What is happening |
|---|---|
| 11:15 | Build window opens. M0 carve-out (stream A engine, stream B web) already running. |
| 11:15-12:00 | M0 acceptance confirmed (`/health` 200, web build, privacy grep clean). M1 starts immediately (Codex, high reasoning). |
| 12:00-13:00 | M1 in progress: `llm.py`, `actions.py`, DB, routes, bus events. M2 (Claude Sonnet) starts once the actions worker exists. M3/M4 scaffolding starts against mocked JSON without waiting for M1 to fully land. |
| 13:00 | Checkpoint: M1 contract locked (schema, routes, DB live). M2 test clip in hand. M3 and M4 switch to the real schema and run fully in parallel. |
| 13:00-14:00 | M3a/M3b (ActionsTab, ActionCard, CopilotKit) and M4 (hands, Ambiguous, Exa, local executor) in parallel. Codex review pass after M4. |
| 14:00 | Integration checkpoint: approve a card, the Trigger.dev run wakes, the item appears in Ambiguous, the card flips to succeeded. |
| 14:00-15:00 | M5 sponsor polish: any-guardrail, OpenRouter fallback, OpenAI Realtime STT flag, README, `.env.example`, video script. Privacy audit before every push. |
| 15:00 | Freeze checkpoint: no new feature work past this point. M6 stretch only if already near done; otherwise cut. |
| 15:00-15:30 | Record the 2-minute video, write the submission description, write the social post. |
| 15:30 | Build window closes. |
| 15:45 | Submit. |

## Accounts and keys checklist

| Env var | Used by | Notes |
|---|---|---|
| `DEEPGRAM_API_KEY` | `engine/workers/deepgram.py` | default STT, required |
| `OPENAI_API_KEY` | `engine/llm.py`, CopilotKit `OpenAIAdapter`, optional `gpt-live-transcribe` | required |
| `OPENROUTER_API_KEY` | `engine/llm.py` fallback path | Tier 3, needed only when `LLM_PROVIDER=openrouter` |
| `LLM_PROVIDER` | `engine/llm.py` | `openai` (default) or `openrouter` |
| `STT_PROVIDER` | `engine/runtime.py` | `deepgram` (default) or `openai` |
| `EXA_API_KEY` | `hands/src/connectors/exa.ts` | Tier 2, `lookup` action kind |
| `AMBIGUOUS_API_KEY` | `hands/src/connectors/ambiguous.ts` | from `npx ambiguous auth signup --name "Overheard"` |
| `TRIGGER_PROJECT_ID`, `TRIGGER_SECRET_KEY` | `hands/trigger.config.ts` | Trigger.dev v4 project |
| `EXECUTOR` | approval flow (engine and `web/src/app/api/execute/route.ts`) | `local` (default, resilient) or `trigger` |
| `ENGINE_URL` | `hands/` status callback | points back at `http://127.0.0.1:8765` |
| `NEXT_PUBLIC_AUTH0_DOMAIN`, `NEXT_PUBLIC_AUTH0_CLIENT_ID`, `NEXT_PUBLIC_AUTH0_AUDIENCE` | `web/src/lib/auth.ts` | existing SPA login, reuse dev tenant, values in `.env.local` only, never tracked |
| `NEXT_PUBLIC_ENGINE_URL` | `web/src/lib/engine.ts` | default `http://127.0.0.1:8765` |

Before the first push, rotate the five keys that lived in the private repo's `.env`, as a precaution, and confirm none of the `.env.example` files carry anything but placeholders.

## Demo script by milestone

- M0: `/health` returns 200; the web app loads the existing `TranscriptTab` against a live session.
- M1: curl the actions endpoint live; a scripted commitment turns into a JSON action within one suggestion cycle.
- M2: play the 3-minute scripted clip with `--from-file`; watch five actions accumulate, one per kind, with no live capture needed.
- M3: approve, inline-edit, and reject cards in `ActionsTab`; then type "create a task for the diagram" into the CopilotKit sidebar and approve the card that renders inline.
- M4: after approval, cut to the Trigger.dev dashboard showing the run parked at "awaiting approval" then completing; cut to the Ambiguous workspace showing the task or doc authored by the Overheard coworker.
- M5: flip the OpenRouter flag with no visible behavior change; show one guardrail-blocked draft example; mention the OpenAI Realtime STT flag.
- M6 (if reached): a CIBA phone push approving the one action that leaves the workspace (`mail.send`).

## Cut list

If running late, drop in this order:

1. M6 stretch entirely (Auth0 CIBA, `@openai/agents` `needsApproval`, `mcpd`, `encoderfile`).
2. OpenAI Realtime STT worker; keep Deepgram only.
3. OpenRouter fallback flag; keep OpenAI only, note the design in the README as not wired live.
4. `any-guardrail` screening; note it as designed but not wired if time runs out.
5. The `lookup` action kind and its Exa connector; demo the remaining four kinds.
6. CopilotKit sidebar wiring (M3b); fall back to the engine-only `ActionsTab` if integration is rocky.
7. `EXECUTOR=trigger`; run the entire demo on `EXECUTOR=local`.
8. `--from-file` replay; keep `--from-transcript` only, it is cheaper to build and just as convincing for tuning.

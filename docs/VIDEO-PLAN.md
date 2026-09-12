# Overheard — 2-minute demo video plan

## 1. Purpose

This is the shot-by-shot production plan for the hackathon submission video
(`docs/SUBMISSION.md` section 3 gives the pitch-level shot list; this
document is the executable version of it). It fixes the pipeline, the
segment timing, the overlay content, the file layout, the run order, the
timeline events the recording driver must emit, and the checks a finished
render must pass before it's submitted.

**Pipeline, fixed:** the engine transcribes `fixtures/demo-short/demo-short.wav`
live through OpenAI Realtime (`--from-file`), the suggestion brain ticks
every 20s (`ACTIONS_INTERVAL_MS=20000`), hands run in Trigger.dev mode, a
Playwright driver drives and records the browser at 1600x900 while logging a
JSON timeline of named events, and `ffmpeg` assembles the final cut: segment
speed-ups, HTML callout overlays, and narration in the author's own cloned
voice (ElevenLabs), output at 1920x1080, hard-capped at 120s.

Trigger.dev and Ambiguous AI are represented as HTML callout overlays (run
id, "waiting on approval" then "resumed", an Ambiguous deep link) rather
than by screen-recording their dashboards — this keeps the whole video
inside the Overheard UI and avoids a context switch mid-cut.

## 2. Segment table

All times are seconds into the final 1920x1080 render.

| Seg | Sec | On screen | Narration id | Overlays | Bounding timeline events |
|---|---|---|---|---|---|
| S0 | 0–7 | Title card, full frame | S0 | `title-card` | start → `login` |
| S1 | 7–17 | Auth0 login, session-start screen (pick the source) | S1 | — | `login` → `session_open` |
| S2 | 17–45 | Transcript scrolls with speaker labels; cards appear one by one (sped up ~2.5×) | S2 | — | `session_open`, `first_transcript` → `card_1`…`card_4` |
| S3 | 45–75 | Inline edit on one card, Approve click, status flips to running, result lands | S3 | `trigger-wait`, `trigger-resume`, `ambiguous-created` | `card_4`/`edit` → `approve` → `running` → `done_1` |
| S4 | 75–88 | Reject click on a different card; lookup card resolves into a doc | S4 | `exa-answer` | `reject` → `done_lookup` |
| S5 | 88–108 | CopilotKit sidebar open; user types a request; approval card renders inline in chat | S5 | — | `sidebar_open` → `chat_sent` → `chat_card` → `chat_done` |
| S6 | 108–120 | Outro card: three-box architecture, sponsor names, repo link | S6 | `outro-card` | `stop` → `summary` |

Total: 120s, matching the hard cap.

## 3. Overlays

Two frame sizes only:

- **Full-frame cards** (title, outro): **1600x900**, centered, same canvas
  as the app content so the cut to/from live footage has no letterbox jump.
- **Callouts** (Trigger.dev, Ambiguous, Exa): **560x160**, anchored
  bottom-right, semi-transparent panel over live footage.

| id | Size | Shown | Exact text |
|---|---|---|---|
| `title-card` | 1600x900 | S0 | **Overheard — the meeting agent that gets things done**<br>*Agents, Everywhere: Bots, Channels & More — AI Tinkerers × OpenAI, Sept 12, 2026* |
| `trigger-wait` | 560x160 | S3, right after Approve is clicked | `Trigger.dev run <runId> waiting on approval` |
| `trigger-resume` | 560x160 | S3, once the waitpoint completes | `run resumed, connector executing` |
| `ambiguous-created` | 560x160 | S3, at `done_1` | `Ambiguous AI: task created by the Overheard coworker <deep link>` |
| `exa-answer` | 560x160 | S4, at `done_lookup` | `Exa: answer with N sources written to a doc` |
| `outro-card` | 1600x900 | S6 | Three boxes — **EARS: OpenAI** / **BRAIN + UI: OpenAI · CopilotKit · Auth0 · Mozilla.ai any-llm · OpenRouter** / **HANDS: Trigger.dev · Ambiguous AI · Exa** — footer: repo URL (placeholder `github.com/frogzdany/overheard` until the repo is made public per the submission checklist) |

`<runId>`, `<deep link>`, and `N` are substituted at assembly time from the
driver's timeline log (`running.runId`, `done_1.resultUrl`,
`done_lookup.sourceCount` — see §5).

## 4. File layout under `demo/`

```
demo/
  narration.md        # the 7-segment script this plan's S column points to
  recipe.json          # segment list + overlay timing + speed-up factors,
                        # consumed by assemble.mjs; generated/edited by hand,
                        # not derived automatically from the timeline log
  record.ts            # Playwright driver: logs in, drives the UI through
                        # every beat below, records raw video, writes the
                        # timeline log (out/timeline.json)
  overlays/
    title.html
    trigger-wait.html
    trigger-resume.html
    ambiguous.html
    exa.html
    outro.html
  assemble.mjs          # ffmpeg pipeline: raw capture + timeline.json +
                        # narration audio + overlays/*.html (rasterized) ->
                        # out/overheard-demo.mp4
  out/
    raw.mp4             # unedited Playwright capture, 1600x900
    timeline.json        # ordered event log from record.ts
    narration.mp3        # ElevenLabs render of narration.md
    overheard-demo.mp4    # final 1920x1080 deliverable
```

## 5. Run order

1. Start the stack against the short fixture, hands in Trigger.dev mode, web
   served separately:
   ```
   ./run-demo.sh --file=fixtures/demo-short/demo-short.wav --executor=trigger --no-web
   ```
2. Start the web app in production mode (not the dev server — the recording
   should match what a viewer would actually get):
   ```
   npm run build && npm run start   # (in web/)
   ```
3. Run the driver against the running stack:
   ```
   npx tsx demo/record.ts
   ```
   `record.ts` logs into the app (Auth0), starts a session, waits for the
   transcript and the four expected cards from
   `fixtures/demo-short/expected-actions.json`, edits and approves one,
   rejects another, opens the CopilotKit sidebar and drives the chat
   flow, then stops the session — emitting the timeline events in §6 as it
   goes and writing `demo/out/raw.mp4` + `demo/out/timeline.json`.
4. Assemble the final cut:
   ```
   node demo/assemble.mjs
   ```
   Reads `demo/out/raw.mp4`, `demo/out/timeline.json`, `demo/narration.mp3`
   (rendered ahead of time from `demo/narration.md` in the author's cloned
   ElevenLabs voice), and `demo/recipe.json` (per-segment speed-up factors
   and overlay placements), and writes `demo/out/overheard-demo.mp4` at
   1920x1080.

## 6. Timeline events

`record.ts` must emit these events, in this order, to `timeline.json`. Each
entry is `{event, t, ...fields}` with `t` the wall-clock second in the raw
capture.

| Event | Fields | Meaning |
|---|---|---|
| `login` | — | Auth0 login submitted |
| `session_open` | — | Meeting session created, capture armed |
| `first_transcript` | — | First transcript line rendered |
| `card_1` .. `card_4` | `kind` | One of the four expected actions rendered as a card (`kind` ∈ `create_task`, `schedule_followup`, `create_doc`, `lookup`) |
| `edit` | — | A card field was changed inline before approval |
| `approve` | — | Approve clicked on the edited card |
| `running` | `runId` | Trigger.dev run resumed and is executing |
| `done_1` | `resultUrl` | The approved action landed in Ambiguous (deep link) |
| `reject` | — | Reject clicked on a different card |
| `done_lookup` | `sourceCount` | The lookup action resolved via Exa with citations, written to a doc |
| `sidebar_open` | — | CopilotKit sidebar opened |
| `chat_sent` | — | User message sent in the sidebar |
| `chat_card` | — | Approval card rendered inline in the chat |
| `chat_done` | — | Chat-originated action approved and completed |
| `stop` | — | Session stopped |
| `summary` | — | End-of-run summary (used to cue the outro card) |

## 7. Acceptance checks

Run these against `demo/out/overheard-demo.mp4` before it's submitted:

- [ ] Duration ≤ 120s (`ffprobe -v error -show_entries format=duration`).
- [ ] Resolution exactly 1920x1080.
- [ ] Narration audible and intelligible on every segment (spot-check with
      headphones; no clipping, no segment silent).
- [ ] Every sponsor named at least once in the narration audio, matching
      `demo/narration.md`'s sponsor-coverage table: OpenAI, CopilotKit,
      Trigger.dev, Ambiguous AI, Exa, Auth0, Mozilla.ai any-llm, OpenRouter.
- [ ] No API key, token, tenant id, or private data visible in any frame
      (terminal panes, `.env` values, browser devtools, network tab) —
      re-run the SUBMISSION.md privacy grep across anything shown on
      screen, not just committed files.

## 8. Fallback plan

If the live Realtime take fails (API hiccup, flaky network, a bad run on
recording day): re-record the same driver script against the same fixture
but with the engine in `--transcript` replay mode (feeding
`fixtures/demo-short/meeting-transcript.jsonl` directly instead of
transcribing `demo-short.wav` live) and hands mocked instead of hitting real
Trigger.dev/Ambiguous/Exa endpoints. The UI beats, card content, and timing
are driven by the same fixture either way, so `demo/narration.md` and
`demo/recipe.json` need no changes — only the engine's input mode and the
hands executor flip. Note in the video's description (not on screen) that
the fallback take used replay mode if it was used, per the "no hype"
standard the rest of the project holds itself to.

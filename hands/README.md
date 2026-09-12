# Overheard Hands

`overheard-hands` executes approved meeting actions and reports each run back to the Overheard engine. With no API keys it uses deterministic-looking mock connector results, so the complete local loop works offline.

## Local mode

Requires Node.js 22 or newer.

```sh
npm install
npm run dev
```

The defaults are `EXECUTOR=local`, `ENGINE_URL=http://127.0.0.1:8765`, and `HANDS_PORT=8790`, so mock local mode needs no environment setup. To customize values, export variables from `.env.example` in your shell before starting the service. Claims are preserved in `.hands-claims.json` across restarts by default. Set `HANDS_RESET_CLAIMS=1` for a one-time reset at startup, then unset it before the next start.

When `ENGINE_TOKEN` is non-empty, every status callback includes `X-Engine-Token: <ENGINE_TOKEN>`.

## Environment files

On startup, `src/server.ts` (and the `execute-action` Trigger.dev task) load `hands/.env` then the repo root `../.env`, in that order, without ever overriding a variable already set in the real process environment — so `export FOO=bar` in your shell always wins, then `hands/.env`, then the root `.env`. Only the file paths that were found are logged, never values.

`ENGINE_URL` is the one variable the Trigger.dev worker cannot infer. The task reports
`running` back to the engine *before* it dispatches, so a worker started without
`ENGINE_URL` (or with the wrong port) fails that callback, never executes, and leaves
the card stuck at `approved` with the reason only in the `trigger.dev dev` log. Export
`ENGINE_URL` in the shell you start `npx trigger.dev@latest dev` from whenever the
engine is not on the default `http://127.0.0.1:8765` (`run-demo.sh` already does).

`npx trigger.dev@latest dev` performs its own automatic env loading (`.env`, `.env.development`, `.env.local`, `.env.development.local`, `dev.vars`), but only from its project directory, which for this package is `hands/` — it never reads the repo root `.env`. The `execute-action` task also imports `../env.js` itself (see above), so the repo root `.env` reaches trigger-mode runs anyway; if that import is ever removed, copy the needed keys into `hands/.env` instead.

## Trigger.dev mode

Set `EXECUTOR=trigger`, `TRIGGER_SECRET_KEY`, and `TRIGGER_PROJECT_REF`, plus real connector keys when desired. Then run the Trigger.dev worker and the HTTP service in separate terminals:

```sh
npx trigger.dev@latest dev
EXECUTOR=trigger npm run dev
```

The engine calls `POST /prepare` when it records a suggested action. Hands creates a 30-minute Trigger.dev waitpoint token, triggers `execute-action` with that token, persists the `runId` to `tokenId` mapping in `.hands-run-tokens.json`, and returns both IDs. Approval sends the full, possibly edited approved action to `POST /runs/{runId}/approve`, which completes the token. The resumed task executes that approved payload rather than the original suggestion. Cancellation completes the token without executing or reporting a status.

`POST /execute` remains the direct path. It executes immediately in local mode and triggers `execute-action` without a wait token in trigger mode.

## Connectors

### Ambiguous AI workspace

`src/connectors/ambiguous.ts` talks to the Ambiguous workspace over MCP (`AMBIGUOUS_MCP_URL`, default `https://app.ambiguous.ai/mcp`, with `AMBIGUOUS_API_KEY` as a bearer token). With `AMBIGUOUS_API_KEY` empty it returns mock results instead and never opens a connection.

That server advertises ~856 tools, so each logical tool is addressed by its **exact** real name — no fuzzy matching, because a near miss there is a wrong write:

| Action kind | Logical tool | Real tool | Env override |
| --- | --- | --- | --- |
| `create_task` | `tasks.create` | `create_task` | `AMBIGUOUS_TOOL_TASKS_CREATE` |
| `schedule_followup` | `calendar.createEvent` | `create_event` | `AMBIGUOUS_TOOL_CALENDAR_CREATE_EVENT` |
| `draft_message` | `chat.sendMessage` | `send_message` | `AMBIGUOUS_TOOL_CHAT_SEND_MESSAGE` |
| `create_doc`, `lookup` | `docs.create` | `create_document` | `AMBIGUOUS_TOOL_DOCS_CREATE` |

If the configured (or default) name is not advertised, the connector fails with the closest advertised names rather than guessing. An MCP result flagged `isError` is raised with the server's own message, so a schema rejection reads as a schema rejection.

The full real schemas are recorded in [`scripts/ambiguous-schemas.md`](scripts/ambiguous-schemas.md); regenerate them any time the workspace changes:

```sh
npx tsx scripts/dump-ambiguous-schemas.ts   # rewrites scripts/ambiguous-schemas.md; tools/list only, no workspace writes
npx tsx scripts/check-ambiguous.ts                                          # connect + resolve the four names
```

#### Argument mapping

Action `args` are human-shaped, so the connector translates them and resolves people, channels and calendars through the workspace's own `list_users` / `list_channels` / `list_calendars` tools (each optional — when a tool is missing or the key lacks the role for it, the dependent argument is simply left out):

- **`create_task`** — `title`; `description` from `notes`/`description`; `due_date` from `due` (normalized to `YYYY-MM-DD`); `assignee_id` resolved from the `assignee` name (display name, first name, email, username, or a UUID passed straight through); `priority` when it is one of `urgent|high|medium|low`.
- **`create_event`** — `title`; `start_at` from `when`/`start`; `end_at` from `end` or **start + 30 minutes** (the schema has no duration field); `calendar_id` from `AMBIGUOUS_DEFAULT_CALENDAR` (id or name) or the workspace's default calendar; `description` from `notes`; `attendees` resolved name → user id (emails and UUIDs pass through, unknown names are dropped); `force: true` for a start time in the past.
- **`send_message`** — `content` from `body`; `channel_id` picked as `AMBIGUOUS_DEFAULT_CHANNEL` (channel id or name, `#` optional) if set, else a DM channel with the `to` recipient, else the first general-looking channel, else the first channel. When the target is not a DM with that person, `to` is prepended to the body as `@name `.
- **`create_document`** — `type` (`doc` by default, `sheet`/`slide` honoured), `title`, `content` from `content`/`body`/`notes` (Markdown). The `lookup` kind writes the Exa answer plus its citations into the same tool.

#### Result URLs

No create tool returns a web URL, so `resultUrl` is a deep link built from the workspace origin (`AMBIGUOUS_WORKSPACE_URL`, else the origin of `AMBIGUOUS_MCP_URL`) plus the app's own routes — task `/tasks?task=<id>`, document `/docs/<id>`, event `/calendar?event=<id>`, message `/chat/<channel_id>?m=<id>`.

## Endpoints

- `GET /health` — service health and executor mode.
- `POST /prepare` — accept a `suggested` action. Local mode returns HTTP 200 and `{ "runId": null }`; trigger mode returns HTTP 202 and `{ "runId": "...", "tokenId": "..." }`.
- `POST /runs/{runId}/approve` — accept the full `approved` action and complete its waitpoint; returns HTTP 202 and `{ "runId": "..." }`, or 404 for an unknown run.
- `POST /runs/{runId}/cancel` — complete the waitpoint without execution; returns HTTP 202 and `{ "runId": "..." }`, or 404 for an unknown run.
- `POST /execute` — direct execution path for a full `approved` action; returns HTTP 202 and `{ "runId": "..." }`.

## Sample action

For the trigger-mode approval flow, first prepare a suggested action:

```sh
curl -i -X POST http://127.0.0.1:8790/prepare \
  -H 'content-type: application/json' \
  --data '{"id":"a7f3","sessionId":"s1","kind":"create_task","title":"Send Ana the Q3 architecture diagram","rationale":"Ana requested the current design","evidence":["Ana: please send the Q3 architecture diagram"],"confidence":0.82,"tool":"ambiguous.tasks.create","args":{"title":"Send Ana the Q3 architecture diagram","assignee":"Ana","due":"2026-09-15"},"status":"suggested","approvedBy":null,"runId":null,"resultUrl":null}'
```

Use the returned `runId` to approve with the full action. This example shows an edited due date:

```sh
curl -i -X POST http://127.0.0.1:8790/runs/RUN_ID/approve \
  -H 'content-type: application/json' \
  --data '{"id":"a7f3","sessionId":"s1","kind":"create_task","title":"Send Ana the Q3 architecture diagram","rationale":"Ana requested the current design","evidence":["Ana: please send the Q3 architecture diagram"],"confidence":0.82,"tool":"ambiguous.tasks.create","args":{"title":"Send Ana the Q3 architecture diagram","assignee":"Ana","due":"2026-09-16"},"status":"approved","approvedBy":"auth0|demo","runId":"RUN_ID","resultUrl":null}'
```

Or cancel the waiting run:

```sh
curl -i -X POST http://127.0.0.1:8790/runs/RUN_ID/cancel
```

For the direct path, send an already approved action:

```sh
curl -i -X POST http://127.0.0.1:8790/execute \
  -H 'content-type: application/json' \
  --data '{"id":"a7f3","sessionId":"s1","kind":"create_task","title":"Send Ana the Q3 architecture diagram","rationale":"Ana requested the current design","evidence":["Ana: please send the Q3 architecture diagram"],"confidence":0.82,"tool":"ambiguous.tasks.create","args":{"title":"Send Ana the Q3 architecture diagram","assignee":"Ana","due":"2026-09-15"},"status":"approved","approvedBy":"auth0|demo","runId":null,"resultUrl":null}'
```

The engine receives `PATCH /sessions/s1/actions/a7f3/status` first with `running`, then with `succeeded` and the created object's URL (or `failed` and an error message).

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

## Trigger.dev mode

Set `EXECUTOR=trigger`, `TRIGGER_SECRET_KEY`, and `TRIGGER_PROJECT_REF`, plus real connector keys when desired. Then run the Trigger.dev worker and the HTTP service in separate terminals:

```sh
npx trigger.dev@latest dev
EXECUTOR=trigger npm run dev
```

The engine calls `POST /prepare` when it records a suggested action. Hands creates a 30-minute Trigger.dev waitpoint token, triggers `execute-action` with that token, persists the `runId` to `tokenId` mapping in `.hands-run-tokens.json`, and returns both IDs. Approval sends the full, possibly edited approved action to `POST /runs/{runId}/approve`, which completes the token. The resumed task executes that approved payload rather than the original suggestion. Cancellation completes the token without executing or reporting a status.

`POST /execute` remains the direct path. It executes immediately in local mode and triggers `execute-action` without a wait token in trigger mode.

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

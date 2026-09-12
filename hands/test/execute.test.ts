import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { Readable } from "node:stream";
import { after, before, test } from "node:test";

import { createHandsServer, handleRequest } from "../src/server.js";
import type { Action } from "../src/schema.js";

type Callback = {
  method: string;
  path: string;
  body: Record<string, unknown>;
  engineToken: string | null;
};

const callbacks: Callback[] = [];
let engine: Server | undefined;
let hands: Server | undefined;
let handsUrl: string;
let networkAvailable = true;
let runningFailuresRemaining = 0;
const originalFetch = globalThis.fetch;

function listen(server: Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") return reject(new Error("Expected TCP address"));
      resolve(address.port);
    });
  });
}

async function waitForCallbacks(count: number): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (callbacks.length < count && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  assert.equal(callbacks.length, count, `expected ${count} callbacks before timeout`);
}

async function persistedClaims(): Promise<string[]> {
  try {
    return JSON.parse(await readFile(".hands-claims.json", "utf8")) as string[];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

before(async () => {
  process.env.EXECUTOR = "local";
  process.env.AMBIGUOUS_API_KEY = "";
  process.env.EXA_API_KEY = "";
  process.env.ENGINE_TOKEN = "test-engine-token";

  engine = createServer(async (request, response) => {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(Buffer.from(chunk));
    const engineTokenHeader = request.headers["x-engine-token"];
    callbacks.push({
      method: request.method || "",
      path: request.url || "",
      body: JSON.parse(Buffer.concat(chunks).toString("utf8")),
      engineToken: Array.isArray(engineTokenHeader) ? engineTokenHeader[0] || null : engineTokenHeader || null,
    });
    if (callbacks.at(-1)?.body.status === "running" && runningFailuresRemaining > 0) {
      runningFailuresRemaining -= 1;
      response.writeHead(500).end("temporary engine failure");
      return;
    }
    response.writeHead(204).end();
  });
  try {
    const enginePort = await listen(engine);
    process.env.ENGINE_URL = `http://127.0.0.1:${enginePort}`;

    hands = createHandsServer();
    handsUrl = `http://127.0.0.1:${await listen(hands)}`;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EPERM") throw error;
    networkAvailable = false;
    console.warn("[test] loopback listen blocked; using in-process HTTP handler fallback");
    globalThis.fetch = (async (input, init) => {
      callbacks.push({
        method: init?.method || "GET",
        path: new URL(String(input)).pathname,
        body: JSON.parse(String(init?.body)),
        engineToken: new Headers(init?.headers).get("x-engine-token"),
      });
      if (callbacks.at(-1)?.body.status === "running" && runningFailuresRemaining > 0) {
        runningFailuresRemaining -= 1;
        return new Response("temporary engine failure", { status: 500 });
      }
      return new Response(null, { status: 204 });
    }) as typeof fetch;
  }
});

after(async () => {
  globalThis.fetch = originalFetch;
  const servers = [engine, hands].filter((server): server is Server => Boolean(server?.listening));
  await Promise.all(servers.map((server) =>
    new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  ));
});

async function postJson(path: string, body: unknown): Promise<{ status: number; body: unknown }> {
  if (networkAvailable) {
    const response = await fetch(`${handsUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    return { status: response.status, body: await response.json() as unknown };
  }

  const request = Readable.from([Buffer.from(JSON.stringify(body))]) as unknown as IncomingMessage;
  request.method = "POST";
  request.url = path;
  let status = 0;
  let responseBody = "";
  const responseState = {
    headersSent: false,
    writeHead(code: number) {
      status = code;
      responseState.headersSent = true;
      return this;
    },
    end(chunk?: string) {
      responseBody += chunk || "";
      return this;
    },
  };
  const response = responseState as unknown as ServerResponse;
  await handleRequest(request, response);
  return { status, body: JSON.parse(responseBody) as unknown };
}

async function postExecute(action: Action): Promise<{ status: number; body: { runId: string } }> {
  const response = await postJson("/execute", action);
  return response as { status: number; body: { runId: string } };
}

test("executes every action kind in mock mode and never double-fires an id", async () => {
  const suffix = randomUUID();
  const kinds: Action["kind"][] = [
    "create_task",
    "schedule_followup",
    "draft_message",
    "create_doc",
    "lookup",
  ];
  const tools: Record<Action["kind"], string> = {
    create_task: "ambiguous.tasks.create",
    schedule_followup: "ambiguous.calendar.createEvent",
    draft_message: "ambiguous.chat.sendMessage",
    create_doc: "ambiguous.docs.create",
    lookup: "exa.answer",
  };
  const actions = kinds.map((kind, index): Action => ({
    id: `test-${kind}-${suffix}`,
    sessionId: "test-session",
    kind,
    title: `Test action ${index + 1}`,
    rationale: "Test rationale",
    evidence: ["Test evidence"],
    confidence: 0.9,
    tool: tools[kind],
    args: kind === "lookup" ? { query: "What is Overheard?" } : { title: `Item ${index + 1}` },
    status: "approved",
    approvedBy: "auth0|test",
    runId: null,
    resultUrl: null,
  }));

  for (const action of actions) {
    const response = await postExecute(action);
    assert.equal(response.status, 202);
    assert.match(response.body.runId, /^hands-/);
  }

  await waitForCallbacks(actions.length * 2);
  for (const action of actions) {
    const actionCallbacks = callbacks.filter((callback) => callback.path.includes(`/actions/${action.id}/status`));
    assert.ok(actionCallbacks.every((callback) => callback.method === "PATCH"));
    assert.ok(actionCallbacks.every((callback) => callback.engineToken === "test-engine-token"));
    assert.deepEqual(actionCallbacks.map((callback) => callback.body.status), ["running", "succeeded"]);
    assert.equal(typeof actionCallbacks[1]?.body.resultUrl, "string");
    assert.ok((actionCallbacks[1]?.body.resultUrl as string).startsWith("https://"));
  }

  const duplicate = await postExecute(actions[0] as Action);
  assert.equal(duplicate.status, 202);
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(callbacks.length, actions.length * 2);
});

test("releases an action when the initial running callback fails so it can be retried", async () => {
  const action: Action = {
    id: `test-running-retry-${randomUUID()}`,
    sessionId: "test-session",
    kind: "create_task",
    title: "Retry after engine recovery",
    rationale: "Test rationale",
    evidence: ["Test evidence"],
    confidence: 0.9,
    tool: "ambiguous.tasks.create",
    args: { title: "Retry after engine recovery" },
    status: "approved",
    approvedBy: "auth0|test",
    runId: null,
    resultUrl: null,
  };
  const callbackStart = callbacks.length;
  runningFailuresRemaining = 1;

  const firstAttempt = await postExecute(action);
  assert.equal(firstAttempt.status, 202);
  await waitForCallbacks(callbackStart + 1);
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.deepEqual(
    callbacks.slice(callbackStart).map((callback) => callback.body.status),
    ["running"],
  );
  assert.equal((await persistedClaims()).includes(action.id), false);

  const retry = await postExecute(action);
  assert.equal(retry.status, 202);
  await waitForCallbacks(callbackStart + 3);
  assert.deepEqual(
    callbacks.slice(callbackStart).map((callback) => callback.body.status),
    ["running", "running", "succeeded"],
  );
});

test("prepare in local mode returns a null run id and does not enqueue work", async () => {
  const callbackStart = callbacks.length;
  const response = await postJson("/prepare", {
    id: `test-prepare-${randomUUID()}`,
    sessionId: "test-session",
    kind: "create_task",
    title: "Prepare locally",
    rationale: "Test rationale",
    evidence: ["Test evidence"],
    confidence: 0.9,
    tool: "ambiguous.tasks.create",
    args: { title: "Prepare locally" },
    status: "suggested",
    approvedBy: null,
    runId: null,
    resultUrl: null,
  });

  assert.equal(response.status, 200);
  assert.deepEqual(response.body, { runId: null });
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(callbacks.length, callbackStart);
});

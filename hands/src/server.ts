// Must be the first import: loads hands/.env then ../.env (repo root) into
// process.env, without overriding anything already set, before any other
// module reads process.env at import time. See src/env.ts for details.
import "./env.js";

import { randomUUID } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { tasks, wait } from "@trigger.dev/sdk";
import { ZodError } from "zod";

import { executeAction, resetClaims } from "./execute.js";
import { actionSchema, suggestedActionSchema } from "./schema.js";
import type { executeActionTask } from "./trigger/execute-action.js";

const RUN_TOKENS_PATH = join(process.cwd(), ".hands-run-tokens.json");
const triggerTokensByRun = new Map<string, string>();
let runTokensLoaded = false;
let runTokenQueue: Promise<void> = Promise.resolve();

function withRunTokenLock<T>(operation: () => Promise<T>): Promise<T> {
  const result = runTokenQueue.then(operation);
  runTokenQueue = result.then(() => undefined, () => undefined);
  return result;
}

async function loadRunTokens(): Promise<void> {
  if (runTokensLoaded) return;
  try {
    const parsed: unknown = JSON.parse(await readFile(RUN_TOKENS_PATH, "utf8"));
    if (
      !parsed ||
      typeof parsed !== "object" ||
      Array.isArray(parsed) ||
      !Object.entries(parsed).every(([runId, tokenId]) => runId && typeof tokenId === "string")
    ) {
      throw new Error("run/token file is not a string map");
    }
    for (const [runId, tokenId] of Object.entries(parsed)) {
      triggerTokensByRun.set(runId, tokenId as string);
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw new Error(
        `Cannot safely read ${RUN_TOKENS_PATH}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  runTokensLoaded = true;
}

async function persistRunTokens(): Promise<void> {
  const temporaryPath = `${RUN_TOKENS_PATH}.${process.pid}.tmp`;
  const entries = [...triggerTokensByRun.entries()].sort(([left], [right]) => left.localeCompare(right));
  await writeFile(temporaryPath, `${JSON.stringify(Object.fromEntries(entries), null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  await rename(temporaryPath, RUN_TOKENS_PATH);
}

function rememberRunToken(runId: string, tokenId: string): Promise<void> {
  return withRunTokenLock(async () => {
    await loadRunTokens();
    triggerTokensByRun.set(runId, tokenId);
    await persistRunTokens();
  });
}

function findRunToken(runId: string): Promise<string | undefined> {
  return withRunTokenLock(async () => {
    await loadRunTokens();
    return triggerTokensByRun.get(runId);
  });
}

function forgetRunToken(runId: string): Promise<void> {
  return withRunTokenLock(async () => {
    await loadRunTokens();
    triggerTokensByRun.delete(runId);
    await persistRunTokens();
  });
}

function json(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > 1_000_000) throw new Error("Request body exceeds 1 MB");
    chunks.push(buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function executorMode(): "local" | "trigger" {
  const value = process.env.EXECUTOR || "local";
  if (value !== "local" && value !== "trigger") {
    throw new Error("EXECUTOR must be local or trigger");
  }
  return value;
}

export async function handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url || "/", "http://hands.local");

  if (request.method === "GET" && url.pathname === "/health") {
    json(response, 200, { ok: true, executor: executorMode() });
    return;
  }

  if (request.method === "POST" && url.pathname === "/execute") {
    const action = actionSchema.parse(await readJson(request));
    if (executorMode() === "local") {
      const runId = `hands-${action.id}-${randomUUID()}`;
      setImmediate(() => {
        void executeAction(action, runId).catch((error) => {
          console.error("[hands] local execution failed", error);
        });
      });
      json(response, 202, { runId });
      return;
    }

    const run = await tasks.trigger<typeof executeActionTask>("execute-action", {
      action,
    });
    json(response, 202, { runId: run.id });
    return;
  }

  if (request.method === "POST" && url.pathname === "/prepare") {
    const action = suggestedActionSchema.parse(await readJson(request));
    if (executorMode() === "local") {
      json(response, 200, { runId: null });
      return;
    }

    const token = await wait.createToken({ timeout: "30m" });
    const run = await tasks.trigger<typeof executeActionTask>("execute-action", {
      action,
      waitToken: token.id,
    });
    await rememberRunToken(run.id, token.id);
    json(response, 202, { runId: run.id, tokenId: token.id });
    return;
  }

  const runCompletion = request.method === "POST"
    ? url.pathname.match(/^\/runs\/([^/]+)\/(approve|cancel)$/)
    : null;
  if (runCompletion) {
    const runId = decodeURIComponent(runCompletion[1] || "");
    const operation = runCompletion[2];
    const tokenId = await findRunToken(runId);
    if (!tokenId) {
      json(response, 404, { error: "Unknown run id" });
      return;
    }

    if (operation === "approve") {
      const action = actionSchema.parse(await readJson(request));
      await wait.completeToken(tokenId, { approved: true, action });
    } else {
      await wait.completeToken(tokenId, { approved: false });
    }
    await forgetRunToken(runId);
    json(response, 202, { runId });
    return;
  }

  json(response, 404, { error: "Not found" });
}

export function createHandsServer(): Server {
  return createServer((request, response) => {
    void handleRequest(request, response).catch((error) => {
      const status = error instanceof ZodError || error instanceof SyntaxError ? 400 : 500;
      console.error("[hands] request failed", error);
      if (!response.headersSent) {
        json(response, status, { error: error instanceof Error ? error.message : String(error) });
      } else {
        response.end();
      }
    });
  });
}

function isMainModule(): boolean {
  return Boolean(process.argv[1]) && import.meta.url === pathToFileURL(process.argv[1] as string).href;
}

if (isMainModule()) {
  const port = Number.parseInt(process.env.HANDS_PORT || "8790", 10);
  const mode = executorMode();

  if (process.env.HANDS_RESET_CLAIMS === "1") {
    await resetClaims();
    console.info("[hands] claims reset");
  }

  createHandsServer().listen(port, "127.0.0.1", () => {
    console.info(`[hands] listening on http://127.0.0.1:${port} (${mode})`);
  });
}

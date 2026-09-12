import { randomUUID } from "node:crypto";
import { readFile, rename, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { createDoc, createEvent, createTask, sendMessage } from "./connectors/ambiguous.js";
import { answer } from "./connectors/exa.js";
import { statusCallbackSchema, type Action, type StatusCallback } from "./schema.js";

const CLAIMS_PATH = join(process.cwd(), ".hands-claims.json");
const claimedInMemory = new Set<string>();
const reservationsInMemory = new Set<string>();
let claimQueue: Promise<void> = Promise.resolve();

export type ExecutionResult = {
  runId: string;
  duplicate: boolean;
  resultUrl?: string;
};

async function readClaims(): Promise<Set<string>> {
  try {
    const parsed: unknown = JSON.parse(await readFile(CLAIMS_PATH, "utf8"));
    if (!Array.isArray(parsed) || !parsed.every((id) => typeof id === "string")) {
      throw new Error("claim file is not a string array");
    }
    return new Set(parsed);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return new Set();
    throw new Error(`Cannot safely read ${CLAIMS_PATH}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function reserveAction(id: string): Promise<boolean> {
  const operation = claimQueue.then(async () => {
    if (claimedInMemory.has(id) || reservationsInMemory.has(id)) return false;
    const persisted = await readClaims();
    if (persisted.has(id)) {
      claimedInMemory.add(id);
      return false;
    }

    reservationsInMemory.add(id);
    return true;
  });
  claimQueue = operation.then(() => undefined, () => undefined);
  return operation;
}

function claimReservedAction(id: string): Promise<void> {
  const operation = claimQueue.then(async () => {
    if (!reservationsInMemory.has(id)) {
      throw new Error(`Action ${id} is not reserved`);
    }

    const persisted = await readClaims();
    persisted.add(id);
    const temporaryPath = `${CLAIMS_PATH}.${process.pid}.tmp`;
    await writeFile(temporaryPath, `${JSON.stringify([...persisted].sort(), null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    await rename(temporaryPath, CLAIMS_PATH);
    reservationsInMemory.delete(id);
    claimedInMemory.add(id);
  });
  claimQueue = operation.then(() => undefined, () => undefined);
  return operation;
}

function releaseReservation(id: string): Promise<void> {
  const operation = claimQueue.then(() => {
    reservationsInMemory.delete(id);
  });
  claimQueue = operation.then(() => undefined, () => undefined);
  return operation;
}

export async function resetClaims(): Promise<void> {
  try {
    await unlink(CLAIMS_PATH);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
  claimedInMemory.clear();
  reservationsInMemory.clear();
}

export async function reportStatus(
  action: Pick<Action, "id" | "sessionId">,
  callback: StatusCallback,
): Promise<void> {
  const body = statusCallbackSchema.parse(callback);
  const base = (process.env.ENGINE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
  const url = `${base}/sessions/${encodeURIComponent(action.sessionId)}/actions/${encodeURIComponent(action.id)}/status`;
  const engineToken = process.env.ENGINE_TOKEN;
  const response = await fetch(url, {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      ...(engineToken ? { "X-Engine-Token": engineToken } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Engine callback failed with HTTP ${response.status}: ${await response.text()}`);
  }
}

function assertNotExpired(action: Action): void {
  if (!action.suggestedAt) return;
  const age = Date.now() - Date.parse(action.suggestedAt);
  if (age > 30 * 60 * 1_000) {
    throw new Error("Approved action expired more than 30 minutes after it was suggested");
  }
}

async function dispatch(action: Action): Promise<{ id: string; url: string }> {
  switch (action.kind) {
    case "create_task":
      return createTask(action.args);
    case "schedule_followup":
      return createEvent(action.args);
    case "draft_message":
      return sendMessage(action.args);
    case "create_doc":
      return createDoc(action.args);
    case "lookup": {
      const query = typeof action.args.query === "string" ? action.args.query : action.title;
      const result = await answer(query);
      const sources = result.citations
        .map((citation) => `- [${citation.title}](${citation.url})`)
        .join("\n");
      return createDoc({
        title: action.title,
        content: `${result.answer}\n\n## Sources\n\n${sources || "No citations returned."}`,
      });
    }
  }
}

export async function executeAction(action: Action, requestedRunId?: string): Promise<ExecutionResult> {
  const runId = requestedRunId || action.runId || `hands-${action.id}-${randomUUID()}`;
  if (!(await reserveAction(action.id))) {
    console.info("[hands] action already claimed; skipping", { actionId: action.id, runId });
    return { runId, duplicate: true };
  }

  try {
    await reportStatus(action, { status: "running", runId });
  } catch (error) {
    await releaseReservation(action.id);
    throw error;
  }

  try {
    await claimReservedAction(action.id);
  } catch (error) {
    await releaseReservation(action.id);
    throw error;
  }

  try {
    assertNotExpired(action);
    const result = await dispatch(action);
    await reportStatus(action, { status: "succeeded", runId, resultUrl: result.url });
    return { runId, duplicate: false, resultUrl: result.url };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    try {
      await reportStatus(action, { status: "failed", runId, error: message });
    } catch (callbackError) {
      console.error("[hands] failed to report action failure", callbackError);
    }
    throw error;
  }
}

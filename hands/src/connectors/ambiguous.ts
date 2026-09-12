import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { mockAmbiguous } from "../mock.js";

type ConnectorResult = { id: string; url: string };
type Arguments = Record<string, unknown>;
type LogicalTool = "tasks.create" | "calendar.createEvent" | "chat.sendMessage" | "docs.create";

const toolOverrides: Record<LogicalTool, string | undefined> = {
  "tasks.create": process.env.AMBIGUOUS_TOOL_TASKS_CREATE,
  "calendar.createEvent": process.env.AMBIGUOUS_TOOL_CALENDAR_CREATE_EVENT,
  "chat.sendMessage": process.env.AMBIGUOUS_TOOL_CHAT_SEND_MESSAGE,
  "docs.create": process.env.AMBIGUOUS_TOOL_DOCS_CREATE,
};

const toolTerms: Record<LogicalTool, string[][]> = {
  "tasks.create": [["task", "tasks"], ["create"]],
  "calendar.createEvent": [["calendar"], ["create"], ["event"]],
  "chat.sendMessage": [["chat"], ["send"], ["message"]],
  "docs.create": [["doc", "docs", "document"], ["create"]],
};

const mockKinds: Record<LogicalTool, string> = {
  "tasks.create": "create_task",
  "calendar.createEvent": "schedule_followup",
  "chat.sendMessage": "draft_message",
  "docs.create": "create_doc",
};

const toolOverrideNames: Record<LogicalTool, string> = {
  "tasks.create": "AMBIGUOUS_TOOL_TASKS_CREATE",
  "calendar.createEvent": "AMBIGUOUS_TOOL_CALENDAR_CREATE_EVENT",
  "chat.sendMessage": "AMBIGUOUS_TOOL_CHAT_SEND_MESSAGE",
  "docs.create": "AMBIGUOUS_TOOL_DOCS_CREATE",
};

let clientPromise: Promise<{ client: Client; names: string[] }> | undefined;
const resolvedNames = new Map<LogicalTool, string>();

function normalize(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]/g, "");
}

async function getClient(): Promise<{ client: Client; names: string[] }> {
  clientPromise ??= (async () => {
    const apiKey = process.env.AMBIGUOUS_API_KEY?.trim();
    if (!apiKey) {
      throw new Error("Ambiguous client requested without AMBIGUOUS_API_KEY");
    }

    const transport = new StreamableHTTPClientTransport(
      new URL(process.env.AMBIGUOUS_MCP_URL || "https://app.ambiguous.ai/mcp"),
      { requestInit: { headers: { Authorization: `Bearer ${apiKey}` } } },
    );
    const mcpClient = new Client({ name: "overheard-hands", version: "0.1.0" });
    await mcpClient.connect(transport);
    const listed = await mcpClient.listTools();
    const names = listed.tools.map((tool) => tool.name);
    console.info("[hands] Ambiguous MCP tools", names);
    return { client: mcpClient, names };
  })();

  return clientPromise;
}

function resolveToolName(logical: LogicalTool, names: string[]): string {
  const cached = resolvedNames.get(logical);
  if (cached) return cached;

  const override = toolOverrides[logical]?.trim();
  if (override) {
    const actual = names.find((name) => name === override) ??
      names.find((name) => name.toLocaleLowerCase() === override.toLocaleLowerCase());
    if (!actual) throw new Error(`Configured Ambiguous tool ${override} was not advertised`);
    resolvedNames.set(logical, actual);
    return actual;
  }

  const exact = names.find((name) => name === logical) ??
    names.find((name) => name.toLocaleLowerCase() === logical.toLocaleLowerCase());
  if (exact) {
    resolvedNames.set(logical, exact);
    return exact;
  }

  const normalizedNames = names.map((name) => ({ name, normalized: normalize(name) }));
  const fuzzy = normalizedNames.filter(({ normalized }) =>
    toolTerms[logical].every((alternatives) =>
      alternatives.some((term) => normalized.includes(normalize(term))),
    ),
  ).map(({ name }) => name);
  if (fuzzy.length === 0) {
    throw new Error(`Could not resolve Ambiguous tool ${logical}; available: ${names.join(", ")}`);
  }
  if (fuzzy.length > 1) {
    throw new Error(
      `Ambiguous tool ${logical} matched multiple advertised tools: ${fuzzy.join(", ")}; ` +
      `set ${toolOverrideNames[logical]} to the exact tool name`,
    );
  }
  const resolved = fuzzy[0] as string;
  resolvedNames.set(logical, resolved);
  return resolved;
}

function findStringByKey(value: unknown, keys: Set<string>): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findStringByKey(item, keys);
      if (found) return found;
    }
    return undefined;
  }
  for (const [key, child] of Object.entries(value)) {
    if (keys.has(key.toLocaleLowerCase()) && typeof child === "string" && child) return child;
  }
  for (const child of Object.values(value)) {
    const found = findStringByKey(child, keys);
    if (found) return found;
  }
  return undefined;
}

function parseToolResult(result: unknown): ConnectorResult {
  const values: unknown[] = [result];
  if (result && typeof result === "object" && "content" in result && Array.isArray(result.content)) {
    for (const part of result.content) {
      if (part && typeof part === "object" && "text" in part && typeof part.text === "string") {
        try {
          values.push(JSON.parse(part.text));
        } catch {
          values.push(part.text);
        }
      }
    }
  }

  let id: string | undefined;
  let url: string | undefined;
  for (const value of values) {
    id ??= findStringByKey(value, new Set(["id", "taskid", "eventid", "messageid", "documentid"]));
    url ??= findStringByKey(value, new Set(["url", "link", "resulturl"]));
    if (typeof value === "string") {
      url ??= value.match(/https?:\/\/[^\s"'<>]+/)?.[0];
    }
  }
  if (!id || !url) {
    throw new Error("Ambiguous tool result did not contain both an id and URL/link");
  }
  return { id, url };
}

async function invoke(logical: LogicalTool, args: Arguments): Promise<ConnectorResult> {
  if (!process.env.AMBIGUOUS_API_KEY?.trim()) {
    return mockAmbiguous(mockKinds[logical]);
  }
  const { client, names } = await getClient();
  const name = resolveToolName(logical, names);
  const result = await client.callTool({ name, arguments: args });
  return parseToolResult(result);
}

export const createTask = (args: Arguments): Promise<ConnectorResult> => invoke("tasks.create", args);
export const createEvent = (args: Arguments): Promise<ConnectorResult> => invoke("calendar.createEvent", args);
export const sendMessage = (args: Arguments): Promise<ConnectorResult> => invoke("chat.sendMessage", args);
export const createDoc = (args: Arguments): Promise<ConnectorResult> => invoke("docs.create", args);

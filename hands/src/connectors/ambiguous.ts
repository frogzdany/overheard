// Ambiguous AI workspace connector.
//
// The MCP server at AMBIGUOUS_MCP_URL advertises ~856 tools, so the four tools
// we need are addressed by their exact real names (overridable per deployment
// via the AMBIGUOUS_TOOL_* variables) — never by fuzzy matching, which used to
// pick the wrong neighbour out of that crowd.
//
// Every real schema this file targets is captured in scripts/ambiguous-schemas.md
// (regenerate with `npx tsx scripts/dump-ambiguous-schemas.ts`). The action args
// the engine sends are human-shaped (`due`, `assignee`, `when`, `to`, `notes`),
// so each builder below translates them into the workspace's own shape and
// resolves people/channels/calendars through the workspace's list tools.
//
// None of the create tools return a web URL, so result URLs are built from the
// SPA's own deep-link routes (read out of the app bundle):
//   task     -> /tasks?task=<id>
//   document -> /docs/<id>
//   event    -> /calendar?event=<id>
//   message  -> /chat/<channel_id>?m=<id>
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { mockAmbiguous } from "../mock.js";

type ConnectorResult = { id: string; url: string };
type Arguments = Record<string, unknown>;
type Payload = Record<string, unknown>;
export type LogicalTool = "tasks.create" | "calendar.createEvent" | "chat.sendMessage" | "docs.create";

/** The real tool names on app.ambiguous.ai, used unless an override is set. */
const defaultToolNames: Record<LogicalTool, string> = {
  "tasks.create": "create_task",
  "calendar.createEvent": "create_event",
  "chat.sendMessage": "send_message",
  "docs.create": "create_document",
};

const toolOverrideNames: Record<LogicalTool, string> = {
  "tasks.create": "AMBIGUOUS_TOOL_TASKS_CREATE",
  "calendar.createEvent": "AMBIGUOUS_TOOL_CALENDAR_CREATE_EVENT",
  "chat.sendMessage": "AMBIGUOUS_TOOL_CHAT_SEND_MESSAGE",
  "docs.create": "AMBIGUOUS_TOOL_DOCS_CREATE",
};

const mockKinds: Record<LogicalTool, string> = {
  "tasks.create": "create_task",
  "calendar.createEvent": "schedule_followup",
  "chat.sendMessage": "draft_message",
  "docs.create": "create_doc",
};

// Read-only helper tools used to turn names into the ids the create tools want.
// Each one is optional: when the workspace does not advertise it (or the caller
// lacks the role for it) the dependent argument is simply omitted.
const LIST_USERS_TOOL = "list_users";
const LIST_CHANNELS_TOOL = "list_channels";
const LIST_CALENDARS_TOOL = "list_calendars";

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

let clientPromise: Promise<{ client: Client; names: string[] }> | undefined;
const resolvedNames = new Map<LogicalTool, string>();
let usersPromise: Promise<Payload[]> | undefined;
let channelsPromise: Promise<Payload[]> | undefined;
let calendarIdPromise: Promise<string | undefined> | undefined;

function workspaceOrigin(): string {
  const raw = process.env.AMBIGUOUS_WORKSPACE_URL?.trim() || process.env.AMBIGUOUS_MCP_URL?.trim();
  try {
    return raw ? new URL(raw).origin : "https://app.ambiguous.ai";
  } catch {
    return "https://app.ambiguous.ai";
  }
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

    const names: string[] = [];
    let cursor: string | undefined;
    do {
      const page = await mcpClient.listTools(cursor ? { cursor } : undefined);
      for (const tool of page.tools) names.push(tool.name);
      cursor = page.nextCursor;
    } while (cursor);

    console.info(`[hands] Ambiguous MCP advertised ${names.length} tools`);
    return { client: mcpClient, names };
  })();

  return clientPromise;
}

function editDistance(left: string, right: string): number {
  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let row = 1; row <= left.length; row += 1) {
    let diagonal = previous[0] as number;
    previous[0] = row;
    for (let column = 1; column <= right.length; column += 1) {
      const candidate = Math.min(
        (previous[column] as number) + 1,
        (previous[column - 1] as number) + 1,
        diagonal + (left[row - 1] === right[column - 1] ? 0 : 1),
      );
      diagonal = previous[column] as number;
      previous[column] = candidate;
    }
  }
  return previous[right.length] as number;
}

function closestNames(wanted: string, names: string[], count = 5): string[] {
  return [...names]
    .map((name) => ({ name, distance: editDistance(wanted.toLocaleLowerCase(), name.toLocaleLowerCase()) }))
    .sort((left, right) => left.distance - right.distance || left.name.localeCompare(right.name))
    .slice(0, count)
    .map(({ name }) => name);
}

/**
 * Exact-match only: the configured override if present, otherwise the known real
 * name for that logical tool. No fuzzy matching — with 856 advertised tools a
 * near miss is a wrong write, not a convenience.
 */
export function resolveToolName(logical: LogicalTool, names: string[]): string {
  const cached = resolvedNames.get(logical);
  if (cached) return cached;

  const override = process.env[toolOverrideNames[logical]]?.trim();
  const wanted = override || defaultToolNames[logical];
  if (!names.includes(wanted)) {
    const source = override ? `${toolOverrideNames[logical]}=${wanted}` : `default name ${wanted}`;
    throw new Error(
      `Ambiguous does not advertise a tool named "${wanted}" for ${logical} (${source}). ` +
      `Closest advertised names: ${closestNames(wanted, names).join(", ")}. ` +
      `Set ${toolOverrideNames[logical]} to the exact tool name.`,
    );
  }
  resolvedNames.set(logical, wanted);
  return wanted;
}

function resultText(result: unknown): string {
  if (!result || typeof result !== "object" || !("content" in result) || !Array.isArray(result.content)) {
    return "";
  }
  return result.content
    .map((part) => (part && typeof part === "object" && "text" in part && typeof part.text === "string" ? part.text : ""))
    .filter(Boolean)
    .join("\n")
    .trim();
}

/** Unwraps a tool result into its payload object, honouring the MCP isError flag. */
function toolPayload(name: string, result: unknown): Payload {
  if (result && typeof result === "object" && (result as { isError?: boolean }).isError) {
    throw new Error(`Ambiguous tool ${name} failed: ${resultText(result) || "no error detail returned"}`);
  }
  const structured = result && typeof result === "object"
    ? (result as { structuredContent?: unknown }).structuredContent
    : undefined;
  if (structured && typeof structured === "object") return structured as Payload;

  const text = resultText(result);
  if (text) {
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object") return parsed as Payload;
    } catch {
      // fall through to the empty payload below
    }
  }
  return {};
}

async function callTool(name: string, args: Arguments): Promise<Payload> {
  const { client } = await getClient();
  return toolPayload(name, await client.callTool({ name, arguments: args }));
}

function rows(payload: Payload): Payload[] {
  const data = payload.data ?? payload.items ?? payload.results;
  return Array.isArray(data) ? (data.filter((row) => row && typeof row === "object") as Payload[]) : [];
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function firstString(args: Arguments, keys: string[]): string | undefined {
  for (const key of keys) {
    const found = text(args[key]);
    if (found) return found;
  }
  return undefined;
}

async function listWorkspaceUsers(): Promise<Payload[]> {
  usersPromise ??= (async () => {
    const { names } = await getClient();
    if (!names.includes(LIST_USERS_TOOL)) {
      console.info(`[hands] Ambiguous does not advertise ${LIST_USERS_TOOL}; people will not be resolved to ids`);
      return [];
    }
    try {
      return rows(await callTool(LIST_USERS_TOOL, { limit: 500 }));
    } catch (error) {
      console.warn(`[hands] ${LIST_USERS_TOOL} failed; people will not be resolved to ids:`,
        error instanceof Error ? error.message : String(error));
      return [];
    }
  })();
  return usersPromise;
}

/** Resolves a human-written name (or email/uuid) to a workspace user id. */
async function resolveUserId(person: string): Promise<string | undefined> {
  const wanted = person.trim().replace(/^@/, "");
  if (UUID.test(wanted)) return wanted;

  const needle = wanted.toLocaleLowerCase();
  const users = await listWorkspaceUsers();
  const candidates = [
    (user: Payload) => text(user.display_name)?.toLocaleLowerCase() === needle,
    (user: Payload) => [user.email, user.primary_email, user.workspace_email, user.username]
      .some((value) => text(value)?.toLocaleLowerCase() === needle),
    (user: Payload) => text(user.display_name)?.toLocaleLowerCase().split(/\s+/)[0] === needle,
    (user: Payload) => Boolean(text(user.display_name)?.toLocaleLowerCase().startsWith(needle)),
  ];
  for (const matches of candidates) {
    const user = users.find(matches);
    const id = user && text(user.id);
    if (id) return id;
  }
  console.warn(`[hands] no Ambiguous workspace user matched "${person}"; leaving it unset`);
  return undefined;
}

async function listChannels(): Promise<Payload[]> {
  channelsPromise ??= (async () => {
    const { names } = await getClient();
    if (!names.includes(LIST_CHANNELS_TOOL)) return [];
    return rows(await callTool(LIST_CHANNELS_TOOL, {}));
  })();
  return channelsPromise;
}

async function defaultCalendarId(): Promise<string | undefined> {
  calendarIdPromise ??= (async () => {
    const configured = text(process.env.AMBIGUOUS_DEFAULT_CALENDAR);
    if (configured && UUID.test(configured)) return configured;

    const { names } = await getClient();
    if (!names.includes(LIST_CALENDARS_TOOL)) return undefined;
    const calendars = rows(await callTool(LIST_CALENDARS_TOOL, {}));
    const byName = configured
      ? calendars.find((calendar) => text(calendar.name)?.toLocaleLowerCase() === configured.toLocaleLowerCase())
      : undefined;
    const chosen = byName ?? calendars.find((calendar) => calendar.is_default === true) ?? calendars[0];
    return chosen && text(chosen.id);
  })();
  return calendarIdPromise;
}

function asDate(value: unknown): string | undefined {
  const raw = text(value);
  if (!raw) return undefined;
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? undefined : new Date(parsed).toISOString().slice(0, 10);
}

function asTimestamp(value: unknown): string | undefined {
  const raw = text(value);
  if (!raw) return undefined;
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T09:00:00Z` : raw);
  return Number.isNaN(parsed) ? undefined : new Date(parsed).toISOString();
}

function requireId(payload: Payload, path: string[], toolName: string): string {
  let cursor: unknown = payload;
  for (const key of path) {
    if (!cursor || typeof cursor !== "object") break;
    cursor = (cursor as Payload)[key];
  }
  const id = text(cursor);
  if (!id) throw new Error(`Ambiguous tool ${toolName} returned no ${path.join(".")}: ${JSON.stringify(payload).slice(0, 400)}`);
  return id;
}

// ---------------------------------------------------------------- create_task

async function buildTaskArguments(args: Arguments): Promise<Arguments> {
  const title = firstString(args, ["title", "name", "summary"]);
  if (!title) throw new Error("create_task needs a title");

  const built: Arguments = { title: title.slice(0, 255) };
  const description = firstString(args, ["description", "notes", "body", "details"]);
  if (description) built.description = description;

  const dueDate = asDate(args.due_date ?? args.due ?? args.dueDate ?? args.deadline);
  if (dueDate) built.due_date = dueDate;

  const assignee = firstString(args, ["assignee_id", "assignee", "owner", "assigned_to"]);
  if (assignee) {
    const assigneeId = await resolveUserId(assignee);
    if (assigneeId) built.assignee_id = assigneeId;
  }

  const priority = firstString(args, ["priority"]);
  if (priority && ["urgent", "high", "medium", "low"].includes(priority.toLocaleLowerCase())) {
    built.priority = priority.toLocaleLowerCase();
  }
  return built;
}

// --------------------------------------------------------------- create_event

async function buildEventArguments(args: Arguments): Promise<Arguments> {
  const title = firstString(args, ["title", "name", "summary"]);
  if (!title) throw new Error("create_event needs a title");

  const start = asTimestamp(args.start_at ?? args.when ?? args.start ?? args.date);
  if (!start) throw new Error("create_event needs a start time (args.when or args.start_at)");
  const end = asTimestamp(args.end_at ?? args.end) ??
    new Date(Date.parse(start) + 30 * 60 * 1_000).toISOString();

  const calendarId = text(args.calendar_id) ?? await defaultCalendarId();
  if (!calendarId) throw new Error("create_event needs a calendar_id and none could be resolved (set AMBIGUOUS_DEFAULT_CALENDAR)");

  const built: Arguments = { calendar_id: calendarId, title, start_at: start, end_at: end };
  const description = firstString(args, ["description", "notes", "body", "agenda"]);
  if (description) built.description = description;
  const location = firstString(args, ["location"]);
  if (location) built.location = location;

  // The schema takes an array of UUIDs or emails; a bare human name would 400,
  // so names are resolved first and silently dropped when unknown.
  const raw = args.attendees ?? args.with ?? args.participants ?? args.attendee;
  const requested = (Array.isArray(raw) ? raw : [raw]).map(text).filter((value): value is string => Boolean(value));
  const attendees: string[] = [];
  for (const person of requested) {
    if (person.includes("@") || UUID.test(person)) {
      attendees.push(person);
      continue;
    }
    const id = await resolveUserId(person);
    if (id) attendees.push(id);
  }
  if (attendees.length > 0) built.attendees = attendees;

  // Past events are rejected unless forced; a follow-up scheduled from a meeting
  // that has already started is a normal case for us.
  if (Date.parse(start) < Date.now()) built.force = true;
  return built;
}

// --------------------------------------------------------------- send_message

function channelName(channel: Payload): string {
  return text(channel.name)?.toLocaleLowerCase() ?? "";
}

function isDirectMessageWith(channel: Payload, person: string): boolean {
  if (text(channel.type) !== "dm") return false;
  const needle = person.toLocaleLowerCase().replace(/^@/, "");
  if (channelName(channel).includes(needle)) return true;
  const members = Array.isArray(channel.members) ? (channel.members as Payload[]) : [];
  return members.some((member) => {
    const name = text(member.display_name)?.toLocaleLowerCase();
    const email = text(member.primary_email)?.toLocaleLowerCase();
    return name === needle || name?.split(/\s+/)[0] === needle || email === needle;
  });
}

async function buildMessageArguments(args: Arguments): Promise<Arguments> {
  const body = firstString(args, ["content", "body", "message", "text", "draft"]);
  if (!body) throw new Error("send_message needs a body");
  const to = firstString(args, ["to", "recipient", "audience"]);

  const explicit = text(args.channel_id);
  const configured = text(process.env.AMBIGUOUS_DEFAULT_CHANNEL);
  const channels = explicit ? [] : await listChannels();

  let channel: Payload | undefined;
  if (!explicit && configured) {
    const needle = configured.toLocaleLowerCase().replace(/^#/, "");
    channel = channels.find((row) => text(row.id) === configured) ??
      channels.find((row) => channelName(row) === needle);
    if (!channel && UUID.test(configured)) {
      return { channel_id: configured, content: to ? `@${to} ${body}` : body };
    }
    if (!channel) {
      throw new Error(`AMBIGUOUS_DEFAULT_CHANNEL="${configured}" matched no channel; available: ${
        channels.map((row) => text(row.name) ?? text(row.id)).join(", ")}`);
    }
  }

  // A direct message to the named recipient is the closest thing to "send this
  // to <person>"; only when there is no DM channel do we fall back to posting
  // in a shared channel and addressing them in the body.
  let addressInBody = Boolean(to);
  if (!explicit && !channel && to) {
    const direct = channels.find((row) => isDirectMessageWith(row, to));
    if (direct) {
      channel = direct;
      addressInBody = false;
    }
  }
  if (!explicit && !channel) {
    channel = channels.find((row) => channelName(row).includes("general")) ??
      channels.find((row) => text(row.type) !== "dm") ??
      channels[0];
  }

  const channelId = explicit ?? (channel && text(channel.id));
  if (!channelId) throw new Error("send_message found no channel to post in (set AMBIGUOUS_DEFAULT_CHANNEL)");
  return { channel_id: channelId, content: addressInBody && to ? `@${to} ${body}` : body };
}

// ------------------------------------------------------------ create_document

function buildDocumentArguments(args: Arguments): Arguments {
  const requested = firstString(args, ["type"])?.toLocaleLowerCase();
  const built: Arguments = { type: requested && ["doc", "sheet", "slide"].includes(requested) ? requested : "doc" };
  const title = firstString(args, ["title", "name", "summary"]);
  if (title) built.title = title;
  const content = firstString(args, ["content", "body", "markdown", "text", "notes"]);
  if (content) built.content = content;
  return built;
}

// ---------------------------------------------------------------- dispatching

async function invoke(
  logical: LogicalTool,
  build: (args: Arguments) => Arguments | Promise<Arguments>,
  read: (payload: Payload, toolName: string) => ConnectorResult,
  args: Arguments,
): Promise<ConnectorResult> {
  if (!process.env.AMBIGUOUS_API_KEY?.trim()) {
    return mockAmbiguous(mockKinds[logical]);
  }
  const { names } = await getClient();
  const name = resolveToolName(logical, names);
  const payload = await callTool(name, await build(args));
  return read(payload, name);
}

export const createTask = (args: Arguments): Promise<ConnectorResult> =>
  invoke("tasks.create", buildTaskArguments, (payload, name) => {
    const id = requireId(payload.task ? payload : { task: payload }, ["task", "id"], name);
    return { id, url: `${workspaceOrigin()}/tasks?task=${encodeURIComponent(id)}` };
  }, args);

export const createEvent = (args: Arguments): Promise<ConnectorResult> =>
  invoke("calendar.createEvent", buildEventArguments, (payload, name) => {
    const source = (payload.event && typeof payload.event === "object" ? payload.event : payload) as Payload;
    const id = requireId(source, ["id"], name);
    return { id, url: `${workspaceOrigin()}/calendar?event=${encodeURIComponent(id)}` };
  }, args);

export const sendMessage = (args: Arguments): Promise<ConnectorResult> =>
  invoke("chat.sendMessage", buildMessageArguments, (payload, name) => {
    const source = (payload.message && typeof payload.message === "object" ? payload.message : payload) as Payload;
    const id = requireId(source, ["id"], name);
    const channelId = text(source.channel_id);
    return {
      id,
      url: channelId
        ? `${workspaceOrigin()}/chat/${encodeURIComponent(channelId)}?m=${encodeURIComponent(id)}`
        : `${workspaceOrigin()}/chat`,
    };
  }, args);

export const createDoc = (args: Arguments): Promise<ConnectorResult> =>
  invoke("docs.create", buildDocumentArguments, (payload, name) => {
    const source = (payload.document && typeof payload.document === "object" ? payload.document : payload) as Payload;
    const id = requireId(source, ["id"], name);
    return { id, url: `${workspaceOrigin()}/docs/${encodeURIComponent(id)}` };
  }, args);

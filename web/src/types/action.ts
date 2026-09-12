// Suggested actions: the engine watches the meeting, proposes a concrete
// follow-through ("send Ana the diagram"), and the user approves, edits or
// rejects it before any tool runs. Human-in-the-loop by construction — nothing
// executes on `suggested`.
import type { IconType } from "react-icons"
import {
  LuCalendarClock,
  LuFileText,
  LuListTodo,
  LuMail,
  LuSearch,
} from "react-icons/lu"

export type ActionKind =
  | "create_task"
  | "schedule_followup"
  | "draft_message"
  | "create_doc"
  | "lookup"

export type ActionStatus =
  | "suggested"
  | "approved"
  | "running"
  | "succeeded"
  | "failed"
  | "rejected"
  | "expired"

/** Arbitrary tool payload. Values stay loose (the engine owns the schema per
 * tool); the UI only edits the fields KIND_META declares editable. */
export type ActionArgs = Record<string, unknown>

export interface Action {
  id: string
  kind: ActionKind
  title: string
  rationale: string
  /** Verbatim transcript quotes that justify the suggestion. */
  evidence: string[]
  /** 0..1 — how sure the engine is. Rendered as a subtle meter. */
  confidence: number
  /** Dotted tool id the engine will invoke, e.g. "ambiguous.tasks.create". */
  tool: string
  args: ActionArgs
  status: ActionStatus
  approvedBy?: string | null
  runId?: string | null
  resultUrl?: string | null
}

/** Input affordance for one editable `args` field. */
export type ActionFieldType = "text" | "textarea" | "date" | "email"

export interface ActionField {
  /** Key inside `action.args`. */
  key: string
  label: string
  type: ActionFieldType
  placeholder?: string
}

export interface ActionKindMeta {
  label: string
  icon: IconType
  /** Chakra colorPalette token — never a raw hex. */
  accent: string
  /** Which `args` fields the user may edit before approving, in render order. */
  fields: ActionField[]
}

export const KIND_META: Record<ActionKind, ActionKindMeta> = {
  create_task: {
    label: "Task",
    icon: LuListTodo,
    accent: "blue",
    fields: [
      { key: "title", label: "Task", type: "text", placeholder: "What needs doing" },
      { key: "assignee", label: "Assignee", type: "text", placeholder: "Who owns it" },
      { key: "due", label: "Due", type: "date" },
      { key: "notes", label: "Notes", type: "textarea", placeholder: "Optional context" },
    ],
  },
  schedule_followup: {
    label: "Follow-up",
    icon: LuCalendarClock,
    accent: "purple",
    fields: [
      { key: "title", label: "Title", type: "text", placeholder: "Meeting title" },
      { key: "when", label: "When", type: "text", placeholder: "2026-09-16T10:00:00" },
      {
        key: "attendees",
        label: "Attendees",
        type: "text",
        placeholder: "name@company.com, Jane",
      },
      { key: "notes", label: "Notes", type: "textarea", placeholder: "Optional context" },
    ],
  },
  draft_message: {
    label: "Message",
    icon: LuMail,
    accent: "teal",
    fields: [
      { key: "to", label: "To", type: "email", placeholder: "name@company.com" },
      { key: "body", label: "Body", type: "textarea", placeholder: "Draft the message" },
    ],
  },
  create_doc: {
    label: "Doc",
    icon: LuFileText,
    accent: "orange",
    fields: [
      { key: "title", label: "Title", type: "text", placeholder: "Document title" },
      { key: "body", label: "Body", type: "textarea", placeholder: "Document body" },
    ],
  },
  lookup: {
    label: "Lookup",
    icon: LuSearch,
    accent: "cyan",
    fields: [
      { key: "query", label: "Query", type: "text", placeholder: "What to look up" },
    ],
  },
}

/** Safe accessor: an unknown kind from a newer engine still renders. */
export function kindMeta(kind: ActionKind): ActionKindMeta {
  return KIND_META[kind] ?? KIND_META.create_task
}

/** Nothing has run yet — the card still offers Approve/Reject. */
export const PENDING_STATUSES: ActionStatus[] = ["suggested"]
export const IN_PROGRESS_STATUSES: ActionStatus[] = ["approved", "running"]
export const DONE_STATUSES: ActionStatus[] = [
  "succeeded",
  "failed",
  "rejected",
  "expired",
]

/** Dotted tool id the engine (or a chat-created action) will invoke. */
export const TOOL_BY_KIND: Record<ActionKind, string> = {
  create_task: "ambiguous.tasks.create",
  schedule_followup: "ambiguous.calendar.createEvent",
  draft_message: "ambiguous.chat.sendMessage",
  create_doc: "ambiguous.docs.create",
  lookup: "exa.answer",
}

/** Coerce ActionCard edits back to the engine/chat args schema. Attendees is
 * edited as a comma-separated text field but stored as `string[]`. */
export function normalizeArgs(kind: ActionKind, args: ActionArgs): ActionArgs {
  const next: ActionArgs = { ...args }
  if (kind === "schedule_followup" && typeof next.attendees === "string") {
    next.attendees = next.attendees
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  }
  return next
}

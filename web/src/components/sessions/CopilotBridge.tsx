"use client"

import { useMemo, useState } from "react"
import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core"
import { CopilotSidebar } from "@copilotkit/react-ui"
import type { CopilotKitCSSProperties } from "@copilotkit/react-ui"
import { ActionCard } from "./ActionCard"
import { engineApi } from "@/lib/engine"
import type { LiveTranscriptLine } from "@/lib/engine"
import { accountSub } from "@/lib/auth"
import { useColorMode } from "@/components/ui/color-mode"
import {
  TOOL_BY_KIND,
  kindMeta,
  normalizeArgs,
  type Action,
  type ActionArgs,
  type ActionKind,
  type ActionStatus,
} from "@/types/action"

export interface CopilotBridgeProps {
  sessionId: string
  transcript: LiveTranscriptLine[]
  actions: Action[]
  onApprove: (action: Action, args: ActionArgs) => void | Promise<void>
  onReject: (action: Action) => void | Promise<void>
}

function random8hex(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
}

function speakerOf(line: LiveTranscriptLine): string {
  return line.speaker?.trim() || "Unknown"
}

function titleFor(kind: ActionKind, args: ActionArgs): string {
  const title = args.title
  if (typeof title === "string" && title.trim()) return title
  if (kind === "draft_message" && typeof args.to === "string") {
    return `Message to ${args.to}`
  }
  if (kind === "lookup" && typeof args.query === "string") return args.query
  return kindMeta(kind).label
}

function syntheticAction(
  id: string,
  kind: ActionKind,
  args: ActionArgs,
  status: ActionStatus,
): Action {
  return {
    id,
    kind,
    title: titleFor(kind, args),
    rationale: "Requested in chat",
    evidence: [],
    confidence: 1,
    tool: TOOL_BY_KIND[kind],
    args,
    status,
  }
}

function cardStatus(
  renderStatus: string,
  result: unknown,
): ActionStatus {
  if (renderStatus !== "complete") return "suggested"
  if (result && typeof result === "object" && "approved" in result) {
    return (result as { approved?: boolean }).approved ? "approved" : "rejected"
  }
  return "approved"
}

const KIND_DESCRIPTIONS: Record<ActionKind, string> = {
  create_task: "Create a task from this meeting.",
  schedule_followup: "Schedule a follow-up meeting.",
  draft_message: "Draft a message to send.",
  create_doc: "Create a document.",
  lookup: "Look something up.",
}

const KIND_PARAMETERS: Record<
  ActionKind,
  { name: string; type: "string" | "string[]"; description: string; required: boolean }[]
> = {
  create_task: [
    { name: "title", type: "string", description: "Task title", required: true },
    { name: "assignee", type: "string", description: "Who owns it", required: false },
    {
      name: "due",
      type: "string",
      description: "Due date as ISO date (YYYY-MM-DD)",
      required: false,
    },
    { name: "notes", type: "string", description: "Optional context", required: false },
  ],
  schedule_followup: [
    { name: "title", type: "string", description: "Meeting title", required: true },
    {
      name: "when",
      type: "string",
      description: "Start time as ISO datetime",
      required: true,
    },
    {
      name: "attendees",
      type: "string[]",
      description: "Emails or names of attendees",
      required: true,
    },
    { name: "notes", type: "string", description: "Optional context", required: false },
  ],
  draft_message: [
    { name: "to", type: "string", description: "Recipient", required: true },
    { name: "body", type: "string", description: "Message body", required: true },
  ],
  create_doc: [
    { name: "title", type: "string", description: "Document title", required: true },
    { name: "body", type: "string", description: "Document body", required: true },
  ],
  lookup: [
    { name: "query", type: "string", description: "What to look up", required: true },
  ],
}

function ChatActionCard({
  sessionId,
  kind,
  args,
  status,
  result,
  respond,
}: {
  sessionId: string
  kind: ActionKind
  args: ActionArgs
  status: string
  result: unknown
  respond?: (result: unknown) => void
}) {
  const [id] = useState(() => "chat-" + random8hex())
  const normalized = normalizeArgs(kind, args)
  const action = useMemo(
    () => syntheticAction(id, kind, normalized, cardStatus(status, result)),
    [id, kind, normalized, status, result],
  )

  const onApprove = async (edited: ActionArgs) => {
    const who = (await accountSub()) ?? "local"
    const nextArgs = normalizeArgs(kind, edited)
    const approved: Action = {
      ...syntheticAction(id, kind, nextArgs, "approved"),
      approvedBy: who,
    }
    try {
      await engineApi.createAction(sessionId, approved)
      respond?.({ approved: true, id })
    } catch (e) {
      respond?.({
        approved: false,
        error: e instanceof Error ? e.message : String(e),
      })
    }
  }

  return (
    <ActionCard
      action={action}
      busy={status === "executing"}
      onApprove={(edited) => void onApprove(edited)}
      onReject={() => respond?.({ approved: false })}
    />
  )
}

function KindAction({
  sessionId,
  kind,
}: {
  sessionId: string
  kind: ActionKind
}) {
  useCopilotAction(
    {
      name: kind,
      description: KIND_DESCRIPTIONS[kind],
      parameters: KIND_PARAMETERS[kind],
      renderAndWaitForResponse: ({ args, status, respond, result }) => (
        <ChatActionCard
          sessionId={sessionId}
          kind={kind}
          args={args as ActionArgs}
          status={status}
          result={result}
          respond={respond}
        />
      ),
    },
    [sessionId, kind],
  )
  return null
}

export function CopilotBridge({
  sessionId,
  transcript,
  actions,
  onApprove,
  onReject,
}: CopilotBridgeProps) {
  const lastTranscript = useMemo(() => {
    return transcript.slice(-60).map((line) => `${speakerOf(line)}: ${line.text}`)
  }, [transcript])

  const actionSummaries = useMemo(
    () =>
      actions.map((a) => ({
        id: a.id,
        kind: a.kind,
        title: a.title,
        status: a.status,
      })),
    [actions],
  )

  useCopilotReadable({
    description: "Last 60 transcript lines from this meeting, with speaker labels",
    value: lastTranscript,
  })

  useCopilotReadable({
    description: "Suggested and in-flight actions for this meeting (id, kind, title, status)",
    value: actionSummaries,
  })

  useCopilotAction(
    {
      name: "approve_action",
      description:
        "Approve a suggested action already in this meeting's list, by id. Use when the user says to approve an existing task, follow-up, message, doc, or lookup.",
      parameters: [
        { name: "id", type: "string", description: "The action id to approve", required: true },
      ],
      handler: async ({ id }) => {
        const action = actions.find((a) => a.id === id)
        if (!action) return { ok: false, error: `No action with id ${id}` }
        await onApprove(action, action.args)
        return { ok: true, id }
      },
    },
    [actions, onApprove],
  )

  useCopilotAction(
    {
      name: "reject_action",
      description:
        "Reject a suggested action already in this meeting's list, by id. Use when the user says to reject or dismiss an existing action.",
      parameters: [
        { name: "id", type: "string", description: "The action id to reject", required: true },
      ],
      handler: async ({ id }) => {
        const action = actions.find((a) => a.id === id)
        if (!action) return { ok: false, error: `No action with id ${id}` }
        await onReject(action)
        return { ok: true, id }
      },
    },
    [actions, onReject],
  )

  return (
    <>
      <KindAction sessionId={sessionId} kind="create_task" />
      <KindAction sessionId={sessionId} kind="schedule_followup" />
      <KindAction sessionId={sessionId} kind="draft_message" />
      <KindAction sessionId={sessionId} kind="create_doc" />
      <KindAction sessionId={sessionId} kind="lookup" />
    </>
  )
}

const SIDEBAR_LABELS = {
  title: "Overheard",
  initial:
    'Ask about this meeting or tell me what to do: "create a task for the diagram", "schedule a follow-up Tuesday 10am", "look up Acme pricing".',
} as const

/** Session-only chat sidebar. CopilotKit's CSS already keys off `.dark` (the
 * class next-themes puts on <html>); we still stamp the resolved mode on the
 * wrapper so the floating panel inherits Chakra's color mode. */
export function SessionCopilotSidebar() {
  const { colorMode } = useColorMode()
  return (
    <div
      className={colorMode === "dark" ? "dark" : undefined}
      style={
        {
          colorScheme: colorMode,
        } as CopilotKitCSSProperties
      }
    >
      <CopilotSidebar defaultOpen={false} labels={SIDEBAR_LABELS} />
    </div>
  )
}

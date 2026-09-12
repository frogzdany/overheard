"use client"

// One suggested action, end to end: what the engine wants to do, why it thinks
// so, the evidence, and the approve/edit/reject controls.
//
// Deliberately presentational — every input arrives as a prop and nothing here
// reaches for session context or the engine client. The same card is rendered
// inside the Actions tab today and inside the CopilotKit chat later.

import { useState } from "react"
import {
  Badge,
  Box,
  Button,
  Field,
  Flex,
  Icon,
  Input,
  Link,
  Spinner,
  Stack,
  Text,
  Textarea,
} from "@chakra-ui/react"
import {
  LuCheck,
  LuCircleCheck,
  LuCircleX,
  LuClock,
  LuExternalLink,
  LuPencil,
  LuX,
} from "react-icons/lu"
import type { IconType } from "react-icons"
import {
  kindMeta,
  type Action,
  type ActionArgs,
  type ActionField,
  type ActionStatus,
} from "@/types/action"

export interface ActionCardProps {
  action: Action
  /** Approve with the (possibly edited) args the user is looking at. */
  onApprove: (args: ActionArgs) => void
  onReject: () => void
  /** A request for this action is in flight — locks the controls. */
  busy?: boolean
}

interface StatusMeta {
  label: string
  palette: string
  icon: IconType | null
}

const STATUS_META: Record<ActionStatus, StatusMeta> = {
  suggested: { label: "Suggested", palette: "gray", icon: null },
  approved: { label: "Approved — queued", palette: "blue", icon: LuCheck },
  running: { label: "Running…", palette: "blue", icon: null },
  succeeded: { label: "Done", palette: "green", icon: LuCircleCheck },
  failed: { label: "Failed", palette: "red", icon: LuCircleX },
  rejected: { label: "Rejected", palette: "gray", icon: LuX },
  expired: { label: "Expired", palette: "gray", icon: LuClock },
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ")
  return typeof value === "string" ? value : String(value)
}

function draftFrom(args: ActionArgs, fields: ActionField[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of fields) out[f.key] = asText(args[f.key])
  return out
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value || 0)) * 100)
  return (
    <Flex align="center" gap="2" flexShrink={0} title={`Confidence ${pct}%`}>
      <Box
        w="14"
        h="1.5"
        rounded="full"
        bg="bg.emphasized"
        overflow="hidden"
        aria-hidden
      >
        <Box w={`${pct}%`} h="full" bg="colorPalette.solid" />
      </Box>
      <Text fontSize="xs" color="fg.muted" fontVariantNumeric="tabular-nums">
        {pct}%
      </Text>
    </Flex>
  )
}

function StatusStrip({ action }: { action: Action }) {
  const meta = STATUS_META[action.status] ?? STATUS_META.suggested
  return (
    <Flex
      align="center"
      gap="2"
      wrap="wrap"
      px="3"
      py="2"
      rounded="md"
      bg="bg.subtle"
      borderWidth="1px"
      borderColor="border"
      colorPalette={meta.palette}
    >
      {action.status === "running" ? (
        <Spinner size="xs" color="colorPalette.solid" />
      ) : meta.icon ? (
        <Icon as={meta.icon} color="colorPalette.fg" boxSize="4" />
      ) : null}
      <Text fontSize="sm" fontWeight="medium" color="colorPalette.fg">
        {meta.label}
      </Text>
      {action.approvedBy ? (
        <Text fontSize="xs" color="fg.muted">
          by {action.approvedBy}
        </Text>
      ) : null}
      {action.runId ? (
        <Text fontSize="xs" color="fg.muted" fontFamily="mono">
          {action.runId}
        </Text>
      ) : null}
      {action.resultUrl ? (
        <Link
          href={action.resultUrl}
          target="_blank"
          rel="noreferrer"
          fontSize="sm"
          color="colorPalette.fg"
          ms="auto"
        >
          Open result <LuExternalLink />
        </Link>
      ) : null}
    </Flex>
  )
}

export function ActionCard({ action, onApprove, onReject, busy }: ActionCardProps) {
  const meta = kindMeta(action.kind)
  const [editing, setEditing] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    draftFrom(action.args, meta.fields),
  )

  const pending = action.status === "suggested"
  // Untouched args go back to the engine exactly as they arrived — no
  // string-coercing values the user never looked at.
  const effectiveArgs: ActionArgs = dirty ? { ...action.args, ...draft } : action.args

  const openEditor = () => {
    if (!dirty) setDraft(draftFrom(action.args, meta.fields))
    setEditing(true)
  }

  const setField = (key: string, value: string) => {
    setDirty(true)
    setDraft((d) => ({ ...d, [key]: value }))
  }

  const filled = meta.fields.filter((f) => asText(effectiveArgs[f.key]).trim() !== "")

  return (
    <Box
      p="4"
      borderWidth="1px"
      borderColor="border"
      borderLeftWidth="3px"
      borderLeftColor="colorPalette.solid"
      rounded="md"
      bg="bg.panel"
      colorPalette={meta.accent}
      opacity={action.status === "rejected" || action.status === "expired" ? 0.7 : 1}
    >
      <Stack gap="3">
        <Flex align="flex-start" justify="space-between" gap="3" wrap="wrap">
          <Flex align="center" gap="2" minW="0" flex="1">
            <Badge variant="subtle" colorPalette={meta.accent} flexShrink={0}>
              <Icon as={meta.icon} boxSize="3.5" />
              {meta.label}
            </Badge>
            <Text fontWeight="medium" lineHeight="short">
              {action.title}
            </Text>
          </Flex>
          <ConfidenceMeter value={action.confidence} />
        </Flex>

        {action.rationale ? (
          <Text fontSize="sm" color="fg.muted">
            {action.rationale}
          </Text>
        ) : null}

        {action.evidence?.length ? (
          <Stack gap="2">
            {action.evidence.map((quote, i) => (
              <Text
                key={i}
                fontSize="sm"
                fontStyle="italic"
                color="fg.muted"
                borderLeftWidth="2px"
                borderColor="border.emphasized"
                ps="3"
              >
                &ldquo;{quote}&rdquo;
              </Text>
            ))}
          </Stack>
        ) : null}

        {editing ? (
          <Stack gap="3" p="3" rounded="md" bg="bg.subtle" borderWidth="1px" borderColor="border">
            {meta.fields.map((f) => (
              <Field.Root key={f.key}>
                <Field.Label fontSize="xs" color="fg.muted">
                  {f.label}
                </Field.Label>
                {f.type === "textarea" ? (
                  <Textarea
                    size="sm"
                    rows={3}
                    bg="bg"
                    value={draft[f.key] ?? ""}
                    placeholder={f.placeholder}
                    onChange={(e) => setField(f.key, e.target.value)}
                  />
                ) : (
                  <Input
                    size="sm"
                    bg="bg"
                    type={f.type === "date" ? "date" : f.type === "email" ? "email" : "text"}
                    value={draft[f.key] ?? ""}
                    placeholder={f.placeholder}
                    onChange={(e) => setField(f.key, e.target.value)}
                  />
                )}
              </Field.Root>
            ))}
          </Stack>
        ) : filled.length ? (
          <Stack gap="1" fontSize="sm">
            {filled.map((f) => (
              <Flex key={f.key} gap="2" align="baseline">
                <Text color="fg.muted" minW="20" flexShrink={0}>
                  {f.label}
                </Text>
                <Text whiteSpace="pre-wrap" lineClamp={2}>
                  {asText(effectiveArgs[f.key])}
                </Text>
              </Flex>
            ))}
          </Stack>
        ) : null}

        {/* EXECUTOR=trigger stages the run (and its approval waitpoint) the
            moment the action is suggested, so a still-pending card already has
            a runId. Show the strip then too — otherwise the one visible proof
            that the run exists before approval never reaches the UI. */}
        {!pending || action.runId ? <StatusStrip action={action} /> : null}

        <Flex align="center" gap="2" wrap="wrap">
          <Text fontSize="xs" color="fg.muted" fontFamily="mono" title="Tool the engine will call">
            {action.tool}
          </Text>
          <Flex gap="2" ms="auto" wrap="wrap">
            {pending ? (
              <>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => (editing ? setEditing(false) : openEditor())}
                  disabled={busy}
                >
                  {editing ? <LuCheck /> : <LuPencil />}
                  {editing ? "Done" : "Edit"}
                </Button>
                <Button size="sm" variant="outline" onClick={onReject} disabled={busy}>
                  Reject
                </Button>
                <Button
                  size="sm"
                  colorPalette="green"
                  loading={busy}
                  onClick={() => onApprove(effectiveArgs)}
                >
                  Approve
                </Button>
              </>
            ) : null}
          </Flex>
        </Flex>
      </Stack>
    </Box>
  )
}

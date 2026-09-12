"use client"

// The Actions tab: everything the engine has proposed for this session, split
// by where it sits in the approve → run → done lifecycle. This is the only
// place that knows about the session or the engine client — ActionCard itself
// stays portable so the CopilotKit chat can render it later.

import { useMemo, useState } from "react"
import {
  Alert,
  Box,
  Collapsible,
  Flex,
  Heading,
  Stack,
  Text,
} from "@chakra-ui/react"
import { LuChevronRight } from "react-icons/lu"
import { ActionCard } from "./ActionCard"
import { engineApi } from "@/lib/engine"
import { accountSub } from "@/lib/auth"
import {
  DONE_STATUSES,
  IN_PROGRESS_STATUSES,
  PENDING_STATUSES,
  type Action,
  type ActionArgs,
  normalizeArgs,
} from "@/types/action"

interface Props {
  sessionId: string
  actions: Action[]
  /** Demo mode (`?mock=actions`): approve/reject resolve locally instead of
   * calling an engine that isn't there. Never set on the real session path. */
  mock?: boolean
  /** Demo mode only — feed a lifecycle step back into the session stream so
   * every consumer (tab badge included) sees the same state. */
  onMockUpdate?: (action: Action) => void
}

/** Local optimistic patch applied over the streamed action until the engine's
 * own `action.updated` catches up (or the request fails and we roll back). */
type Patch = Partial<Pick<Action, "status" | "args" | "approvedBy">>

function Group({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  return (
    <Stack gap="3">
      <Flex align="baseline" gap="2">
        <Heading size="sm">{title}</Heading>
        <Text fontSize="xs" color="fg.muted">
          {count}
        </Text>
      </Flex>
      {children}
    </Stack>
  )
}

export function ActionsTab({
  sessionId,
  actions,
  mock = false,
  onMockUpdate,
}: Props) {
  const [patches, setPatches] = useState<Record<string, Patch>>({})
  const [busyIds, setBusyIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  // A patch only stands in for the engine while the streamed action is still
  // `suggested`. The moment the engine's own `action.updated` lands the patch
  // is ignored — otherwise it pins the card at "Approved — queued" forever and
  // the run's later running / succeeded / failed never shows.
  const merged = useMemo(
    () =>
      actions.map((a) => {
        const patch = a.status === "suggested" ? patches[a.id] : undefined
        return patch ? { ...a, ...patch } : a
      }),
    [actions, patches],
  )

  const pending = merged.filter((a) => PENDING_STATUSES.includes(a.status))
  const inProgress = merged.filter((a) => IN_PROGRESS_STATUSES.includes(a.status))
  const done = merged.filter((a) => DONE_STATUSES.includes(a.status))

  const setBusy = (id: string, on: boolean) =>
    setBusyIds((ids) => (on ? [...ids, id] : ids.filter((x) => x !== id)))

  const approve = async (action: Action, args: ActionArgs) => {
    const who = (await accountSub()) ?? "local"
    const normalized = normalizeArgs(action.kind, args)
    setError(null)
    setBusy(action.id, true)
    setPatches((p) => ({
      ...p,
      [action.id]: { status: "approved", args: normalized, approvedBy: who },
    }))
    if (mock) {
      // Play the lifecycle the engine would drive over `action.updated`.
      const base = { ...action, args: normalized, approvedBy: who }
      setPatches((p) => {
        const next = { ...p }
        delete next[action.id]
        return next
      })
      setBusy(action.id, false)
      onMockUpdate?.({ ...base, status: "approved" })
      setTimeout(() => onMockUpdate?.({ ...base, status: "running" }), 800)
      setTimeout(
        () =>
          onMockUpdate?.({
            ...base,
            status: "succeeded",
            runId: `run_${action.id}`,
          }),
        2200,
      )
      return
    }
    try {
      await engineApi.approveAction(sessionId, action.id, normalized, who)
    } catch (e) {
      // Roll the card back so the user can retry rather than staring at a
      // queued action the engine never heard about.
      setPatches((p) => {
        const next = { ...p }
        delete next[action.id]
        return next
      })
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(action.id, false)
    }
  }

  const reject = async (action: Action) => {
    setError(null)
    setBusy(action.id, true)
    setPatches((p) => ({ ...p, [action.id]: { status: "rejected" } }))
    if (mock) {
      setPatches((p) => {
        const next = { ...p }
        delete next[action.id]
        return next
      })
      setBusy(action.id, false)
      onMockUpdate?.({ ...action, status: "rejected" })
      return
    }
    try {
      await engineApi.rejectAction(sessionId, action.id)
    } catch (e) {
      setPatches((p) => {
        const next = { ...p }
        delete next[action.id]
        return next
      })
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(action.id, false)
    }
  }

  const cardsFor = (list: Action[]) =>
    list.map((a) => (
      <ActionCard
        key={a.id}
        action={a}
        busy={busyIds.includes(a.id)}
        onApprove={(args) => void approve(a, args)}
        onReject={() => void reject(a)}
      />
    ))

  if (!merged.length) {
    return (
      <Box py="10" textAlign="center" color="fg.muted">
        <Text>No suggested actions yet.</Text>
        <Text fontSize="sm" mt="2">
          When the engine spots a commitment, a follow-up or a document worth
          creating, it proposes it here for your approval. Nothing runs until
          you approve it.
        </Text>
      </Box>
    )
  }

  return (
    <Stack gap="6" pt="2">
      {error ? (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Could not reach the engine</Alert.Title>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      {pending.length ? (
        <Group title="Pending your approval" count={pending.length}>
          <Stack gap="3">{cardsFor(pending)}</Stack>
        </Group>
      ) : null}

      {inProgress.length ? (
        <Group title="In progress" count={inProgress.length}>
          <Stack gap="3">{cardsFor(inProgress)}</Stack>
        </Group>
      ) : null}

      {done.length ? (
        <Collapsible.Root>
          <Collapsible.Trigger
            cursor="pointer"
            width="100%"
            textAlign="start"
            _open={{ "& svg": { transform: "rotate(90deg)" } }}
          >
            <Flex align="center" gap="2" color="fg.muted">
              <LuChevronRight />
              <Heading size="sm" color="fg">
                Done
              </Heading>
              <Text fontSize="xs">{done.length}</Text>
            </Flex>
          </Collapsible.Trigger>
          <Collapsible.Content>
            <Stack gap="3" pt="3">
              {cardsFor(done)}
            </Stack>
          </Collapsible.Content>
        </Collapsible.Root>
      ) : null}
    </Stack>
  )
}
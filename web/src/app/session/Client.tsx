"use client"

import { useEffect, useRef, useState } from "react"
import {
  Alert,
  Badge,
  Box,
  Button,
  Editable,
  Flex,
  IconButton,
  Spinner,
  Tabs,
  Text,
} from "@chakra-ui/react"
import { useRouter } from "next/navigation"
import { formatDateTime } from "@/lib/format"
import { SessionNotices } from "@/components/sessions/SessionNotices"
import { LuArrowLeft, LuCheck, LuPencil, LuPlay, LuSquare, LuTrash2, LuX } from "react-icons/lu"
import { engineApi } from "@/lib/engine"
import { NewSessionDialog } from "@/components/sessions/NewSessionDialog"
import { useSessionStream } from "@/lib/useSessionStream"
import { TranscriptTab } from "@/components/sessions/TranscriptTab"
import { SummaryTab } from "@/components/sessions/SummaryTab"
import { QuestionsTab } from "@/components/sessions/QuestionsTab"
import { ActionsTab } from "@/components/sessions/ActionsTab"
import {
  CopilotBridge,
  SessionCopilotSidebar,
} from "@/components/sessions/CopilotBridge"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import { accountSub } from "@/lib/auth"
import {
  normalizeArgs,
  type Action,
  type ActionArgs,
} from "@/types/action"

export function SessionDetailClient({
  id,
  mock = false,
}: {
  /** Demo mode (`?mock=actions`): fixture data, no engine, no socket. */
  id: string
  mock?: boolean
}) {
  const router = useRouter()
  const state = useSessionStream(id, { mock })
  const [stopping, setStopping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string>(mock ? "actions" : "transcript")
  const [titleOverride, setTitleOverride] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [continueOpen, setContinueOpen] = useState(false)
  // Stays true from the moment the user clicks Stop until either the
  // `session.ended` event arrives over the websocket or 30 s elapse (matches
  // the engine-side stop timeout). The HTTP request itself returns fast on
  // some paths, so we can't rely on `stopping` for the user-visible overlay.
  const [finalizeTimedOut, setFinalizeTimedOut] = useState(false)
  const [stopRequestedAt, setStopRequestedAt] = useState<number | null>(null)
  const isLive = state.detail?.status === "live" && !state.ended
  // The overlay stays up from the click on Stop until either `session.ended`
  // arrives or the 30 s safety timer fires.
  const finalizing = stopRequestedAt !== null && !state.ended && !finalizeTimedOut
  const titleSource = titleOverride ?? state.detail?.title ?? id
  // Once we've auto-flipped to Summary on session end, don't re-flip if the
  // user manually clicks back to another tab.
  const autoSwitchedRef = useRef(false)

  // When a live session ends (either via Stop button or session.ended event),
  // jump the user to the Summary tab so they see the post-session output.
  useEffect(() => {
    if (mock) return
    if (state.ended && !autoSwitchedRef.current) {
      autoSwitchedRef.current = true
      setActiveTab("summary")
    }
  }, [state.ended, mock])

  const onStop = async () => {
    setStopping(true)
    setFinalizeTimedOut(false)
    setStopRequestedAt(Date.now())
    try {
      await engineApi.stopSession(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStopRequestedAt(null)
    } finally {
      setStopping(false)
    }
  }

  // Safety net: drop the finalizing overlay after 30 s in case the
  // `session.ended` event is lost.
  useEffect(() => {
    if (stopRequestedAt === null || state.ended) return
    const t = setTimeout(() => setFinalizeTimedOut(true), 30_000)
    return () => clearTimeout(t)
  }, [stopRequestedAt, state.ended])

  // After a stop request, reconcile with the engine's REST truth until the
  // session actually flips to "ended". The session.ended event can be lost on
  // a stale socket (slept/paused tab), which left the UI showing Stop
  // until a manual reload; finalization itself (final summary via the LLM)
  // can also outlast the 30 s overlay. Poll for up to 3 minutes.
  const refresh = state.refresh
  useEffect(() => {
    if (stopRequestedAt == null || state.ended) return
    const iv = setInterval(() => {
      if (Date.now() - stopRequestedAt > 180_000) {
        clearInterval(iv)
        return
      }
      void refresh()
    }, 4_000)
    return () => clearInterval(iv)
  }, [stopRequestedAt, state.ended, refresh])

  const onMockUpdate = (action: Action) => {
    state.dispatch({
      type: "action.updated",
      sessionId: id,
      ts: Date.now() / 1000,
      data: { action },
    })
  }

  const onCopilotApprove = async (action: Action, args: ActionArgs) => {
    const who = (await accountSub()) ?? "local"
    const normalized = normalizeArgs(action.kind, args)
    if (mock) {
      const base = { ...action, args: normalized, approvedBy: who }
      onMockUpdate({ ...base, status: "approved" })
      setTimeout(() => onMockUpdate({ ...base, status: "running" }), 800)
      setTimeout(
        () =>
          onMockUpdate({
            ...base,
            status: "succeeded",
            runId: `run_${action.id}`,
          }),
        2200,
      )
      return
    }
    await engineApi.approveAction(id, action.id, normalized, who)
  }

  const onCopilotReject = async (action: Action) => {
    if (mock) {
      onMockUpdate({ ...action, status: "rejected" })
      return
    }
    await engineApi.rejectAction(id, action.id)
  }

  const detail = state.detail
  const pendingActions = state.actions.filter((a) => a.status === "suggested").length
  const statusBadge = isLive ? (
    <Badge colorPalette="red" variant="solid">LIVE</Badge>
  ) : state.ended ? (
    <Badge colorPalette="gray">ended</Badge>
  ) : (
    <Badge colorPalette="gray" variant="outline">{state.status}</Badge>
  )

  if (state.status === "connecting" && !detail) {
    return (
      <Flex justify="center" py="20">
        <Spinner />
      </Flex>
    )
  }

  return (
    <Box>
      <Flex align="center" justify="space-between" mb="4" gap="4" wrap="wrap">
        <Flex align="center" gap="3">
          <Button variant="ghost" size="sm" onClick={() => router.push("/")}>
            <LuArrowLeft /> Back
          </Button>
          <Box minW="0" flex="1">
            <Editable.Root
              // Uncontrolled (defaultValue) so typing is captured natively. A
              // controlled `value=` without `onValueChange` pins the input to the
              // current title, so the commit saves the old name back — that was
              // the "rename does nothing" bug. `key` remounts with the new value
              // after a commit or an external (titler) update so it stays in sync.
              key={titleSource}
              defaultValue={titleSource}
              onValueCommit={async (d) => {
                const next = d.value.trim() || null
                setTitleOverride(next)
                try {
                  await engineApi.renameSession(id, next)
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e))
                }
              }}
              placeholder="Untitled session"
              fontSize="xl"
              fontWeight="semibold"
            >
              <Flex align="center" gap="2">
                <Editable.Preview py="0.5" />
                <Editable.Input />
                <Editable.Control>
                  <Editable.EditTrigger asChild>
                    <IconButton
                      variant="ghost"
                      size="xs"
                      aria-label="Rename session"
                    >
                      <LuPencil />
                    </IconButton>
                  </Editable.EditTrigger>
                  <Editable.CancelTrigger asChild>
                    <IconButton
                      variant="ghost"
                      size="xs"
                      aria-label="Cancel rename"
                    >
                      <LuX />
                    </IconButton>
                  </Editable.CancelTrigger>
                  <Editable.SubmitTrigger asChild>
                    <IconButton
                      variant="ghost"
                      size="xs"
                      aria-label="Save title"
                    >
                      <LuCheck />
                    </IconButton>
                  </Editable.SubmitTrigger>
                </Editable.Control>
              </Flex>
            </Editable.Root>
            <Flex align="center" gap="2" mt="1" color="fg.muted" fontSize="sm">
              {statusBadge}
              {detail?.startedAt ? (
                <Text>{formatDateTime(detail.startedAt)}</Text>
              ) : null}
            </Flex>

          </Box>
        </Flex>
        {isLive || finalizing ? (
          <Flex gap="2">
            <Button
              colorPalette="red"
              onClick={onStop}
              loading={stopping || finalizing}
              loadingText="Finalizing…"
              disabled={finalizing}
            >
              <LuSquare /> Stop
            </Button>
          </Flex>
        ) : (
          <Flex gap="2">
            <Button colorPalette="blue" onClick={() => setContinueOpen(true)}>
              <LuPlay /> Continue
            </Button>
            <Button
              colorPalette="red"
              variant="outline"
              onClick={() => setDeleteOpen(true)}
            >
              <LuTrash2 /> Delete
            </Button>
          </Flex>
        )}
      </Flex>

      {finalizing ? (
        <Alert.Root status="info" mb="4">
          <Alert.Indicator>
            <Spinner size="sm" />
          </Alert.Indicator>
          <Alert.Content>
            <Alert.Title>Finalizing session…</Alert.Title>
            <Alert.Description>
              Closing audio streams, flushing the transcript, and generating
              the final summary. This usually takes a few seconds.
            </Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      <ConfirmDialog
        open={deleteOpen}
        title={`Delete "${titleSource}"?`}
        destructive
        confirmLabel="Delete session"
        body={
          <Text>
            This will permanently remove the session and its transcript,
            summary, and audio files. This cannot be undone.
          </Text>
        }
        onClose={() => setDeleteOpen(false)}
        onConfirm={async () => {
          await engineApi.deleteSession(id)
          router.push("/")
        }}
      />

      {/* Continue this meeting: start a fresh session pre-filled from this
          one's context — no re-entry. The prior transcript isn't appended to
          (sessions are immutable once ended); this is a new session. */}
      <NewSessionDialog
        open={continueOpen}
        onClose={() => setContinueOpen(false)}
        onStarted={(newId) => {
          setContinueOpen(false)
          router.push(`/session?id=${encodeURIComponent(newId)}`)
        }}
        initial={{ context: detail?.context ?? null }}
      />

      {error ? (
        <Alert.Root status="error" mb="4">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Error</Alert.Title>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      {isLive && !finalizing ? (
        <Alert.Root status="info" mb="4" variant="subtle">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>
              This session keeps recording in the background — you can navigate
              away or close this view safely. Click <b>Stop</b> to end it.
            </Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      <SessionNotices notices={state.notices} />

      <Tabs.Root
        value={activeTab}
        onValueChange={(d) => setActiveTab(d.value)}
        variant="line"
      >
        <Tabs.List>
          <Tabs.Trigger value="transcript">
            Transcript{" "}
            <Badge ml="2" variant="subtle">{state.transcript.length}</Badge>
          </Tabs.Trigger>
          <Tabs.Trigger value="actions">
            Actions{" "}
            <Badge
              ml="2"
              variant={pendingActions ? "solid" : "subtle"}
              colorPalette={pendingActions ? "blue" : "gray"}
            >
              {pendingActions}
            </Badge>
          </Tabs.Trigger>
          <Tabs.Trigger value="summary">Summary</Tabs.Trigger>
          <Tabs.Trigger value="questions">
            Questions{" "}
            <Badge ml="2" variant="subtle">{state.qa.length}</Badge>
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="transcript">
          <TranscriptTab
            sessionId={id}
            lines={state.transcript}
            interim={state.interim}
            speakerLabels={state.speakerLabels}
            selfName={state.detail?.selfName}
          />
        </Tabs.Content>
        <Tabs.Content value="actions">
          <ActionsTab
            sessionId={id}
            actions={state.actions}
            mock={mock}
            onMockUpdate={onMockUpdate}
          />
        </Tabs.Content>
        <Tabs.Content value="summary">
          <SummaryTab
            summary={state.summary}
            archive={detail?.archive ?? null}
          />
        </Tabs.Content>
        <Tabs.Content value="questions">
          <QuestionsTab
            sessionId={id}
            qa={state.qa}
            questionsForMe={state.questionsForMe}
          />
        </Tabs.Content>
      </Tabs.Root>

      <CopilotBridge
        sessionId={id}
        transcript={state.transcript}
        actions={state.actions}
        onApprove={onCopilotApprove}
        onReject={onCopilotReject}
      />
      <SessionCopilotSidebar />
    </Box>
  )
}

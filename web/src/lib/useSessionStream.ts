"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  ENGINE_WS,
  engineApi,
  type EngineEvent,
  type LiveSessionState,
  type LiveTranscriptLine,
  type SessionDetail,
} from "./engine"
import type { Action } from "@/types/action"

const INITIAL: LiveSessionState = {
  status: "connecting",
  detail: null,
  transcript: [],
  interim: { system: null, mic: null },
  summary: null,
  speakerLabels: {},
  qa: [],
  ended: false,
  seenSpeakerIds: [],
  notices: [],
  questionsForMe: [],
  actions: [],
}

/** Newest first, stable: a known id is replaced where it already sits, an
 * unknown one goes to the front. Approving an action must never make the card
 * jump. */
function upsertAction(list: Action[], action: Action): Action[] {
  const i = list.findIndex((a) => a.id === action.id)
  if (i === -1) return [action, ...list]
  const next = list.slice()
  next[i] = action
  return next
}

/** Reconcile a fetched list with whatever the socket already delivered. The
 * fetched order wins (the engine sorts newest first); live-only items that the
 * REST list hasn't caught up to yet stay on top. */
function mergeActions(current: Action[], incoming: Action[]): Action[] {
  const ids = new Set(incoming.map((a) => a.id))
  const liveOnly = current.filter((a) => !ids.has(a.id))
  return [...liveOnly, ...incoming]
}

/** The engine wraps every payload in `data` (see engine/bus.py). Accept the
 * action under `data.action`, as the bare `data` payload, or on a top-level
 * `action` key, so a shape tweak on the engine side can't blank the tab. */
function actionFromEvent(ev: EngineEvent): Action | null {
  const data = (ev as { data?: unknown }).data
  const candidates: unknown[] = [
    (data as { action?: unknown } | undefined)?.action,
    data,
    (ev as { action?: unknown }).action,
  ]
  for (const c of candidates) {
    if (c && typeof c === "object" && typeof (c as Action).id === "string") {
      return c as Action
    }
  }
  return null
}

function collectSpeakerIds(d: SessionDetail | null): number[] {
  if (!d) return []
  const ids = new Set<number>()
  for (const t of d.transcript) {
    if (typeof t.speakerId === "number") ids.add(t.speakerId)
  }
  for (const k of Object.keys(d.speakerLabels || {})) {
    const n = Number(k)
    if (Number.isFinite(n)) ids.add(n)
  }
  return [...ids].sort((a, b) => a - b)
}

function detailToTranscript(d: SessionDetail | null): LiveTranscriptLine[] {
  if (!d) return []
  return d.transcript.map((t) => ({
    tStart: t.tStart ?? 0,
    text: t.text,
    speakerId: t.speakerId ?? null,
    source: (t.source as "system" | "mic") ?? "system",
    speaker: t.speaker ?? null,
    kind: "final",
  }))
}

export function useSessionStream(
  sessionId: string | null,
  opts?: { mock?: boolean },
): LiveSessionState & {
  refresh: () => Promise<void>
  dispatch: (ev: EngineEvent) => void
} {
  const mock = opts?.mock ?? false
  const [state, setState] = useState<LiveSessionState>(INITIAL)
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)

  // On-demand reconciliation with the engine's REST truth. Live updates can
  // be lost on a stale socket (slept/paused tab) — most visibly the
  // `session.ended` event, which left the UI on "Stop" until a manual
  // reload. Callers poll this after state-changing actions.
  const refresh = useCallback(async () => {
    if (!sessionId) return
    try {
      const detail = await engineApi.getSession(sessionId)
      const snapshot: EngineEvent = { type: "snapshot", sessionId, data: detail }
      setState((s) => applyEvent(s, snapshot))
    } catch {
      // transient — the next poll or WS event reconciles
    }
  }, [sessionId])

  // Demo path (`?mock=actions`): no socket, no engine — seed from the fixture.
  // Dynamically imported so the fixture is code-split out of the normal bundle.
  useEffect(() => {
    if (!mock || !sessionId) return
    let cancelled = false
    void import("./mockActions").then(({ mockSessionDetail }) => {
      if (cancelled) return
      const snapshot: EngineEvent = {
        type: "snapshot",
        sessionId,
        data: mockSessionDetail(sessionId),
      }
      setState((s) => applyEvent(s, snapshot))
    })
    return () => {
      cancelled = true
    }
  }, [mock, sessionId])

  useEffect(() => {
    if (!sessionId || mock) return
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout> | null = null

    // Suggested actions live behind their own route rather than the snapshot,
    // so seed them whenever the socket (re)connects.
    const seedActions = async () => {
      try {
        const { actions } = await engineApi.listActions(sessionId)
        if (cancelled || !Array.isArray(actions)) return
        setState((s) => ({ ...s, actions: mergeActions(s.actions, actions) }))
      } catch {
        // Engine predates the route (or is briefly down) — live events still fill in.
      }
    }

    const connect = () => {
      if (cancelled) return
      setState((s) => ({ ...s, status: "connecting" }))
      const ws = new WebSocket(`${ENGINE_WS}/sessions/${sessionId}/events`)
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        setState((s) => ({ ...s, status: "open" }))
        void seedActions()
      }

      ws.onclose = () => {
        if (cancelled) return
        setState((s) => ({ ...s, status: "closed" }))
        const delay = Math.min(10_000, 500 * 2 ** retryRef.current++)
        timeout = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        setState((s) => ({ ...s, status: "error" }))
      }

      ws.onmessage = (msg) => {
        let ev: EngineEvent
        try {
          ev = JSON.parse(msg.data) as EngineEvent
        } catch {
          return
        }
        setState((s) => applyEvent(s, ev))
      }
    }

    connect()
    return () => {
      cancelled = true
      if (timeout) clearTimeout(timeout)
      wsRef.current?.close()
    }
  }, [sessionId, mock])

  // Apply an engine event locally. The socket is the only producer in
  // production; the demo path uses it to play back an `action.updated` the
  // engine would have sent, so there's still exactly one source of truth.
  const dispatch = useCallback((ev: EngineEvent) => {
    setState((s) => applyEvent(s, ev))
  }, [])

  return { ...state, refresh, dispatch }
}

function applyEvent(s: LiveSessionState, ev: EngineEvent): LiveSessionState {
  switch (ev.type) {
    case "snapshot": {
      const detail = ev.data as SessionDetail | null
      return {
        ...s,
        // A snapshot means we're receiving engine state — so we're open. This
        // also auto-clears a prior "error" when a reconnect (e.g. after a tab
        // resume) replays the subscription and the engine re-emits its snapshot.
        status: "open",
        detail,
        transcript: detailToTranscript(detail),
        interim: { system: null, mic: null },
        summary: detail?.summary ?? null,
        speakerLabels: detail?.speakerLabels ?? {},
        qa: detail?.qa ?? [],
        ended: detail?.status === "ended" || detail?.status === "stopped",
        seenSpeakerIds: collectSpeakerIds(detail),
        questionsForMe: detail?.questionsForMe ?? [],
        // A snapshot without an `actions` key says nothing about actions —
        // keep what the dedicated route and live events already gave us.
        actions: detail?.actions
          ? mergeActions(s.actions, detail.actions)
          : s.actions,
      }
    }
    case "transcript.interim": {
      const d = ev.data as { source: string; text: string }
      const key = d.source === "mic" ? "mic" : "system"
      return { ...s, interim: { ...s.interim, [key]: d.text } }
    }
    case "transcript.final": {
      const d = ev.data as {
        source: string
        speaker: string
        speakerId: number | null
        text: string
        relT: number
      }
      const line: LiveTranscriptLine = {
        tStart: d.relT,
        text: d.text,
        speakerId: d.speakerId,
        source: (d.source as "system" | "mic") ?? "system",
        speaker: d.speaker,
        kind: "final",
      }
      const seen =
        typeof d.speakerId === "number" && !s.seenSpeakerIds.includes(d.speakerId)
          ? [...s.seenSpeakerIds, d.speakerId].sort((a, b) => a - b)
          : s.seenSpeakerIds
      const interimKey = d.source === "mic" ? "mic" : "system"
      return {
        ...s,
        transcript: [...s.transcript, line],
        interim: { ...s.interim, [interimKey]: null },
        seenSpeakerIds: seen,
      }
    }
    case "summary.updated": {
      const d = ev.data as { text: string; meta: { force_final?: boolean } }
      return {
        ...s,
        summary: {
          text: d.text,
          updatedAt: ev.ts,
          forcedFinal: Boolean(d.meta?.force_final),
        },
      }
    }
    case "insight.extracted": {
      const d = ev.data as { questions?: (string | { text?: string })[] }
      const newQs = (d.questions ?? []).map((q, i) => {
        const text = typeof q === "string" ? q : q.text ?? ""
        return { id: `${ev.ts}-${i}`, question: text, askedAt: ev.ts }
      })
      const seen = new Set(s.qa.map((q) => q.question))
      const additions = newQs.filter((q) => q.question && !seen.has(q.question))
      return { ...s, qa: [...s.qa, ...additions] }
    }
    case "questions.forme": {
      // The engine publishes the full curated list each time (refinements
      // replace variants in place; dismissed items are already excluded).
      const d = ev.data as { items?: { id: string; text: string }[] }
      return { ...s, questionsForMe: d.items ?? [] }
    }
    case "action.suggested":
    case "action.updated": {
      // Both topics carry the full action object; upsert covers either (an
      // update for an id we never saw simply lands at the front).
      const action = actionFromEvent(ev)
      if (!action) return s
      return { ...s, actions: upsertAction(s.actions, action) }
    }
    case "session.ended": {
      return {
        ...s,
        ended: true,
        // Keep detail.status in sync — some consumers (isLive) read it
        // directly, and a later snapshot recomputes `ended` from it.
        detail: s.detail ? { ...s.detail, status: "ended" } : s.detail,
        interim: { system: null, mic: null },
      }
    }
    case "engine.notice": {
      const d = ev.data as {
        level?: "error" | "warning"
        message?: string
        code?: string | null
      }
      if (!d.message) return s
      const notice = {
        level: d.level ?? "warning",
        message: d.message,
        code: d.code ?? null,
        ts: ev.ts ?? 0,
      }
      // Dedupe identical consecutive notices (workers can re-emit each tick);
      // keep the last 20.
      const last = s.notices[s.notices.length - 1]
      if (last && last.message === notice.message) return s
      return { ...s, notices: [...s.notices, notice].slice(-20) }
    }
    default:
      return s
  }
}

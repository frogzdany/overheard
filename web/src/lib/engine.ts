// Typed client for the Python engine.
//
// One transport: fetch/WS straight to the local engine (FastAPI on :8765),
// overridable with NEXT_PUBLIC_ENGINE_URL / NEXT_PUBLIC_ENGINE_WS.
import type { Session, TranscriptLine, QuestionAnswer } from "@/types/session"
import type { Action, ActionArgs } from "@/types/action"

export const ENGINE_URL =
  process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8765"

// Default the socket to the SAME origin as ENGINE_URL. Deriving it (instead of
// a second hardcoded default) means overriding only NEXT_PUBLIC_ENGINE_URL --
// which is all run-demo.sh and the docs set -- moves REST *and* the WebSocket
// together. With a fixed ws://127.0.0.1:8765 default, any non-default engine
// port left the socket pointed at whatever happened to own 8765.
export const ENGINE_WS =
  process.env.NEXT_PUBLIC_ENGINE_WS ??
  ENGINE_URL.replace(/^http:/, "ws:").replace(/^https:/, "wss:")

export interface SessionSummary {
  id: string
  title: string
  blurb: string | null
  tags: string[]
  startedAt: string | null
  durationSec: number
  speakers: { id: number; label: string | null }[]
  questionCount: number
  backend: string | null
  status: "live" | "ended" | "stopped"
  finals: number
}

export interface SessionDetail extends SessionSummary {
  transcript: {
    tStart: number
    text: string
    speakerId: number | null
    speaker: string | null
    source: string | null
  }[]
  summary: { text: string; updatedAt: number | string | null; forcedFinal: boolean }
  archive: string | null
  qa: { id: string; question: string; askedAt: number | null }[]
  /** Curated questions other participants directed at the user. */
  questionsForMe?: QuestionForMe[]
  /** Suggested actions, when the engine inlines them in the snapshot. The
   * dedicated `GET /sessions/{id}/actions` route stays the source of truth. */
  actions?: Action[]
  speakerLabels: Record<string, string>
  /** Display name for the local microphone speaker ("You" unless overridden
   * via the selfDisplayName setting). */
  selfName?: string
  /** Context the user typed at session start. */
  context?: string | null
}

/** Pre-fill payload for NewSessionDialog when a launcher wants to seed the
 * form (e.g. "Continue" on an ended session). Everything stays editable. */
export interface NewSessionInitial {
  context?: string | null
  /** Bundle id of the app whose audio was captured, to preselect the picker. */
  captureApp?: string | null
}

export interface StartRequest {
  device?: string | null
  language?: string | null
  context?: string | null
  /** Bundle ids to scope system-audio capture to. Empty/omitted = whole system. */
  captureApps?: string[] | null
}

export interface InputDevice {
  index: number
  name: string
  channels: number
  sampleRate: number
}

export interface DeviceListResponse {
  devices: InputDevice[]
  defaultName: string | null
}

/** A running app whose audio can be captured on its own, as reported by the
 * Swift helper's `list-apps`. */
export interface CaptureApp {
  bundleId: string
  name: string
  pid?: number
}

export interface Settings {
  micDevice: string
  /** How the local microphone speaker is labelled in transcripts/exports.
   * Empty falls back to "You". */
  selfDisplayName: string
  /** Comma-separated name variants other participants use to address the
   * user — powers "questions asked to me" detection. */
  selfAliases: string
  /** One-line role/title, helps the LLM judge what's directed at the user. */
  selfRole: string
  defaultLanguage: string | null
  defaultContext: string
  summaryIntervalMs: number
  groqModel: string
  deepgramModel: string
}

export type SettingsPatch = Partial<Settings>

// Per-launch engine token. The engine requires it as `X-Engine-Token` on
// state-changing requests. The browser acquires it via a *pairing* handoff:
// whoever launches the dashboard opens it with `?engineToken=…`. We lift that
// into localStorage and scrub it from the URL so refreshes and in-app
// navigation keep working without leaking the token in the address bar.
//
// When the engine runs token-less (pure dev via run-dev.sh) no token is found
// and this resolves to null — the engine ignores the missing header, so that
// flow is unchanged.
const ENGINE_TOKEN_STORAGE_KEY = "overheard_engine_token"
let _engineTokenPromise: Promise<string | null> | null = null

async function resolveEngineToken(): Promise<string | null> {
  if (typeof window === "undefined") return null
  try {
    const url = new URL(window.location.href)
    const fromQuery = url.searchParams.get("engineToken")
    if (fromQuery) {
      window.localStorage.setItem(ENGINE_TOKEN_STORAGE_KEY, fromQuery)
      url.searchParams.delete("engineToken")
      window.history.replaceState({}, "", url.toString())
      return fromQuery
    }
    return window.localStorage.getItem(ENGINE_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function engineToken(): Promise<string | null> {
  if (!_engineTokenPromise) {
    const p = resolveEngineToken()
    _engineTokenPromise = p
    // Never cache a miss: if the token wasn't available yet, let the next call
    // retry instead of being permanently stuck at null.
    void p.then((t) => {
      if (t == null) _engineTokenPromise = null
    })
  }
  return _engineTokenPromise
}

export type PermissionState = "granted" | "denied" | "unknown" | "unsupported"

export interface PermissionsSnapshot {
  platform: string
  screenRecording: PermissionState
  microphone: PermissionState
}

/**
 * Single source of truth for "is capture allowed to run?". Used by the
 * per-session preflight notice. Non-macOS has no TCC, so it's always
 * satisfied. Microphone "unknown" (detection inconclusive — e.g.
 * not-yet-determined) is treated as OK: the real capture path surfaces a
 * failure if the mic can't actually open, and we don't want to block on a
 * state we can't read. Screen Recording must be explicitly granted because
 * system-audio capture hard-depends on it.
 */
export function permissionsSatisfied(perms: PermissionsSnapshot | null): boolean {
  if (!perms) return false
  if (perms.platform !== "darwin") return true
  const srOk = perms.screenRecording === "granted"
  const micOk = perms.microphone === "granted" || perms.microphone === "unknown"
  return srOk && micOk
}

// macOS System Settings deep-links for the capture permissions.
export const SETTINGS_URL = {
  screenRecording:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
  microphone:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}

/** Open a System Settings deep-link. The browser may refuse to hand off an
 * unknown scheme, in which case the user opens Settings manually. */
export async function openExternal(url: string): Promise<void> {
  if (typeof window === "undefined") return
  try {
    window.location.href = url
  } catch (e) {
    console.warn("could not open", url, e)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await engineToken()
  const res = await fetch(`${ENGINE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Engine-Token": token } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`engine ${path} ${res.status}: ${body}`)
  }
  return (await res.json()) as T
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null
  const m = /filename="?([^";]+)"?/i.exec(disposition)
  return m ? m[1].trim() : null
}

/**
 * Fetch a binary engine resource (e.g. the transcript download) as a Blob.
 * `path` is the engine path incl. any query string, e.g.
 * "/sessions/abc/transcript?fmt=md".
 */
export async function fetchEngineBlob(
  path: string,
): Promise<{ blob: Blob; filename: string | null }> {
  const token = await engineToken()
  const r = await fetch(`${ENGINE_URL}${path}`, {
    cache: "no-store",
    headers: token ? { "X-Engine-Token": token } : {},
  })
  if (!r.ok) throw new Error(`engine ${path} ${r.status}`)
  return {
    blob: await r.blob(),
    filename: filenameFromDisposition(r.headers.get("content-disposition")),
  }
}

export const engineApi = {
  health: () => req<{ ok: boolean; running: boolean; currentSessionId: string | null }>("/health"),
  listSessions: () => req<SessionSummary[]>("/sessions"),
  getSession: (id: string) => req<SessionDetail>(`/sessions/${id}`),
  startSession: (body: StartRequest = {}) =>
    req<{ id: string; wsUrl: string }>("/sessions/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  stopSession: (id: string) =>
    req<{ ok: boolean }>(`/sessions/${id}/stop`, { method: "POST" }),
  renameSession: (id: string, title: string | null) =>
    req<{ id: string; title: string; userTitle: string | null; generatedTitle: string | null }>(
      `/sessions/${id}/title`,
      { method: "PUT", body: JSON.stringify({ title }) },
    ),
  deleteSession: (id: string) =>
    req<{ id: string; removedFiles: string[] }>(
      `/sessions/${id}`,
      { method: "DELETE" },
    ),
  /** Engine path for the faithful, correctly-attributed transcript download.
   * Built live from the engine's finals, so it always reflects the latest
   * state. `fmt` is "md" | "txt". */
  transcriptDownloadPath: (sessionId: string, fmt: "md" | "txt" = "md") =>
    `/sessions/${sessionId}/transcript?fmt=${fmt}`,
  /** Absolute URL for the transcript download. */
  transcriptDownloadUrl: (sessionId: string, fmt: "md" | "txt" = "md") =>
    `${ENGINE_URL}/sessions/${sessionId}/transcript?fmt=${fmt}`,
  listDevices: () => req<DeviceListResponse>("/devices"),
  /** Running apps whose audio can be captured on their own (Swift helper). */
  listApps: () => req<{ apps: CaptureApp[] }>("/apps"),
  /** macOS capture-permission snapshot for the pre-session preflight. */
  getPermissions: () => req<PermissionsSnapshot>("/permissions"),
  /** Trigger the native Screen Recording prompt / register the app, then
   * return the resulting status. */
  requestScreenRecording: () =>
    req<{ screenRecording: PermissionState }>(
      "/permissions/screen-recording/request",
      { method: "POST" },
    ),
  /** Surface the native Microphone prompt by briefly opening an input stream
   * engine-side, then return the resulting status. */
  requestMicrophone: () =>
    req<{ microphone: PermissionState }>(
      "/permissions/microphone/request",
      { method: "POST" },
    ),
  /** Hide a directed question the user waved off (engine stops re-surfacing it). */
  dismissQuestionForMe: (sessionId: string, id: string) =>
    req<{ ok: boolean }>(
      `/sessions/${sessionId}/questions-for-me/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" },
    ),
  /** Suggested actions for a session (engine's current list, newest first). */
  listActions: (sessionId: string) =>
    req<{ actions: Action[] }>(`/sessions/${sessionId}/actions`),
  /** Approve an action, optionally with user-edited args. The engine runs the
   * tool and reports progress back over `action.updated`. */
  approveAction: (
    sessionId: string,
    actionId: string,
    args: ActionArgs,
    approvedBy: string,
  ) =>
    req<{ action: Action }>(
      `/sessions/${sessionId}/actions/${encodeURIComponent(actionId)}/approve`,
      { method: "POST", body: JSON.stringify({ args, approvedBy }) },
    ),
  /** Decline an action — the engine stops re-surfacing it. */
  rejectAction: (sessionId: string, actionId: string) =>
    req<{ action: Action }>(
      `/sessions/${sessionId}/actions/${encodeURIComponent(actionId)}/reject`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  /** Create an action from chat (already approved). Engine route is the
   * counterpart being added; we POST the full action object. */
  createAction: (sessionId: string, action: Action) =>
    req<{ action: Action }>(`/sessions/${sessionId}/actions`, {
      method: "POST",
      body: JSON.stringify(action),
    }),
  getSettings: () => req<Settings>("/settings"),
  updateSettings: (patch: SettingsPatch) =>
    req<Settings>("/settings", { method: "PUT", body: JSON.stringify(patch) }),
}

// Map an engine session summary to the UI's Session type for SessionCard reuse.
export function summaryToCardSession(s: SessionSummary): Session {
  const speakers = s.speakers?.length
    ? s.speakers
    : [{ id: 0, label: null }]
  const summaryText =
    s.blurb ??
    (s.status === "live" ? "Recording in progress…" : "Saved session.")
  return {
    id: s.id,
    title: s.title,
    startedAt: s.startedAt ?? new Date().toISOString(),
    durationSec: s.durationSec,
    speakers,
    questionCount: s.questionCount,
    summary: {
      text: summaryText,
      updatedAt: s.startedAt ?? new Date().toISOString(),
    },
  }
}

export type EngineEvent =
  | { type: "snapshot"; sessionId: string; data: SessionDetail | null }
  | { type: "transcript.interim"; sessionId: string; ts: number; data: { source: string; text: string; relT: number } }
  | { type: "transcript.final"; sessionId: string; ts: number; data: { source: string; speaker: string; speakerId: number | null; text: string; speechFinal: boolean; relT: number } }
  | { type: "summary.updated"; sessionId: string; ts: number; data: { text: string; meta: Record<string, unknown> } }
  | { type: "insight.extracted"; sessionId: string; ts: number; data: { questions?: (string | { text?: string })[] } }
  | { type: "action.suggested"; sessionId: string; ts: number; data: { action: Action } }
  | { type: "action.updated"; sessionId: string; ts: number; data: { action: Action } }
  | { type: "session.started"; sessionId: string; ts: number; data: { id: string } }
  | { type: "session.ended"; sessionId: string; ts: number; data: { id: string | null } }
  | { type: string; sessionId: string; ts: number; data: Record<string, unknown> }

export type LineKind = "interim" | "final"

export interface LiveTranscriptLine extends TranscriptLine {
  kind: LineKind
  speaker: string | null
}

export type AudioSource = "system" | "mic"

export interface InterimLine {
  source: AudioSource
  text: string
}

export interface LiveSessionState {
  status: "connecting" | "open" | "closed" | "error"
  detail: SessionDetail | null
  transcript: LiveTranscriptLine[]
  /** Per-source interim text. Each source gets its own slot so the system and
   * mic streams don't overwrite each other while both are speaking. */
  interim: { system: string | null; mic: string | null }
  summary: { text: string; updatedAt: number | string | null; forcedFinal: boolean } | null
  speakerLabels: Record<string, string>
  qa: QuestionAnswer[]
  ended: boolean
  seenSpeakerIds: number[]
  /** Human-facing engine notices (capture failures, rate limits, auth). */
  notices: EngineNotice[]
  /** Questions other participants directed at the user (curated, deduped). */
  questionsForMe: QuestionForMe[]
  /** Suggested actions awaiting (or past) the user's approval, newest first. */
  actions: Action[]
}

/** A question another participant directed at the user, canonicalized and
 * deduped by the engine (refinements replace variants under the same id). */
export interface QuestionForMe {
  id: string
  text: string
}

export interface EngineNotice {
  level: "error" | "warning"
  message: string
  /** Optional action code: "screen_recording" | "microphone" | "rate_limit"
   * | "deepgram". Lets the UI offer a targeted fix. */
  code: string | null
  ts: number
}

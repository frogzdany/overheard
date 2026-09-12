"""FastAPI server exposing the engine over HTTP + WebSocket.

Runs in a background thread inside the Qt process. `SessionEngine` passes
itself in as the controller implementing the surface defined in `Controller`.

Endpoints:
    GET  /health
    GET  /permissions              -> macOS TCC status
    GET  /devices                  -> input devices
    GET  /apps                     -> running apps (per-app audio capture)
    GET  /settings, PUT /settings
    GET  /integrations, PUT /integrations
    GET  /sessions                 -> [SessionSummary]
    GET  /sessions/{id}            -> SessionDetail
    POST /sessions/start           -> { id, wsUrl }
    POST /sessions/{id}/stop       -> { ok: bool }
    WS   /sessions/{id}/events     -> bus event stream (filtered to session)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from . import permissions
from .bus import get_bus
from .config import LOG_DIR
from .db import get_db, resolve_title
from .llm import status as llm_status
from .secrets import get_secrets
from .settings import get_settings
from .swift_audio import list_apps, SwiftHelperNotFound
from .transcript import DEFAULT_SELF_NAME, render_transcript_md
from .workers.actions import (
    ACTION_EXPIRY_S,
    ACTION_KINDS,
    ACTION_TERMINAL,
    ACTION_WRITE_LOCK,
    ARG_FIELDS,
    TOOL_FOR_KIND,
    hands_post,
    normalize_args,
    now_iso,
    start_cancel,
    start_prepare,
)

log = logging.getLogger(__name__)

_SESSION_RE = re.compile(r"^session-\d{8}-\d{6}-[a-z]+$")

# Session lifecycle status reported to the UI. Mirrors the TS union in
# web/src/lib/engine.ts: "live" | "ended" | "stopped".
STATUS_LIVE = "live"
STATUS_ENDED = "ended"
STATUS_STOPPED = "stopped"

# Bounds for user-supplied metadata — defense against unbounded payloads
# bloating the DB / on-disk sidecars. Generous enough for any real use.
_MAX_TITLE_LEN = 300
_MAX_PERSON_NAME_LEN = 200
_MAX_PERSON_FIELD_LEN = 200      # title / org
_MAX_ROSTER = 100
_MAX_CAPTURE_APPS = 32
_MAX_BUNDLE_ID_LEN = 200

# Action lifecycle a hands callback (PATCH .../status) is allowed to drive.
# Anything else — a replayed callback, a run reporting on an action the user
# already rejected, a second `running` after the run finished — is refused with
# 409 rather than silently rewinding the action.
_CALLBACK_TRANSITIONS: dict[str, set[str]] = {
    "approved": {"running", "succeeded", "failed"},
    "running": {"succeeded", "failed"},
}


class Controller(Protocol):
    def current_session_id(self) -> str | None: ...
    def is_session_running(self) -> bool: ...
    def enqueue_control(self, fn) -> None: ...
    def start_session_from_server(self, *, device: str | None = None,
                                  language: str | None = None,
                                  context: str | None = None,
                                  roster: list[dict] | None = None,
                                  capture_apps: list[str] | None = None,
                                  transcript_only: bool = False,
                                  audio_file: str | None = None) -> str | None: ...
    def dismiss_question_for_me(self, qid: str) -> None: ...
    def inject_transcript(self, speaker: str, text: str) -> None: ...
    def trigger_actions(self) -> None: ...
    def sync_action(self, action: dict) -> None: ...
    def stop_session_from_server(self) -> bool: ...


class RosterPerson(BaseModel):
    # A declared session participant, typed into the New Session dialog.
    # Carried into the session log as meeting context.
    name: str = Field(min_length=1, max_length=_MAX_PERSON_NAME_LEN)
    title: str | None = Field(default=None, max_length=_MAX_PERSON_FIELD_LEN)
    org: str | None = Field(default=None, max_length=_MAX_PERSON_FIELD_LEN)
    id: str | None = Field(default=None, max_length=_MAX_PERSON_FIELD_LEN)


class StartRequest(BaseModel):
    # `device` here is the per-session mic override. System audio is always SCK.
    device: str | None = None
    language: str | None = None
    context: str | None = None
    # Structured participants picked in New Session. Names also appear folded
    # into `context`; this typed form is persisted on the session_start event.
    roster: list[RosterPerson] | None = Field(default=None, max_length=_MAX_ROSTER)
    # Bundle ids from the app-to-capture picker (GET /apps). Empty / omitted
    # captures the whole system, which is the default.
    captureApps: list[str] | None = Field(default=None, max_length=_MAX_CAPTURE_APPS)
    transcriptOnly: bool = False


class TitleUpdate(BaseModel):
    # null / empty string both clear the user override and fall back to the
    # LLM-generated title (or session id if neither exists).
    title: str | None = Field(default=None, max_length=_MAX_TITLE_LEN)


class SettingsPatch(BaseModel):
    # Pydantic silently discards fields this model doesn't declare, so a
    # settings key the web UI edits MUST appear here as well as in
    # engine.settings.DEFAULTS — two whitelists, and the save survives only
    # if both know the key.
    micDevice: str | None = None
    selfDisplayName: str | None = None
    selfAliases: str | None = None
    selfRole: str | None = None
    defaultLanguage: str | None = None
    defaultContext: str | None = None
    summaryIntervalMs: int | None = None
    deepgramModel: str | None = None


class IntegrationsPatch(BaseModel):
    """API keys entered in the Settings → Integrations panel. A non-empty
    string sets a key; an empty string clears it. Omitted fields are left as
    they are."""

    deepgram: str | None = None


class ActionApprove(BaseModel):
    args: dict[str, Any] | None = None
    approvedBy: str = Field(min_length=1, max_length=300)


class ActionStatusPatch(BaseModel):
    status: str
    runId: str | None = None
    resultUrl: str | None = None
    error: str | None = None


class ActionCreate(BaseModel):
    """A chat-initiated action from the UI: a full or partial action object.

    Only `kind` and a valid `args` for that kind are actually required —
    everything else is filled in by the route. `status: "approved"` makes the
    create behave exactly like the approve route (persist, publish, dispatch).
    """

    id: str | None = Field(default=None, max_length=64)
    kind: str
    title: str | None = Field(default=None, max_length=_MAX_TITLE_LEN)
    tool: str | None = Field(default=None, max_length=200)
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = Field(default=None, max_length=2000)
    evidence: list[str] | None = Field(default=None, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None
    approvedBy: str | None = Field(default=None, max_length=300)


class TranscriptInject(BaseModel):
    speaker: str = Field(default="Speaker 1", min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


# ---------- session log parsing ----------

def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return out


def _session_files(session_id: str) -> dict[str, Path]:
    base = LOG_DIR / session_id
    return {
        "jsonl": base.with_suffix(".jsonl"),
        "summary": base.with_suffix(".summary.md"),
        "wav": base.with_suffix(".system.wav"),
    }


def _self_name() -> str:
    return (get_settings().get("selfDisplayName") or "").strip() or DEFAULT_SELF_NAME


def _dg_finals(events: list[dict[str, Any]], *, source: str | None = None) -> list[dict[str, Any]]:
    """All ``dg_final`` events, optionally filtered to one source (mic/system)."""
    return [
        e for e in events
        if e.get("event") == "dg_final" and (source is None or e.get("source") == source)
    ]


_SESSION_EVENT_LOCK = threading.Lock()


def _append_session_event(session_id: str, event: str, **fields) -> None:
    """Append one event line to a session's JSONL from a server thread.

    Enrollment runs outside the engine's live `JSONLLogger` (and may target a
    stopped session whose logger is gone), so it appends directly. Same record
    shape as `JSONLLogger.log`; single-line O_APPEND writes interleave safely
    with the live logger's."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    path = _session_files(session_id)["jsonl"]
    try:
        with _SESSION_EVENT_LOCK, path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, default=str) + "\n")
    except OSError as e:
        log.warning("session event append failed (%s): %s", event, e)


def _delete_session_files(session_id: str) -> list[str]:
    """Remove the per-session on-disk artifacts (jsonl, summary, wav).
    Returns the paths that were actually unlinked so the response can report
    what changed."""
    removed: list[str] = []
    for p in _session_files(session_id).values():
        try:
            if p.exists():
                p.unlink()
                removed.append(str(p))
        except OSError as e:
            log.warning("could not unlink %s: %s", p, e)
    return removed


def _list_session_ids() -> list[str]:
    ids: list[str] = []
    for p in sorted(LOG_DIR.glob("session-*-*.jsonl")):
        sid = p.stem
        if _SESSION_RE.match(sid):
            ids.append(sid)
    # newest first
    ids.sort(reverse=True)
    return ids


def _summarize_session(
    session_id: str,
    *,
    live_id: str | None,
    db_rows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    files = _session_files(session_id)
    events = _parse_jsonl(files["jsonl"])
    started_at: str | None = None
    backend: str | None = None
    ended = False
    speakers: set[str] = set()
    finals = 0
    questions = 0
    last_t: float | None = None
    first_t: float | None = None
    for e in events:
        ev = e.get("event")
        if ev == "session_start":
            backend = e.get("backend")
            started_at = e.get("ts") or e.get("time")
        elif ev == "session_end":
            ended = True
        elif ev == "dg_final":
            finals += 1
            sp = e.get("speaker")
            if sp:
                speakers.add(sp)
        elif ev == "insight_extracted":
            questions += int(e.get("n_questions", 0) or 0)
        t = e.get("ts") or e.get("time")
        if isinstance(t, (int, float)):
            first_t = first_t if first_t is not None else float(t)
            last_t = float(t)
    duration = (last_t - first_t) if (first_t is not None and last_t is not None) else 0.0
    # Resolve display title: user override > LLM-generated > session id stem.
    db_row = (db_rows or {}).get(session_id) if db_rows else get_db().get(session_id)
    title = resolve_title(db_row, session_id)
    blurb = (db_row or {}).get("summary_blurb") if db_row else None
    status = (STATUS_LIVE if session_id == live_id
              else (STATUS_ENDED if ended else STATUS_STOPPED))
    return {
        "id": session_id,
        "title": title,
        "blurb": blurb,
        # Session tagging was dropped with the projects domain; the key stays
        # so the dashboard's session card can render without a guard.
        "tags": [],
        "startedAt": started_at,
        "durationSec": int(duration),
        "speakers": [{"id": i, "label": s} for i, s in enumerate(sorted(speakers))],
        "questionCount": questions,
        "backend": backend,
        "status": status,
        "finals": finals,
    }


def _read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _session_detail(session_id: str, *, live_id: str | None) -> dict[str, Any]:
    files = _session_files(session_id)
    if not files["jsonl"].exists():
        raise HTTPException(404, f"session {session_id} not found")
    summary = _summarize_session(session_id, live_id=live_id)
    events = _parse_jsonl(files["jsonl"])
    transcript = [
        {
            "tStart": e.get("rel_t", 0.0),
            "text": e.get("text", ""),
            "speakerId": e.get("speaker_id"),
            "speaker": e.get("speaker"),
            "source": e.get("source"),
        }
        for e in events
        if e.get("event") == "dg_final"
    ]
    # Latest summary_updated payload, if any
    summary_md = _read_text(files["summary"])
    rolling = next(
        (e for e in reversed(events) if e.get("event") == "summary_updated"),
        None,
    )
    questions: list[dict[str, Any]] = []
    for e in events:
        if e.get("event") == "insight_extracted":
            for q in e.get("questions", []) or []:
                if isinstance(q, str):
                    questions.append({"id": q[:32], "question": q, "askedAt": e.get("ts")})
                elif isinstance(q, dict):
                    qtext = q.get("text") or q.get("question") or ""
                    questions.append({"id": str(q.get("id") or qtext[:32]),
                                      "question": qtext,
                                      "askedAt": e.get("ts")})
    # Questions other participants directed at the user: replay the curated
    # JSONL trail — refinements share an id (last text wins), dismissals hide.
    qfm: dict[str, str] = {}
    qfm_dismissed: set[str] = set()
    for e in events:
        if e.get("event") == "question_for_me" and e.get("id"):
            qfm[str(e["id"])] = str(e.get("text") or "")
        elif e.get("event") == "question_for_me_dismissed" and e.get("id"):
            qfm_dismissed.add(str(e["id"]))
    questions_for_me = [
        {"id": k, "text": v} for k, v in qfm.items()
        if v and k not in qfm_dismissed
    ]
    # Declared participants (from New Session), persisted in the session_start
    # event. Lets the UI offer roster quick-assign for unresolved speakers.
    start_ev = next((e for e in events if e.get("event") == "session_start"), None)
    roster = [p for p in ((start_ev or {}).get("roster") or [])
              if isinstance(p, dict) and (p.get("name") or "").strip()]
    # The narrative summary text lives in the .summary.md sidecar; the JSONL
    # `summary_updated` events only carry meta (token counts, char counts).
    # Prefer the markdown file; fall back to whatever the rolling event has.
    rolling_text = ""
    if rolling:
        rolling_text = (
            rolling.get("text")
            or rolling.get("summary")
            or rolling.get("summary_text")
            or ""
        )
    summary_text = summary_md or rolling_text
    return {
        **summary,
        "transcript": transcript,
        "summary": {
            "text": summary_text,
            "updatedAt": rolling.get("ts") if rolling else None,
            "forcedFinal": bool(rolling.get("force_final")) if rolling else False,
        },
        "qa": questions,
        "questionsForMe": questions_for_me,
        "actions": get_db().get_actions(session_id),
        # Deepgram live diarization only — the UI renders "Speaker N" unless a
        # future labeler fills this in.
        "speakerLabels": {},
        "selfName": _self_name(),
        "roster": roster,
        "context": (start_ev or {}).get("context"),
        # Bundle ids the session scoped system-audio capture to ([] = whole system).
        "captureApps": [b for b in ((start_ev or {}).get("capture_apps") or [])
                        if isinstance(b, str)],
    }


# ---------- device enumeration ----------
# CoreAudio enumeration (sd.query_devices()) occasionally stalls for several
# seconds when the audio HAL is in flux (a Bluetooth device joining/leaving,
# another app holding the mic exclusively). Run it off-thread with a short
# deadline and fall back to the last-known list so a stall returns fast
# instead of hanging toward the relay's 15s request timeout — a single slow
# /devices call must not take other in-flight relay requests down with it.
_devices_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="devices-query")
_last_devices: dict[str, Any] | None = None
_DEVICES_TIMEOUT_S = 3.0


def _query_input_devices() -> dict[str, Any]:
    import sounddevice as sd
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        devices.append({
            "index": i,
            "name": d["name"],
            "channels": d["max_input_channels"],
            "sampleRate": int(d.get("default_samplerate") or 0),
        })
    try:
        default_in = sd.default.device[0]
        default_name = (
            sd.query_devices(default_in)["name"]
            if isinstance(default_in, int) and default_in >= 0
            else None
        )
    except Exception:
        default_name = None
    return {"devices": devices, "defaultName": default_name}


# ---------- app factory ----------

def create_app(controller: Controller) -> FastAPI:
    app = FastAPI(title="Overheard Engine")

    # Optional per-launch shared secret. A host that sets ENGINE_TOKEN and
    # hands the same value to the browser (sent back as `X-Engine-Token`) gets
    # forgery protection on every state-changing request: a stray tab or other
    # local process can't silently drive the engine via a cross-origin POST,
    # because the token isn't readable cross-origin.
    #
    # When the var is unset (the normal dev loop via run-dev.sh) enforcement is
    # disabled so those flows keep working.
    engine_token = os.environ.get("ENGINE_TOKEN", "").strip()
    _MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    # Registered BEFORE CORS so CORS stays the outermost layer and still tags
    # the 403 with the right headers (Starlette applies the last-added
    # middleware outermost).
    @app.middleware("http")
    async def _enforce_engine_token(request, call_next):
        # Enforce the token on state-changing requests (forgery protection)
        # AND on /health, which the UI uses as its readiness probe — so the UI
        # treats an engine as "ready" only when that engine accepts ITS token
        # (a stale engine still holding the port answers 403 instead).
        if engine_token:
            needs_token = (
                request.method in _MUTATING_METHODS
                or request.url.path == "/health"
            )
            if needs_token and request.headers.get("X-Engine-Token") != engine_token:
                return JSONResponse(
                    {"detail": "invalid or missing engine token"},
                    status_code=403,
                )
        return await call_next(request)

    # The engine binds 127.0.0.1 only, so an attacker can't reach it from
    # off-box. Inside the user's machine we accept any origin so the Next.js
    # dev server (and any future hosted UI) works without code changes.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    bus = get_bus()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "running": controller.is_session_running(),
            "currentSessionId": controller.current_session_id(),
            "llm": llm_status(),
        }

    @app.get("/permissions")
    def get_permissions() -> dict[str, Any]:
        """Capture-relevant macOS TCC status so the UI can run a preflight
        before starting a session (Screen Recording is the one that silently
        resets on every ad-hoc rebuild)."""
        return permissions.snapshot()

    @app.post("/permissions/screen-recording/request")
    def request_screen_recording() -> dict[str, Any]:
        """Trigger the native Screen Recording prompt / register the app in the
        list, then report the resulting status."""
        return {"screenRecording": permissions.request_screen_recording()}

    @app.post("/permissions/microphone/request")
    def request_microphone() -> dict[str, Any]:
        """Trigger the native Microphone prompt, then report the resulting status.

        There's no preflight API that prompts for the mic the way Screen
        Recording has — the TCC dialog only fires when something actually opens
        an input stream. The engine is the right identity to ask (it's the
        process that opens `sounddevice` during a session), so we briefly open
        and immediately close a stream here to surface the prompt during the
        first-run setup wizard. Best-effort: any failure just degrades to the
        current status, which the UI re-polls."""
        plog = logging.getLogger("meet.permissions")
        plog.info("microphone REQUEST: opening a sounddevice InputStream to "
                  "surface the TCC prompt")
        try:
            import sounddevice as sd
            stream = sd.InputStream(channels=1)
            try:
                stream.start()
                plog.info("microphone REQUEST: stream opened+started OK")
            finally:
                stream.close()
        except Exception as e:
            # Denied / no device / PortAudio hiccup — the status check below
            # still tells the UI where things stand.
            plog.warning("microphone REQUEST: stream open failed: %r", e)
        status = permissions.microphone_status()
        plog.info("microphone REQUEST result status=%s", status)
        return {"microphone": status}

    @app.get("/devices")
    def list_devices() -> dict[str, Any]:
        """Enumerate input devices visible to CoreAudio."""
        global _last_devices
        try:
            result = _devices_executor.submit(_query_input_devices).result(
                timeout=_DEVICES_TIMEOUT_S,
            )
            _last_devices = result
            return result
        except FutureTimeoutError:
            # The query is still running on its worker thread; it'll finish
            # and update _last_devices for next time. Serve what we have now.
            if _last_devices is not None:
                return {**_last_devices, "stale": True}
            raise HTTPException(503, "device enumeration is slow to respond, try again")
        except Exception as e:
            raise HTTPException(500, f"could not enumerate devices: {e}")

    @app.get("/settings")
    def get_settings_endpoint() -> dict[str, Any]:
        return get_settings().get_all()

    @app.put("/settings")
    def update_settings_endpoint(patch: SettingsPatch) -> dict[str, Any]:
        # Drop keys the user didn't actually set (None) so we don't overwrite
        # stored values with explicit nulls — except for `defaultLanguage`,
        # where None means auto-detect and is a real value the user can pick.
        body = patch.model_dump(exclude_unset=True)
        return get_settings().update(body)

    def _integrations_state() -> dict[str, Any]:
        return {"services": get_secrets().status()}

    @app.get("/integrations")
    def get_integrations_endpoint() -> dict[str, Any]:
        """Per-service credential status for Settings → Integrations. Returns
        only configured/masked-hint, never raw keys."""
        return _integrations_state()

    @app.put("/integrations")
    def update_integrations_endpoint(patch: IntegrationsPatch) -> dict[str, Any]:
        get_secrets().update(patch.model_dump(exclude_unset=True))
        return _integrations_state()

    @app.get("/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        live = controller.current_session_id()
        rows = get_db().all()
        return [
            _summarize_session(sid, live_id=live, db_rows=rows)
            for sid in _list_session_ids()
        ]

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        return _session_detail(session_id, live_id=controller.current_session_id())

    @app.put("/sessions/{session_id}/title")
    def rename_session(session_id: str, body: TitleUpdate) -> dict[str, Any]:
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        if not _session_files(session_id)["jsonl"].exists():
            raise HTTPException(404, f"session {session_id} not found")
        # Empty string / None both clear the user override and revert to the
        # LLM-generated title (or session id stem if neither exists).
        new_title = body.title.strip() if isinstance(body.title, str) else None
        get_db().set_user_title(session_id, new_title or None)
        row = get_db().get(session_id) or {}
        resolved = resolve_title(row, session_id)
        bus.publish("session.renamed", {
            "id": session_id,
            "title": resolved,
            "blurb": row.get("summary_blurb"),
            "source": "user",
        }, session_id=session_id)
        return {"id": session_id, "title": resolved,
                "userTitle": row.get("title"),
                "generatedTitle": row.get("generated_title")}

    @app.delete("/sessions/{session_id}")
    def delete_session_endpoint(session_id: str) -> dict[str, Any]:
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        if controller.current_session_id() == session_id:
            raise HTTPException(
                409,
                "that session is currently recording; stop it before deleting.",
            )
        get_db().delete_session(session_id)
        removed = _delete_session_files(session_id)
        bus.publish(
            "session.deleted",
            {"id": session_id, "removedFiles": removed},
            session_id=session_id,
        )
        return {"id": session_id, "removedFiles": removed}

    @app.post("/sessions/start")
    async def start_session(req: StartRequest) -> dict[str, Any]:
        if controller.is_session_running():
            raise HTTPException(409, "a session is already running")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str | None] = loop.create_future()

        def runner() -> None:
            try:
                sid = controller.start_session_from_server(
                    device=req.device,
                    language=req.language, context=req.context,
                    roster=[p.model_dump() for p in (req.roster or [])],
                    capture_apps=[
                        b.strip()[:_MAX_BUNDLE_ID_LEN]
                        for b in (req.captureApps or [])
                        if isinstance(b, str) and b.strip()
                    ],
                    transcript_only=req.transcriptOnly,
                )
                loop.call_soon_threadsafe(fut.set_result, sid)
            except Exception as e:  # noqa: BLE001
                loop.call_soon_threadsafe(fut.set_exception, e)

        controller.enqueue_control(runner)
        try:
            sid = await asyncio.wait_for(fut, timeout=10.0)
        except asyncio.TimeoutError:
            raise HTTPException(504, "engine did not respond in time")
        if sid is None:
            raise HTTPException(409, "engine refused to start (already running?)")
        return {"id": sid, "wsUrl": f"/sessions/{sid}/events"}

    @app.post("/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict[str, Any]:
        if controller.current_session_id() != session_id:
            raise HTTPException(409, "that session is not currently running")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()

        def runner() -> None:
            try:
                ok = controller.stop_session_from_server()
                loop.call_soon_threadsafe(fut.set_result, ok)
            except Exception as e:  # noqa: BLE001
                loop.call_soon_threadsafe(fut.set_exception, e)

        controller.enqueue_control(runner)
        ok = await asyncio.wait_for(fut, timeout=30.0)
        return {"ok": ok}

    @app.get("/apps")
    def list_capturable_apps() -> dict[str, Any]:
        """Running apps with a bundle id — the "which app am I capturing"
        picker in New Session. Served by the Swift helper (NSWorkspace, no
        ScreenCaptureKit, so it needs no permission)."""
        try:
            return {"apps": list_apps()}
        except SwiftHelperNotFound as e:
            raise HTTPException(503, str(e))
        except (OSError, ValueError) as e:
            raise HTTPException(502, f"app list failed: {e}")

    @app.post("/sessions/{session_id}/questions-for-me/{qid}/dismiss")
    def dismiss_question_for_me(session_id: str, qid: str) -> dict[str, Any]:
        """Hide a directed question the user waved off. Live sessions also
        update engine state (so the LLM never re-surfaces it); ended sessions
        just append the dismissal to the JSONL trail."""
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        if not _session_files(session_id)["jsonl"].exists():
            raise HTTPException(404, f"session {session_id} not found")
        qid = qid.strip()[:300]
        if not qid:
            raise HTTPException(400, "missing question id")
        if controller.current_session_id() == session_id:
            controller.enqueue_control(
                lambda: controller.dismiss_question_for_me(qid))
        else:
            _append_session_event(session_id, "question_for_me_dismissed", id=qid)
        return {"ok": True, "id": qid}

    def _require_action_session(session_id: str) -> None:
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        if not _session_files(session_id)["jsonl"].exists():
            raise HTTPException(404, f"session {session_id} not found")

    def _store_action(action: dict[str, Any], event_type: str) -> dict[str, Any]:
        get_db().upsert_action(action)
        controller.sync_action(action)
        bus.publish(event_type, action, session_id=action["sessionId"])
        return action

    def _apply_expiry(action: dict[str, Any]) -> dict[str, Any]:
        """Age a stale suggestion out on read/approve.

        The live engine tick expires suggestions too, but only while a session
        is running — an ended session (or an engine that was restarted) would
        otherwise keep offering hours-old suggestions as approvable. Call under
        ACTION_WRITE_LOCK.
        """
        if action.get("status") != "suggested":
            return action
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(action["suggestedAt"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return action
        if age <= ACTION_EXPIRY_S:
            return action
        expired = dict(action)
        expired["status"] = "expired"
        expired["updatedAt"] = now_iso()
        return _store_action(expired, "action.updated")

    @app.get("/sessions/{session_id}/actions")
    def get_actions(session_id: str) -> dict[str, Any]:
        _require_action_session(session_id)
        with ACTION_WRITE_LOCK:
            actions = [_apply_expiry(a) for a in get_db().get_actions(session_id)]
        return {"actions": actions}

    def _dispatch_to_hands(approved: dict[str, Any]) -> None:
        """Send an approved action to hands on a worker thread.

        With a waitpoint run already staged for this action (EXECUTOR=trigger,
        see start_prepare) approving is just completing that run; otherwise it
        is a plain POST /execute. Hands being down is a normal outcome, not a
        crash: the action flips to `failed` with the connection error attached
        and the UI shows it.
        """
        payload = dict(approved)
        session_id, action_id = payload["sessionId"], payload["id"]
        prepared = str(payload.get("runId") or "")

        def execute() -> None:
            run_id: str = prepared
            error: str | None = None
            try:
                path = (f"/runs/{urllib.parse.quote(prepared, safe='')}/approve"
                        if prepared else "/execute")
                _, body = hands_post(path, payload)
                if body.get("runId"):
                    run_id = str(body["runId"])
            except Exception as exc:
                error = str(exc)[:1000]
            # Re-read under the lock instead of writing back the snapshot we
            # dispatched: hands may already have called PATCH .../status with
            # running / succeeded / failed while this POST was in flight, and
            # the user may have rejected in the meantime. Only the runId — or a
            # dispatch failure on a still-`approved` action — is ours to write.
            with ACTION_WRITE_LOCK:
                current = get_db().get_action(session_id, action_id)
                if current is None:
                    return
                if error is not None:
                    if current.get("status") != "approved":
                        return          # someone else already decided the outcome
                    current["status"] = "failed"
                    current["error"] = error
                elif run_id and not current.get("runId"):
                    current["runId"] = run_id
                else:
                    return              # nothing left for this thread to write
                current["updatedAt"] = now_iso()
                _store_action(current, "action.updated")

        threading.Thread(target=execute, daemon=True,
                         name=f"hands-{action_id}").start()

    @app.post("/sessions/{session_id}/actions")
    def create_action(session_id: str, body: ActionCreate) -> dict[str, Any]:
        """Create an action the user asked for in chat, rather than one the
        brain suggested. Missing fields are filled in; `kind` + `args` are
        validated against the same per-kind schema the worker uses."""
        _require_action_session(session_id)
        kind = (body.kind or "").strip()
        if kind not in ACTION_KINDS:
            raise HTTPException(422, f"invalid kind (expected one of {', '.join(ACTION_KINDS)})")
        tool = (body.tool or "").strip() or TOOL_FOR_KIND[kind]
        if tool != TOOL_FOR_KIND[kind]:
            raise HTTPException(422, f"tool for kind {kind} must be {TOOL_FOR_KIND[kind]}")
        args = normalize_args(kind, body.args)
        if args is None:
            required = ", ".join(sorted(ARG_FIELDS[kind][0]))
            raise HTTPException(422, f"args for kind {kind} must contain: {required}")
        # Chat-initiated actions often carry the title only inside args.
        title = " ".join((body.title or "").split()).strip()
        if not title:
            for key in ("title", "query", "to"):
                candidate = " ".join(str(args.get(key) or "").split()).strip()
                if candidate:
                    title = candidate if key != "to" else f"Message to {candidate}"
                    break
        if not title:
            raise HTTPException(422, "missing title")
        status = (body.status or "suggested").strip() or "suggested"
        if status not in {"suggested", "approved"}:
            raise HTTPException(422, "status on create must be 'suggested' or 'approved'")
        action_id = (body.id or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}", action_id):
            action_id = secrets.token_hex(4)
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        action = {
            "id": action_id, "kind": kind, "title": title[:_MAX_TITLE_LEN],
            "rationale": (body.rationale or "Requested by the user"),
            "evidence": [str(e) for e in (body.evidence or []) if isinstance(e, str)],
            "confidence": 1.0 if body.confidence is None else float(body.confidence),
            "tool": tool, "args": args, "status": "suggested",
            "approvedBy": None, "runId": None, "resultUrl": None, "error": None,
            "suggestedAt": now, "updatedAt": now, "sessionId": session_id,
        }
        # Always announce the suggestion first, so the UI renders the card the
        # same way it does for a brain-generated one.
        _store_action(action, "action.suggested")
        if status != "approved":
            # EXECUTOR=trigger: stage the run + approval waitpoint now. No-op
            # in local mode, and never blocking — the POST answers immediately.
            start_prepare(action, lambda a: _store_action(a, "action.updated"))
            return action
        action = dict(action)
        action.update({
            "status": "approved", "approvedBy": body.approvedBy or "user", "error": None,
            "updatedAt": now_iso(),
        })
        approved = _store_action(action, "action.updated")
        _dispatch_to_hands(approved)
        return approved

    @app.post("/sessions/{session_id}/actions/{action_id}/approve")
    def approve_action(session_id: str, action_id: str,
                       body: ActionApprove) -> dict[str, Any]:
        _require_action_session(session_id)
        with ACTION_WRITE_LOCK:
            action = get_db().get_action(session_id, action_id)
            if action is None:
                raise HTTPException(404, f"action {action_id} not found")
            action = _apply_expiry(action)
            status = action.get("status")
            if status in ACTION_TERMINAL:
                raise HTTPException(409, f"action is {status} and can no longer be approved")
            if body.args is not None:
                # Edited args are user input and get exactly the same schema
                # check as the worker's and the chat-create route's.
                kind = str(action.get("kind") or "")
                args = normalize_args(kind, body.args)
                if args is None:
                    if kind not in ARG_FIELDS:
                        raise HTTPException(422, f"action has unknown kind {kind!r}")
                    required = ", ".join(sorted(ARG_FIELDS[kind][0]))
                    raise HTTPException(422, f"args for kind {kind} must contain: {required}")
                # normalize_args trims to the kind's declared fields; carry the
                # guardrail verdict over so editing a flagged draft can't
                # silently drop the warning the UI shows.
                previous = action.get("args")
                if isinstance(previous, dict) and "guardrail" in previous:
                    args.setdefault("guardrail", previous["guardrail"])
                action["args"] = args
            action.update({
                "approvedBy": body.approvedBy, "status": "approved", "error": None,
                "updatedAt": now_iso(),
            })
            approved = _store_action(action, "action.updated")
        _dispatch_to_hands(approved)
        return approved

    @app.post("/sessions/{session_id}/actions/{action_id}/reject")
    def reject_action(session_id: str, action_id: str) -> dict[str, Any]:
        _require_action_session(session_id)
        with ACTION_WRITE_LOCK:
            action = get_db().get_action(session_id, action_id)
            if action is None:
                raise HTTPException(404, f"action {action_id} not found")
            status = action.get("status")
            if status in ACTION_TERMINAL:
                raise HTTPException(409, f"action is already {status}")
            action["status"] = "rejected"
            action["updatedAt"] = now_iso()
            stored = _store_action(action, "action.updated")
        # A waitpoint run staged for this suggestion is no longer wanted.
        start_cancel(str(stored.get("runId") or ""), stored.get("id", ""))
        return stored

    @app.patch("/sessions/{session_id}/actions/{action_id}/status")
    def patch_action_status(session_id: str, action_id: str,
                            body: ActionStatusPatch) -> dict[str, Any]:
        """Run progress reported by hands. Only the run lifecycle is drivable
        here, and only forwards: the UI owns approve / reject, and a terminal
        action is final."""
        _require_action_session(session_id)
        target = (body.status or "").strip()
        if target not in {"suggested", "approved", "running", "succeeded",
                          "failed", "rejected", "expired"}:
            raise HTTPException(422, "invalid action status")
        with ACTION_WRITE_LOCK:
            action = get_db().get_action(session_id, action_id)
            if action is None:
                raise HTTPException(404, f"action {action_id} not found")
            current = str(action.get("status") or "")
            if current in ACTION_TERMINAL:
                raise HTTPException(409, f"action is {current}; terminal states are final")
            if target not in _CALLBACK_TRANSITIONS.get(current, set()):
                raise HTTPException(409, f"cannot move action from {current} to {target}")
            # Two runs can exist for one action (a prepared waitpoint plus a
            # retry); a callback from the run we are not tracking is stale.
            run_id = str(action.get("runId") or "")
            if run_id and body.runId and str(body.runId) != run_id:
                raise HTTPException(409, f"callback runId does not match run {run_id}")
            action["status"] = target
            for key in ("runId", "resultUrl", "error"):
                value = getattr(body, key)
                if value is not None:
                    action[key] = value
            if target not in {"failed", "rejected"} and body.error is None:
                action["error"] = None
            action["updatedAt"] = now_iso()
            return _store_action(action, "action.updated")

    def _require_dev() -> None:
        if os.environ.get("ENGINE_DEV") != "1":
            raise HTTPException(404, "not found")

    @app.post("/sessions/{session_id}/transcript/inject")
    async def inject_transcript(session_id: str, body: TranscriptInject) -> dict[str, Any]:
        _require_dev()
        _require_action_session(session_id)
        if controller.current_session_id() != session_id:
            raise HTTPException(409, "that session is not currently running")
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def inject() -> None:
            try:
                controller.inject_transcript(body.speaker, body.text)
                loop.call_soon_threadsafe(done.set_result, True)
            except Exception as exc:
                loop.call_soon_threadsafe(done.set_exception, exc)

        controller.enqueue_control(inject)
        await asyncio.wait_for(done, timeout=5)
        return {"ok": True, "speaker": body.speaker, "text": body.text}

    @app.post("/sessions/{session_id}/actions/tick")
    async def tick_actions(session_id: str) -> dict[str, Any]:
        _require_dev()
        _require_action_session(session_id)
        if controller.current_session_id() != session_id:
            raise HTTPException(409, "that session is not currently running")
        controller.enqueue_control(controller.trigger_actions)
        return {"ok": True}

    @app.get("/sessions/{session_id}/transcript")
    def download_transcript(session_id: str, fmt: str = "md") -> Response:
        """Faithful, correctly-attributed transcript built live from the
        ``dg_final`` events + the current labels + the user's display name, so
        the download always reflects the latest manual corrections.

        `fmt` is "md" (default) or "txt". Returned as a download attachment."""
        if not _SESSION_RE.match(session_id):
            raise HTTPException(400, "invalid session id")
        files = _session_files(session_id)
        if not files["jsonl"].exists():
            raise HTTPException(404, f"session {session_id} not found")
        events = _parse_jsonl(files["jsonl"])
        finals = _dg_finals(events)
        title = resolve_title(get_db().get(session_id), session_id)
        md = render_transcript_md(
            finals, labels={}, self_name=_self_name(), title=title,
        )
        if fmt == "txt":
            # Strip the **[ts] Speaker:** markdown emphasis for a plain export.
            body = md.replace("**", "")
            media, ext = "text/plain", "txt"
        else:
            body = md
            media, ext = "text/markdown", "md"
        # session_id already validated against _SESSION_RE above.
        headers = {"Content-Disposition": f'attachment; filename="{session_id}.transcript.{ext}"'}
        return Response(content=body, media_type=media, headers=headers)

    @app.websocket("/sessions/{session_id}/events")
    async def session_events(ws: WebSocket, session_id: str) -> None:
        bus.bind_loop(asyncio.get_running_loop())
        await ws.accept()
        q = bus.subscribe()
        try:
            # Initial snapshot so the client can render immediately.
            try:
                snap = _session_detail(session_id, live_id=controller.current_session_id())
                await ws.send_json({"type": "snapshot", "sessionId": session_id, "data": snap})
            except HTTPException:
                # New session: no log file yet, send empty snapshot
                await ws.send_json({"type": "snapshot", "sessionId": session_id, "data": None})
            while True:
                event = await q.get()
                # Filter to this session (allow events with no sessionId for global noise)
                if event.get("sessionId") and event["sessionId"] != session_id:
                    continue
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(q)

    return app


# ---------- threaded runner ----------

class ServerThread(threading.Thread):
    """Runs uvicorn on its own asyncio loop in a daemon thread.

    Binds the bus to that loop so publish() from anywhere reaches WS clients.
    """

    def __init__(self, controller: Controller, host: str = "127.0.0.1", port: int = 8765):
        super().__init__(daemon=True, name="engine-server")
        self._controller = controller
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None
        self.ready = threading.Event()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        get_bus().bind_loop(loop)
        app = create_app(self._controller)
        config = uvicorn.Config(
            app, host=self._host, port=self._port, log_level="info",
            loop="asyncio", lifespan="on",
        )
        self._server = uvicorn.Server(config)

        async def _serve() -> None:
            # Signal readiness once uvicorn has installed signal handlers etc.
            loop.call_later(0.2, self.ready.set)
            await self._server.serve()

        try:
            loop.run_until_complete(_serve())
        finally:
            loop.close()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

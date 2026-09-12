"""Differential worker that turns transcript commitments into executable actions."""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Annotated, Callable, Literal

from PySide6.QtCore import QObject, Signal
from pydantic import BaseModel, ConfigDict, Field

from engine.guardrail import screen as guardrail_screen
from engine.llm import complete_json
from engine.logger import JSONLLogger

# Kinds whose args carry free text worth screening before publishing.
_GUARDED_KINDS = ("draft_message", "create_doc")

ACTION_KINDS = ("create_task", "schedule_followup", "draft_message", "create_doc", "lookup")
TOOLS = (
    "ambiguous.tasks.create", "ambiguous.calendar.createEvent",
    "ambiguous.chat.sendMessage", "ambiguous.docs.create", "exa.answer",
)
TOOL_FOR_KIND = dict(zip(ACTION_KINDS, TOOLS))
# kind -> (required arg names, accepted arg names). The single source of truth
# for the per-kind args contract: the worker validates model output with it and
# POST /sessions/{id}/actions validates chat-initiated actions with it too.
ARG_FIELDS = {
    "create_task": ({"title"}, {"title", "assignee", "due", "notes"}),
    "schedule_followup": ({"title", "when", "attendees"}, {"title", "when", "attendees", "notes"}),
    "draft_message": ({"to", "body"}, {"to", "body"}),
    "create_doc": ({"title", "body"}, {"title", "body"}),
    "lookup": ({"query"}, {"query"}),
}


def normalize_args(kind: str, args: object) -> dict | None:
    """Validate `args` for `kind` and return it trimmed to the accepted keys.

    Returns None when the kind is unknown, a required key is missing, or a
    typed field has the wrong shape. Shared by the worker and the HTTP create
    route so both enforce exactly one schema.
    """
    if kind not in ARG_FIELDS or not isinstance(args, dict):
        return None
    required, allowed = ARG_FIELDS[kind]
    if not required.issubset(args):
        return None
    if kind == "schedule_followup" and not isinstance(args.get("attendees"), list):
        return None
    return {key: args[key] for key in allowed if key in args and args[key] is not None}


# ---- action lifecycle constants ----

# A suggestion nobody touched for this long stops being actionable. Applied by
# the live tick, by GET /actions and by approve, so the state is the same
# whether or not an engine tick happened to run.
ACTION_EXPIRY_S = 1800.0
# Once an action reaches one of these it never moves again.
ACTION_TERMINAL = frozenset({"succeeded", "failed", "rejected", "expired"})
# Serializes read-modify-write cycles on a stored action. The hands dispatch
# thread, the /prepare thread and the PATCH .../status callback all mutate the
# same row from different threads; without this, a slow writer can resurrect a
# snapshot it read before a faster writer moved the action on.
ACTION_WRITE_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---- hands executor client ----
#
# `EXECUTOR=local` (the default) dispatches an action only once the user
# approves it: POST /execute. `EXECUTOR=trigger` pre-creates a Trigger.dev run
# with an approval waitpoint the moment the action is suggested (POST /prepare),
# so approving is just completing the waitpoint (POST /runs/{runId}/approve) and
# rejecting cancels it (POST /runs/{runId}/cancel).

HANDS_TIMEOUT_S = 10.0


def executor_mode() -> str:
    return (os.environ.get("EXECUTOR") or "local").strip().lower()


def hands_base_url() -> str:
    return (os.environ.get("HANDS_URL") or "http://127.0.0.1:8790").rstrip("/")


def hands_post(path: str, payload: dict, timeout: float = HANDS_TIMEOUT_S) -> tuple[int, dict]:
    """POST JSON to the hands service. Returns (http status, decoded object).

    Raises on transport errors and on HTTP >= 400 — every caller treats hands
    being unreachable as a normal outcome and decides what to do about it.
    """
    request = urllib.request.Request(
        hands_base_url() + path,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", None) or response.getcode())
        raw = response.read()
    try:
        body = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


def start_prepare(action: dict, store: Callable[[dict], object]) -> None:
    """EXECUTOR=trigger only: create the waitpoint run for a NEW suggestion.

    Runs on a daemon thread so suggestion publishing never waits on hands. On
    202 the returned runId is written back with a compare-and-set — only if the
    action is still `suggested` and still has no runId, so a user who approved
    or rejected in the meantime wins. Any failure is silent: the action simply
    keeps runId=None and approve falls back to POST /execute.
    """
    if executor_mode() != "trigger" or not (os.environ.get("HANDS_URL") or "").strip():
        return
    if action.get("runId") or action.get("status") != "suggested":
        return
    snapshot = dict(action)

    def prepare() -> None:
        try:
            status, body = hands_post("/prepare", snapshot)
        except Exception:
            return
        run_id = str(body.get("runId") or "") if status == 202 else ""
        if not run_id:
            return
        from engine.db import get_db
        with ACTION_WRITE_LOCK:
            current = get_db().get_action(snapshot["sessionId"], snapshot["id"])
            if current is None or current.get("runId"):
                return
            if current.get("status") != "suggested":
                return
            current["runId"] = run_id
            current["updatedAt"] = now_iso()
            store(current)

    threading.Thread(target=prepare, daemon=True,
                     name=f"hands-prepare-{action.get('id')}").start()


def start_cancel(run_id: str, action_id: str = "") -> None:
    """Best-effort cancel of a prepared waitpoint run after a rejection."""
    if not run_id:
        return

    def cancel() -> None:
        try:
            hands_post(f"/runs/{urllib.parse.quote(str(run_id), safe='')}/cancel", {})
        except Exception:
            pass

    threading.Thread(target=cancel, daemon=True,
                     name=f"hands-cancel-{action_id or run_id}").start()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Candidate(_StrictModel):
    id: str | None = None
    title: str
    rationale: str
    evidence: list[str]
    confidence: float = Field(ge=0, le=1)


class _CreateTaskArgs(_StrictModel):
    title: str
    assignee: str | None = None
    due: str | None = None
    notes: str | None = None


class _ScheduleArgs(_StrictModel):
    title: str
    when: str
    attendees: list[str]
    notes: str | None = None


class _MessageArgs(_StrictModel):
    to: str
    body: str


class _DocArgs(_StrictModel):
    title: str
    body: str


class _LookupArgs(_StrictModel):
    query: str


class _CreateTask(_Candidate):
    kind: Literal["create_task"]
    tool: Literal["ambiguous.tasks.create"]
    args: _CreateTaskArgs


class _ScheduleFollowup(_Candidate):
    kind: Literal["schedule_followup"]
    tool: Literal["ambiguous.calendar.createEvent"]
    args: _ScheduleArgs


class _DraftMessage(_Candidate):
    kind: Literal["draft_message"]
    tool: Literal["ambiguous.chat.sendMessage"]
    args: _MessageArgs


class _CreateDoc(_Candidate):
    kind: Literal["create_doc"]
    tool: Literal["ambiguous.docs.create"]
    args: _DocArgs


class _Lookup(_Candidate):
    kind: Literal["lookup"]
    tool: Literal["exa.answer"]
    args: _LookupArgs


class ActionsResponse(_StrictModel):
    actions: list[Annotated[
        _CreateTask | _ScheduleFollowup | _DraftMessage | _CreateDoc | _Lookup,
        Field(discriminator="kind"),
    ]]


ACTION_RESPONSE_SCHEMA = ActionsResponse.model_json_schema()

ACTION_SYSTEM_PROMPT = """Analyze a live meeting transcript incrementally. Emit ONLY concrete commitments and requests that can be executed as exactly one of: create_task, schedule_followup, draft_message, create_doc, lookup. Omit vague ideas, completed work, rhetorical questions, and anything without transcript evidence. Copy evidence verbatim. Use the matching tool and args shape: create_task {title, assignee?, due?, notes?}; schedule_followup {title, when (ISO), attendees[], notes?}; draft_message {to, body}; create_doc {title, body}; lookup {query}. ALREADY_KNOWN titles must not be duplicated; an improved version may return its existing id. Return strict JSON matching the supplied schema."""


class ActionsWorker(QObject):
    actions_ready = Signal(object)
    finished = Signal()
    status = Signal(str)

    def __init__(self, logger: JSONLLogger | None):
        super().__init__()
        self._log = logger
        self._lock = threading.Lock()
        self._busy = False

    def extract(self, transcript: str, rolling_context: str, already_known: dict,
                session_id: str) -> bool:
        """Run one extraction pass over the new transcript window.

        Returns True only when the model answered and its JSON parsed. The
        caller advances its transcript cutoff on True and keeps the pending
        window on False (worker busy, timeout, malformed response) so the next
        tick re-sends that window instead of silently dropping it.
        """
        with self._lock:
            if self._busy:
                self.finished.emit()
                return False
            self._busy = True
        try:
            return self._do_extract(transcript, rolling_context, already_known, session_id)
        finally:
            with self._lock:
                self._busy = False
            self.finished.emit()

    def _do_extract(self, transcript: str, rolling_context: str,
                    already_known: dict, session_id: str) -> bool:
        transcript = transcript.strip()
        if len(transcript) < 80:
            return False
        user = (
            f"ROLLING_CONTEXT:\n---\n{rolling_context[-3000:]}\n---\n\n"
            f"ALREADY_KNOWN:\n{json.dumps(already_known, ensure_ascii=False)}\n\n"
            f"NEW_TRANSCRIPT:\n---\n{transcript}\n---"
        )
        try:
            payload = complete_json(ACTION_SYSTEM_PROMPT, user, schema=ActionsResponse,
                                    max_tokens=1200, timeout=60)
        except Exception as exc:
            self.status.emit(f"actions error: {exc}")
            if self._log:
                self._log.log("actions_error", error=str(exc))
            return False
        if not isinstance(payload, dict):
            if self._log:
                self._log.log("actions_error", error="non-object response")
            return False
        now = now_iso()
        actions = []
        for raw in payload.get("actions", []):
            if not isinstance(raw, dict) or raw.get("kind") not in ACTION_KINDS:
                continue
            title = " ".join(str(raw.get("title") or "").split()).strip()
            kind = raw["kind"]
            args = normalize_args(kind, raw.get("args"))
            if not title or raw.get("tool") != TOOL_FOR_KIND[kind] or args is None:
                continue
            action_id = str(raw.get("id") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{8}", action_id):
                import secrets
                action_id = secrets.token_hex(4)
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
            # Screen outbound text (any-guardrail, GUARDRAIL=on) right before a
            # new or refined draft_message/create_doc is published. Never drops
            # the action: a failed screen just tags args.guardrail and knocks
            # confidence down so the card can show a warning and the user still
            # decides.
            if kind in _GUARDED_KINDS:
                text = "\n".join(part for part in (title, str(args.get("body") or "")) if part)
                guard = guardrail_screen(text)
                args = {**args, "guardrail": guard}
                if not guard.get("passed", True):
                    confidence = max(0.0, confidence - 0.3)
            actions.append({
                "id": action_id.lower(), "kind": kind, "title": title,
                "rationale": str(raw.get("rationale") or ""),
                "evidence": [str(v) for v in raw.get("evidence", []) if isinstance(v, str)],
                "confidence": confidence,
                "tool": raw["tool"], "args": args,
                "status": "suggested", "approvedBy": None, "runId": None,
                "resultUrl": None, "error": None, "suggestedAt": now,
                "updatedAt": now, "sessionId": session_id,
            })
        if actions:
            self.actions_ready.emit(actions)
        # Parsed cleanly (even with zero actions) — the window is consumed.
        return True

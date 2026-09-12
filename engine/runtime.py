"""Headless session engine.

`SessionEngine` owns the workers (DeepgramStreamer, InsightExtractor,
SummaryWorker, plus the one-shot titler), tracks per-session state, and
exposes the small `Controller` surface that `engine/server.py` calls into.

This is a `QObject` (not `QMainWindow`) so it can run under a plain
`QCoreApplication` — no Dock icon, no NSApplication, clean Ctrl-C.
"""
from __future__ import annotations

import difflib
import os
import queue
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Slot

from .bus import get_bus
from .config import (
    ACTIONS_INTERVAL_MS,
    DG_MODEL,
    INSIGHT_INTERVAL_MS,
    INSIGHT_WINDOW_MIN,
    LOG_DIR,
    MIC_BOOST_DG,
    MIN_SESSION_KEEP_SECONDS,
    OPENAI_STT_MODEL,
    SAMPLE_RATE,
    STT_PROVIDER,
    SUMMARY_INTERVAL_MS,
    SUMMARY_MIN_NEW_WORDS,
)
from .db import get_db
from .logger import JSONLLogger
from .settings import get_settings
from .workers import (
    ActionsWorker,
    DeepgramStreamer,
    InsightExtractor,
    SummaryWorker,
    name_session,
)
from .workers.actions import (
    ACTION_EXPIRY_S,
    ACTION_TERMINAL,
    ACTION_WRITE_LOCK,
    now_iso,
    start_prepare,
)
from .workers.openai_stt import OpenAIStreamer

_BUS = get_bus()

# Substrings that mark a worker status line as a user-facing error worth a UI
# notice (rate limits). Kept specific to avoid bannering benign status.
# Matched case-insensitively.
_WORKER_ERROR_HINTS = ("rate limit", "rate_limit", "quota")


def _classify_failure(msg: str) -> str | None:
    """Map a failure/status string to a code the UI can act on (deep-links,
    targeted hints). Best-effort substring match (EN + the Spanish TCC text)."""
    low = msg.lower()
    if any(k in low for k in ("screen recording", "captura de pantalla",
                              "screencapturekit", "tcc", "rechaz")):
        return "screen_recording"
    if "micr" in low or "microphone" in low:
        return "microphone"
    if any(k in low for k in ("rate limit", "rate_limit", "quota", "429")):
        return "rate_limit"
    if "deepgram" in low:
        return "deepgram"
    return None


class SessionEngine(QObject):
    """Headless equivalent of the legacy MainWindow.

    Lifecycle is driven by `start_session_from_server()` / `stop_session_from_server()`
    which the FastAPI server queues onto this object's thread via `enqueue_control`.
    """

    def __init__(self) -> None:
        super().__init__()

        # ---- session-scoped state ----
        self._worker: QObject | None = None
        self._thread: QThread | None = None
        self._logger = None
        self._archive_audio_path: Path | None = None
        self._session_id: str | None = None
        # Snapshots of the params used to start the current session; the LLM
        # workers consult them.
        self._active_language: str | None = None
        self._active_context: str = ""
        # Structured participant roster for the session (list of {name, title,
        # org, id}). Drives the deterministic speaker short-circuits (1:1
        # auto-map, closed-set elimination) so the LLM labeler is only used for
        # genuinely ambiguous IDs. Empty when the user picked no participants.
        self._active_roster: list[dict] = []

        # Each transcript entry: (epoch_t, source, speaker_id, text)
        self._full_transcript: list[tuple[float, str, int | None, str]] = []
        # Deepgram live diarization labels only (Speaker 0/1/2...). Kept as a
        # map so the transcript formatter and the summary prompt have one place
        # to read a speaker's display name from.
        self._speaker_labels: dict[int, str | None] = {}

        self._known_questions: dict[str, str] = {}
        self._known_topics: dict[str, str] = {}
        self._known_decisions: dict[str, str] = {}
        # Questions other participants direct at the local user (norm key →
        # canonical text), curated: fuzzy-merged so refinements replace
        # variants instead of accumulating. Dismissed keys stay known (so the
        # LLM doesn't re-surface them) but are excluded from the UI.
        self._questions_for_me: dict[str, str] = {}
        self._qfm_dismissed: set[str] = set()
        self._last_extract_cutoff_t: float = 0.0
        self._last_actions_cutoff_t: float = 0.0
        self._actions: list[dict] = []
        self._actions_lock = threading.Lock()
        # Guards the actions transcript cutoff: the Qt thread reads it when a
        # tick fires, the extraction thread advances it when a pass succeeds.
        self._cutoff_lock = threading.Lock()
        self._transcript_only = False

        self._last_summary_cutoff_t: float = 0.0
        self._last_summary_at: float = 0.0
        self._session_started_at: float = 0.0

        # ---- control queue (thread-safe RPC from server) ----
        self._control_queue: queue.Queue = queue.Queue()
        self._control_timer = QTimer(self)
        self._control_timer.setInterval(100)
        self._control_timer.timeout.connect(self._drain_control_queue)
        self._control_timer.start()

        # ---- background workers (insight, summary) ----
        self._insight_extractor = InsightExtractor(logger=None)
        self._insight_thread = QThread(self)
        self._insight_extractor.moveToThread(self._insight_thread)
        self._insight_extractor.insights_ready.connect(self.on_insights)
        self._insight_extractor.status.connect(self._log_status)
        self._insight_thread.start()

        self._insight_timer = QTimer(self)
        self._insight_timer.setInterval(INSIGHT_INTERVAL_MS)
        self._insight_timer.timeout.connect(self.trigger_insight)

        self._summary_worker = SummaryWorker(logger=None)
        self._summary_worker.moveToThread(self._insight_thread)
        self._summary_worker.summary_ready.connect(self.on_summary_ready)
        self._summary_worker.status.connect(self._log_status)

        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(SUMMARY_INTERVAL_MS)
        self._summary_timer.timeout.connect(self.trigger_summary)

        self._actions_worker = ActionsWorker(logger=None)
        self._actions_worker.moveToThread(self._insight_thread)
        self._actions_worker.actions_ready.connect(self.on_actions)
        self._actions_worker.status.connect(self._log_status)

        self._actions_timer = QTimer(self)
        self._actions_timer.setInterval(ACTIONS_INTERVAL_MS)
        self._actions_timer.timeout.connect(self.trigger_actions)

    # ---- Controller protocol (for engine/server.py) ----

    def enqueue_control(self, fn) -> None:
        self._control_queue.put(fn)

    def _drain_control_queue(self) -> None:
        while True:
            try:
                fn = self._control_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001
                # Deliberate top-level guard: this drains arbitrary control
                # callbacks (start/stop session) and must keep running even if
                # one throws — otherwise the engine can no longer be driven.
                # Log a full traceback so a genuine bug isn't silently hidden.
                print("control queue error:\n" + traceback.format_exc(),
                      file=sys.stderr)

    def current_session_id(self) -> str | None:
        return self._session_id

    def is_session_running(self) -> bool:
        return self._session_id is not None

    def start_session_from_server(
        self,
        *,
        device: str | None = None,
        language: str | None = None,
        context: str | None = None,
        roster: list[dict] | None = None,
        capture_apps: list[str] | None = None,
        transcript_only: bool = False,
        audio_file: str | Path | None = None,
    ) -> str | None:
        if self.is_session_running():
            return None
        s = get_settings().get_all()
        # `device` is the per-session mic override (from the New Session dialog).
        # Empty string => fall back to settings.micDevice => sounddevice default.
        mic_device = device or s.get("micDevice") or None
        language = language if language is not None else s.get("defaultLanguage")
        context = context if context is not None else (s.get("defaultContext") or "")
        return self._start_session(
            mic_device=mic_device, language=language, context=context,
            roster=roster or [], capture_apps=capture_apps or [],
            transcript_only=transcript_only, audio_file=audio_file,
        )

    def stop_session_from_server(self) -> bool:
        if not self.is_session_running():
            return False
        self._stop_session()
        return True

    # ---- lifecycle ----

    def _start_session(
        self,
        *,
        mic_device: str | None,
        language: str | None,
        context: str,
        roster: list[dict] | None = None,
        capture_apps: list[str] | None = None,
        transcript_only: bool = False,
        audio_file: str | Path | None = None,
    ) -> str | None:
        capture_apps = [b for b in (capture_apps or []) if isinstance(b, str) and b.strip()]
        if STT_PROVIDER not in {"deepgram", "openai"}:
            raise ValueError(
                f"Unsupported STT_PROVIDER={STT_PROVIDER!r}; expected 'deepgram' or 'openai'")
        if (not transcript_only and STT_PROVIDER == "openai"
                and not os.environ.get("OPENAI_API_KEY", "").strip()):
            raise RuntimeError("OPENAI_API_KEY is required when STT_PROVIDER=openai")
        streamer_class = OpenAIStreamer if STT_PROVIDER == "openai" else DeepgramStreamer
        stt_model = OPENAI_STT_MODEL if STT_PROVIDER == "openai" else DG_MODEL
        session = datetime.now().strftime("%Y%m%d-%H%M%S")
        # "-deepgram" suffix preserved for log-file compatibility with the
        # existing analyze_logs.py + .summary.md / .archive.md naming.
        session_id = f"session-{session}-deepgram"
        self._session_id = session_id
        _BUS.set_session_id(session_id)
        self._active_language = language
        self._active_context = context
        self._transcript_only = transcript_only
        # Normalize the roster to a clean [{name, title, org, id}] — drop any
        # entries without a usable name (they can't anchor a label).
        self._active_roster = [
            {
                "name": (p.get("name") or "").strip(),
                "title": (p.get("title") or None),
                "org": (p.get("org") or None),
                "id": (p.get("id") or None),
            }
            for p in (roster or [])
            if (p.get("name") or "").strip()
        ]

        log_path = LOG_DIR / f"{session_id}.jsonl"
        self._logger = JSONLLogger(log_path)
        self._logger.log(
            "session_start",
            device=(mic_device or "default"),
            language=language, model=stt_model, stt_provider=STT_PROVIDER,
            sample_rate=SAMPLE_RATE, mic_boost=MIC_BOOST_DG, context=context,
            capture_apps=capture_apps,
            transcript_only=transcript_only,
            audio_file=str(audio_file) if audio_file else None,
            # Persisted so the UI can rebuild the participant picker (speaker
            # quick-assign) from the JSONL alone, across reloads.
            roster=self._active_roster,
        )
        _BUS.publish("session.started", {
            "id": session_id,
            "device": mic_device, "language": language, "context": context,
            "roster": self._active_roster, "captureApps": capture_apps,
        })
        # Register a DB row so reads from `/sessions` immediately see this
        # session (even before any titler / summary runs).
        try:
            get_db().upsert_created(session_id, time.time())
        except (sqlite3.Error, OSError, ValueError) as e:
            print(f"engine: db upsert_created failed: {e}", file=sys.stderr)

        if not transcript_only:
            archive_path = log_path.with_suffix(".system.wav")
            self._archive_audio_path = archive_path
            self._thread = QThread(self)
            self._worker = streamer_class(
                language=language, context_keywords=context,
                logger=self._logger, archive_path=archive_path,
                mic_device=mic_device, capture_apps=capture_apps,
                audio_file=Path(audio_file) if audio_file else None,
            )
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.start)
            self._worker.interim_text.connect(self.on_interim)
            self._worker.final_text.connect(self.on_final)
            self._worker.status.connect(self._log_status)
            self._worker.failed.connect(self.on_failed)
            self._thread.start()

        # Workers share the active logger so their JSONL events land in the same file.
        self._insight_extractor._log = self._logger
        self._summary_worker._log = self._logger
        self._actions_worker._log = self._logger
        self._summary_worker.reset()

        # Reset per-session state.
        self._last_summary_cutoff_t = 0.0
        self._last_summary_at = 0.0
        self._session_started_at = time.time()
        self._known_questions.clear()
        self._known_topics.clear()
        self._known_decisions.clear()
        self._questions_for_me.clear()
        self._qfm_dismissed.clear()
        self._last_extract_cutoff_t = 0.0
        with self._cutoff_lock:
            self._last_actions_cutoff_t = 0.0
        self._full_transcript.clear()
        self._speaker_labels.clear()
        with self._actions_lock:
            self._actions = get_db().get_actions(session_id)

        # Periodic LLM passes.
        self._insight_timer.start()
        self._summary_timer.start()
        self._actions_timer.start()
        return session_id

    def _stop_session(self) -> None:
        self._insight_timer.stop()
        self._summary_timer.stop()
        self._actions_timer.stop()
        self._final_summary_snapshot()

        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._worker = None
        self._thread = None
        self._close_logger_and_finish()

    def _close_logger_and_finish(self) -> None:
        if self._logger:
            self._logger.log("session_end")
            self._logger.close()
            self._logger = None
        # Decide whether the session is worth keeping. We discard if it was
        # both very short AND produced no transcript — those are typically
        # accidental starts or aborted sessions and they clutter the list.
        ended_id = self._session_id
        ended_at = time.time()
        duration = max(0.0, ended_at - self._session_started_at)
        discarded = self._maybe_discard_short_session(ended_id)
        if ended_id and not discarded:
            try:
                get_db().mark_ended(ended_id, ended_at, duration)
            except (sqlite3.Error, OSError) as e:
                print(f"engine: db mark_ended failed: {e}", file=sys.stderr)
            # Kick the LLM titler in the background. It reads the .summary.md
            # we just wrote and stores the name in the DB. Doing this here
            # (not inside _final_summary_snapshot) keeps the session state
            # cleanly closed before the titler runs.
            summary_path = LOG_DIR / f"{ended_id}.summary.md"
            self._spawn_titler(ended_id, summary_path)
        _BUS.publish("session.ended", {"id": ended_id})
        _BUS.set_session_id(None)
        self._session_id = None

    def _spawn_titler(self, session_id: str, summary_path: Path) -> None:
        def _runner() -> None:
            text = ""
            try:
                if summary_path.exists():
                    text = summary_path.read_text(encoding="utf-8")
            except OSError:
                pass
            try:
                result = name_session(session_id, text)
                if result:
                    _BUS.publish("session.renamed", {
                        "id": session_id,
                        "title": result.get("title"),
                        "blurb": result.get("blurb"),
                        "source": "auto",
                    })
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as e:
                # name_session calls an external API (OSError), parses JSON
                # (ValueError covers JSONDecodeError), and writes the DB
                # (sqlite3.Error). ValueError also covers a malformed result.
                print(f"engine: titler failed: {e}", file=sys.stderr)

        threading.Thread(target=_runner, daemon=True, name="titler").start()

    def _maybe_discard_short_session(self, session_id: str | None) -> bool:
        """Returns True iff the session was discarded (caller skips DB writes)."""
        if not session_id or MIN_SESSION_KEEP_SECONDS <= 0:
            return False
        duration = max(0.0, time.time() - self._session_started_at)
        finals = len([t for t in self._full_transcript if t[3]])
        if duration >= MIN_SESSION_KEEP_SECONDS or finals > 0:
            return False
        # Wipe every artefact that belongs to this session.
        base = LOG_DIR / session_id
        for suffix in (".jsonl", ".system.wav", ".summary.md"):
            p = base.with_suffix(suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # Drop the DB row too — discarded sessions should leave no trace.
        try:
            get_db().delete_session(session_id)
        except (sqlite3.Error, OSError) as e:
            print(f"engine: db cleanup of discarded session failed: {e}",
                  file=sys.stderr)
        print(
            f"engine: discarded short session {session_id} "
            f"(duration={duration:.1f}s, finals={finals})",
            file=sys.stderr,
        )
        return True

    # ---- transcript helpers ----

    def _format_speaker(self, source: str, speaker_id: int | None) -> str:
        if source == "mic":
            return "You"
        if speaker_id is None:
            return ""
        if speaker_id in self._speaker_labels:
            label = self._speaker_labels[speaker_id]
            if label is None:
                return f"Speaker {speaker_id}?"
            if label == "mixed":
                return f"Speaker {speaker_id} (mixed?)"
            return label
        return f"Speaker {speaker_id}"

    def _format_line(self, t: float, source: str, speaker_id: int | None, text: str) -> str:
        ts = datetime.fromtimestamp(t).strftime("%H:%M:%S")
        speaker = self._format_speaker(source, speaker_id)
        return f"[{ts}] {speaker}: {text}" if speaker else f"[{ts}] {text}"

    def _append_transcript_entry(self, source: str, speaker_id: int | None, text: str) -> None:
        t = time.time()
        self._full_transcript.append((t, source, speaker_id, text))

    @Slot(str, str)
    def on_interim(self, source: str, text: str) -> None:
        # Bus already publishes transcript.interim from DeepgramStreamer; nothing
        # more to do server-side. Kept as a slot so wiring stays intact.
        pass

    @Slot(str, str, str, bool)
    def on_final(self, source: str, speaker: str, text: str, speech_final: bool) -> None:
        speaker_id: int | None = None
        if source != "mic" and speaker.startswith("Speaker "):
            try:
                speaker_id = int(speaker.split()[1])
            except (IndexError, ValueError):
                speaker_id = None
        self._append_transcript_entry(source, speaker_id, text)

    def inject_transcript(self, speaker: str, text: str) -> None:
        """Dev-only caller supplies one final exactly as the STT path would."""
        if not self._session_id:
            return
        speaker = " ".join(speaker.split()).strip() or "Speaker 1"
        text = " ".join(text.split()).strip()
        if not text:
            return
        speaker_id = None
        if speaker.startswith("Speaker "):
            try:
                speaker_id = int(speaker.split()[1])
            except (IndexError, ValueError):
                pass
        rel_t = max(0.0, time.time() - self._session_started_at)
        if self._logger:
            self._logger.log("dg_final", source="system", speaker=speaker,
                             speaker_id=speaker_id, text=text,
                             speech_final=True, rel_t=rel_t, words=None)
        _BUS.publish("transcript.final", {
            "source": "system", "speaker": speaker, "speakerId": speaker_id,
            "text": text, "speechFinal": True, "relT": rel_t,
        })
        self.on_final("system", speaker, text, True)

    @Slot(str)
    def on_failed(self, msg: str) -> None:
        # Capture failed (e.g. Screen Recording TCC denied) — surface it to the
        # UI as an error notice so the session doesn't just end silently with an
        # empty transcript, then stop.
        self._log_status(f"ERROR: {msg}")
        self._publish_notice("error", msg, code=_classify_failure(msg))
        self._stop_session()

    def _new_since(self, cutoff_t: float, fallback_minutes: float) -> tuple[str, float]:
        if cutoff_t <= 0:
            cutoff_t = time.time() - fallback_minutes * 60
        new = [(t, src, sp, txt) for (t, src, sp, txt) in self._full_transcript if t > cutoff_t]
        if not new:
            return "", cutoff_t
        joined = "\n".join(self._format_line(t, src, sp, txt) for (t, src, sp, txt) in new)
        return joined, new[-1][0]

    # ---- LLM triggers ----

    @Slot()
    def trigger_insight(self) -> None:
        text, new_cutoff = self._new_since(self._last_extract_cutoff_t, INSIGHT_WINDOW_MIN)
        if len(text.strip()) < 80:
            return
        known = {
            "questions": list(self._known_questions.values()),
            "topics":    list(self._known_topics.values()),
            "decisions": list(self._known_decisions.values()),
            # Includes dismissed ones on purpose — the LLM must not re-surface
            # a question the user already waved off.
            "questions_for_me": list(self._questions_for_me.values()),
        }
        self._last_extract_cutoff_t = new_cutoff
        threading.Thread(
            target=self._insight_extractor.extract,
            args=(text, known, self._active_language, self._active_context,
                  self._self_profile()),
            daemon=True,
        ).start()

    def _self_profile(self) -> dict | None:
        """{name, aliases, role} for directed-question detection; None when no
        name is configured (detection off — the LLM can't tell who 'me' is)."""
        s = get_settings()
        name = (s.get("selfDisplayName") or "").strip()
        if not name:
            return None
        aliases = [a.strip() for a in (s.get("selfAliases") or "").split(",")
                   if a.strip()]
        return {
            "name": name,
            "aliases": aliases,
            "role": (s.get("selfRole") or "").strip(),
        }

    @Slot()
    def trigger_summary(self) -> None:
        # Gate so we don't burn an LLM call every tick if nothing happened —
        # compare against the cutoff to require some new content.
        cutoff = self._last_summary_cutoff_t or self._session_started_at or 0.0
        new_entries = [(t, src, sp, txt) for (t, src, sp, txt) in self._full_transcript
                       if t > cutoff]
        if not new_entries:
            return
        word_count = sum(len(txt.split()) for (_, _, _, txt) in new_entries)
        if word_count < SUMMARY_MIN_NEW_WORDS:
            return
        # The model regenerates from the full transcript each tick; the worker
        # caps the block it actually sends (SUMMARY_TRANSCRIPT_MAX_CHARS).
        full_lines = "\n".join(
            self._format_line(t, src, sp, txt)
            for (t, src, sp, txt) in self._full_transcript
        )
        self._last_summary_cutoff_t = self._full_transcript[-1][0]
        speaker_map = dict(self._speaker_labels)
        threading.Thread(
            target=self._summary_worker.update,
            args=(full_lines, self._active_context, speaker_map, self._active_language),
            daemon=True,
        ).start()

    @Slot()
    def trigger_actions(self) -> None:
        self._expire_actions()
        if not self._session_id:
            return
        with self._cutoff_lock:
            cutoff = self._last_actions_cutoff_t
        text, new_cutoff = self._new_since(cutoff, INSIGHT_WINDOW_MIN)
        if len(text.strip()) < 80:
            return
        full_context = "\n".join(
            self._format_line(t, src, sp, value)
            for (t, src, sp, value) in self._full_transcript
        )
        with self._actions_lock:
            known = {
                "actions": [{"id": a["id"], "title": a["title"], "status": a["status"]}
                            for a in self._actions if a.get("status") != "rejected"],
                "rejectedTitles": [a["title"] for a in self._actions
                                   if a.get("status") == "rejected"],
            }
        session_id = self._session_id

        def run() -> None:
            # The cutoff advances only after the model answered and its JSON
            # parsed. A busy worker, a timeout or a malformed response leaves
            # the window pending, so the next tick re-sends it instead of
            # dropping everything said during it.
            if self._actions_worker.extract(text, full_context, known, session_id):
                with self._cutoff_lock:
                    self._last_actions_cutoff_t = max(
                        self._last_actions_cutoff_t, new_cutoff)

        threading.Thread(target=run, daemon=True, name="actions-extract").start()

    @Slot(object)
    def on_actions(self, actions: list[dict]) -> None:
        for action in actions:
            self._merge_action(action)

    def _expire_actions(self) -> None:
        """Age out suggestions nobody acted on. The stored row is re-read under
        the action write lock before the flip, so an approve or a /prepare
        write that landed since the last tick is never clobbered."""
        now = datetime.now(timezone.utc)
        stale: list[tuple[str, str]] = []
        with self._actions_lock:
            for action in self._actions:
                if action.get("status") != "suggested":
                    continue
                try:
                    age = now - datetime.fromisoformat(action["suggestedAt"])
                except (KeyError, TypeError, ValueError):
                    continue
                if age.total_seconds() > ACTION_EXPIRY_S:
                    stale.append((action.get("sessionId", ""), action.get("id", "")))
        for session_id, action_id in stale:
            if not session_id or not action_id:
                continue
            with ACTION_WRITE_LOCK:
                current = get_db().get_action(session_id, action_id)
                if current is None or current.get("status") != "suggested":
                    continue
                current["status"] = "expired"
                current["updatedAt"] = now_iso()
                get_db().upsert_action(current)
            self.sync_action(current)
            _BUS.publish("action.updated", current, session_id=current["sessionId"])

    def sync_action(self, action: dict) -> None:
        """Keep live worker state aligned with changes made by HTTP routes.

        An HTTP route can touch an action belonging to an *ended* session while
        a different one is live (the dashboard still lists old sessions). That
        row is already persisted and published by the route; merging it into
        the live list would poison this session's dedupe and rejected-title
        state with another meeting's actions, so it is ignored here.
        """
        if action.get("sessionId") != self._session_id:
            return
        with self._actions_lock:
            for index, existing in enumerate(self._actions):
                if existing.get("id") == action.get("id"):
                    self._actions[index] = dict(action)
                    return
            self._actions.append(dict(action))

    @Slot(str, object)
    def on_summary_ready(self, text: str, meta: dict) -> None:
        self._last_summary_at = time.time()

    def _final_summary_snapshot(self) -> None:
        """End-of-session: force one final summary pass + write .summary.md."""
        log_path = getattr(self._logger, "path", None) if self._logger else None
        full_lines = "\n".join(
            self._format_line(t, src, sp, txt)
            for (t, src, sp, txt) in self._full_transcript
        )
        speaker_map = dict(self._speaker_labels)

        captured: dict = {}

        def _capture(text, _meta):
            captured["text"] = text

        self._summary_worker.summary_ready.connect(_capture)
        done = threading.Event()

        def _runner() -> None:
            try:
                self._summary_worker.update(
                    full_lines, self._active_context, speaker_map,
                    self._active_language, force_final=True,
                )
            finally:
                done.set()

        try:
            threading.Thread(target=_runner, daemon=True).start()
            done.wait(timeout=8.0)
        finally:
            try:
                self._summary_worker.summary_ready.disconnect(_capture)
            except (RuntimeError, TypeError):
                pass

        text = captured.get("text") or getattr(self._summary_worker, "_current_summary", "")
        if not text or not log_path:
            return
        try:
            out_path = log_path.with_suffix(".summary.md")
            header = (
                f"# Meeting summary\n\nSession: `{log_path.name}`  \n"
                f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n---\n\n"
            )
            out_path.write_text(header + text, encoding="utf-8")
        except OSError as e:
            self._log_status(f"Summary save failed: {e}")

    # ---- insight accumulation ----

    @staticmethod
    def _norm_key(s: str) -> str:
        return " ".join(s.lower().strip().split())

    def _add_unique(self, bucket: dict[str, str], item: str) -> bool:
        item = item.strip()
        if not item:
            return False
        key = self._norm_key(item)
        if key in bucket:
            return False
        bucket[key] = item
        return True

    @Slot(object)
    def on_insights(self, data: dict) -> None:
        for q in data.get("questions", []):
            self._add_unique(self._known_questions, q)
        for t in data.get("topics", []):
            self._add_unique(self._known_topics, t)
        for d in data.get("decisions", []):
            self._add_unique(self._known_decisions, d)
        changed = False
        for q in data.get("questions_for_me", []):
            changed = self._merge_question_for_me(q) or changed
        if changed:
            self._publish_questions_for_me()

    # ---- questions directed at the user ----

    # Two normalized texts at or above this similarity are the same question;
    # the longer (more specific) phrasing wins, replacing the variant in place.
    _QFM_SIMILARITY = 0.8

    def _merge_question_for_me(self, text: str) -> bool:
        """Curated merge: exact/near duplicates collapse onto one entry, a
        refinement replaces its shorter variant under the SAME key (so the UI
        updates the item instead of growing the list). Returns True if the
        visible set changed."""
        text = " ".join(text.split()).strip()
        if not text:
            return False
        key = self._norm_key(text)
        if key in self._questions_for_me:
            return False
        for k, existing in self._questions_for_me.items():
            ratio = difflib.SequenceMatcher(
                None, key, self._norm_key(existing)).ratio()
            if ratio >= self._QFM_SIMILARITY:
                if len(text) > len(existing) and k not in self._qfm_dismissed:
                    self._questions_for_me[k] = text   # refinement wins
                    if self._logger:
                        self._logger.log("question_for_me", id=k, text=text,
                                         refined=True)
                    return True
                return False   # shorter/equal variant of a known question
        self._questions_for_me[key] = text
        if self._logger:
            self._logger.log("question_for_me", id=key, text=text, refined=False)
        return True

    _ACTION_SIMILARITY = 0.8
    # Suppressing a suggestion because the user rejected something similar is
    # destructive (the action never reaches the UI), so it takes a much closer
    # match than an in-place refinement does — and the same kind.
    _REJECTED_SIMILARITY = 0.9
    _ACTION_TERMINAL = set(ACTION_TERMINAL)

    def _merge_action(self, action: dict) -> bool:
        """Merge a new suggestion by id or fuzzy title, preserving lifecycle state."""
        title = " ".join(str(action.get("title") or "").split()).strip()
        if not title:
            return False
        # A worker pass started under a previous session can land after the
        # next one began. Its actions belong to that session: persist and
        # publish them there, but keep them out of this session's live dedupe
        # and rejected-title state.
        if action.get("sessionId") != self._session_id:
            return self._store_foreign_action(action, title)
        kind = action.get("kind")
        title_key = self._norm_key(title)
        event_type = "action.suggested"
        stored: dict | None = None
        is_new = False
        with self._actions_lock:
            for existing in self._actions:
                if existing.get("status") != "rejected" or existing.get("kind") != kind:
                    continue
                ratio = difflib.SequenceMatcher(
                    None, title_key, self._norm_key(existing.get("title", ""))).ratio()
                if ratio >= self._REJECTED_SIMILARITY:
                    return False
            for index, existing in enumerate(self._actions):
                same_id = action.get("id") == existing.get("id")
                same_kind = existing.get("kind") == kind
                ratio = difflib.SequenceMatcher(
                    None, title_key, self._norm_key(existing.get("title", ""))).ratio()
                # Fuzzy title matching only ever collapses two suggestions of
                # the SAME kind — "Send Ana the Q3 diagram" as a draft_message
                # and as a create_task are two different things to do.
                fuzzy = (same_kind and ratio >= self._ACTION_SIMILARITY
                         and existing.get("status") not in self._ACTION_TERMINAL)
                if not (same_id or fuzzy):
                    continue
                # Only a still-suggested action is refined in place. Once the
                # user approved it (or it ran, or it finished) its kind and args
                # are what was approved and what hands is executing — a later
                # model pass must never rewrite them.
                if existing.get("status") != "suggested":
                    return False
                merged = dict(action)
                merged["id"] = existing["id"]
                merged["suggestedAt"] = existing.get("suggestedAt", action["suggestedAt"])
                # A waitpoint run prepared for this suggestion survives refinement.
                merged["runId"] = existing.get("runId") or action.get("runId")
                merged["updatedAt"] = now_iso()
                self._actions[index] = merged
                stored = dict(merged)
                event_type = "action.updated"
                break
            else:
                action = dict(action)
                action["title"] = title
                self._actions.append(action)
                stored = dict(action)
                is_new = True
        if stored is None:
            return False
        get_db().upsert_action(stored)
        if self._logger:
            self._logger.log(event_type.replace(".", "_"), action=stored)
        _BUS.publish(event_type, stored, session_id=stored["sessionId"])
        if is_new:
            # EXECUTOR=trigger: ask hands to stage the run + approval waitpoint
            # now, so approving later is one waitpoint completion. No-op in
            # local mode.
            start_prepare(stored, self._store_prepared_action)
        return True

    def _store_foreign_action(self, action: dict, title: str) -> bool:
        """Persist + publish an action for a session that is no longer live."""
        stored = dict(action)
        stored["title"] = title
        session_id = stored.get("sessionId")
        if not session_id:
            return False
        get_db().upsert_action(stored)
        _BUS.publish("action.suggested", stored, session_id=session_id)
        return True

    def _store_prepared_action(self, action: dict) -> dict:
        """Write-back path for the hands /prepare thread (runId only)."""
        get_db().upsert_action(action)
        self.sync_action(action)
        _BUS.publish("action.updated", action, session_id=action["sessionId"])
        return action

    def _publish_questions_for_me(self) -> None:
        items = [{"id": k, "text": v}
                 for k, v in self._questions_for_me.items()
                 if k not in self._qfm_dismissed]
        _BUS.publish("questions.forme", {"items": items})

    def dismiss_question_for_me(self, qid: str) -> None:
        """User waved the question off. It stays in the known set (so the LLM
        never re-surfaces it) but leaves the UI. Runs on the engine thread via
        enqueue_control."""
        self._qfm_dismissed.add(qid)
        if self._logger:
            self._logger.log("question_for_me_dismissed", id=qid)
        self._publish_questions_for_me()

    # ---- misc ----

    def _log_status(self, msg: str) -> None:
        # Headless: print short engine status lines to stderr.
        if not msg:
            return
        print(f"engine: {msg}", file=sys.stderr)
        # Surface worker-level errors (rate limits) to the UI as
        # notices. Capture failures are published explicitly in on_failed with
        # the "ERROR:" prefix, so skip those here to avoid a duplicate.
        if msg.startswith("ERROR:"):
            return
        low = msg.lower()
        if any(hint in low for hint in _WORKER_ERROR_HINTS):
            self._publish_notice("warning", msg, code=_classify_failure(msg))

    def _publish_notice(self, level: str, message: str,
                        code: str | None = None) -> None:
        """Push a human-facing notice to the UI over the bus (scoped to the
        current session). `level` is "error" | "warning"; `code` lets the UI
        offer a targeted action (e.g. a permission deep-link)."""
        _BUS.publish("engine.notice",
                     {"level": level, "message": message, "code": code})

    def shutdown(self) -> None:
        """Best-effort clean shutdown of worker threads. Called from main()'s
        SIGINT handler before quitting the Qt event loop."""
        if self.is_session_running():
            self._stop_session()
        if self._insight_thread is not None:
            self._insight_thread.quit()
            self._insight_thread.wait(2000)

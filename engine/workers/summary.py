"""Rolling meeting summary — configured LLM completion driven.

Every ~45 seconds the engine sends the transcript so far + the previous summary
as prior and gets back a structured multi-section Markdown summary. The worker
maintains its own previous-summary state and takes the full transcript each
tick; the model regenerates the structured output from scratch with
PREVIOUS_SUMMARY as a soft anchor.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal

from engine.bus import get_bus
from engine.config import (
    LANGUAGE_DISPLAY_NAMES,
    SUMMARY_LLM_TIMEOUT_S,
    SUMMARY_TRANSCRIPT_MAX_CHARS,
)
from engine.llm import complete_text, status as llm_status
from engine.logger import JSONLLogger

_BUS = get_bus()


SUMMARY_SYSTEM_PROMPT = """You maintain a live, comprehensive rolling summary of a meeting while it is happening. You will be called every ~60 seconds with the FULL transcript so far, the previous summary you produced, and meeting context. Regenerate a fresh structured summary that reflects the entire meeting up to this moment.

Inputs:
  • MEETING_CONTEXT: free-form notes (participants, project, topic).
  • SPEAKER_MAP: optional {id: name} hints — use names when present.
  • PREVIOUS_SUMMARY: your last output. Use it as a soft anchor (don't lose facts that are still relevant), but the FULL_TRANSCRIPT below is authoritative.
  • FULL_TRANSCRIPT: every transcript line so far, in order, with speakers + timestamps.

Output: Markdown with EXACTLY these sections, in this order:

**Now discussing:** one line — what's happening right now (most recent moments win).

**Topics covered:**
- bullet — topic 1, with a one-sentence gist
- bullet — topic 2, ...
- (cover the whole meeting, not just the last window; ~6–10 bullets max)

**Decisions / commitments:**
- bullet — concrete decisions, asks, or commitments made by participants
- (use "—" if none)

**Open questions:**
- bullet — anything raised that's still unanswered
- (use "—" if none)

**Action items:**
- bullet — explicit TODOs assigned (who owes what), or "—"

**Risks / concerns:**
- bullet — risks, blockers, or worries surfaced, or "—"

Rules:
- Be FACTUAL — only state things that appear in transcript content. Never invent.
- Use participants' real names when SPEAKER_MAP provides them; otherwise "Speaker N".
- Match the meeting's language (Spanish transcript → Spanish summary).
- Skip filler ("you know", "I mean"). Compress aggressively.
- No preamble, no meta-commentary, no closing remarks. Just the sections."""


class SummaryWorker(QObject):
    """Maintains a rolling Markdown summary via a configured LLM completion.

    Emits `summary_ready(text, meta)` every successful tick.
    """

    summary_ready = Signal(str, object)
    finished = Signal()
    status = Signal(str)

    def __init__(self, logger: JSONLLogger | None):
        super().__init__()
        self._log = logger
        self._lock = threading.Lock()
        # Serializes the actual LLM call in _do_update so two ticks can never
        # run concurrently (the old _busy flag let a force_final tick overlap a
        # regular one — two calls racing on _current_summary).
        self._work_lock = threading.Lock()
        self._current_summary = ""

    def reset(self):
        with self._lock:
            self._current_summary = ""

    def _ensure_client(self) -> bool:
        if not llm_status()["configured"]:
            msg = "LLM key not set; rolling summary disabled"
            self.status.emit(msg)
            # Log to the JSONL too — status only goes to stderr, which made
            # this failure invisible in past sessions. A real event means a
            # missing-summary can always be diagnosed from the session log.
            if self._log:
                self._log.log("summary_error", error="llm_key_missing")
            return False
        return True

    def update(self, full_transcript: str, meeting_context: str = "",
               speaker_map: dict | None = None, language: str | None = None,
               *, force_final: bool = False):
        """Regenerate the summary from the full transcript.

        full_transcript: every formatted line in the meeting so far. (Empty
                         allowed when force_final=True so we can re-emit at
                         end-of-session.)
        force_final:     always run, even if another tick is in flight — but
                         serialized, never overlapping.
        """
        # A regular tick that finds a summary already in flight just skips
        # (non-blocking acquire). The end-of-session force_final tick must
        # always produce output, so it waits for the in-flight tick to finish
        # (blocking acquire) instead of issuing a second call and racing on
        # _current_summary.
        if not self._work_lock.acquire(blocking=force_final):
            self.finished.emit()
            return
        try:
            self._do_update(full_transcript, meeting_context, speaker_map or {},
                            language, force_final=force_final)
        finally:
            self._work_lock.release()
            self.finished.emit()

    def _do_update(self, full_transcript: str, meeting_context: str,
                   speaker_map: dict, language: str | None, *, force_final: bool):
        if not self._ensure_client():
            return
        if not full_transcript.strip() and not force_final:
            return

        # Keep only the transcript tail: PREVIOUS_SUMMARY already carries the
        # older content, and an uncapped block makes tick latency grow with
        # meeting length until it hits the request timeout.
        if len(full_transcript) > SUMMARY_TRANSCRIPT_MAX_CHARS:
            tail = full_transcript[-SUMMARY_TRANSCRIPT_MAX_CHARS:]
            cut = tail.find("\n")
            if 0 <= cut < 2000:   # resume at a line boundary when one is near
                tail = tail[cut + 1:]
            full_transcript = (
                "(earlier transcript omitted — PREVIOUS_SUMMARY covers it)\n"
                + tail
            )

        ctx_block = (
            f"MEETING_CONTEXT:\n{meeting_context.strip()}\n\n"
            if meeting_context.strip() else ""
        )
        spk_block = ""
        if speaker_map:
            named = {str(k): v for k, v in speaker_map.items()
                     if v not in (None, "mixed")}
            if named:
                import json as _json
                spk_block = (
                    f"SPEAKER_MAP:\n{_json.dumps(named, ensure_ascii=False)}\n\n"
                )
        prev_block = (
            f"PREVIOUS_SUMMARY:\n{self._current_summary}\n\n"
            if self._current_summary else
            "PREVIOUS_SUMMARY: (none — this is the first tick)\n\n"
        )
        transcript_block = (
            f"FULL_TRANSCRIPT:\n---\n{full_transcript}\n---\n"
            if full_transcript.strip() else
            "FULL_TRANSCRIPT: (none — produce a final cleanup of PREVIOUS_SUMMARY)\n"
        )
        lang_directive = ""
        if language and language != "multi":
            lang_name = LANGUAGE_DISPLAY_NAMES.get(language, language)
            lang_directive = f"\nWrite the summary in {lang_name}.\n"

        user_msg = (
            f"{lang_directive}{ctx_block}{spk_block}{prev_block}{transcript_block}\n"
            "Regenerate the structured summary now."
        )

        t0 = time.perf_counter()
        try:
            text = complete_text(
                SUMMARY_SYSTEM_PROMPT, user_msg, max_tokens=2000,
                timeout=SUMMARY_LLM_TIMEOUT_S,
            )
        except Exception as e:
            self.status.emit(f"summary error: {e}")
            if self._log:
                self._log.log("summary_error", error=str(e))
            return
        elapsed = time.perf_counter() - t0

        if not text:
            if self._log:
                self._log.log("summary_error", error="empty_completion")
            return
        self._current_summary = text

        meta = dict(
            api_s=elapsed,
            backend=llm_status()["provider"],
            model=llm_status()["model"],
            transcript_chars=len(full_transcript),
            summary_chars=len(text),
            force_final=force_final,
        )
        if self._log:
            self._log.log("summary_updated", **meta)
        _BUS.publish("summary.updated", {"text": text, "meta": meta})
        self.summary_ready.emit(text, meta)

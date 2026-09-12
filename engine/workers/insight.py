"""Insight extractor — LLM stage 1.

Periodically asks the configured LLM to pull questions / topics / decisions
out of the rolling transcript. Differential: every call receives only the new
text since the previous call plus the items already surfaced, so the LLM
doesn't re-emit duplicates.
"""
from __future__ import annotations

import json
import threading
import time

from PySide6.QtCore import QObject, Signal

from engine.bus import get_bus
from engine.config import LANGUAGE_DISPLAY_NAMES
from engine.llm import complete_json, status as llm_status
from engine.logger import JSONLLogger

_BUS = get_bus()


INSIGHT_SYSTEM_PROMPT = """You analyze live meeting transcripts incrementally and surface the points worth following up on.

You will be given:
  • MEETING_CONTEXT (optional): background — project names, people, jargon, products being discussed. Use this to disambiguate fragments and produce specific, well-named items.
  • ALREADY_KNOWN: items that were already surfaced in earlier calls — do NOT repeat or rephrase these.
  • NEW_TRANSCRIPT: only the latest portion of the meeting (new content since the last call).

From NEW_TRANSCRIPT extract:
1. "questions" — questions raised that would benefit from external context (project docs, code, prior decisions). Skip rhetorical questions and ones answered in the same passage.
2. "topics" — the substantive topics being discussed (1-5 words each, Title Case).
3. "decisions" — concrete decisions, commitments, or action items mentioned.
4. "questions_for_me" — only when a USER_PROFILE block is present: questions or requests that OTHER speakers direct AT the user — addressing them by name/alias from the profile, or clearly directed at them given their role and the conversation. Lines spoken by the user themselves (labeled with their name or "You") are NEVER a source for this list — those are things the user said, not things asked of them. Rewrite each as one clean, self-contained question the user must answer (≤ 20 words, keep the asker's intent, resolve pronouns using context). If NEW_TRANSCRIPT adds detail to a question already in ALREADY_KNOWN's questions_for_me, return the REFINED version of that question; otherwise never repeat or rephrase known ones. When unsure whether something was directed at the user, omit it — precision over recall.

Rules:
- STRICT JSON output. No prose, no markdown, no commentary.
- Questions MUST be specific and decontextualized. They must include the SUBJECT (what the question is about). REJECT bare fragments like "¿Qué es?" / "What is it?" / "And that?" — when the transcript is too vague, either rewrite using MEETING_CONTEXT or omit.
- Each item ≤ 15 words, self-contained (a stranger seeing only this item could understand it).
- Use consistent casing (Title Case for topics, sentence case for questions/decisions).
- Empty arrays if nothing concrete and new. Quality > quantity — one specific question beats three generic ones.
- Skip items whose meaning is already in ALREADY_KNOWN even if phrased differently.
- Do NOT invent items. If unsure, omit."""

INSIGHT_RESPONSE_SCHEMA_EXAMPLE = (
    '{"questions": ["..."], "topics": ["..."], "decisions": ["..."], '
    '"questions_for_me": ["..."]}'
)
INSIGHT_RESPONSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["questions", "topics", "decisions", "questions_for_me"],
    "properties": {name: {"type": "array", "items": {"type": "string"}}
                   for name in ("questions", "topics", "decisions", "questions_for_me")},
}


class InsightExtractor(QObject):
    """Periodically asks an LLM to pull questions/topics/decisions from the rolling transcript."""

    # `Signal(object)` rather than `Signal(dict)` because Qt's QVariant
    # copy-conversion silently drops dicts whose keys aren't strings across
    # threads. Same reason as SpeakerLabeler.labels_ready.
    insights_ready = Signal(object)
    finished = Signal()
    status = Signal(str)

    def __init__(self, logger: JSONLLogger | None):
        super().__init__()
        self._log = logger
        self._lock = threading.Lock()
        self._busy = False

    def _ensure_client(self) -> bool:
        configured = bool(llm_status()["configured"])
        if not configured:
            self.status.emit("LLM key not set; insights disabled")
        return configured

    def extract(self, new_transcript: str,
                already_known: dict[str, list[str]] | None = None,
                language: str | None = None,
                meeting_context: str = "",
                self_profile: dict | None = None):
        """Differential extraction.

        new_transcript: only the lines added since the last call.
        already_known: dict so the LLM avoids re-surfacing items.
        language: ISO code; LLM will reply in that language.
        meeting_context: free-form background (names, jargon, products).
        self_profile: {name, aliases, role} of the local user — enables the
        questions_for_me extraction (omitted when no usable name is set).
        """
        with self._lock:
            if self._busy:
                self.finished.emit()
                return  # previous extraction still running
            self._busy = True
        try:
            self._do_extract(new_transcript, already_known or {}, language,
                             meeting_context, self_profile)
        finally:
            with self._lock:
                self._busy = False
            self.finished.emit()

    def _do_extract(self, transcript: str, already_known: dict, language: str | None,
                    meeting_context: str, self_profile: dict | None = None):
        if not self._ensure_client():
            return
        transcript = transcript.strip()
        if len(transcript) < 80:
            return

        known_block = json.dumps({
            "questions": already_known.get("questions", []),
            "topics":    already_known.get("topics", []),
            "decisions": already_known.get("decisions", []),
            "questions_for_me": already_known.get("questions_for_me", []),
        }, ensure_ascii=False)

        profile_block = ""
        if self_profile and (self_profile.get("name") or "").strip():
            profile_block = (
                "USER_PROFILE (the local user — detect questions addressed to them):\n"
                + json.dumps(self_profile, ensure_ascii=False) + "\n\n"
            )

        lang_directive = ""
        if language and language != "multi":
            lang_name = LANGUAGE_DISPLAY_NAMES.get(language, language)
            lang_directive = (
                f"\nIMPORTANT: The meeting is in {lang_name}. Write ALL extracted "
                f"items (questions, topics, decisions) in {lang_name}.\n"
            )

        ctx_block = ""
        if meeting_context.strip():
            ctx_block = f"MEETING_CONTEXT:\n{meeting_context.strip()}\n\n"

        user_msg = (
            f"{lang_directive}"
            f"{ctx_block}"
            f"{profile_block}"
            f"ALREADY_KNOWN (do not repeat or rephrase these):\n{known_block}\n\n"
            f"NEW_TRANSCRIPT:\n---\n{transcript}\n---\n\n"
            f"Return JSON matching: {INSIGHT_RESPONSE_SCHEMA_EXAMPLE}"
        )

        t0 = time.perf_counter()
        try:
            data = complete_json(
                INSIGHT_SYSTEM_PROMPT, user_msg, schema=INSIGHT_RESPONSE_SCHEMA,
                max_tokens=400, timeout=60,
            )
        except Exception as e:
            self.status.emit(f"insight error: {e}")
            if self._log:
                self._log.log("insight_error", error=str(e))
            return
        elapsed = time.perf_counter() - t0

        data = {
            "questions": [s for s in (data.get("questions") or []) if isinstance(s, str)],
            "topics":    [s for s in (data.get("topics")    or []) if isinstance(s, str)],
            "decisions": [s for s in (data.get("decisions") or []) if isinstance(s, str)],
            "questions_for_me": [
                s for s in (data.get("questions_for_me") or []) if isinstance(s, str)
            ],
        }
        meta = dict(
            api_s=elapsed,
            provider=llm_status()["provider"],
            model=llm_status()["model"],
            transcript_chars=len(transcript),
        )
        data["meta"] = meta

        if self._log:
            self._log.log(
                "insight_extracted",
                **meta,
                n_questions=len(data["questions"]),
                n_topics=len(data["topics"]),
                n_decisions=len(data["decisions"]),
                n_questions_for_me=len(data["questions_for_me"]),
                questions=data["questions"],
                topics=data["topics"],
                decisions=data["decisions"],
                questions_for_me=data["questions_for_me"],
            )
        _BUS.publish("insight.extracted", data)
        self.insights_ready.emit(data)

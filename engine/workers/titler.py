"""Session titler — LLM that names a session from its final summary.

Called once at the end of every session (after the rolling summary worker
has produced its last update). Returns a short, human-readable title (3-6
words) plus a one-line blurb suitable for the sessions list.

This is a plain Python function, not a QObject worker — it runs on a
background thread the runtime spawns at end-of-session and writes its
result directly to the SQLite store.
"""
from __future__ import annotations

import logging
import time

from engine.db import get_db
from engine.llm import complete_json, status as llm_status
from engine.logger import JSONLLogger

log = logging.getLogger(__name__)

TITLE_RESPONSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "blurb"],
    "properties": {"title": {"type": "string"}, "blurb": {"type": "string"}},
}


TITLE_SYSTEM_PROMPT = """You name meeting recordings so a person can find them again later.

Given the meeting summary, produce a STRICT JSON object:
  { "title": "...", "blurb": "..." }

Rules:
- "title": 3-6 words, Title Case. The most distinctive identifier of the
  meeting (topic + a named participant if useful). Skip generic words like
  "Meeting" or "Session" unless absolutely necessary. No trailing period.
- "blurb": one sentence, ≤ 18 words. Says what the meeting was actually about.
- Match the meeting's language: if the summary is in Spanish, return Spanish.
- Never invent participants or topics not in the summary.
- If the summary is empty or unclear, return a reasonable best-effort name
  derived from whatever's there.
- NO Markdown, NO commentary, just the JSON object."""


def name_session(session_id: str, summary_text: str,
                 logger: JSONLLogger | None = None) -> dict[str, str] | None:
    """Ask the LLM for `{title, blurb}` and persist to the DB.

    Returns the saved row payload, or `None` if the LLM call failed.
    """
    summary_text = (summary_text or "").strip()
    if not summary_text:
        return None
    if not llm_status()["configured"]:
        log.info("titler: LLM key not set; skipping auto-name")
        return None
    t0 = time.perf_counter()
    try:
        data = complete_json(
            TITLE_SYSTEM_PROMPT, summary_text[:8000], schema=TITLE_RESPONSE_SCHEMA,
            max_tokens=120, timeout=60,
        )
    except Exception as e:
        log.warning("titler: API error: %s", e)
        if logger:
            logger.log("titler_error", error=str(e))
        return None
    elapsed = time.perf_counter() - t0

    title = str(data.get("title") or "").strip()
    blurb = str(data.get("blurb") or "").strip()
    if not title:
        return None

    get_db().set_generated_title(session_id, title, blurb)

    if logger:
        logger.log(
            "titler_done",
            api_s=elapsed,
            provider=llm_status()["provider"], model=llm_status()["model"],
            title=title,
            blurb=blurb,
        )
    return {"title": title, "blurb": blurb}

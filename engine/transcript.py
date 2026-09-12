"""Speaker-label hygiene + transcript rendering — shared across workers/server.

Single source of truth for three things that would otherwise be
re-implemented (and drift) in `server.py` and `runtime.py`:

1. `clean_speaker_name()` — coerce junk the labeling LLM sometimes emits
   (the literal strings ``"null"`` / ``"none"`` / ``""``, the placeholder
   ``Name | null | "mixed"`` it occasionally echoes from its own prompt, or
   the ``"mixed"`` sentinel) into ``None`` so it never reaches the UI or a
   rendered transcript as if it were a real name.
2. `resolve_speaker()` — given a transcript line's source/speaker_id/speaker
   plus the label map and the user's own display name, decide the single
   string to show. The mic source is always the local user.
3. `render_transcript_md()` — build a faithful, correctly-attributed Markdown
   transcript from the raw ``dg_final`` events + the *current* labels, so a
   download always reflects the latest manual corrections (unlike the static
   end-of-session archive).
"""
from __future__ import annotations

from typing import Any, Iterable

# Strings the labeler may emit that are NOT real names. Compared case-folded.
# `mixed` is a real sentinel (diarization fused two voices) but it is not a
# name, so for display purposes it collapses to "unknown" too.
_JUNK_LABELS = {
    "", "null", "none", "n/a", "na", "unknown", "undefined", "mixed",
    # The example/placeholder baked into the speaker-labeler prompt. The LLM
    # has been observed echoing it verbatim as a "name".
    'name | null | "mixed"',
    "name | null | mixed",
}

# Default label for the local microphone speaker when the user hasn't set a
# display name.
DEFAULT_SELF_NAME = "You"


def clean_speaker_name(value: Any) -> str | None:
    """Return a real display name, or ``None`` if `value` is junk/sentinel.

    Used everywhere a label crosses a trust boundary: when storing the LLM's
    output, when reading the sidecar, and when rendering. Idempotent.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.casefold() in _JUNK_LABELS:
        return None
    return s


def clean_label_map(raw: dict | None) -> dict[str, str]:
    """Filter a ``{speaker_id: name}`` map down to entries with real names.

    Keys are normalized to ``str``. Junk values are dropped entirely (so the
    caller falls back to a generic ``Speaker N``).
    """
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        name = clean_speaker_name(v)
        if name is not None:
            out[str(k)] = name
    return out


def resolve_speaker(
    *,
    source: str | None,
    speaker_id: Any,
    speaker: str | None,
    labels: dict[str, str],
    self_name: str = DEFAULT_SELF_NAME,
) -> str:
    """Decide the display name for one transcript line.

    Precedence:
      1. Mic source → the local user's display name (`self_name`).
      2. A real name in `labels` for this `speaker_id`.
      3. The raw Deepgram `speaker` string if it's a real name.
      4. ``Speaker <id>`` / ``Speaker ?`` fallback.
    """
    if source == "mic":
        return self_name or DEFAULT_SELF_NAME
    if speaker_id is not None:
        mapped = clean_speaker_name(labels.get(str(speaker_id)))
        if mapped is not None:
            return mapped
    raw = clean_speaker_name(speaker)
    if raw is not None and raw.lower() != "you":
        return raw
    if speaker_id is not None:
        return f"Speaker {speaker_id}"
    return "Speaker ?"


def _hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_transcript_md(
    finals: Iterable[dict[str, Any]],
    *,
    labels: dict[str, str],
    self_name: str = DEFAULT_SELF_NAME,
    title: str | None = None,
    merge_consecutive: bool = True,
) -> str:
    """Render a faithful Markdown transcript from ``dg_final`` events.

    `finals` are the raw event dicts (each with `rel_t`, `text`, `source`,
    `speaker`, `speaker_id`). Labels are applied at render time, so this always
    reflects the latest manual corrections. Consecutive lines from the same
    speaker are merged into one paragraph for readability.
    """
    rows: list[tuple[float, str, str]] = []  # (rel_t, speaker, text)
    for e in finals:
        text = (e.get("text") or "").strip()
        if not text:
            continue
        spk = resolve_speaker(
            source=e.get("source"),
            speaker_id=e.get("speaker_id"),
            speaker=e.get("speaker"),
            labels=labels,
            self_name=self_name,
        )
        rel_t = float(e.get("rel_t") or 0.0)
        if merge_consecutive and rows and rows[-1][1] == spk:
            prev_t, prev_spk, prev_text = rows[-1]
            rows[-1] = (prev_t, prev_spk, f"{prev_text} {text}")
        else:
            rows.append((rel_t, spk, text))

    lines = [f"**[{_hhmmss(t)}] {spk}:** {text}" for t, spk, text in rows]
    body = "\n\n".join(lines) if lines else "(no transcribed content)"
    head = f"# {title}\n\n" if title else ""
    return head + body


def format_archive_header(
    meta: dict[str, Any],
    *,
    source_name: str | None,
    generated: str,
    duration_s: float | None = None,
) -> str:
    """Human-readable header for the re-diarized archive transcript.

    Replaces the old cryptic ``Speakers: {'0': 155} · utterances: 155 ·
    api: 3.8s`` line with a plain-language summary.
    """
    speakers = meta.get("speakers") or {}
    n_speakers = len([k for k in speakers.keys()]) if isinstance(speakers, dict) else 0
    segments = meta.get("utterances") or (
        sum(speakers.values()) if isinstance(speakers, dict) else 0
    )
    api_s = meta.get("api_s", 0) or 0

    spk_word = "speaker" if n_speakers == 1 else "speakers"
    seg_word = "segment" if segments == 1 else "segments"
    bits = [f"{n_speakers} {spk_word}", f"{segments} {seg_word}"]
    if duration_s:
        bits.append(_hhmmss(duration_s))

    return (
        "# Archive transcript\n\n"
        f"Re-diarized from the meeting's system audio · {' · '.join(bits)}\n\n"
        f"Generated {generated}"
        + (f" · source `{source_name}`" if source_name else "")
        + (f" · processed in {api_s:.1f}s" if api_s else "")
        + "\n\n---\n\n"
    )

"""Prompt-injection screen for outbound action text (Mozilla.ai any-guardrail).

Runs `deepset/deberta-v3-base-injection` (a ~184M-param DeBERTa-v3-base
sequence classifier, ~370MB safetensors download) locally on CPU through
`any-guardrail`'s HuggingFace backend — no GPU and no API key. It is the
smallest guardrail in the installed set that needs neither a hosted API key
(`AnyGuardrail.list_guardrails(backend=BackendType.LOCAL_ENCODER,
requires_api_key=False)`) nor a multi-hundred-million-parameter judge/LLM
backend.

Disabled by default (`GUARDRAIL=off`) so teammates without the extra
dependencies installed, or who just don't want the download, are unaffected.
Set `GUARDRAIL=on` to enable. The model loads once, lazily, on first call to
`screen()`, behind a lock so concurrent workers don't race the load.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

_ENABLED = (os.environ.get("GUARDRAIL") or "off").strip().lower() == "on"

_lock = threading.Lock()
_guardrail: Any = None
_load_failed = False


def enabled() -> bool:
    return _ENABLED


def _get_guardrail() -> Any:
    """Lazily create and cache the any-guardrail instance (loads the model)."""
    global _guardrail, _load_failed
    if _guardrail is not None or _load_failed:
        return _guardrail
    with _lock:
        if _guardrail is not None or _load_failed:
            return _guardrail
        from any_guardrail import AnyGuardrail, GuardrailName

        _guardrail = AnyGuardrail.create(GuardrailName.DEEPSET)
        return _guardrail


def screen(text: str) -> dict[str, Any]:
    """Screen `text` for prompt injection. Never raises.

    Returns one of:
    - `{"passed": True}` — the guardrail ran and text looks fine.
    - `{"passed": False, "reason": "<short>"}` — the guardrail flagged it.
    - `{"passed": True, "skipped": "off"}` — GUARDRAIL is not "on".
    - `{"passed": True, "skipped": "error"}` — the guardrail raised; logged
      and treated as a pass so a broken/missing model never blocks an action.
    """
    if not _ENABLED:
        return {"passed": True, "skipped": "off"}
    text = (text or "").strip()
    if not text:
        return {"passed": True}
    try:
        guardrail = _get_guardrail()
        if guardrail is None:
            return {"passed": True, "skipped": "error"}
        result = guardrail.validate(text)
        if result.valid:
            return {"passed": True}
        return {"passed": False, "reason": "possible prompt injection detected"}
    except Exception:
        global _load_failed
        _load_failed = True
        log.exception("guardrail screen failed; treating as pass")
        return {"passed": True, "skipped": "error"}

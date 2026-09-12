"""Small any-llm facade shared by every engine LLM worker."""
from __future__ import annotations
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from typing import Any

try:
    from any_llm import completion
except ImportError:  # Mock mode remains usable before optional SDK installation.
    completion = None  # type: ignore[assignment]

_FALLBACK_OPENAI_MODEL = "gpt-5.6"
_KEY_ENV = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
def _provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or "openai").strip().lower()


def _discover_openai_model() -> tuple[str, str]:
    configured = (os.environ.get("LLM_MODEL") or "").strip()
    if configured:
        return configured, "environment"
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return _FALLBACK_OPENAI_MODEL, "fallback"
    req = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            models = json.load(response).get("data", [])
        allowed = []
        for item in models:
            model_id = str(item.get("id") or "")
            if re.fullmatch(r"gpt-5(?:\.\d+)*(?:-\d{4}-\d{2}-\d{2})?", model_id):
                allowed.append((int(item.get("created") or 0), model_id))
        if allowed:
            newest_created = max(created for created, _ in allowed)
            newest = [model_id for created, model_id in allowed if created == newest_created]
            newest.sort(key=lambda value: (bool(re.search(r"-\d{4}-", value)), value))
            return newest[0], "api"
    except Exception:
        pass
    return _FALLBACK_OPENAI_MODEL, "fallback"


PROVIDER = _provider()
if PROVIDER == "openai":
    MODEL, MODEL_SOURCE = _discover_openai_model()
else:
    MODEL = (os.environ.get("LLM_MODEL") or "openai/gpt-5.6").strip()
    MODEL_SOURCE = "environment" if os.environ.get("LLM_MODEL", "").strip() else "fallback"


def status() -> dict[str, Any]:
    key_env = _KEY_ENV.get(PROVIDER)
    configured = PROVIDER == "mock" or bool(key_env and os.environ.get(key_env, "").strip())
    return {"provider": PROVIDER, "model": MODEL, "configured": configured}


def _is_transient(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    return code in {408, 409, 429, 500, 502, 503, 504} or any(
        word in name for word in ("timeout", "connection", "ratelimit", "internalserver")
    )


def _call(*, system: str, user: str, max_tokens: int, timeout: float,
          response_format: Any = None) -> Any:
    if PROVIDER == "mock":
        return _mock_json(user, response_format) if response_format else _mock_text(user)
    if PROVIDER not in _KEY_ENV: raise RuntimeError(f"unsupported LLM_PROVIDER: {PROVIDER}")
    if not status()["configured"]: raise RuntimeError(f"{_KEY_ENV[PROVIDER]} not set; LLM disabled")
    if completion is None: raise RuntimeError("any-llm-sdk is not installed")
    kwargs = dict(
        model=MODEL, provider=PROVIDER,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens, timeout=timeout, temperature=0.2,
    )
    if response_format is not None:
        kwargs["response_format"] = response_format
    for attempt in range(2):
        try:
            return completion(**kwargs)
        except Exception as exc:
            if attempt or not _is_transient(exc):
                raise
            time.sleep(0.5)
    raise RuntimeError("unreachable")


def complete_text(system: str, user: str, *, max_tokens: int, timeout: float) -> str:
    response = _call(system=system, user=user, max_tokens=max_tokens, timeout=timeout)
    if isinstance(response, str):
        return response.strip()
    return str(response.choices[0].message.content or "").strip()


def complete_json(system: str, user: str, *, schema: dict | type,
                  max_tokens: int, timeout: float) -> dict[str, Any]:
    fmt: Any = schema
    if isinstance(schema, dict):
        fmt = {"type": "json_schema", "json_schema": {
            "name": "overheard_response", "strict": True, "schema": schema,
        }}
    response = _call(system=system, user=user, max_tokens=max_tokens,
                     timeout=timeout, response_format=fmt)
    if isinstance(response, dict):
        return response
    message = response.choices[0].message
    parsed = getattr(message, "parsed", None)
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    return json.loads(message.content or "{}")


def _mock_text(user: str) -> str:
    return ("**Now discussing:** Mock transcript\n\n**Topics covered:**\n- Acceptance test\n\n"
            "**Decisions / commitments:**\n- Send the requested diagram\n\n**Open questions:**\n- —\n\n"
            "**Action items:**\n- Send Ana the Q3 architecture diagram\n\n**Risks / concerns:**\n- —")


def _mock_json(user: str, schema: Any) -> dict[str, Any]:
    if isinstance(schema, type) and hasattr(schema, "model_json_schema"):
        schema = schema.model_json_schema()
    properties = ((schema.get("json_schema") or {}).get("schema") or schema).get("properties", {}) if isinstance(schema, dict) else {}
    if "actions" in properties:
        delta = user.rsplit("NEW_TRANSCRIPT:", 1)[-1].lower()
        if "pricing" in delta:
            return {"actions": [{"kind": "lookup", "title": "Look up Atlas vendor pricing",
                "rationale": "Maya explicitly requested current pricing",
                "evidence": ["Maya: please look up the current Atlas vendor pricing before tomorrow."],
                "confidence": 0.91, "tool": "exa.answer",
                "args": {"query": "current Atlas vendor pricing"}}]}
        return {"actions": [{"kind": "create_task", "title": "Send Ana the Q3 architecture diagram",
            "rationale": "Ana asked for it and Daniel committed to send it today",
            "evidence": ["Ana: can you send me the Q3 architecture diagram today?", "Daniel: sure, I'll send it this afternoon"],
            "confidence": 0.94, "tool": "ambiguous.tasks.create",
            # `due` is an ISO date, as in fixtures/expected-actions.json — the UI
            # renders it in a <input type="date">, which silently blanks anything else.
            "args": {"title": "Send Ana the Q3 architecture diagram", "assignee": "Daniel",
                     "due": datetime.now().strftime("%Y-%m-%d")}}]}
    if "title" in properties:
        return {"title": "Q3 Architecture Follow-up", "blurb": "The team agreed to send Ana the Q3 architecture diagram."}
    return {"questions": [], "topics": [], "decisions": [], "questions_for_me": []}
print(f"llm: provider={PROVIDER} model={MODEL} configured={status()['configured']} source={MODEL_SOURCE}")

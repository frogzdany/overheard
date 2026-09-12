"""Ephemeral, runtime-injected credentials (the CredentialProvider seam).

The local client mints short-lived, scoped provider keys from the cloud
(POST /sessions/credentials -> an ephemeral Deepgram key) and pushes them into
the engine via POST /credentials. Workers resolve their key through resolve(),
which prefers a live (unexpired) ephemeral override and otherwise falls back to
the persistent value in os.environ (set from .env / the in-app SecretsStore).

So with nothing pushed, behaviour is identical to today — this layer is purely
additive. When the cloud broker is wired up, the master provider keys never have
to live on the machine: the engine only ever sees the short-lived key.
"""
from __future__ import annotations

import threading
import time
import os

from engine.secrets import FIELDS

_lock = threading.Lock()
# provider id -> (value, expires_at_epoch | None). None expiry = no TTL.
_ephemeral: dict[str, tuple[str, float | None]] = {}


def set_ephemeral(provider: str, value: str, ttl_seconds: float | None = None) -> None:
    """Install a runtime override for `provider`, optionally expiring after
    `ttl_seconds`. Raises KeyError for unknown providers."""
    if provider not in FIELDS:
        raise KeyError(f"unknown provider: {provider}")
    expires = time.time() + ttl_seconds if ttl_seconds else None
    with _lock:
        _ephemeral[provider] = (value, expires)


def clear(provider: str | None = None) -> None:
    """Drop one override (or all when provider is None)."""
    with _lock:
        if provider is None:
            _ephemeral.clear()
        else:
            _ephemeral.pop(provider, None)


def resolve(provider: str) -> str | None:
    """The live ephemeral override if present and unexpired, else the persistent
    env value (DEEPGRAM_API_KEY, etc.). This is what workers call."""
    now = time.time()
    with _lock:
        item = _ephemeral.get(provider)
        if item is not None:
            value, expires = item
            if expires is None or expires > now:
                return value
            _ephemeral.pop(provider, None)  # expired
    env = FIELDS.get(provider)
    return os.environ.get(env) if env else None


def status() -> dict:
    """Which providers currently have a live ephemeral override + seconds left.
    Never returns the value. For debugging / the integrations panel."""
    now = time.time()
    with _lock:
        return {
            p: {
                "expiresInSeconds": None if exp is None else max(0, round(exp - now))
            }
            for p, (_, exp) in _ephemeral.items()
            if exp is None or exp > now
        }

"""In-app API credentials for Overheard.

Entered via the Integrations section of Settings instead of a hand-edited
.env, so users never have to touch the terminal. Stored as JSON at:

    macOS:  ~/Library/Application Support/Overheard/secrets.json
    other:  ~/.config/overheard/secrets.json

The file is written 0600 (user-only). Each logical service maps to the
environment variable the engine workers read *lazily* at session start (see
engine/workers/*), so saving a key and starting the next session is enough —
no app restart. At startup, app.py calls apply_to_env() AFTER load_dotenv(),
so an in-app key supplements or overrides a value from .env.

Keys are NEVER echoed back to the UI: status() returns only whether each
service is configured plus a masked hint (last 4 chars). This mirrors the
shape of settings.py::SettingsStore but is kept separate so secrets can't
accidentally leak through the unmasked GET /settings response.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)


def _secrets_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Overheard"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "overheard"
    return Path.home() / ".config" / "overheard"


SECRETS_PATH = _secrets_dir() / "secrets.json"

# Logical service id -> the env var the workers read. Insertion order is the
# display order in the UI.
FIELDS: dict[str, str] = {
    "deepgram": "DEEPGRAM_API_KEY",
}

# Services without which the core capture + summarize loop can't run.
REQUIRED: set[str] = {"deepgram"}


def _mask(value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if len(v) <= 4:
        return "••••"
    return "••••" + v[-4:]


class SecretsStore:
    """Thread-safe JSON store for API keys, mirrored into os.environ."""

    def __init__(self, path: Path = SECRETS_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._cache = self._read_from_disk()
            self._loaded = True

    def _read_from_disk(self) -> dict[str, str]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as e:
            log.warning("secrets: could not read %s: %s", self._path, e)
            return {}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("secrets file root must be an object")
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("secrets: %s is corrupt (%s); ignoring", self._path, e)
            return {}
        # Keep only known, non-empty fields, coerced to str.
        return {k: str(v) for k, v in data.items() if k in FIELDS and v}

    def _write_to_disk(self) -> None:
        # Open the fd with mode 0o600 BEFORE writing a byte: write_text() +
        # chmod-after left a window where the secrets briefly existed at the
        # umask default (typically 0644).
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._cache, indent=2))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        try:
            # A stale .tmp from a pre-fix crash may carry an older mode.
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self._path)

    def apply_to_env(self) -> None:
        """Push stored keys into os.environ so lazily-reading workers see them.
        Called at startup (after load_dotenv) and on every update. Only sets
        keys we actually have, so a hand-maintained .env value is left intact
        for any field the user hasn't set in-app."""
        self._ensure_loaded()
        with self._lock:
            for field, env in FIELDS.items():
                val = self._cache.get(field, "").strip()
                if val:
                    os.environ[env] = val

    def status(self) -> list[dict]:
        """Per-service config status for the UI. Never returns raw keys.

        A service counts as configured if we have a stored key OR the env var
        is already set (e.g. from a .env the user maintains by hand), so the
        panel reflects reality for both setup paths.
        """
        self._ensure_loaded()
        with self._lock:
            stored = dict(self._cache)
        out: list[dict] = []
        for field, env in FIELDS.items():
            stored_val = stored.get(field, "").strip()
            env_val = os.environ.get(env, "").strip()
            effective = stored_val or env_val
            out.append(
                {
                    "id": field,
                    "envVar": env,
                    "required": field in REQUIRED,
                    "configured": bool(effective),
                    "hint": _mask(effective),
                    # True when the value is only present via a hand-maintained
                    # .env, not the in-app store — the UI flags it so the user
                    # knows replacing it here takes precedence.
                    "fromEnvFile": bool(env_val and not stored_val),
                }
            )
        return out

    def update(self, patch: dict[str, str | None]) -> None:
        """Set or clear keys. A non-empty string sets; empty string / None
        clears. Persists to disk (0600) and re-applies to os.environ so the
        next session picks it up without a restart. Unknown fields ignored."""
        self._ensure_loaded()
        with self._lock:
            for field in FIELDS:
                if field not in patch:
                    continue
                raw = patch[field]
                val = raw.strip() if isinstance(raw, str) else ""
                if val:
                    self._cache[field] = val
                    os.environ[FIELDS[field]] = val
                else:
                    self._cache.pop(field, None)
                    os.environ.pop(FIELDS[field], None)
            self._write_to_disk()


_store: SecretsStore | None = None


def get_secrets() -> SecretsStore:
    global _store
    if _store is None:
        _store = SecretsStore()
    return _store


def apply_to_env() -> None:
    """Module-level convenience for app.py startup wiring."""
    get_secrets().apply_to_env()

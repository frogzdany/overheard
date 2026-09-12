"""Persistent global settings for Overheard.

Stored as JSON at:
    macOS:  ~/Library/Application Support/Overheard/settings.json
    other:  ~/.config/overheard/settings.json

Settings cover global defaults (mic device, language, context, models). A
session start request can override any field; if it doesn't, the engine
falls back to the stored default.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _settings_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Overheard"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "overheard"
    return Path.home() / ".config" / "overheard"


SETTINGS_PATH = _settings_dir() / "settings.json"

DEFAULTS: dict[str, Any] = {
    # Physical microphone the engine opens for "you". System audio is always
    # captured separately via the ScreenCaptureKit Swift helper, so this is
    # purely the mic side. Empty string = system default input.
    "micDevice": "",
    # How "you" (the local microphone speaker) is labelled in the transcript
    # and exports. Empty falls back to "You". System-audio speakers keep their
    # Deepgram diarization labels (Speaker 0/1/2...).
    "selfDisplayName": "",
    # The user's identity for "questions asked to me" detection: name variants
    # other participants use to address them (comma-separated) and a one-line
    # role so the LLM can judge what's directed at them. This is the seed of a
    # per-user profile — a future multi-user/login layer would replace these
    # with a profile record of the same shape.
    "selfAliases": "",
    "selfRole": "",
    "defaultLanguage": None,            # null = auto-detect
    "defaultContext": "",
    "summaryIntervalMs": 45_000,
    "deepgramModel": "nova-3",
}


class SettingsStore:
    """Thread-safe read/write JSON store."""

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._cache = self._read_from_disk()
            self._loaded = True

    def _read_from_disk(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return dict(DEFAULTS)
        except OSError as e:
            log.warning("settings: could not read %s: %s", self._path, e)
            return dict(DEFAULTS)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("settings file root must be an object")
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("settings: %s is corrupt (%s); using defaults", self._path, e)
            return dict(DEFAULTS)
        return {**DEFAULTS, **data}

    def get_all(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            return dict(self._cache)

    def get(self, key: str, default: Any = None) -> Any:
        self._ensure_loaded()
        with self._lock:
            return self._cache.get(key, default)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge `patch` into the store and persist. Returns the new full dict.
        Only keys present in DEFAULTS are accepted; unknown keys are ignored
        so a malicious or stale client can't pollute the file."""
        self._ensure_loaded()
        with self._lock:
            # Re-read the file before merging: writing this process's whole
            # cache would also write back its stale copy of every key another
            # process changed since launch. Merging the patch over the
            # freshest disk state makes concurrent writers converge per-key.
            self._cache = self._read_from_disk()
            for k, v in patch.items():
                if k in DEFAULTS:
                    self._cache[k] = v
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            return dict(self._cache)


_store: SettingsStore | None = None


def get_settings() -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store

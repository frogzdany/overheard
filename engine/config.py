"""Engine-wide constants. Workers and the runtime read everything from here
so a future packaging step doesn't have to chase magic numbers across files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- audio ---
SAMPLE_RATE = 16_000          # 16 kHz matches Deepgram's expected input rate
BYTES_PER_SAMPLE = 2          # signed 16-bit PCM (what we capture, archive, and send)
MIC_BOOST_DG = 4.0            # light mic gain so the Deepgram VAD picks up quiet talkers

# --- Deepgram ---
DG_MODEL = "nova-3"           # Deepgram streaming model
DG_UTTERANCE_END_MS = 1000    # silence (ms) that closes an utterance

# --- speech-to-text provider ---
STT_PROVIDER = (os.environ.get("STT_PROVIDER") or "deepgram").strip().lower()
OPENAI_STT_MODEL = (os.environ.get("OPENAI_STT_MODEL") or "gpt-live-transcribe").strip()

# --- insight extraction ---
INSIGHT_INTERVAL_MS = 60_000  # extract every 60s
INSIGHT_WINDOW_MIN = 2.0      # send the last N minutes of transcript to the LLM

# --- actions worker ---
# Discover executable commitments every N ms; override with ACTIONS_INTERVAL_MS env var (min 5000).
_actions_interval = os.environ.get("ACTIONS_INTERVAL_MS")
ACTIONS_INTERVAL_MS = 45_000
if _actions_interval:
    try:
        _val = int(_actions_interval)
        ACTIONS_INTERVAL_MS = max(_val, 5000) if _val >= 5000 else 45_000
    except (ValueError, TypeError):
        pass

# Skip action extraction if fewer than N new characters in transcript (min 0).
_actions_min_chars = os.environ.get("ACTIONS_MIN_NEW_CHARS")
ACTIONS_MIN_NEW_CHARS = 80
if _actions_min_chars:
    try:
        _val = int(_actions_min_chars)
        ACTIONS_MIN_NEW_CHARS = _val if _val >= 0 else 80
    except (ValueError, TypeError):
        pass

# --- rolling summary ---
SUMMARY_INTERVAL_MS = 45_000  # tick every 45s
SUMMARY_MIN_NEW_WORDS = 30    # skip the tick if too little new content
SUMMARY_MAX_WORDS = 300       # target length for the running summary
# Regular ticks that overlap are skipped by the work lock, so a generous cap
# costs nothing; a tick that hasn't answered by now is stuck, not slow.
SUMMARY_LLM_TIMEOUT_S = 90.0
# The prompt re-sends the whole transcript every tick while PREVIOUS_SUMMARY
# already carries the older content — cap the transcript block so latency
# stops growing with meeting length (~24K chars ≈ the last 20-25 min).
SUMMARY_TRANSCRIPT_MAX_CHARS = 24_000

# If a session ended with less than this much audio AND zero transcript
# finals from both streams, the engine deletes the session files on stop so
# accidental / aborted sessions don't clutter the list. Set to 0 to disable.
MIN_SESSION_KEEP_SECONDS = 10.0

# Human-readable language names used in the LLM prompts so the model knows
# which language to write its output in.
LANGUAGE_DISPLAY_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "multi": "the meeting's language",
}

# --- paths ---
#
# Sessions live under a stable user-data directory so the bundled engine
# inside a PyInstaller .app and the dev engine running from the repo both
# read from the same place. Inside the bundle, `Path(__file__).parent`
# resolves to a temp-dir that gets cleaned up on quit — useless for
# persistence.
def _user_data_dir() -> Path:
    override = os.environ.get("OVERHEARD_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Overheard"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "overheard"
    return Path.home() / ".local" / "share" / "overheard"


LOG_DIR = _user_data_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

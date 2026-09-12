"""Engine workers — long-lived QObject subclasses, one per pipeline stage.

Each worker is independent: it consumes its inputs (audio frames, transcript
text), emits Qt signals + bus events, and writes JSONL log records via the
shared `JSONLLogger`. The `SessionEngine` in `engine/runtime.py` is the only
caller that wires them together.
"""
from __future__ import annotations

from .deepgram import DeepgramStreamer
from .actions import ActionsWorker
from .insight import InsightExtractor
from .summary import SummaryWorker
from .titler import name_session

__all__ = [
    "DeepgramStreamer",
    "ActionsWorker",
    "InsightExtractor",
    "SummaryWorker",
    "name_session",
]

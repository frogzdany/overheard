"""In-process pub/sub bus for engine events.

Designed to be safe to call publish() from any thread (Qt worker threads,
daemon threads spawned by Deepgram, the FastAPI event loop). Subscribers
are asyncio.Queue instances that live on an asyncio event loop.

Event shape:
    {
        "type":      str,           # dotted, e.g. "transcript.final"
        "sessionId": str | None,    # current session id, if any
        "ts":        float,         # time.time()
        "data":      dict,          # event payload
    }
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_QUEUE_MAXSIZE = 1000


class Bus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._current_session_id: str | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to the asyncio loop where subscribers live (typically the
        FastAPI server's loop). publish() will schedule queue.put_nowait on it."""
        self._loop = loop

    def set_session_id(self, session_id: str | None) -> None:
        self._current_session_id = session_id

    def subscribe(self, maxsize: int = _DEFAULT_QUEUE_MAXSIZE) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(
        self,
        type_: str,
        data: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        """Thread-safe. Drops the event if there are no subscribers or no loop bound."""
        event = {
            "type": type_,
            "sessionId": session_id or self._current_session_id,
            "ts": time.time(),
            "data": data or {},
        }
        loop = self._loop
        if loop is None:
            return
        # Snapshot subscribers under lock so we don't hold it across loop calls.
        with self._lock:
            subs = list(self._subscribers)
        if not subs:
            return
        for q in subs:
            try:
                loop.call_soon_threadsafe(self._enqueue, q, event)
            except RuntimeError:
                # Loop is closed; subscriber is dead.
                self.unsubscribe(q)

    @staticmethod
    def _enqueue(q: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest, then enqueue. Best-effort backpressure.
            try:
                _ = q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("bus: subscriber queue still full after drop, losing event")


_singleton: Bus | None = None


def get_bus() -> Bus:
    global _singleton
    if _singleton is None:
        _singleton = Bus()
    return _singleton

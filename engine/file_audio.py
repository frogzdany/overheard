"""WAV-file audio source — a drop-in stand-in for the Swift system-audio helper.

`FileAudioSource` has the same surface `engine/workers/deepgram.py` uses on
`SystemAudioSource` (``start(on_audio, on_status)`` / ``stop()`` /
``is_running()``) and yields the same frame shape: ``np.ndarray[(N, 2), int16]``
at the requested sample rate. Frames are paced in wall-clock time so Deepgram
sees the file arriving exactly like a live meeting would.

Used by ``app.py --from-file PATH.wav``.
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


class AudioFileError(RuntimeError):
    """The file is missing, unreadable, or not in the format we stream."""


class FileAudioSource:
    """Streams a 16-bit PCM WAV as if it were live system audio.

    The file must already be 16-bit PCM at `sample_rate` (the fixtures are
    16 kHz mono) — no resampling happens here, because a wrong-rate stream
    reaches Deepgram as garbage rather than as an error. Mono input is
    duplicated across two channels so the consumer's stereo downmix is a no-op.
    """

    def __init__(
        self,
        path: str | Path,
        sample_rate: int = 16_000,
        chunk_samples: int = 800,     # 50ms @ 16kHz, matching SystemAudioSource
        realtime: bool = True,
    ) -> None:
        self._path = Path(path).expanduser()
        self._sample_rate = sample_rate
        self._chunk_samples = max(1, chunk_samples)
        self._realtime = realtime
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._done = threading.Event()
        self._frames_sent = 0
        self.probe()

    # ------- validation -------

    def probe(self) -> dict:
        """Open the file and check it is streamable. Raises AudioFileError."""
        if not self._path.is_file():
            raise AudioFileError(f"audio file not found: {self._path}")
        try:
            with wave.open(str(self._path), "rb") as w:
                channels, width, rate, frames = (
                    w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        except (wave.Error, OSError) as exc:
            raise AudioFileError(f"{self._path} is not a readable WAV file: {exc}") from exc
        if width != 2:
            raise AudioFileError(
                f"{self._path}: need 16-bit PCM, got {width * 8}-bit. Convert it: "
                f"afconvert -f WAVE -d LEI16@{self._sample_rate} -c 1 in.wav out.wav")
        if rate != self._sample_rate:
            raise AudioFileError(
                f"{self._path}: need {self._sample_rate} Hz, got {rate} Hz. Convert it: "
                f"afconvert -f WAVE -d LEI16@{self._sample_rate} -c 1 in.wav out.wav")
        if channels not in (1, 2):
            raise AudioFileError(f"{self._path}: need 1 or 2 channels, got {channels}")
        return {"channels": channels, "sampleRate": rate, "frames": frames,
                "seconds": frames / float(rate)}

    # ------- lifecycle (SystemAudioSource surface) -------

    def start(
        self,
        on_audio: Callable[[np.ndarray], None],
        on_status: Callable[[dict], None] | None = None,
    ) -> None:
        if self._thread is not None:
            raise RuntimeError("already started")
        self._stop_event.clear()
        self._done.clear()
        self._frames_sent = 0
        info = self.probe()
        self._emit_status(on_status, "info",
                          f"streaming {self._path.name} "
                          f"({info['seconds']:.2f}s @ {info['sampleRate']} Hz)")
        self._thread = threading.Thread(
            target=self._reader_loop, args=(on_audio, on_status), daemon=True,
            name="file-audio-reader")
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the file has been fully streamed (or `stop()` ran)."""
        return self._done.wait(timeout)

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    # ------- internal -------

    def _emit_status(self, on_status, level: str, message: str, code: str | None = None) -> None:
        # Mirrors the Swift helper's stderr JSON. Never "error" for a normal
        # end-of-file: the consumer routes error statuses to session failure.
        event = {"level": level, "message": message}
        if code:
            event["code"] = code
        if on_status is None:
            log.info("file-audio: %s", message)
            return
        try:
            on_status(event)
        except Exception:
            log.exception("on_status handler raised")

    def _reader_loop(self, on_audio, on_status) -> None:
        try:
            with wave.open(str(self._path), "rb") as w:
                channels = w.getnchannels()
                started = time.monotonic()
                while not self._stop_event.is_set():
                    raw = w.readframes(self._chunk_samples)
                    if not raw:
                        break
                    mono = np.frombuffer(raw, dtype=np.int16)
                    if channels == 2:
                        pairs = mono.reshape(-1, 2)
                        mono = ((pairs[:, 0].astype(np.int32)
                                 + pairs[:, 1].astype(np.int32)) // 2).astype(np.int16)
                    if mono.size == 0:
                        break
                    self._frames_sent += int(mono.size)
                    if self._realtime:
                        # Pace against the total emitted so far, not per-chunk
                        # sleeps, so handler time doesn't accumulate as drift.
                        ahead = (self._frames_sent / float(self._sample_rate)
                                 - (time.monotonic() - started))
                        if ahead > 0 and self._stop_event.wait(ahead):
                            break
                    stereo = np.repeat(mono.reshape(-1, 1), 2, axis=1)
                    try:
                        on_audio(stereo)
                    except Exception:
                        log.exception("on_audio handler raised")
        except Exception as exc:
            self._emit_status(on_status, "warn", f"file audio stopped: {exc}")
        finally:
            self._done.set()
            if not self._stop_event.is_set():
                seconds = self._frames_sent / float(self._sample_rate)
                self._emit_status(on_status, "info",
                                  f"end of {self._path.name} after {seconds:.2f}s",
                                  code="file-eof")

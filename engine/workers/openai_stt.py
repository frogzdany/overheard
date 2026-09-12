"""OpenAI Realtime transcription worker.

Mirrors ``DeepgramStreamer``'s Qt signal and audio-source contract while using
one transcription WebSocket per source. OpenAI Realtime doesn't diarize this
path, so system audio is always ``Speaker 0`` and microphone audio is ``You``.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal, Slot
from websockets.sync.client import connect

from engine.bus import get_bus
from engine.config import BYTES_PER_SAMPLE, MIC_BOOST_DG, OPENAI_STT_MODEL, SAMPLE_RATE
from engine.logger import JSONLLogger

_BUS = get_bus()
_REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
_INT16_MIN = -32768
_INT16_MAX = 32767
_INT16_SCALE = 32768.0
# The Realtime API consumes 24 kHz PCM16 — `audio.input.format` accepts
# {"type": "audio/pcm", "rate": 24000} and nothing else. Every other stage of
# the capture path runs at engine.config.SAMPLE_RATE (16 kHz — Deepgram's rate,
# and the rate the WAV archive is written at), so audio is upsampled on its way
# to the socket only. 16k -> 24k is an exact 3:2 ratio.
REALTIME_SAMPLE_RATE = 24_000
_RESAMPLE_RATIO = REALTIME_SAMPLE_RATE / SAMPLE_RATE
# Transcription models that stream `.delta` text but reject `turn_detection`,
# so the server never closes an item and no
# `conversation.item.input_audio_transcription.completed` is ever emitted.
# This worker's whole contract is one final per utterance, so such a model
# would publish interims and nothing else; the alternative — the client
# sending `input_audio_buffer.commit` on a timer — slices finals mid-word.
# Verified live 2026-09-12: `gpt-live-transcribe` answers a session.update
# carrying turn_detection with "Turn detection is not supported for this
# transcription model.", and with turn_detection omitted produced 140 deltas
# and zero finals over 45 s of the fixture clip.
_NO_TURN_DETECTION_MODELS = frozenset({"gpt-live-transcribe", "gpt-realtime-whisper"})
_SEGMENTING_MODEL = "gpt-transcribe"


class OpenAIStreamer(QObject):
    """Two-stream OpenAI Realtime transcriber with Deepgram-compatible signals."""

    interim_text = Signal(str, str)
    final_text = Signal(str, str, str, bool)
    status = Signal(str)
    failed = Signal(str)

    def __init__(self, language: str | None, context_keywords: str,
                 logger: JSONLLogger | None, archive_path: Path | None = None,
                 mic_device: str | None = None,
                 capture_apps: list[str] | None = None,
                 audio_file: Path | None = None):
        super().__init__()
        self._audio_file = Path(audio_file) if audio_file else None
        self._language = language or "multi"
        self._context = (context_keywords or "").strip()
        self._log = logger
        self._archive_path = archive_path
        self._mic_device = mic_device or None
        self._capture_apps = [b for b in (capture_apps or []) if b]
        self._model_requested = OPENAI_STT_MODEL
        self._model = (_SEGMENTING_MODEL
                       if OPENAI_STT_MODEL in _NO_TURN_DETECTION_MODELS
                       else OPENAI_STT_MODEL)

        self._running = False
        self._t_session_start = 0.0
        self._sck_source = None
        self._mic_stream: sd.InputStream | None = None
        self._archive_wav: wave.Wave_write | None = None
        self._archive_lock = threading.Lock()
        self._archive_frames = 0

        self._streams: dict[str, dict] = {}
        self._streams_lock = threading.RLock()
        self._generations: dict[str, int] = {}
        self._reconnects: dict[str, int] = {}
        self._partials: dict[tuple[str, str], str] = {}
        # Per-source resampler state: the previous chunk's last sample and the
        # leftover fractional output position, so 16k -> 24k stays continuous
        # across chunk boundaries.
        self._resample_carry: dict[str, int] = {}
        self._resample_phase: dict[str, float] = {}

    def _session_update(self) -> dict:
        """The GA Realtime transcription-session config.

        The beta shape this worker used to send (`transcription_session.update`
        with `input_audio_format` / `input_audio_transcription`, behind the
        `OpenAI-Beta: realtime=v1` header) is switched off server-side: the
        socket now closes with 4000
        `invalid_request_error.beta_api_shape_disabled` the moment it is sent.
        GA takes `session.update` with a `type: "transcription"` session and
        everything nested under `audio.input`.
        """
        transcription: dict[str, str] = {"model": self._model}
        if self._language != "multi":
            transcription["language"] = self._language
        if self._context:
            transcription["prompt"] = self._context
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        # `audio.input` is replaced wholesale, so every field
                        # this worker needs has to be restated here — leaving
                        # turn_detection out sets it to null, not "unchanged".
                        "format": {"type": "audio/pcm",
                                   "rate": REALTIME_SAMPLE_RATE},
                        "transcription": transcription,
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            # Server VAD is what closes an item, so this
                            # number IS the transcript's line length. 500 ms
                            # rarely fires between two turns of a real
                            # back-and-forth: over the same 60 s of
                            # fixtures/meeting-clip.wav it produced 2 finals
                            # (one of 63 words spanning six speaker turns)
                            # where 250 ms produced 13, one per scripted line.
                            # The API's own default for a transcription
                            # session is 200 ms.
                            "silence_duration_ms": 250,
                        },
                    },
                },
            },
        }

    def _open_stream(self, source: str, *, reconnecting: bool = False) -> bool:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        try:
            ws = connect(
                _REALTIME_URL,
                additional_headers={"Authorization": f"Bearer {api_key}"},
                open_timeout=10,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=20,
                # This socket outlives the call and is closed by _cleanup, so
                # it can't be a context manager; `legacy=True` is how
                # websockets.sync wants that spelled.
                legacy=True,
            )
            ws.send(json.dumps(self._session_update()))
        except Exception as exc:
            message = f"OpenAI Realtime connect failed ({source}): {exc}"
            if reconnecting:
                self.status.emit(message)
            else:
                self.failed.emit(message)
            if self._log:
                self._log.log("openai_stt_connect_error", source=source, error=str(exc)[:300])
            return False

        with self._streams_lock:
            generation = self._generations.get(source, 0) + 1
            self._generations[source] = generation
            reader = threading.Thread(
                target=self._receive_loop,
                args=(source, ws, generation),
                daemon=True,
                name=f"openai-stt-{source}",
            )
            self._streams[source] = {"ws": ws, "thread": reader, "generation": generation}
            reader.start()
        verb = "reconnected" if reconnecting else "connected"
        self.status.emit(f"OpenAI STT {source} {verb}")
        return True

    def _receive_loop(self, source: str, ws, generation: int) -> None:
        error: Exception | None = None
        try:
            for raw in ws:
                event = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
                if isinstance(event, dict):
                    self._handle_realtime_event(source, event)
        except Exception as exc:  # socket errors vary across websockets versions
            error = exc
            if self._log:
                self._log.log("openai_stt_socket_error", source=source, error=str(exc)[:300])
        finally:
            if self._running and generation == self._generations.get(source):
                detail = f": {error}" if error else ""
                self.status.emit(f"OpenAI STT {source} socket dropped{detail}")
                self._reconnect_once(source, generation)

    def _reconnect_once(self, source: str, generation: int) -> None:
        with self._streams_lock:
            if not self._running or generation != self._generations.get(source):
                return
            attempts = self._reconnects.get(source, 0)
            old = self._streams.pop(source, None)
            if old:
                try:
                    old["ws"].close()
                except Exception:
                    pass
            if attempts >= 1:
                self.failed.emit(f"OpenAI Realtime socket dropped again ({source}); reconnect exhausted")
                return
            self._reconnects[source] = attempts + 1

        self.status.emit(f"OpenAI STT {source} reconnecting (attempt 1)")
        if not self._open_stream(source, reconnecting=True):
            self.failed.emit(f"OpenAI Realtime reconnect failed ({source})")

    def _handle_realtime_event(self, source: str, event: dict) -> None:
        """Map OpenAI Realtime JSON events to the existing transcript contract."""
        event_type = event.get("type")
        item_id = str(event.get("item_id") or event.get("event_id") or "current")
        key = (source, item_id)
        rel_t = max(0.0, time.time() - self._t_session_start)

        if event_type == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta") or ""
            if not isinstance(delta, str) or not delta:
                return
            text = self._partials.get(key, "") + delta
            self._partials[key] = text
            clean = text.strip()
            if not clean:
                return
            self.interim_text.emit(source, clean)
            _BUS.publish("transcript.interim", {"source": source, "text": clean, "relT": rel_t})
            if self._log:
                self._log.log("openai_stt_interim", source=source, text=clean, rel_t=rel_t)
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript") or self._partials.get(key, "")
            self._partials.pop(key, None)
            if not isinstance(text, str) or not text.strip():
                return
            clean = text.strip()
            speaker = "You" if source == "mic" else "Speaker 0"
            speaker_id = None if source == "mic" else 0
            self.final_text.emit(source, speaker, clean, True)
            _BUS.publish("transcript.final", {
                "source": source, "speaker": speaker, "speakerId": speaker_id,
                "text": clean, "speechFinal": True, "relT": rel_t,
            })
            if self._log:
                # Keep dg_final for the existing transcript/export readers.
                self._log.log("dg_final", source=source, speaker=speaker,
                              speaker_id=speaker_id, text=clean,
                              speech_final=True, rel_t=rel_t, words=None,
                              stt_provider="openai")
            return

        if event_type == "conversation.item.input_audio_transcription.failed":
            error = event.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            self.failed.emit(f"OpenAI transcription failed ({source}): {message or 'unknown error'}")
        elif event_type == "error":
            error = event.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            self.failed.emit(f"OpenAI Realtime error ({source}): {message or 'unknown error'}")

    def _resample_to_realtime(self, source: str, pcm: np.ndarray) -> np.ndarray:
        """Upsample one 16 kHz PCM16 chunk to 24 kHz by linear interpolation.

        The previous chunk's final sample is carried over and prepended, so the
        output samples that fall between two chunks interpolate against their
        real neighbour instead of being clamped to the edge of the block —
        without the carry every 50 ms boundary ends on a flat step and clicks.
        The fractional position left over from the previous chunk is carried
        too, so the output grid never drifts.
        """
        samples = np.asarray(pcm, dtype=np.int16).reshape(-1)
        n = int(samples.size)
        if n == 0 or SAMPLE_RATE == REALTIME_SAMPLE_RATE:
            return samples
        phase = self._resample_phase.get(source, 0.0)
        carry = self._resample_carry.get(source)
        if carry is None:
            carry = int(samples[0])
        # Positions are expressed in the extended grid [carry, *samples], whose
        # indices run 0..n — one input sample behind the live block.
        grid = np.empty(n + 1, dtype=np.float64)
        grid[0] = carry
        grid[1:] = samples
        count = int((n - phase) * _RESAMPLE_RATIO + 0.5)
        self._resample_carry[source] = int(samples[-1])
        if count <= 0:
            self._resample_phase[source] = phase - n
            return np.empty(0, dtype=np.int16)
        positions = phase + np.arange(count, dtype=np.float64) / _RESAMPLE_RATIO
        np.clip(positions, 0.0, float(n), out=positions)
        self._resample_phase[source] = phase + count / _RESAMPLE_RATIO - n
        out = np.interp(positions, np.arange(n + 1, dtype=np.float64), grid)
        return np.clip(np.rint(out), _INT16_MIN, _INT16_MAX).astype(np.int16)

    def _send(self, source: str, pcm: np.ndarray) -> None:
        with self._streams_lock:
            stream = self._streams.get(source)
            ws = stream.get("ws") if stream else None
        if ws is None:
            return
        payload = self._resample_to_realtime(source, pcm)
        if payload.size == 0:
            return
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(payload.tobytes()).decode("ascii"),
        }
        try:
            ws.send(json.dumps(event))
        except Exception as exc:
            if self._log:
                self._log.log("openai_stt_send_error", source=source, error=str(exc)[:300])
            try:
                ws.close()
            except Exception:
                pass

    def _on_sck_audio(self, stereo_int16: np.ndarray) -> None:
        if not self._running or stereo_int16.shape[0] == 0:
            return
        mono = ((stereo_int16[:, 0].astype(np.int32)
                 + stereo_int16[:, 1].astype(np.int32)) // 2).astype(np.int16)
        self._send("system", mono)
        if self._archive_wav is not None:
            with self._archive_lock:
                try:
                    self._archive_wav.writeframes(mono.tobytes())
                    self._archive_frames += mono.shape[0]
                except Exception as exc:
                    if self._log:
                        self._log.log("archive_write_error", error=str(exc))
                    self._archive_wav = None

    def _on_mic_audio(self, indata, frames, time_info, status) -> None:
        if status and self._log:
            self._log.log("audio_status", status=str(status), source="mic")
        if not self._running:
            return
        values = indata.astype(np.float32)
        mono = values[:, 0] if values.ndim > 1 else values
        pcm = np.clip(mono * _INT16_SCALE * MIC_BOOST_DG,
                      _INT16_MIN, _INT16_MAX).astype(np.int16)
        self._send("mic", pcm)

    def _on_sck_status(self, event: dict) -> None:
        level = event.get("level", "info")
        message = event.get("message", "")
        if self._log:
            self._log.log("sck_status", level=level, message=message,
                          code=event.get("code"))
        if level == "error":
            self.failed.emit(f"ScreenCaptureKit helper: {message}")

    @Slot()
    def start(self) -> None:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            self.failed.emit("OPENAI_API_KEY is required when STT_PROVIDER=openai")
            return

        self._running = True
        self._t_session_start = time.time()
        if self._model != self._model_requested:
            self.status.emit(
                f"OpenAI STT: {self._model_requested} cannot segment utterances "
                f"(no turn detection) — using {self._model}")
        if not self._open_stream("system"):
            self._running = False
            return
        if self._audio_file is None and not self._open_stream("mic"):
            self._cleanup()
            return

        if self._archive_path is not None:
            try:
                self._archive_path.parent.mkdir(parents=True, exist_ok=True)
                archive = wave.open(str(self._archive_path), "wb")
                archive.setnchannels(1)
                archive.setsampwidth(BYTES_PER_SAMPLE)
                archive.setframerate(SAMPLE_RATE)
                self._archive_wav = archive
            except Exception as exc:
                if self._log:
                    self._log.log("archive_open_error", error=str(exc))

        try:
            if self._audio_file is not None:
                from engine.file_audio import FileAudioSource
                self._sck_source = FileAudioSource(
                    self._audio_file, sample_rate=SAMPLE_RATE, chunk_samples=800)
            else:
                from engine.swift_audio import SystemAudioSource
                self._sck_source = SystemAudioSource(
                    sample_rate=SAMPLE_RATE,
                    include_bundle_ids=self._capture_apps or None)
            self._sck_source.start(on_audio=self._on_sck_audio,
                                   on_status=self._on_sck_status)
        except Exception as exc:
            source = "file audio" if self._audio_file is not None else "SCK helper"
            self.failed.emit(f"Could not start {source}: {exc}")
            self._cleanup()
            return

        if self._audio_file is None:
            try:
                self._mic_stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    device=self._mic_device, callback=self._on_mic_audio,
                    blocksize=int(SAMPLE_RATE * 0.05))
                self._mic_stream.start()
            except Exception as exc:
                self.failed.emit(
                    f"Mic device '{self._mic_device or 'default'}' could not open: {exc}")
                self._cleanup()
                return

        detail = (f"from file '{self._audio_file.name}' (system stream only, no mic)"
                  if self._audio_file is not None
                  else f"via ScreenCaptureKit + mic '{self._mic_device or 'system default'}'")
        self.status.emit(f"Streaming -> OpenAI {self._model} {detail}")

    def _cleanup(self) -> None:
        self._running = False
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        if self._sck_source is not None:
            try:
                self._sck_source.stop()
            except Exception:
                pass
            self._sck_source = None
        with self._streams_lock:
            streams, self._streams = list(self._streams.values()), {}
        self._resample_carry.clear()
        self._resample_phase.clear()
        for stream in streams:
            try:
                stream["ws"].close()
            except Exception:
                pass
        current = threading.current_thread()
        for stream in streams:
            reader = stream.get("thread")
            if reader and reader is not current and reader.is_alive():
                reader.join(timeout=2.0)
        if self._archive_wav is not None:
            with self._archive_lock:
                try:
                    self._archive_wav.close()
                except Exception:
                    pass
                self._archive_wav = None

    @Slot()
    def stop(self) -> None:
        self._cleanup()
        if self._log and self._archive_path is not None:
            self._log.log("archive_closed", path=str(self._archive_path),
                          frames=self._archive_frames,
                          seconds=self._archive_frames / float(SAMPLE_RATE))


# ---- fake-socket unit check: `.venv/bin/python -m engine.workers.openai_stt` ----

class _FakeWebSocket:
    """Stand-in for the Realtime socket: records the frames `_send` writes."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, raw: str) -> None:
        self.sent.append(raw)

    def close(self) -> None:
        pass


def _appended_pcm(ws: _FakeWebSocket) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for raw in ws.sent:
        event = json.loads(raw)
        assert event["type"] == "input_audio_buffer.append", event["type"]
        out.append(np.frombuffer(base64.b64decode(event["audio"]), dtype=np.int16))
    return out


def _self_check() -> None:
    def streamer_with_socket() -> tuple[OpenAIStreamer, _FakeWebSocket]:
        streamer = OpenAIStreamer(language="en", context_keywords="", logger=None)
        ws = _FakeWebSocket()
        streamer._streams["system"] = {"ws": ws, "thread": None, "generation": 1}
        return streamer, ws

    # A 440 Hz tone at the engine's 16 kHz capture rate, split the way the
    # capture path delivers it (800-sample / 50 ms blocks).
    block = 800
    t = np.arange(4 * block) / float(SAMPLE_RATE)
    tone = (np.sin(2 * np.pi * 440 * t) * 8000.0).astype(np.int16)
    chunks = [tone[i:i + block] for i in range(0, tone.size, block)]

    streamer, ws = streamer_with_socket()
    for chunk in chunks:
        streamer._send("system", chunk)

    appended = _appended_pcm(ws)
    assert len(appended) == len(chunks), f"{len(appended)} appends for {len(chunks)} chunks"
    bytes_in = sum(int(c.nbytes) for c in chunks)
    bytes_out = sum(int(a.nbytes) for a in appended)
    expected = int(bytes_in * REALTIME_SAMPLE_RATE / SAMPLE_RATE)
    assert bytes_out == expected, f"appended {bytes_out} bytes, expected {expected}"
    for chunk, pcm in zip(chunks, appended):
        assert pcm.size == chunk.size * 3 // 2, f"{pcm.size} samples for {chunk.size}"

    # The carry must make chunking invisible: the same audio pushed as one
    # block has to produce the same 24 kHz stream as four 50 ms blocks, to
    # within a quantization step. A dropped carry shows up here as a flat,
    # clamped sample at every boundary.
    whole_streamer, whole_ws = streamer_with_socket()
    whole_streamer._send("system", tone)
    chunked = np.concatenate(appended).astype(np.int32)
    whole = _appended_pcm(whole_ws)[0].astype(np.int32)
    assert chunked.size == whole.size, f"{chunked.size} != {whole.size}"
    drift = int(np.abs(chunked - whole).max())
    assert drift <= 1, f"chunk boundaries drift by {drift} LSB"

    print(f"openai_stt resample ok: {bytes_in} bytes @ {SAMPLE_RATE} Hz -> "
          f"{bytes_out} bytes @ {REALTIME_SAMPLE_RATE} Hz "
          f"(x{bytes_out / bytes_in:.1f}), boundary drift {drift} LSB")


if __name__ == "__main__":
    _self_check()

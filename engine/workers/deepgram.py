"""Deepgram streaming worker.

Owns two Deepgram WebSocket connections (one for system audio via the Swift
helper, one for mic via a sounddevice InputStream) and routes finals/interims
back to `SessionEngine` via Qt signals + bus events.
"""
from __future__ import annotations

import collections
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from PySide6.QtCore import QObject, Signal, Slot

from engine.bus import get_bus
from engine.config import (
    BYTES_PER_SAMPLE,
    DG_MODEL,
    DG_UTTERANCE_END_MS,
    MIC_BOOST_DG,
    SAMPLE_RATE,
)
from engine.logger import JSONLLogger

try:
    from deepgram import DeepgramClient
    from deepgram.core.events import EventType as DGEventType
    from deepgram.listen.v1.types import (
        ListenV1Results,
        ListenV1SpeechStarted,
        ListenV1UtteranceEnd,
    )
    DEEPGRAM_AVAILABLE = True
except ImportError:
    DEEPGRAM_AVAILABLE = False

_BUS = get_bus()

# Signed 16-bit PCM range. _INT16_SCALE is the full-scale factor for converting
# float32 audio in [-1, 1] to/from int16.
_INT16_MIN = -32768
_INT16_MAX = 32767
_INT16_SCALE = 32768.0

# --- watchdog / self-healing tunables ---
# SCK delivers PCM continuously (silence included), so any gap in system
# audio means the helper or its stream is dead, not that the room is quiet.
_WATCHDOG_TICK_S = 1.0
_SYS_STALL_S = 5.0                 # no system PCM for this long → restart helper
_SCK_RESTART_MIN_INTERVAL_S = 5.0  # floor between helper restarts
_DG_RECONNECT_BASE_S = 1.0         # backoff after a failed DG reconnect…
_DG_RECONNECT_MAX_S = 30.0         # …doubling up to this cap
_DG_BACKOFF_RESET_AFTER_S = 60.0   # healthy for this long → backoff forgiven
_SEND_ERR_LOG_INTERVAL_S = 5.0     # rate limit for send_media_error spam


def _group_words_by_speaker(words) -> list[tuple[int | None, str]]:
    """Collapse a list of Deepgram word objects into per-speaker segments.

    `words` are the SDK's typed `ListenV1ResultsChannelAlternativesItemWordsItem`
    objects (attribute access). Returns `[(speaker_id, joined_text), ...]`.
    """
    out: list[tuple[int | None, list[str]]] = []
    for w in words or []:
        sp = getattr(w, "speaker", None)
        text = (getattr(w, "punctuated_word", None)
                or getattr(w, "word", "")
                or "").strip()
        if not text:
            continue
        if out and out[-1][0] == sp:
            out[-1][1].append(text)
        else:
            out.append((sp, [text]))
    return [(sp, " ".join(toks)) for sp, toks in out]


class DeepgramStreamer(QObject):
    """Two-stream live transcriber: one Deepgram socket per audio source.

    System audio comes from the Swift `MeetAudioHelper` via `SystemAudioSource`
    (stereo int16 @ 16 kHz, downmixed to mono before sending). Mic audio comes
    from `sounddevice.InputStream` on the user-picked physical device (mono
    float32, scaled to int16).

    Signals:
      interim_text(source, text)
          Partial hypothesis from one of the streams. `source` is "system" | "mic".
      final_text(source, speaker_label, text, speech_final)
          Committed segment. `speaker_label` is "You" for mic, or "Speaker N"
          for diarized system audio (or "" if diarization didn't return one).
    """

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
        # When set, the "system" stream is fed from this WAV instead of the
        # Swift helper and the mic stream is not opened at all
        # (`app.py --from-file`). See engine/file_audio.py.
        self._audio_file = Path(audio_file) if audio_file else None
        self._language = language or "multi"
        self._keywords = [k.strip() for k in (context_keywords or "").split(",") if k.strip()]
        self._log = logger
        self._running = False
        self._mic_stream: sd.InputStream | None = None
        self._sck_source = None
        self._mic_device = mic_device or None
        # Bundle ids to scope system-audio capture to (empty/None = whole
        # system). Passed straight through to the helper's
        # --include-bundle-id flags; also re-applied on watchdog restarts.
        self._capture_apps = [b for b in (capture_apps or []) if b]
        self._t_session_start = 0.0
        self._streams: dict[str, dict] = {}
        self._archive_path: Path | None = archive_path
        self._archive_wav: wave.Wave_write | None = None
        self._archive_lock = threading.Lock()
        self._archive_frames = 0
        self._diar_stats: dict[str, dict] = {
            "system": {"finals": 0, "switches": 0, "last_speaker": None,
                       "speaker_lines": collections.Counter()},
            "mic":    {"finals": 0, "switches": 0, "last_speaker": None,
                       "speaker_lines": collections.Counter()},
        }
        self._mic_rms_acc = 0.0
        self._mic_rms_n = 0
        self._mic_peak = 0.0
        self._mic_rms_last_log = 0.0
        # System-audio level, mirroring mic_level. Diagnostic for the
        # "speech_started but no transcripts" failure: SCK records at the
        # volume the user hears, so a low output volume yields near-silent
        # capture that trips VAD but never transcribes. `system_level` makes
        # that visible in the JSONL.
        self._sys_rms_acc = 0.0
        self._sys_rms_n = 0
        self._sys_peak = 0.0
        self._sys_rms_last_log = 0.0
        # Watchdog state (see _watchdog_loop). The 2026-07-03 session lost
        # system audio 2.4s in — a second same-identity SCK connection tore
        # the stream down, Deepgram closed with 1011 after its no-audio
        # timeout, and nothing restarted either. The watchdog owns both
        # recoveries: helper restarts and Deepgram reconnects.
        self._client = None
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._last_sys_audio = 0.0
        self._sck_died = False
        self._sck_restarts = 0
        self._sck_last_restart = 0.0
        self._gen: dict[str, int] = {}
        self._dg_dead: dict[str, float] = {}
        self._dg_next_try: dict[str, float] = {}
        self._dg_backoff: dict[str, float] = {}
        self._dg_attempts: dict[str, int] = {}
        self._send_err_last: dict[str, float] = {}

    # ----- audio callback (PortAudio thread, mic-only) -----
    def _on_mic_audio(self, indata, frames, time_info, status):
        """Mic stream — `indata` is mono float32 in [-1, 1]. Scale to int16
        range so the shared mic handler can convert + send."""
        if status and self._log:
            self._log.log("audio_status", status=str(status), source="mic")
        if not self._streams:
            return
        a = indata.astype(np.float32)
        mono = a[:, 0] if a.ndim > 1 else a
        mic_f = mono * _INT16_SCALE * MIC_BOOST_DG
        self._handle_mic_pcm_from_float(mic_f)

    # ----- SCK callback (helper thread) -----
    def _on_sck_audio(self, stereo_int16):
        self._last_sys_audio = time.time()
        if not self._streams or stereo_int16.shape[0] == 0:
            return
        mono = ((stereo_int16[:, 0].astype(np.int32) +
                 stereo_int16[:, 1].astype(np.int32)) // 2).astype(np.int16)
        self._handle_system_pcm(mono)

    def _on_sck_status(self, event: dict):
        level = event.get("level", "info")
        msg = event.get("message", "")
        code = event.get("code")
        if self._log:
            if code:
                self._log.log("sck_status", level=level, message=msg, code=code)
            else:
                self._log.log("sck_status", level=level, message=msg)
        if code == "stream-died":
            # macOS tore the capture down mid-session (second same-identity
            # capture, display change, replayd restart). The watchdog restarts
            # it; routing this through failed would kill the whole session.
            self._sck_died = True
            self.status.emit(f"SCK stream died: {msg}")
            return
        if level == "error":
            self.failed.emit(f"ScreenCaptureKit helper: {msg}")

    # ----- shared per-source PCM handling -----
    def _handle_system_pcm(self, sys_mono: np.ndarray) -> None:
        sf = sys_mono.astype(np.float32) / _INT16_SCALE
        self._sys_rms_acc += float(np.mean(sf * sf))
        self._sys_peak = max(self._sys_peak, float(np.max(np.abs(sf))))
        self._sys_rms_n += 1
        now = time.time()
        if now - self._sys_rms_last_log > 5.0 and self._sys_rms_n > 0 and self._log:
            rms = float(np.sqrt(self._sys_rms_acc / self._sys_rms_n))
            self._log.log("system_level", rms=rms, peak=self._sys_peak,
                          rel_t=now - self._t_session_start)
            self._sys_rms_acc = 0.0
            self._sys_peak = 0.0
            self._sys_rms_n = 0
            self._sys_rms_last_log = now
        self._send("system", sys_mono)
        if self._archive_wav is not None:
            with self._archive_lock:
                try:
                    self._archive_wav.writeframes(sys_mono.tobytes())
                    self._archive_frames += sys_mono.shape[0]
                except Exception as e:
                    if self._log:
                        self._log.log("archive_write_error", error=str(e))
                    self._archive_wav = None

    def _handle_mic_pcm_from_float(self, mic_f: np.ndarray) -> None:
        mic_mono = np.clip(mic_f, _INT16_MIN, _INT16_MAX).astype(np.int16)
        mf = mic_f.astype(np.float32) / _INT16_SCALE
        self._mic_rms_acc += float(np.mean(mf * mf))
        self._mic_peak = max(self._mic_peak, float(np.max(np.abs(mf))))
        self._mic_rms_n += 1
        now = time.time()
        if now - self._mic_rms_last_log > 5.0 and self._mic_rms_n > 0 and self._log:
            rms = float(np.sqrt(self._mic_rms_acc / self._mic_rms_n))
            self._log.log("mic_level", rms=rms, peak=self._mic_peak,
                          rel_t=now - self._t_session_start)
            self._mic_rms_acc = 0.0
            self._mic_peak = 0.0
            self._mic_rms_n = 0
            self._mic_rms_last_log = now
        self._send("mic", mic_mono)

    def _track_diar(self, source: str, speaker_label: str):
        st = self._diar_stats.get(source)
        if st is None:
            return
        st["finals"] += 1
        st["speaker_lines"][speaker_label] += 1
        if st["last_speaker"] is not None and st["last_speaker"] != speaker_label:
            st["switches"] += 1
        st["last_speaker"] = speaker_label

    def _send(self, source: str, pcm: np.ndarray):
        st = self._streams.get(source)
        if not st or st.get("conn") is None:
            return
        try:
            st["conn"].send_media(pcm.tobytes())
        except Exception as e:
            # Rate-limited: a dead socket at 50ms audio cadence would log
            # 20 lines/s until the watchdog reconnects.
            now = time.time()
            if self._log and now - self._send_err_last.get(source, 0.0) > _SEND_ERR_LOG_INTERVAL_S:
                self._send_err_last[source] = now
                self._log.log("send_media_error", source=source, error=str(e))

    # ----- deepgram event handlers (one bound per source) -----
    def _make_on_message(self, source: str):
        def handler(m):
            if isinstance(m, ListenV1Results):
                if not (m.channel and m.channel.alternatives):
                    return
                alt = m.channel.alternatives[0]
                text = (alt.transcript or "").strip()
                if not text:
                    return
                t = time.time() - self._t_session_start
                if m.is_final:
                    speech_final = bool(getattr(m, "speech_final", False))
                    words = getattr(alt, "words", None) or []
                    word_speakers = [
                        {"w": getattr(w, "punctuated_word", None) or getattr(w, "word", "") or "",
                         "sp": getattr(w, "speaker", None),
                         "spc": getattr(w, "speaker_confidence", None)}
                        for w in words
                    ]
                    if source == "mic":
                        self._track_diar(source, "You")
                        self.final_text.emit(source, "You", text, speech_final)
                        _BUS.publish("transcript.final", {
                            "source": source, "speaker": "You", "speakerId": None,
                            "text": text, "speechFinal": speech_final, "relT": t,
                        })
                        if self._log:
                            self._log.log("dg_final", source=source, speaker="You",
                                          text=text, speech_final=speech_final, rel_t=t,
                                          words=word_speakers)
                    else:
                        segs = _group_words_by_speaker(words)
                        if not segs:
                            segs = [(None, text)]
                        for i, (sp, seg_text) in enumerate(segs):
                            label = f"Speaker {sp}" if sp is not None else ""
                            final_flag = speech_final and (i == len(segs) - 1)
                            self._track_diar(source, label)
                            self.final_text.emit(source, label, seg_text, final_flag)
                            _BUS.publish("transcript.final", {
                                "source": source, "speaker": label, "speakerId": sp,
                                "text": seg_text, "speechFinal": final_flag, "relT": t,
                            })
                            if self._log:
                                self._log.log("dg_final", source=source, speaker=label,
                                              speaker_id=sp, text=seg_text,
                                              speech_final=final_flag, rel_t=t,
                                              words=word_speakers if i == 0 else None)
                else:
                    self.interim_text.emit(source, text)
                    _BUS.publish("transcript.interim", {"source": source, "text": text, "relT": t})
                    if self._log:
                        self._log.log("dg_interim", source=source, text=text, rel_t=t)
            elif isinstance(m, ListenV1UtteranceEnd):
                if self._log:
                    self._log.log("dg_utterance_end", source=source,
                                  rel_t=time.time() - self._t_session_start)
            elif isinstance(m, ListenV1SpeechStarted):
                if self._log:
                    self._log.log("dg_speech_started", source=source,
                                  rel_t=time.time() - self._t_session_start)
        return handler

    def _open_stream(self, source: str, client, *, diarize: bool,
                     emit_failed: bool = True) -> bool:
        kwargs = dict(
            model=DG_MODEL,
            language=self._language,
            encoding="linear16",
            sample_rate=SAMPLE_RATE,
            channels=1,
            interim_results=True,
            utterance_end_ms=DG_UTTERANCE_END_MS,
            vad_events=True,
            smart_format=True,
            punctuate=True,
            numerals=True,
        )
        if diarize:
            kwargs["diarize"] = True
        if self._keywords:
            kwargs["keyterm"] = self._keywords
        try:
            cm = client.listen.v1.connect(**kwargs)
            conn = cm.__enter__()
        except Exception as e:
            if emit_failed:
                self.failed.emit(f"Deepgram connect failed ({source}): {e}")
            else:
                self.status.emit(f"Deepgram connect failed ({source}): {e}")
            return False

        # Generation tag: events from a superseded connection (closed by a
        # reconnect) must not re-mark the fresh one as dead.
        self._gen[source] = gen = self._gen.get(source, 0) + 1

        on_msg = self._make_on_message(source)
        conn.on(DGEventType.OPEN, lambda _, s=source: self.status.emit(f"DG {s} connected"))
        conn.on(DGEventType.MESSAGE, on_msg)
        conn.on(DGEventType.CLOSE, lambda _, s=source, g=gen: self._on_dg_close(s, g))
        conn.on(DGEventType.ERROR, lambda e, s=source, g=gen: self._on_dg_error(s, g, e))

        listen_thread = threading.Thread(target=conn.start_listening, daemon=True)
        listen_thread.start()
        self._streams[source] = {"conn": conn, "cm": cm, "thread": listen_thread,
                                 "opened_at": time.time()}
        return True

    def _on_dg_close(self, source: str, gen: int) -> None:
        self.status.emit(f"DG {source} closed")
        if (self._running and gen == self._gen.get(source)
                and source in self._streams):
            self._mark_dg_dead(source)

    def _on_dg_error(self, source: str, gen: int, err) -> None:
        self.status.emit(f"DG {source} err: {err}")
        if self._log:
            self._log.log("dg_error", source=source, error=str(err)[:300])
        # Errors normally come paired with CLOSE; the close handler (or the
        # watchdog's listen-thread liveness check) does the dead-marking.

    def _mark_dg_dead(self, source: str) -> None:
        now = time.time()
        self._dg_dead[source] = now
        backoff = self._dg_backoff.get(source, _DG_RECONNECT_BASE_S)
        # First death after a healthy stretch reconnects immediately;
        # repeated deaths back off up to _DG_RECONNECT_MAX_S.
        delay = 0.0 if backoff == _DG_RECONNECT_BASE_S else backoff
        self._dg_next_try[source] = now + delay
        self._dg_backoff[source] = min(backoff * 2.0, _DG_RECONNECT_MAX_S)
        if self._log:
            self._log.log("dg_dead", source=source, retry_in_s=delay)

    # ----- start / stop -----
    @Slot()
    def start(self):
        if not DEEPGRAM_AVAILABLE:
            self.failed.emit("deepgram-sdk not installed")
            return
        # Prefer a live ephemeral key pushed by the client (cloud-minted), else
        # the persistent DEEPGRAM_API_KEY from .env / the in-app SecretsStore.
        from engine.credentials import resolve as resolve_credential

        api_key = resolve_credential("deepgram")
        if not api_key:
            self.failed.emit("DEEPGRAM_API_KEY not set in environment / .env")
            return

        client = DeepgramClient(api_key=api_key)
        self._client = client
        if not self._open_stream("system", client, diarize=True):
            return
        # File playback is a system-stream-only path: there is no live mic to
        # mix in, and an open mic would contaminate the replay.
        if self._audio_file is None and not self._open_stream("mic", client, diarize=False):
            self._close_stream("system")
            return

        if self._archive_path is not None:
            try:
                self._archive_path.parent.mkdir(parents=True, exist_ok=True)
                w = wave.open(str(self._archive_path), "wb")
                w.setnchannels(1)
                w.setsampwidth(BYTES_PER_SAMPLE)
                w.setframerate(SAMPLE_RATE)
                self._archive_wav = w
            except Exception as e:
                if self._log:
                    self._log.log("archive_open_error", error=str(e))
                self._archive_wav = None

        self._t_session_start = time.time()
        self._last_sys_audio = time.time()
        self._sck_last_restart = time.time()
        self._sck_died = False

        try:
            from engine.swift_audio import SystemAudioSource, SwiftHelperNotFound
            if self._audio_file is not None:
                from engine.file_audio import FileAudioSource
                self._sck_source = FileAudioSource(
                    self._audio_file, sample_rate=SAMPLE_RATE, chunk_samples=800,
                )
            else:
                self._sck_source = SystemAudioSource(
                    sample_rate=SAMPLE_RATE,
                    include_bundle_ids=self._capture_apps or None,
                )
            self._sck_source.start(
                on_audio=self._on_sck_audio,
                on_status=self._on_sck_status,
            )
        except SwiftHelperNotFound as e:
            self.failed.emit(str(e))
            self._cleanup_partial_start()
            return
        except Exception as e:
            source = "file audio" if self._audio_file is not None else "SCK helper"
            self.failed.emit(f"Could not start {source}: {e}")
            self._cleanup_partial_start()
            return

        mic_device = self._mic_device
        if self._audio_file is None:
            try:
                self._mic_stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    device=mic_device,
                    callback=self._on_mic_audio,
                    blocksize=int(SAMPLE_RATE * 0.05),
                )
                self._mic_stream.start()
            except Exception as e:
                self.failed.emit(f"Mic device '{mic_device or 'default'}' could not open: {e}")
                self._cleanup_partial_start()
                return

        self._running = True
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="dg-watchdog")
        self._watchdog_thread.start()
        if self._audio_file is not None:
            self.status.emit(
                f"Streaming → Deepgram {DG_MODEL} from file "
                f"'{self._audio_file.name}' (system stream only, no mic)"
            )
        else:
            self.status.emit(
                f"Streaming → Deepgram {DG_MODEL} via ScreenCaptureKit + "
                f"mic '{mic_device or 'system default'}'"
            )

    # ----- watchdog: helper restarts + Deepgram reconnects -----

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(_WATCHDOG_TICK_S):
            if not self._running:
                continue
            now = time.time()
            try:
                self._check_sck(now)
                self._check_dg(now)
            except Exception as e:
                if self._log:
                    self._log.log("watchdog_error", error=str(e)[:300])

    def _check_sck(self, now: float) -> None:
        if self._audio_file is not None:
            # A file source legitimately ends (and then stops producing audio).
            # Restarting it would replay the clip forever.
            return
        if now - self._sck_last_restart < _SCK_RESTART_MIN_INTERVAL_S:
            return
        src = self._sck_source
        died = self._sck_died
        helper_gone = src is None or not src.is_running()
        stalled = (now - self._last_sys_audio) > _SYS_STALL_S
        if not (died or helper_gone or stalled):
            return
        reason = ("stream-died" if died
                  else "helper-exited" if helper_gone
                  else "audio-stall")
        self._sck_died = False
        self._restart_sck(reason)

    def _restart_sck(self, reason: str) -> None:
        from engine.swift_audio import SystemAudioSource

        if not self._running:
            return
        self._sck_restarts += 1
        self._sck_last_restart = time.time()
        if self._log:
            self._log.log("sck_restart", reason=reason, attempt=self._sck_restarts)
        self.status.emit(f"SCK capture restarting ({reason}, #{self._sck_restarts})")
        old, self._sck_source = self._sck_source, None
        if old is not None:
            try:
                old.stop(timeout=1.0)
            except Exception:
                pass
        try:
            src = SystemAudioSource(
                sample_rate=SAMPLE_RATE,
                include_bundle_ids=self._capture_apps or None,
            )
            src.start(on_audio=self._on_sck_audio, on_status=self._on_sck_status)
        except Exception as e:
            if self._log:
                self._log.log("sck_restart_error", error=str(e))
            self.status.emit(f"SCK restart failed: {e}")
            return
        if not self._running:
            # stop() raced us — don't leave an orphan helper streaming.
            try:
                src.stop(timeout=1.0)
            except Exception:
                pass
            return
        self._sck_source = src
        self._last_sys_audio = time.time()

    def _check_dg(self, now: float) -> None:
        for source in ("system", "mic"):
            st = self._streams.get(source)
            dead = source in self._dg_dead
            if st is not None and not dead:
                thread = st.get("thread")
                if thread is not None and not thread.is_alive():
                    # Listen loop exited without a CLOSE event reaching us.
                    self._mark_dg_dead(source)
                    dead = True
                elif (self._dg_backoff.get(source, _DG_RECONNECT_BASE_S)
                        != _DG_RECONNECT_BASE_S
                        and now - st.get("opened_at", now) > _DG_BACKOFF_RESET_AFTER_S):
                    self._dg_backoff[source] = _DG_RECONNECT_BASE_S
                    self._dg_attempts[source] = 0
            if dead and now >= self._dg_next_try.get(source, 0.0):
                self._reconnect_dg(source)

    def _reconnect_dg(self, source: str) -> None:
        if self._client is None or not self._running:
            return
        attempt = self._dg_attempts.get(source, 0) + 1
        self._dg_attempts[source] = attempt
        if self._log:
            self._log.log("dg_reconnect", source=source, attempt=attempt)
        self.status.emit(f"DG {source} reconnecting (attempt {attempt})")
        self._close_stream(source)
        ok = self._open_stream(source, self._client,
                               diarize=(source == "system"), emit_failed=False)
        if ok and not self._running:
            # stop() raced us — close the socket we just opened.
            self._close_stream(source)
            return
        if ok:
            self._dg_dead.pop(source, None)
            self.status.emit(f"DG {source} reconnected")
        else:
            backoff = self._dg_backoff.get(source, _DG_RECONNECT_BASE_S)
            self._dg_next_try[source] = time.time() + backoff
            self._dg_backoff[source] = min(backoff * 2.0, _DG_RECONNECT_MAX_S)

    def _cleanup_partial_start(self):
        """Tear down everything opened so far in start() when a later step
        fails. Without this, a half-started session (e.g. SCK or mic open
        throws after the archive wav + Deepgram sockets are up) leaks the wav
        handle and the sockets. Idempotent; safe to call from any failure path."""
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
        for source in list(self._streams.keys()):
            self._close_stream(source)
        if self._archive_wav is not None:
            with self._archive_lock:
                try:
                    self._archive_wav.close()
                except Exception:
                    pass
                self._archive_wav = None

    def _close_stream(self, source: str):
        st = self._streams.pop(source, None)
        if not st:
            return
        conn = st.get("conn")
        cm = st.get("cm")
        thread = st.get("thread")
        if conn is not None:
            try:
                conn.send_finalize()
                conn.send_close_stream()
            except Exception:
                pass
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass
        # Join the listen thread (running conn.start_listening) so it doesn't
        # outlive the connection. The __exit__ above closes the socket, which
        # unblocks start_listening; the timeout caps how long stop() can wait
        # if the SDK doesn't return promptly.
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive() and self._log:
                self._log.log("dg_listen_thread_join_timeout", source=source)

    @Slot()
    def stop(self):
        self._running = False
        # Watchdog first: it must not restart the helper or reconnect
        # Deepgram while we're tearing everything down.
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=_WATCHDOG_TICK_S + 2.0)
            self._watchdog_thread = None
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
        for source in list(self._streams.keys()):
            self._close_stream(source)
        if self._archive_wav is not None:
            with self._archive_lock:
                try:
                    self._archive_wav.close()
                except Exception:
                    pass
                self._archive_wav = None
            if self._log:
                self._log.log("archive_closed",
                              path=str(self._archive_path) if self._archive_path else None,
                              frames=self._archive_frames,
                              seconds=self._archive_frames / float(SAMPLE_RATE))
        if self._log:
            duration = max(0.0, time.time() - self._t_session_start)
            for source, st in self._diar_stats.items():
                if st["finals"] == 0:
                    continue
                spm = (st["switches"] / duration * 60.0) if duration > 0 else 0.0
                self._log.log(
                    "diar_summary", source=source,
                    duration_s=duration, finals=st["finals"],
                    switches=st["switches"], switches_per_min=spm,
                    speakers=dict(st["speaker_lines"]),
                )

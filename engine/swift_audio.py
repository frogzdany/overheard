"""Python adapter for the Swift `MeetAudioHelper` binary.

Spawns the helper, reads its stdout (raw int16 LE stereo PCM @ 48kHz by default)
and yields it as numpy chunks. Status lines from stderr (one JSON per line) are
parsed and exposed via on_status callbacks.

Usage:
    src = SystemAudioSource()
    src.start(on_audio=lambda frames: ..., on_status=lambda ev: ...)
    ...
    src.stop()

    # Optionally scope capture to specific running apps instead of the
    # whole system:
    src = SystemAudioSource(include_bundle_ids=["com.apple.QuickTimePlayerX"])
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
# A packaging step can point at a helper elsewhere through this env var.
# Falls back to the dev location next to the repo so `./run-dev.sh` works
# unchanged.
_ENV_HELPER = os.environ.get("OVERHEARD_AUDIO_HELPER_PATH")
DEFAULT_BIN = (
    Path(_ENV_HELPER)
    if _ENV_HELPER
    else ROOT / "audio-helper" / ".build" / "release" / "MeetAudioHelper"
)


class SwiftHelperNotFound(RuntimeError):
    pass


def list_apps(binary_path: Path | None = None) -> list[dict]:
    """Running apps with a bundle id, via the helper's `list-apps` subcommand.

    NSWorkspace only — no ScreenCaptureKit, so this needs no permission and is
    safe to call before the user has granted Screen Recording. Each entry is
    ``{"bundleId": str, "name": str, "pid": int}``.
    """
    bin_path = binary_path or DEFAULT_BIN
    if not bin_path.exists():
        raise SwiftHelperNotFound(
            f"MeetAudioHelper not found at {bin_path}. "
            "Build it first: ./build-audio-helper.sh"
        )
    out = subprocess.run(
        [str(bin_path), "list-apps"],
        capture_output=True, text=True, timeout=10,
    )
    if out.returncode != 0:
        raise OSError((out.stderr or "list-apps failed").strip()[:300])
    data = json.loads(out.stdout or "[]")
    return data if isinstance(data, list) else []


class SystemAudioSource:
    """Spawns the Swift helper and streams PCM frames.

    Output frame shape: ``np.ndarray[(N, 2), np.int16]`` where N is the number
    of stereo samples in the chunk. Sample rate is fixed at 48 kHz unless
    overridden via the helper's ``--sample-rate`` flag.
    """

    def __init__(
        self,
        binary_path: Path | None = None,
        sample_rate: int = 16_000,
        chunk_samples: int = 800,     # 50ms @ 16kHz, 2 channels
        include_bundle_ids: list[str] | None = None,
    ) -> None:
        bin_path = binary_path or DEFAULT_BIN
        if not bin_path.exists():
            raise SwiftHelperNotFound(
                f"MeetAudioHelper not found at {bin_path}. "
                "Build it first: (cd audio-helper && swift build -c release)"
            )
        self._bin = bin_path
        self._sample_rate = sample_rate
        self._chunk_bytes = chunk_samples * 2 * 2  # 2 channels * 2 bytes (int16)
        self._include_bundle_ids = include_bundle_ids
        self._proc: subprocess.Popen[bytes] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------- lifecycle -------

    def start(
        self,
        on_audio: Callable[[np.ndarray], None],
        on_status: Callable[[dict], None] | None = None,
    ) -> None:
        if self._proc is not None:
            raise RuntimeError("already started")
        self._stop_event.clear()
        args = [
            str(self._bin),
            "capture-system",
            "--sample-rate", str(self._sample_rate),
        ]
        if self._include_bundle_ids:
            for bid in self._include_bundle_ids:
                args += ["--include-bundle-id", bid]
        log.info("spawning audio helper: %s", " ".join(args))
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
        )
        self._stdout_thread = threading.Thread(
            target=self._reader_loop, args=(on_audio,), daemon=True,
            name="swift-audio-reader",
        )
        self._stderr_thread = threading.Thread(
            target=self._status_loop, args=(on_status,), daemon=True,
            name="swift-audio-status",
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("helper didn't exit after SIGTERM; killing")
            proc.kill()
            proc.wait(timeout=1.0)
        finally:
            self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------- internal -------

    def _reader_loop(self, on_audio: Callable[[np.ndarray], None]) -> None:
        assert self._proc and self._proc.stdout
        stdout = self._proc.stdout
        chunk_bytes = self._chunk_bytes
        try:
            while not self._stop_event.is_set():
                buf = stdout.read(chunk_bytes)
                if not buf:
                    proc = self._proc
                    rc = proc.poll() if proc is not None else None
                    log.info("helper stdout closed (exit=%s)", rc)
                    break
                if len(buf) % 4 != 0:
                    # int16 stereo = 4 bytes per stereo sample; if the read is
                    # short at EOF, round down.
                    buf = buf[: len(buf) - (len(buf) % 4)]
                if not buf:
                    continue
                arr = np.frombuffer(buf, dtype=np.int16).reshape(-1, 2)
                try:
                    on_audio(arr)
                except Exception:
                    log.exception("on_audio handler raised")
        except Exception:
            log.exception("reader loop crashed")

    def _status_loop(self, on_status: Callable[[dict], None] | None) -> None:
        assert self._proc and self._proc.stderr
        stderr = self._proc.stderr
        try:
            for raw in iter(stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("helper stderr (non-json): %s", line)
                    continue
                if on_status is not None:
                    try:
                        on_status(ev)
                    except Exception:
                        log.exception("on_status handler raised")
                else:
                    level = ev.get("level", "info")
                    msg = ev.get("message", "")
                    log.log(
                        {"info": logging.INFO, "warn": logging.WARNING,
                         "error": logging.ERROR}.get(level, logging.INFO),
                        "swift-audio: %s", msg,
                    )
        except Exception:
            log.exception("status loop crashed")


# ----- standalone CLI: capture N seconds → WAV (sanity check) -----

def _save_wav(path: Path, samples: list[np.ndarray], sample_rate: int) -> None:
    import wave
    arr = np.concatenate(samples, axis=0) if samples else np.zeros((0, 2), dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(arr.tobytes())


def _cli() -> int:
    import argparse
    import time

    p = argparse.ArgumentParser(description="Smoke-test the Swift audio helper.")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--out", default="swift-capture.wav")
    p.add_argument("--binary", default=str(DEFAULT_BIN))
    p.add_argument("--include-bundle-id", action="append", default=None,
                    dest="include_bundle_ids")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    samples: list[np.ndarray] = []

    src = SystemAudioSource(binary_path=Path(args.binary), sample_rate=48_000,
                            chunk_samples=2_400,
                            include_bundle_ids=args.include_bundle_ids)
    src.start(on_audio=lambda chunk: samples.append(chunk.copy()))
    print(f"capturing {args.seconds:.1f}s of system audio @ 48kHz…", flush=True)
    time.sleep(args.seconds)
    src.stop()

    out = Path(args.out)
    _save_wav(out, samples, 48_000)
    total = sum(s.shape[0] for s in samples)
    print(f"wrote {out} — {total} stereo samples ({total / 48_000:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

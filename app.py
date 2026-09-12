"""Overheard — headless engine entry point.

System audio comes from the Swift ScreenCaptureKit helper. Mic audio comes
from a `sounddevice` mono stream on the user-picked physical device. Each
stream goes to its own Deepgram WebSocket. The rolling-summary, speaker-
    labeling, insight extraction, and action suggestion workers run on a shared QThread.

The UI is the Next.js web app at http://localhost:3000. The Python process
exposes its lifecycle over FastAPI on http://127.0.0.1:8765 (REST + WS).

Run:
    .venv/bin/python app.py --no-window --port=8765   # engine + server
    .venv/bin/python app.py --no-server               # engine only (debugging)

Demo / fixture replay (no microphone, no Swift helper):
    # Replay a scripted JSONL transcript straight into the workers. Pace comes
    # from each line's `t`, divided by REPLAY_SPEED (0 = as fast as possible).
    ENGINE_DEV=1 LLM_PROVIDER=mock REPLAY_SPEED=0 \
        .venv/bin/python app.py --no-window --port=8766 \
        --from-transcript fixtures/meeting-transcript.jsonl

    # Stream a 16 kHz mono WAV through the real Deepgram path (needs a key).
    .venv/bin/python app.py --no-window --from-file fixtures/meeting-clip.wav
"""
from __future__ import annotations

import os
import signal
import sys

from pathlib import Path

# Fast path: a fresh-process microphone-permission probe. The long-lived engine
# caches macOS mic authorization for its lifetime and can't see a grant until
# restart; spawning this short-lived probe reads the CURRENT status uncached.
# Handled before any heavy import (PySide6/runtime live inside main()) so it
# stays near-instant. See engine/permissions.py::_microphone_status_subprocess.
if "--check-mic" in sys.argv:
    import json

    from engine import permissions

    print(json.dumps({"microphone": permissions._microphone_status_inproc()}))
    sys.exit(0)

from dotenv import load_dotenv


# The packaged .app launches with cwd "/", so a bare load_dotenv() finds
# nothing. Try the canonical app-support location first (works for the
# packaged build), then fall back to a .env sitting next to this file (dev
# from the repo). Last resort: cwd, the python-dotenv default.
_ENV_CANDIDATES = [
    Path.home() / "Library" / "Application Support" / "Overheard" / ".env",
    Path(__file__).resolve().parent / ".env",
]
for _env in _ENV_CANDIDATES:
    if _env.is_file():
        load_dotenv(_env)
        break
else:
    load_dotenv()

# API keys entered in-app (Settings → Integrations) are stored in secrets.json
# and pushed into os.environ here, AFTER load_dotenv so the stored value wins
# over any .env entry. Workers read os.environ lazily at session start, so this
# is all that's needed for a no-terminal setup path.
from engine.secrets import apply_to_env as _apply_secrets_to_env

_apply_secrets_to_env()


def _flag_value(name: str) -> str | None:
    """Read `--flag=value` or `--flag value` out of argv."""
    prefix = f"--{name}"
    for index, arg in enumerate(sys.argv):
        if arg.startswith(prefix + "="):
            return arg.split("=", 1)[1]
        if arg == prefix and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def _replay_speed() -> float:
    """REPLAY_SPEED multiplies the transcript's own timestamps. 0 = no waiting."""
    try:
        speed = float(os.environ.get("REPLAY_SPEED") or 1.0)
    except ValueError:
        speed = 1.0
    return max(0.0, speed)


def _load_transcript_lines(path: Path) -> list[dict]:
    """Parse a `{t, speaker, text}` JSONL fixture, sorted by timestamp."""
    import json

    lines: list[dict] = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            print(f"replay: skipping unparseable line: {raw[:80]}", file=sys.stderr)
            continue
        text = " ".join(str(row.get("text") or "").split()).strip()
        if not text:
            continue
        lines.append({
            "t": float(row.get("t") or 0.0),
            "speaker": " ".join(str(row.get("speaker") or "Speaker 1").split()).strip(),
            "text": text,
        })
    lines.sort(key=lambda row: row["t"])
    return lines


def _start_session_blocking(engine, **kwargs) -> str:
    """Start a session on the engine thread and wait for its id.

    Goes through the same control queue the HTTP routes use, so the session is
    created by the Qt thread that owns the workers.
    """
    import queue as _queue

    result: "_queue.Queue[tuple[str, object]]" = _queue.Queue()

    def runner() -> None:
        try:
            result.put(("ok", engine.start_session_from_server(**kwargs)))
        except Exception as exc:  # noqa: BLE001
            result.put(("err", exc))

    engine.enqueue_control(runner)
    kind, value = result.get(timeout=30)
    if kind == "err":
        raise value  # type: ignore[misc]
    if not value:
        raise RuntimeError("engine refused to start a session")
    return str(value)


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Block until the FastAPI thread is accepting connections on `port`."""
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
            time.sleep(0.2)
        finally:
            sock.close()
    return False


def _replay_transcript(engine, path: Path, port: int, wait_for_server: bool) -> None:
    """Replay a JSONL transcript into a `transcriptOnly` session.

    Each line goes through `inject_transcript` — exactly the path
    `POST /sessions/{id}/transcript/inject` takes — paced by its own `t`
    divided by REPLAY_SPEED. After the last line we force one actions tick so
    the brain does not have to wait out its 45s timer, then leave the session
    open so the normal timers keep running and the UI can attach.
    """
    import functools
    import time

    try:
        lines = _load_transcript_lines(path)
    except OSError as exc:
        print(f"replay: cannot read {path}: {exc}", file=sys.stderr)
        return
    if not lines:
        print(f"replay: {path} has no usable lines", file=sys.stderr)
        return
    if wait_for_server and not _wait_for_server(port):
        print("replay: server did not come up in time; replaying anyway",
              file=sys.stderr)
    try:
        session_id = _start_session_blocking(engine, transcript_only=True)
    except Exception as exc:  # noqa: BLE001
        print(f"replay: could not start session: {exc}", file=sys.stderr)
        return

    speed = _replay_speed()
    pace = "as fast as possible" if speed == 0 else f"{speed:g}x"
    print(f"replay: session {session_id} — {len(lines)} lines from {path.name} ({pace})",
          file=sys.stderr)

    started = time.monotonic()
    for row in lines:
        if speed > 0:
            delay = row["t"] / speed - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
        engine.enqueue_control(
            functools.partial(engine.inject_transcript, row["speaker"], row["text"]))
        snippet = row["text"][:72] + ("…" if len(row["text"]) > 72 else "")
        print(f'replay: [{row["t"]:7.2f}s] {row["speaker"]}: {snippet}', file=sys.stderr)

    # Queued after every inject, and the control queue drains in order, so the
    # tick always sees the complete transcript.
    engine.enqueue_control(engine.trigger_actions)
    print(f"replay: done — forced an actions tick; session {session_id} stays open "
          f"(GET /sessions/{session_id}/actions)", file=sys.stderr)


def _replay_audio_file(engine, path: Path, port: int, wait_for_server: bool) -> None:
    """Start a normal (STT) session whose system audio is `path`."""
    if wait_for_server and not _wait_for_server(port):
        print("replay: server did not come up in time; starting anyway", file=sys.stderr)
    try:
        session_id = _start_session_blocking(engine, device=None, audio_file=str(path))
    except Exception as exc:  # noqa: BLE001
        print(f"replay: could not start session: {exc}", file=sys.stderr)
        return
    print(f"replay: session {session_id} — streaming {path.name} to Deepgram "
          f"(system stream only, no mic)", file=sys.stderr)


def _reclaim_port(port: int) -> None:
    """Free our HTTP port if a stale engine from a previous launch still holds
    it.

    macOS force-relaunches the app after a TCC grant ("Quit & Reopen"), which
    can orphan the previous engine sidecar. The new launch generates a fresh
    per-session token and hands it to the WebView, but if the old engine is
    still bound to the port, the UI talks to it with a mismatched token and
    every request 403s. So the newest engine reclaims the port: kill the stale
    listener (only if it's one of ours) and wait for the port to free.
    """
    import socket
    import subprocess
    import time

    def _free() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    if _free():
        return
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return
    me = os.getpid()
    for pid_s in out.split():
        if not pid_s.isdigit() or int(pid_s) == me:
            continue
        try:
            comm = subprocess.run(
                ["ps", "-p", pid_s, "-o", "command="],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            comm = ""
        # Only kill our own kind — never some unrelated process on the port.
        if "meet-engine" in comm or "app.py" in comm:
            print(f"engine: reclaiming port {port} from stale engine pid {pid_s}",
                  file=sys.stderr)
            try:
                os.kill(int(pid_s), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
    for _ in range(30):  # up to ~3s for the port to free
        if _free():
            return
        time.sleep(0.1)


def main() -> None:
    from PySide6.QtCore import QCoreApplication, QTimer

    from engine.runtime import SessionEngine

    # --no-window is accepted for compatibility with the dev scripts: this
    # build is headless already (QCoreApplication, no Qt window ever created).
    no_server = "--no-server" in sys.argv
    port = 8765
    for arg in sys.argv:
        if arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    # --from-transcript / --from-file replace the live capture for demos and
    # for iterating on the suggestion brain. They are mutually exclusive.
    from_transcript = _flag_value("from-transcript")
    from_file = _flag_value("from-file")
    if from_transcript and from_file:
        print("app.py: pass only one of --from-transcript / --from-file",
              file=sys.stderr)
        sys.exit(2)
    transcript_path = audio_path = None
    if from_transcript:
        transcript_path = Path(from_transcript).expanduser()
        if not transcript_path.is_file():
            print(f"app.py: --from-transcript: no such file: {transcript_path}",
                  file=sys.stderr)
            sys.exit(2)
    if from_file:
        audio_path = Path(from_file).expanduser()
        from engine.file_audio import AudioFileError, FileAudioSource

        try:
            info = FileAudioSource(audio_path).probe()
        except AudioFileError as exc:
            print(f"app.py: --from-file: {exc}", file=sys.stderr)
            sys.exit(2)
        stt_provider = os.environ.get("STT_PROVIDER", "deepgram").strip().lower() or "deepgram"
        stt_key = "OPENAI_API_KEY" if stt_provider == "openai" else "DEEPGRAM_API_KEY"
        if not os.environ.get(stt_key, "").strip():
            print(f"app.py: --from-file streams the WAV through {stt_provider} and needs a "
                  f"real {stt_key}.\n"
                  "        Set it in .env, or use "
                  "--from-transcript fixtures/meeting-transcript.jsonl for a "
                  "keyless replay.", file=sys.stderr)
            sys.exit(2)
        print(f"app.py: --from-file {audio_path.name}: {info['seconds']:.2f}s, "
              f"{info['channels']}ch @ {info['sampleRate']} Hz", file=sys.stderr)

    # QCoreApplication (not QApplication) → no NSApplication → no Dock icon.
    app = QCoreApplication(sys.argv)
    engine = SessionEngine()

    server_thread = None
    if not no_server:
        _reclaim_port(port)
        from engine.server import ServerThread
        server_thread = ServerThread(controller=engine, port=port)
        server_thread.start()
        print(f"engine server listening on http://127.0.0.1:{port}", file=sys.stderr)
    print("Engine running. Drive everything from the web UI "
          "(http://localhost:3000). Ctrl-C to stop.", file=sys.stderr)

    # Wire SIGINT/SIGTERM so Ctrl-C cleanly exits the Qt event loop. Python's
    # default SIGINT handler doesn't fire inside Qt's blocking exec() unless
    # we (a) install a Python-aware handler AND (b) give the interpreter time
    # to run via a periodic heartbeat timer.
    def _shutdown(*_a) -> None:
        engine.shutdown()
        if server_thread is not None:
            server_thread.stop()
        QCoreApplication.quit()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Replay drives the engine from a worker thread: the control queue is
    # drained by the Qt event loop below, so this must not block it.
    if transcript_path is not None or audio_path is not None:
        import threading

        target, source = ((_replay_transcript, transcript_path)
                          if transcript_path is not None
                          else (_replay_audio_file, audio_path))
        threading.Thread(
            target=target, args=(engine, source, port, not no_server),
            daemon=True, name="replay",
        ).start()
    pulse = QTimer()
    pulse.setInterval(250)
    pulse.timeout.connect(lambda: None)
    pulse.start()

    try:
        sys.exit(app.exec())
    finally:
        if server_thread is not None:
            server_thread.stop()


if __name__ == "__main__":
    main()

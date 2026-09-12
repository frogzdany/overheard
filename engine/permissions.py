"""macOS TCC permission checks for the capture pipeline.

Screen Recording is the permission that silently "resets" on every rebuild of
an ad-hoc-signed app: TCC authorizes a specific binary by its code-hash
(cdhash), which changes each build, so a granted entry still shows enabled in
System Settings while the new binary is actually denied. The UI needs to detect
that and guide the user, so we expose the status here.

Implementation uses the public CoreGraphics / AVFoundation C entry points via
``ctypes`` — no pyobjc dependency, and it works inside the PyInstaller bundle
because the frameworks are loaded from the system at runtime.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

GRANTED = "granted"
DENIED = "denied"
UNKNOWN = "unknown"
UNSUPPORTED = "unsupported"  # non-macOS

# Last *definitive* Screen Recording answer from the helper (GRANTED/DENIED).
# When a later check is inconclusive (helper cold-start / timeout) we return this
# instead of letting the status flip — see screen_recording_status().
_last_sr_status: str | None = None


# --- Diagnostic logging ------------------------------------------------------
# The permission flow is the hardest thing to debug from the outside: a click
# spawns a Swift subprocess (Screen Recording) or opens an audio stream (mic),
# and macOS may silently decline to re-prompt. So we trace every step to a
# dedicated, human-readable log the user can hand back — and mirror a short line
# to stderr so it also shows up in the live `engine.log` tail.
_plog = logging.getLogger("meet.permissions")


def _perm_log_path() -> Path:
    # Sit next to engine.log (the file the user already tails), NOT under
    # Application Support — that's where they look for logs.
    return Path.home() / "Library" / "Logs" / "Overheard" / "permissions.log"


def _init_perm_log() -> None:
    if getattr(_plog, "_meet_configured", False):
        return
    _plog.setLevel(logging.DEBUG)
    _plog.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s", "%Y-%m-%dT%H:%M:%S"
    )
    try:
        p = _perm_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(p)
        fh.setFormatter(fmt)
        _plog.addHandler(fh)
    except Exception:
        pass  # never let logging setup break a permission check
    # Mirror to stderr (→ engine.log) but only WARNING+ — the routine per-poll
    # snapshot/probe INFO lines would otherwise flood engine.log every ~3s. Full
    # INFO detail still lands in permissions.log via the file handler above.
    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(logging.Formatter("[perm] %(message)s"))
    _plog.addHandler(sh)
    _plog._meet_configured = True  # type: ignore[attr-defined]
    _plog.info("permission log initialised → %s", _perm_log_path())


_init_perm_log()


def _load(framework: str) -> ctypes.CDLL | None:
    path = ctypes.util.find_library(framework)
    return ctypes.CDLL(path) if path else None


def _helper_bin() -> str | None:
    """Path to the MeetAudioHelper binary — the process that actually captures
    system audio. Mirrors engine/swift_audio.py's resolution (env var set by
    the Tauri shell in the packaged app; repo build location in dev)."""
    env = os.environ.get("OVERHEARD_AUDIO_HELPER_PATH")
    if env and Path(env).exists():
        return env
    dev = (Path(__file__).resolve().parent.parent
           / "audio-helper" / ".build" / "release" / "MeetAudioHelper")
    return str(dev) if dev.exists() else None


def _screen_recording_inproc(request: bool) -> str:
    """Fallback: check/request from THIS process. Less accurate than the helper
    (different TCC identity) but better than nothing if the helper is missing."""
    try:
        cg = _load("CoreGraphics")
        if cg is None:
            return UNKNOWN
        fn = (cg.CGRequestScreenCaptureAccess if request
              else cg.CGPreflightScreenCaptureAccess)
        fn.restype = ctypes.c_bool
        fn.argtypes = []
        return GRANTED if fn() else DENIED
    except Exception:
        return UNKNOWN


def _helper_permission(subcommand: str, timeout: float) -> str | None:
    """Run a MeetAudioHelper permission subcommand; exit 0 = granted, 1 =
    denied. Returns None if the helper is unavailable / inconclusive so the
    caller can fall back."""
    bin_ = _helper_bin()
    if not bin_:
        _plog.warning(
            "helper '%s' SKIPPED — MeetAudioHelper binary not found "
            "(OVERHEARD_AUDIO_HELPER_PATH=%r)",
            subcommand,
            os.environ.get("OVERHEARD_AUDIO_HELPER_PATH"),
        )
        return None
    t0 = time.monotonic()
    try:
        r = subprocess.run([bin_, subcommand], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        dt = (time.monotonic() - t0) * 1000
        _plog.warning(
            "helper '%s' TIMEOUT after %.0fms (limit %.0fs) — bin=%s",
            subcommand, dt, timeout, bin_,
        )
        return None
    except Exception as e:
        _plog.warning("helper '%s' SPAWN FAILED: %r — bin=%s", subcommand, e, bin_)
        return None
    dt = (time.monotonic() - t0) * 1000
    out = r.stdout.decode(errors="replace").strip()
    err = r.stderr.decode(errors="replace").strip()
    _plog.info(
        "helper '%s' rc=%d in %.0fms stdout=%r stderr=%r",
        subcommand, r.returncode, dt, out, err,
    )
    if r.returncode == 0:
        return GRANTED
    if r.returncode == 1:
        return DENIED
    _plog.warning("helper '%s' inconclusive rc=%d — caller will fall back",
                  subcommand, r.returncode)
    return None


def screen_recording_status() -> str:
    """GRANTED / DENIED / UNKNOWN for Screen Recording (system-audio capture
    needs it).

    The HELPER — the process that actually captures — is the only authoritative
    source, because TCC authorizes by code-signing identity and the helper's
    differs from the engine sidecar's. So:

      • Helper gives a definitive answer → trust it (and remember it).
      • Helper is slow / inconclusive → return the last definitive answer, or
        UNKNOWN. We deliberately do NOT fall back to the engine sidecar's own
        preflight here: that's a different TCC identity that almost always
        reports a false DENIED, which made the status flap between refreshes.
      • No helper binary at all (dev build) → the in-proc preflight is the only
        signal available, so use it as a best-effort fallback.
    """
    global _last_sr_status
    if sys.platform != "darwin":
        return UNSUPPORTED
    result = _helper_permission("check-permission", timeout=12)
    if result in (GRANTED, DENIED):
        _last_sr_status = result
        return result
    if _helper_bin() is None:
        fb = _screen_recording_inproc(request=False)
        _plog.info("screen-recording check: no helper, in-proc preflight=%s", fb)
        return fb
    _plog.info("screen-recording check inconclusive; returning last=%s",
               _last_sr_status or UNKNOWN)
    return _last_sr_status or UNKNOWN


def request_screen_recording() -> str:
    """Trigger the Screen Recording prompt / register the app in the list, via
    the helper (the capturing identity). Returns the resulting status."""
    global _last_sr_status
    if sys.platform != "darwin":
        return UNSUPPORTED
    _plog.info("screen-recording REQUEST: spawning helper 'request-permission' "
               "(macOS only shows the prompt while status is notDetermined)")
    result = _helper_permission("request-permission", timeout=60)
    if result in (GRANTED, DENIED):
        _last_sr_status = result
        _plog.info("screen-recording REQUEST result=%s", result)
        return result
    fb = _screen_recording_inproc(request=True)
    _plog.info("screen-recording REQUEST helper inconclusive; in-proc request=%s", fb)
    return fb


def _microphone_status_inproc() -> str:
    """Best-effort GRANTED / DENIED / UNKNOWN for the microphone, read in THIS
    process.

    Reads ``AVCaptureDevice authorizationStatusForMediaType:`` through the objc
    runtime. Any failure degrades to UNKNOWN so this never destabilizes the
    engine — the capture path surfaces a real failure if the mic can't open.

    Caveat: AVFoundation caches the authorization for the process lifetime, so a
    long-lived engine that read this once as notDetermined keeps reading the
    stale value even after the user grants — it only refreshes on restart. The
    public ``microphone_status()`` works around that with a fresh probe.
    """
    if sys.platform != "darwin":
        return UNSUPPORTED
    try:
        objc = _load("objc")
        if objc is None or _load("AVFoundation") is None:
            return UNKNOWN
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        # NSString* mediaType = [NSString stringWithUTF8String:"soun"]
        # ("soun" is AVMediaTypeAudio's underlying value.)
        msg_ptr = objc.objc_msgSend
        msg_ptr.restype = ctypes.c_void_p
        msg_ptr.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        ns_string = objc.objc_getClass(b"NSString")
        sel_with_utf8 = objc.sel_registerName(b"stringWithUTF8String:")
        media_type = msg_ptr(ns_string, sel_with_utf8, b"soun")

        # NSInteger status =
        #   [AVCaptureDevice authorizationStatusForMediaType:mediaType]
        msg_int = objc.objc_msgSend
        msg_int.restype = ctypes.c_long
        msg_int.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        av_capture = objc.objc_getClass(b"AVCaptureDevice")
        sel_auth = objc.sel_registerName(b"authorizationStatusForMediaType:")
        status = msg_int(av_capture, sel_auth, media_type)

        # AVAuthorizationStatus: 0 notDetermined, 1 restricted, 2 denied,
        # 3 authorized.
        mapped = {3: GRANTED, 2: DENIED, 1: DENIED, 0: UNKNOWN}.get(status, UNKNOWN)
        _plog.info("microphone status: AVAuthorizationStatus=%d -> %s", status, mapped)
        return mapped
    except Exception as e:
        _plog.warning("microphone status check failed: %r -> unknown", e)
        return UNKNOWN


def _microphone_status_subprocess() -> str | None:
    """Read mic authorization from a fresh, short-lived process so a grant is
    seen immediately (the long-lived engine caches it for its lifetime — see
    _microphone_status_inproc). Only meaningful in the packaged build, where
    ``sys.executable`` IS the meet-engine binary and re-invoking it with
    ``--check-mic`` short-circuits before any heavy import. Returns None (so the
    caller falls back to the in-proc read) in dev or on any failure."""
    if not getattr(sys, "frozen", False):
        return None
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [sys.executable, "--check-mic"], capture_output=True, timeout=20
        )
    except Exception as e:
        _plog.warning("mic probe spawn failed: %r — falling back to in-proc", e)
        return None
    dt = (time.monotonic() - t0) * 1000
    out = r.stdout.decode(errors="replace").strip()
    try:
        import json
        val = json.loads(out).get("microphone")
    except Exception:
        _plog.warning("mic probe bad output rc=%d in %.0fms: %r", r.returncode, dt, out)
        return None
    if val in (GRANTED, DENIED, UNKNOWN):
        _plog.info("mic probe -> %s in %.0fms (fresh subprocess)", val, dt)
        return val
    _plog.warning("mic probe unexpected value %r in %.0fms", val, dt)
    return None


def microphone_status() -> str:
    """GRANTED / DENIED / UNKNOWN for the microphone.

    Prefers a fresh-process probe so a just-granted permission is observed
    without an engine restart; falls back to the (possibly stale) in-process
    read in dev or if the probe fails.
    """
    if sys.platform != "darwin":
        return UNSUPPORTED
    fresh = _microphone_status_subprocess()
    return fresh if fresh is not None else _microphone_status_inproc()


def snapshot() -> dict[str, str]:
    """All capture-relevant permission states for the UI preflight."""
    t0 = time.monotonic()
    snap = {
        "platform": sys.platform,
        "screenRecording": screen_recording_status(),
        "microphone": microphone_status(),
    }
    _plog.info("snapshot %s in %.0fms",
               {k: snap[k] for k in ("screenRecording", "microphone")},
               (time.monotonic() - t0) * 1000)
    return snap

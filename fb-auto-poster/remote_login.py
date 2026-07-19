"""
Remote (VNC) Facebook Login
===========================
Lets a human log into Facebook interactively even though the server has no
physical display. It works by:

  1. Starting a virtual X display (Xvfb)
  2. Starting a VNC server (x11vnc) pointed at that display
  3. Starting websockify + noVNC to expose the VNC session over HTTP/WebSocket
     so it can be viewed in a normal browser tab (proxied through nginx)
  4. Launching a real, visible (non-headless) Chrome via Playwright on that
     display, navigated to facebook.com/login
  5. The user drives the browser through the VNC viewer, logs in, solves any
     checkpoint/2FA, then clicks "Save Session" in the dashboard
  6. `finish_remote_login()` grabs `context.storage_state()` from the still-open
     browser and writes it to the session file in the same format the rest of
     the app already expects (see `create_browser_context` in app.py)

Nothing here is exposed with authentication of its own — protect the
dashboard itself (e.g. put it behind Railway's private networking, a VPN, or
basic auth) since anyone who can reach the VNC URL while a session is open
can see and control the browser.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

DISPLAY = ":99"
VNC_PORT = 5900
NOVNC_PORT = 6080
SCREEN_GEOMETRY = "1280x800x24"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "procs": [],          # Xvfb / x11vnc / websockify Popen handles
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
    "error": None,
}


def _spawn(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def is_running() -> bool:
    with _lock:
        return _state["running"]


def start_remote_login() -> dict[str, Any]:
    """Boot Xvfb + x11vnc + websockify + a real Chrome pointed at Facebook login.

    Returns a dict with either {"success": True, "vnc_path": "..."} or
    {"success": False, "error": "..."}.
    """
    with _lock:
        if _state["running"]:
            return {"success": True, "vnc_path": "/proxy/poster/vnc/vnc.html?autoconnect=true&resize=scale"}

        procs: list[subprocess.Popen] = []
        try:
            # 1. Virtual display
            procs.append(_spawn(["Xvfb", DISPLAY, "-screen", "0", SCREEN_GEOMETRY, "-nolisten", "tcp"]))
            time.sleep(1.5)

            os.environ["DISPLAY"] = DISPLAY

            # 2. VNC server on that display
            procs.append(_spawn([
                "x11vnc", "-display", DISPLAY, "-forever", "-shared",
                "-nopw", "-rfbport", str(VNC_PORT), "-quiet",
            ]))
            if not _wait_for_port(VNC_PORT, timeout=10):
                raise RuntimeError("x11vnc did not come up on port %d" % VNC_PORT)

            # 3. noVNC web client + websocket bridge
            novnc_web = "/usr/share/novnc"
            procs.append(_spawn([
                "websockify", "--web", novnc_web,
                str(NOVNC_PORT), f"127.0.0.1:{VNC_PORT}",
            ]))
            if not _wait_for_port(NOVNC_PORT, timeout=10):
                raise RuntimeError("websockify did not come up on port %d" % NOVNC_PORT)

            # 4. Real, visible Chrome via Playwright on the virtual display
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--start-maximized", "--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            page.goto("https://www.facebook.com/login", timeout=30000)

            _state.update({
                "running": True,
                "procs": procs,
                "playwright": pw,
                "browser": browser,
                "context": context,
                "page": page,
                "error": None,
            })
            return {"success": True, "vnc_path": "/proxy/poster/vnc/vnc.html?autoconnect=true&resize=scale"}

        except Exception as exc:  # noqa: BLE001
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    pass
            _state.update({"running": False, "procs": [], "error": str(exc)})
            return {"success": False, "error": str(exc)}


def finish_remote_login(session_path: Path) -> dict[str, Any]:
    """Grab cookies from the still-open remote browser, save the session, tear everything down."""
    with _lock:
        if not _state["running"] or not _state["context"]:
            return {"success": False, "error": "No remote login session is active."}

        try:
            storage_state = _state["context"].storage_state()
            cookie_names = {c.get("name") for c in storage_state.get("cookies", [])}
            missing = {"c_user", "xs"} - cookie_names
            if missing:
                return {
                    "success": False,
                    "error": f"Not logged in yet (missing cookies: {', '.join(missing)}). "
                             f"Finish logging in in the VNC window, then try again.",
                }

            session_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(session_path, "w", encoding="utf-8") as fh:
                json.dump(storage_state, fh, indent=2)

        finally:
            _teardown_locked()

        return {"success": True, "message": "Session saved from remote login."}


def stop_remote_login() -> dict[str, Any]:
    with _lock:
        if not _state["running"]:
            return {"success": True, "message": "Nothing running."}
        _teardown_locked()
        return {"success": True, "message": "Remote login session stopped."}


def _teardown_locked() -> None:
    """Must be called with _lock held."""
    try:
        if _state["browser"]:
            _state["browser"].close()
    except Exception:
        pass
    try:
        if _state["playwright"]:
            _state["playwright"].stop()
    except Exception:
        pass
    for p in _state["procs"]:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(0.5)
    for p in _state["procs"]:
        try:
            if p.poll() is None:
                p.send_signal(signal.SIGKILL)
        except Exception:
            pass
    _state.update({
        "running": False, "procs": [], "playwright": None,
        "browser": None, "context": None, "page": None,
    })

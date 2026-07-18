"""
REKOMND+ v3 — Unified Platform Entry Point
============================================
Serves the shell UI on port 7070 with:
  • Multi-user authentication (login / register / profile / admin)
  • GMaps Scraper (embedded FastAPI router)
  • FB Auto Poster proxy (:5000)
  • FB Commenter V2 proxy (:5001)
  • FB Buyers Egypt proxy (:8000)
  • WhatsApp Bulk Sender (embedded iframe → :3000 + :3001)
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from auth import get_current_user, init_db, require_user, is_tool_allowed, User
from routers.gmaps_router import router as gmaps_router
from routers.auth_router import router as auth_router
from routers.whatsapp_shell_router import router as wa_router

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PROJ_DIR = BASE_DIR.parent   # workspace root

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rekomnd_plus")

app = FastAPI(title="REKOMND+ v3")

# Static files & templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Sub-routers
app.include_router(auth_router)                    # /login /register /logout /profile /admin/...
app.include_router(gmaps_router, prefix="/api/gmaps")
app.include_router(wa_router)                      # /whatsapp  /api/whatsapp/*


# ---------------------------------------------------------------------------
# Exception handler: redirect 307 to login
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_307_TEMPORARY_REDIRECT:
        return RedirectResponse(exc.headers["Location"])
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ---------------------------------------------------------------------------
# Sub-process management
# ---------------------------------------------------------------------------

_procs: list[subprocess.Popen] = []


def _launch(cmd: list[str], cwd: str, label: str) -> None:
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        _procs.append(proc)
        logger.info("Started %s (PID %s)", label, proc.pid)
    except Exception as exc:
        logger.warning("Could not start %s: %s", label, exc)


def _kill_all() -> None:
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass


atexit.register(_kill_all)


@app.on_event("startup")
async def startup_event() -> None:
    # Initialise auth database (creates tables + default admin)
    init_db()
    logger.info("Auth DB initialised — default admin: admin / admin123")

    # Services are now launched externally by Start_REKOMND_PLUS.bat
    logger.info("REKOMND+ v3 shell started — http://localhost:7070")


# ---------------------------------------------------------------------------
# Helper: render template with current_user injected
# ---------------------------------------------------------------------------

def _render(request: Request, template: str, ctx: dict | None = None, code: int = 200):
    user = get_current_user(request)
    base = {
        "current_user": user,
        "POSTER_URL": os.environ.get("POSTER_URL", "http://localhost:5000"),
        "COMMENTER_URL": os.environ.get("COMMENTER_URL", "http://localhost:5001"),
        "BUYERS_URL": os.environ.get("BUYERS_URL", "http://localhost:8000"),
        "WHATSAPP_URL": os.environ.get("WHATSAPP_URL", "http://localhost:3001"),
        "WA_GATEWAY_URL": os.environ.get("WA_GATEWAY_URL", "http://localhost:8085")
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, template, base, status_code=code)


def _check_tool(request: Request, slug: str):
    user = require_user(request)
    if not is_tool_allowed(user, slug):
        return _render(request, "access_denied.html", {
            "tool_slug": slug, "tool_name": slug.replace("_", " ").title(),
        }, code=403)
    return None


# ---------------------------------------------------------------------------
# Protected page routes (require login)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    require_user(request)
    return _render(request, "index.html")


@app.get("/gmaps", response_class=HTMLResponse)
async def gmaps_page(request: Request):
    denied = _check_tool(request, "gmaps")
    if denied:
        return denied
    return _render(request, "gmaps.html")


@app.get("/poster", response_class=HTMLResponse)
async def poster_page(request: Request):
    denied = _check_tool(request, "poster")
    if denied:
        return denied
    return _render(request, "poster.html")


@app.get("/commenter", response_class=HTMLResponse)
async def commenter_page(request: Request):
    denied = _check_tool(request, "commenter")
    if denied:
        return denied
    return _render(request, "commenter.html")


@app.get("/buyers", response_class=HTMLResponse)
async def buyers_page(request: Request):
    denied = _check_tool(request, "buyers")
    if denied:
        return denied
    return _render(request, "buyers.html")


# /whatsapp is handled by wa_router (protected inside that router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "REKOMND+ v3"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    import uvicorn

    time.sleep(0.5)
    webbrowser.open("http://localhost:7070")
    uvicorn.run("main:app", host="0.0.0.0", port=7070, reload=False)

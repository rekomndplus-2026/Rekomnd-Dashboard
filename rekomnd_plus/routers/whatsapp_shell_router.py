"""
REKOMND+ WhatsApp Shell Router — no-Docker edition
====================================================
Serves a native WhatsApp Bulk Sender page inside the unified REKOMND+ shell.

Architecture (no Docker needed):
  :8085  — wa-server  (Baileys, replaces Evolution API)
  :3001  — FastAPI backend  (whatsapp-bulk-sender/backend)
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from auth import get_current_user, is_tool_allowed, require_user

logger = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
TMPL_DIR  = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TMPL_DIR))

router = APIRouter(tags=["WhatsApp"])

import os
WA_BAILEYS_URL = os.environ.get("WA_GATEWAY_URL", "http://localhost:8085")
WA_BACKEND_URL = os.environ.get("WHATSAPP_URL", "http://localhost:3001")


@router.get("/whatsapp", response_class=HTMLResponse, include_in_schema=False)
async def whatsapp_page(request: Request):
    user = require_user(request)
    if not is_tool_allowed(user, "whatsapp"):
        return templates.TemplateResponse(request, "access_denied.html", {
            "current_user": user,
            "tool_slug": "whatsapp",
            "tool_name": "WhatsApp",
        }, status_code=403)
    return templates.TemplateResponse(request, "whatsapp.html", {
        "current_user": user,
        "wa_backend_url": WA_BACKEND_URL,
        "wa_baileys_url": WA_BAILEYS_URL,
    })


@router.get("/api/whatsapp/status")
async def whatsapp_status(request: Request):
    """Check if WhatsApp services are running."""
    results = {}

    async with httpx.AsyncClient(timeout=3.0) as client:
        # 1. Baileys gateway
        try:
            r = await client.get(f"{WA_BAILEYS_URL}/health", headers={"apikey": "supersecretapikey"})
            results["baileys"] = {"online": r.status_code == 200, "url": WA_BAILEYS_URL}
        except Exception:
            results["baileys"] = {"online": False, "url": WA_BAILEYS_URL}

        # 2. FastAPI backend
        try:
            r = await client.get(f"{WA_BACKEND_URL}/api/health")
            results["backend"] = {"online": r.status_code == 200, "url": WA_BACKEND_URL}
        except Exception:
            results["backend"] = {"online": False, "url": WA_BACKEND_URL}

    return JSONResponse(results)

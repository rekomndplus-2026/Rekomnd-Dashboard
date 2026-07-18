"""
Message sending router — no-Docker edition.
Uses an in-memory job store + threading instead of Celery + Redis.
"""

import asyncio
import base64
import logging
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
import shutil

from models.schemas import (
    JobStatus,
    MessagePayload,
    MessageResult,
    SendStatus,
)
from services.excel_processor import process_contacts, retrieve_dataframe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/messages", tags=["Messages"])

# ── In-memory job store (thread-safe via lock) ────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _get_job_raw(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


def _save_job(job_id: str, data: dict) -> None:
    with _jobs_lock:
        _jobs[job_id] = data


# ── Upload media endpoint ────────────────────────────────────────────────────

@router.post("/upload-media", response_model=dict)
async def upload_media(file: UploadFile = File(...)):
    """Upload a media file (image/video) to be sent with messages."""
    try:
        upload_dir = Path("uploads")
        upload_dir.mkdir(exist_ok=True)
        ext = Path(file.filename).suffix if file.filename else ""
        unique_name = f"media_{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / unique_name
        with file_path.open("wb") as buf:
            shutil.copyfileobj(file.file, buf)
        return {"media_filename": unique_name, "original_name": file.filename}
    except Exception as e:
        logger.error(f"Media upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload media file")


# ── Background sender thread ─────────────────────────────────────────────────

def _send_thread(
    job_id: str,
    records: list[dict],
    message_template: str,
    instance_name: str,
    evolution_url: str,
    evolution_key: str,
    delay_min: float,
    delay_max: float,
    media_filename: str | None,
):
    """Thread that sends messages one by one and updates the in-memory job."""
    headers = {"apikey": evolution_key, "Content-Type": "application/json"}

    # Load media file as base64 if needed
    media_b64: str | None = None
    media_type: str | None = None
    mime_type: str | None = None
    if media_filename:
        media_path = Path("uploads") / media_filename
        if media_path.exists():
            with open(media_path, "rb") as f:
                media_b64 = base64.b64encode(f.read()).decode()
            suffix = media_path.suffix.lower().lstrip(".")
            if suffix in ("jpg", "jpeg", "png", "gif", "webp"):
                media_type = "image"
                mime_type = f"image/{suffix if suffix != 'jpg' else 'jpeg'}"
            elif suffix in ("mp4", "mov", "avi"):
                media_type = "video"
                mime_type = f"video/{suffix}"
            else:
                media_type = "document"
                mime_type = "application/octet-stream"

    results: list[dict] = []
    sent = failed = skipped = 0

    for i, record in enumerate(records):
        # Check for cancellation
        with _jobs_lock:
            current = _jobs.get(job_id, {})
        if current.get("status") == "cancelled":
            break

        phone = str(record.get("phone_e164", record.get("_raw_phone", ""))).strip()
        if not phone:
            skipped += 1
            results.append({"row_index": i, "phone": phone, "status": "skipped", "error": "No phone"})
            _update_job(job_id, sent, failed, skipped, len(records), results, "running")
            continue

        # Format message from template
        try:
            msg = message_template.format(**{k: str(v) for k, v in record.items()})
        except KeyError:
            msg = message_template

        # Apply human delay
        time.sleep(random.uniform(delay_min, delay_max))

        try:
            if media_b64:
                payload = {
                    "number": phone.lstrip("+"),
                    "caption": msg,
                    "media": media_b64,
                    "mediatype": media_type,
                    "fileName": media_filename,
                    "options": {"delay": 1200, "presence": "composing"},
                }
                resp = httpx.post(
                    f"{evolution_url}/message/sendMedia/{instance_name}",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
            else:
                payload = {"number": phone.lstrip("+"), "text": msg, "delay": 1000}
                resp = httpx.post(
                    f"{evolution_url}/message/sendText/{instance_name}",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

            if resp.status_code in (200, 201):
                sent += 1
                results.append({"row_index": i, "phone": phone, "status": "sent"})
            else:
                failed += 1
                results.append({"row_index": i, "phone": phone, "status": "failed", "error": f"HTTP {resp.status_code}"})

        except Exception as exc:
            failed += 1
            results.append({"row_index": i, "phone": phone, "status": "failed", "error": str(exc)})
            logger.warning(f"Send failed for {phone}: {exc}")

        _update_job(job_id, sent, failed, skipped, len(records), results, "running")

    final_status = "completed" if _jobs.get(job_id, {}).get("status") != "cancelled" else "cancelled"
    _update_job(job_id, sent, failed, skipped, len(records), results, final_status)
    logger.info(f"Job {job_id} finished: sent={sent} failed={failed} skipped={skipped}")


def _update_job(job_id, sent, failed, skipped, total, results, status):
    done = sent + failed + skipped
    pct = round(done / total * 100, 1) if total else 0
    with _jobs_lock:
        _jobs[job_id].update({
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "pending": max(0, total - done),
            "status": status,
            "results": results[-100:],  # keep last 100 to avoid memory bloat
            "progress_percent": pct,
        })


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.post("/send", response_model=dict)
async def start_send_job(payload: MessagePayload, request: Request):
    """
    Start a bulk message sending job.
    Returns a job_id immediately; sending happens in a background thread.
    Frontend polls /messages/job/{job_id} for progress.
    """
    evo = request.app.state.evolution_api
    settings = request.app.state.settings

    # Verify WhatsApp is connected
    try:
        state = await evo.get_connection_state(payload.instance_name)
        connection_state = state.get("instance", state).get("state", "close")
        if connection_state != "open":
            raise HTTPException(
                status_code=400,
                detail="WhatsApp is not connected. Please scan the QR code first.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not verify WhatsApp connection: {e}")

    # Load and process contact file
    df = retrieve_dataframe(payload.file_id)
    if df is None:
        raise HTTPException(status_code=404, detail="Contact file not found. Please re-upload.")

    try:
        processed_df = process_contacts(df, payload.phone_column, payload.country_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    records = processed_df.fillna("").to_dict(orient="records")
    for rec in records:
        rec["_raw_phone"] = rec.get(payload.phone_column, "")

    job_id = str(uuid.uuid4())
    job_data = {
        "job_id": job_id,
        "total": len(records),
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "pending": len(records),
        "status": "starting",
        "results": [],
        "progress_percent": 0.0,
    }
    _save_job(job_id, job_data)

    # Start background thread
    t = threading.Thread(
        target=_send_thread,
        args=(
            job_id,
            records,
            payload.message_template,
            payload.instance_name,
            settings.evolution_api_url,
            settings.evolution_api_key,
            settings.message_delay_min,
            settings.message_delay_max,
            payload.media_filename,
        ),
        daemon=True,
        name=f"send-{job_id[:8]}",
    )
    t.start()

    logger.info(f"Started send job {job_id} for {len(records)} contacts")
    return {"job_id": job_id, "message": f"Job started. Sending to {len(records)} contacts.", "total": len(records)}


@router.get("/job/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll the status of a send job."""
    raw = _get_job_raw(job_id)
    return JobStatus(**raw)


@router.delete("/job/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    raw = _get_job_raw(job_id)
    if raw["status"] in ("running", "starting"):
        with _jobs_lock:
            _jobs[job_id]["status"] = "cancelled"
        return {"message": "Job cancellation requested"}
    return {"message": f"Job is already in '{raw['status']}' state"}

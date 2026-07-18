import os
import asyncio
import logging
import random
from celery import Celery
import redis
import json
import base64
import mimetypes
from pathlib import Path

from services.evolution_api import EvolutionAPIService
from services.excel_processor import render_message

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "http://evolution_api:8080")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "supersecretapikey")

celery_app = Celery("wbs_tasks", broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Synchronous wrapper to run async Evolution API calls
def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

@celery_app.task(bind=True)
def send_messages_task(self, job_id: str, df_data: list, message_template: str, instance_name: str, delay_min: float, delay_max: float, media_filename: str = None):
    """
    Celery background task to send messages.
    """
    evo_service = EvolutionAPIService(base_url=EVOLUTION_API_URL, api_key=EVOLUTION_API_KEY)
    
    total = len(df_data)
    sent = 0
    failed = 0
    skipped = 0
    results = []
    
    def update_job_status():
        job_data = {
            "job_id": job_id,
            "total": total,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "pending": total - (sent + failed + skipped),
            "status": "running" if (sent + failed + skipped) < total else "completed",
            "results": results,
            "progress_percent": round(((sent + failed + skipped) / total) * 100, 1) if total > 0 else 0
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_data))

    update_job_status()

    for i, row in enumerate(df_data):
        phone = row.get("_cleaned_phone", "")
        is_valid = row.get("_phone_valid", False)

        if not phone or not is_valid:
            results.append({
                "row_index": i,
                "phone": row.get("_raw_phone", "unknown"),
                "status": "skipped",
                "error": "Invalid or missing phone number"
            })
            skipped += 1
            update_job_status()
            continue

        try:
            message = render_message(message_template, row)
        except Exception as e:
            logger.error(f"Message render error for row {i}: {e}")
            results.append({
                "row_index": i,
                "phone": phone,
                "status": "failed",
                "error": f"Message rendering failed: {str(e)}"
            })
            failed += 1
            update_job_status()
            continue

        try:
            if media_filename:
                # Load media file and convert to base64
                file_path = Path("uploads") / media_filename
                if not file_path.exists():
                    raise FileNotFoundError(f"Media file not found: {media_filename}")
                
                mime_type, _ = mimetypes.guess_type(str(file_path))
                if not mime_type:
                    mime_type = "application/octet-stream"
                    
                media_type = mime_type.split("/")[0] # 'image', 'video', etc.
                
                with open(file_path, "rb") as f:
                    base64_data = base64.b64encode(f.read()).decode("utf-8")
                    
                response = _run_async(evo_service.send_media_message(
                    instance_name=instance_name,
                    phone=phone,
                    caption=message,
                    base64_data=base64_data,
                    media_type=media_type,
                    mime_type=mime_type
                ))
            else:
                response = _run_async(evo_service.send_text_message(
                    instance_name=instance_name,
                    phone=phone,
                    message=message,
                ))

            msg_id = response.get("key", {}).get("id") or response.get("messageId") or "sent"

            results.append({
                "row_index": i,
                "phone": phone,
                "status": "sent",
                "message_id": msg_id
            })
            sent += 1
            logger.info(f"✓ Sent to {phone} (job {job_id})")

        except Exception as e:
            error_str = str(e)
            logger.error(f"✗ Failed to send to {phone}: {error_str}")
            results.append({
                "row_index": i,
                "phone": phone,
                "status": "failed",
                "error": error_str
            })
            failed += 1

        update_job_status()

        if i < len(df_data) - 1:
            delay = random.uniform(delay_min, delay_max)
            _run_async(asyncio.sleep(delay))

    update_job_status()
    _run_async(evo_service.close())
    return {"status": "completed", "sent": sent, "failed": failed, "skipped": skipped}

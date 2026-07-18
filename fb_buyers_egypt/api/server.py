import os
import sys
import json
import threading
import subprocess
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import DatabaseManager
from config.settings import Config
import pandas as pd

app = FastAPI(title="Egypt RE Leads API")

# Allow CORS for React frontend (Vite defaults to 5173) and REKOMND+ shell (7070)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB Manager
db = DatabaseManager(Config.DB_URL)

def get_groups_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "groups.json")

def load_groups():
    path = get_groups_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_groups(groups):
    path = get_groups_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=4, ensure_ascii=False)

@app.get("/api/stats")
def get_stats():
    return db.get_stats()

@app.get("/api/leads")
def get_leads(limit: int = 100, skip: int = 0, min_score: int = 0):
    df = db.get_all_leads()
    if len(df) == 0:
        return []
    if min_score > 0:
        df = df[df["lead_score"] >= min_score]
    
    # Sort and paginate
    df = df.sort_values("lead_score", ascending=False)
    df = df.iloc[skip: skip + limit]
    
    # Convert NaN to None for JSON compliance
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if pd.isna(v):
                r[k] = None
    return records
class UpdateLeadReq(BaseModel):
    is_contacted: Optional[bool] = None
    contact_notes: Optional[str] = None

@app.patch("/api/leads/{lead_id}")
def update_lead_status(lead_id: str, req: UpdateLeadReq):
    session = db.get_session()
    try:
        from database.models import BuyerLead
        lead = session.query(BuyerLead).get(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if req.is_contacted is not None:
            lead.is_contacted = req.is_contacted
        if req.contact_notes is not None:
            lead.contact_notes = req.contact_notes
        session.commit()
        return {"message": "Lead updated"}
    finally:
        session.close()

@app.delete("/api/leads/{lead_id}")
def delete_lead_api(lead_id: str):
    session = db.get_session()
    try:
        from database.models import BuyerLead
        lead = session.query(BuyerLead).get(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        session.delete(lead)
        session.commit()
        return {"message": "Lead deleted"}
    finally:
        session.close()

@app.get("/api/groups")
def get_groups():
    return load_groups()

class GroupReq(BaseModel):
    name: str
    url: str
    region: str
    enabled: bool = True

@app.post("/api/groups")
def add_group(req: GroupReq):
    groups = load_groups()
    if any(g["url"] == req.url for g in groups):
        raise HTTPException(status_code=400, detail="Group already exists.")
    
    groups.append(req.model_dump())
    save_groups(groups)
    return {"message": "Group added successfully"}

@app.put("/api/groups")
def update_group(req: GroupReq):
    groups = load_groups()
    for i, g in enumerate(groups):
        if g["url"] == req.url:
            groups[i] = req.model_dump()
            save_groups(groups)
            return {"message": "Group updated successfully"}
    raise HTTPException(status_code=404, detail="Group not found.")

class DeleteGroupReq(BaseModel):
    url: str

@app.delete("/api/groups")
def delete_group(req: DeleteGroupReq):
    groups = load_groups()
    new_groups = [g for g in groups if g["url"] != req.url]
    if len(groups) == len(new_groups):
        raise HTTPException(status_code=404, detail="Group not found.")
    save_groups(new_groups)
    return {"message": "Group deleted successfully"}

@app.get("/api/session")
def check_session():
    session_file = Config.SESSION_FILE
    if not os.path.exists(session_file):
        return {"status": "missing", "message": "No session file found. Please run the login command."}

    meta_path = session_file + ".meta"
    if not os.path.exists(meta_path):
        return {"status": "warning", "message": "Session exists but has no metadata."}

    try:
        with open(meta_path) as f:
            meta = json.load(f)
        saved_at = meta.get("saved_at", "")
        # Check session age
        from datetime import datetime, timezone, timedelta
        saved_dt = datetime.fromisoformat(saved_at)
        age = datetime.now(timezone.utc) - saved_dt
        age_hours = age.total_seconds() / 3600
        age_str = f"{int(age.total_seconds() / 60)}m" if age_hours < 1 else f"{age_hours:.1f}h"

        if age_hours > 48:
            return {"status": "expired", "saved_at": saved_at, "age": age_str,
                    "message": f"Session is {age_str} old and likely expired. Please re-login."}
        elif age_hours > 24:
            return {"status": "stale", "saved_at": saved_at, "age": age_str,
                    "message": f"Session is {age_str} old. Consider refreshing."}
        else:
            return {"status": "ok", "saved_at": saved_at, "age": age_str}
    except Exception as e:
        return {"status": "warning", "message": f"Could not read session metadata: {e}"}

scraper_process = None

@app.post("/api/actions/scrape")
def trigger_scrape():
    global scraper_process
    if scraper_process is not None and scraper_process.poll() is None:
        raise HTTPException(status_code=400, detail="Scraper is already running.")
        
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    scraper_process = subprocess.Popen([sys.executable, script_path, "--scrape"])
    return {"message": "Scraping started in the background."}

class ScrapePostReq(BaseModel):
    url: str

@app.post("/api/actions/scrape-post")
def trigger_scrape_post(req: ScrapePostReq):
    global scraper_process
    if scraper_process is not None and scraper_process.poll() is None:
        raise HTTPException(status_code=400, detail="Scraper is already running.")
        
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    scraper_process = subprocess.Popen([sys.executable, script_path, "--scrape-post", req.url])
    return {"message": "Post scraping started in the background."}

@app.post("/api/actions/stop")
def stop_scrape():
    global scraper_process
    if scraper_process is None or scraper_process.poll() is not None:
        return {"message": "Scraper is not running."}
    
    scraper_process.terminate()
    scraper_process = None
    return {"message": "Scraper stopped."}

@app.get("/api/status")
def get_status():
    global scraper_process
    is_running = scraper_process is not None and scraper_process.poll() is None
    return {"is_running": is_running}

# ── Login State ───────────────────────────────────────────────────────────
login_state = {"running": False, "success": None, "message": ""}
login_done_event = threading.Event()

def _run_login_in_background():
    """Runs the Chrome-based login flow in a background thread."""
    global login_state
    login_done_event.clear()
    login_state = {"running": True, "success": None, "message": "Opening Chrome — please log in to Facebook…"}
    try:
        from scraper.auth import login_and_save_session
        
        def _wait_for_user():
            login_done_event.wait()

        ok = login_and_save_session(Config.SESSION_FILE, wait_callback=_wait_for_user)
        if ok:
            login_state = {"running": False, "success": True, "message": "✅ Login successful! Session saved."}
        else:
            login_state = {"running": False, "success": False, "message": "❌ Login failed or was cancelled."}
    except Exception as e:
        login_state = {"running": False, "success": False, "message": f"Error during login: {e}"}

@app.post("/api/actions/login")
def trigger_login():
    """Open Chrome so the user can log in to Facebook, then wait for signal."""
    global login_state
    if login_state.get("running"):
        raise HTTPException(status_code=400, detail="Login is already in progress.")
    t = threading.Thread(target=_run_login_in_background, daemon=True)
    t.start()
    return {"message": "Chrome opened. Click 'Finished' when done."}

@app.post("/api/actions/login/finish")
def finish_login():
    """Signal the background thread that the user is done logging in."""
    login_done_event.set()
    return {"message": "Finalizing login session..."}

@app.get("/api/login-status")
def get_login_status():
    """Poll this to check if login is still in progress."""
    return login_state


def run_refresh_task():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(base_dir, "login.py")
    session_file = os.path.join(base_dir, "config", "session.json")
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    subprocess.run([sys.executable, script_path, "--session-file", session_file], cwd=base_dir, env=env)

@app.post("/api/actions/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_refresh_task)
    return {"message": "Session refresh started in the background."}

@app.get("/api/logs")
def get_logs():
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "buyers_scraper.log")
    if not os.path.exists(log_path):
        return {"logs": ["No logs yet."]}
    
    try:
        # Read last 100 lines
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return {"logs": lines[-100:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {e}"]}

@app.get("/api/export")
def export_leads(min_score: int = 0):
    """Export leads to Excel and return as a file download."""
    import tempfile
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    tmp_path = os.path.join(tempfile.gettempdir(), f"leads_{ts}.xlsx")
    try:
        db.export_to_excel(tmp_path, min_score=min_score)
        return FileResponse(
            tmp_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=f"egypt_buyers_leads_{ts}.xlsx",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")


# Serve the frontend build if it exists
dist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)

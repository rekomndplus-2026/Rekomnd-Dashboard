"""
FB Auto Poster — Flask Backend
================================
A consolidated Telegram-to-Facebook auto-posting pipeline.
Listens for Telegram messages, rewrites them using OpenAI, and posts
to Facebook groups using Playwright browser automation.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from flask import Flask, Response, jsonify, render_template, request
from dotenv import load_dotenv
try:
    from flask_cors import CORS as _CORS
except ImportError:
    _CORS = None

load_dotenv(Path(__file__).resolve().parent / "config.env")
import remote_login
# ---------------------------------------------------------------------------
# App & Logging Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOADS_DIR = DATA_DIR / "uploads"

from flask_cors import CORS
app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
CORS(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", uuid.uuid4().hex)
# Global CORS is applied above

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fb-auto-poster")

# ---------------------------------------------------------------------------
# JSON Storage Helpers
# ---------------------------------------------------------------------------

_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _get_file_lock(path: str) -> threading.Lock:
    """Return a per-path threading lock for safe concurrent file access."""
    with _file_locks_guard:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def load_json(path: str | Path, default: Any = None) -> Any:
    """Load a JSON file, returning *default* if it does not exist or is corrupt."""
    path = Path(path)
    lock = _get_file_lock(str(path))
    with lock:
        if not path.exists():
            return default if default is not None else []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s — returning default", path, exc)
            return default if default is not None else []


def save_json(path: str | Path, data: Any) -> None:
    """Atomically write *data* as JSON to *path*, creating parent dirs as needed."""
    path = Path(path)
    lock = _get_file_lock(str(path))
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            tmp.replace(path)
        except OSError as exc:
            logger.error("Failed to write %s: %s", path, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# Default Settings & Paths
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "posting_delay_min": 60,
    "posting_delay_max": 300,
    "max_posts_per_run": 5,
    "session_refresh_hours": 1,
    "rewrite_style": "professional",
    "auto_schedule_enabled": False,
    "auto_schedule_interval_hours": 4.0,
    "schedule_times": "",          # comma-separated HH:MM times e.g. "09:00,15:00,21:00"
    "schedule_burst_enabled": False,
    "schedule_burst_count": 4,
    "schedule_burst_interval_minutes": 120,
    "schedule_burst_start_time": "09:00",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "session_file": "data/fb_session.json",
    "headless": True,
    "require_manual_approval": False,
}

def _ensure_data_files() -> None:
    """Create the data/ directory and seed default files if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    defaults: dict[str, Any] = {
        "posts.json": [],
        "groups.json": [],
        "channels.json": [],
        "run_history.json": [],
        "settings.json": DEFAULT_SETTINGS,
    }
    for name, default_value in defaults.items():
        fp = DATA_DIR / name
        if not fp.exists():
            save_json(fp, default_value)
            logger.info("Created default data file: %s", fp)


_ensure_data_files()

POSTS_FILE = DATA_DIR / "posts.json"
GROUPS_FILE = DATA_DIR / "groups.json"
CHANNELS_FILE = DATA_DIR / "channels.json"
HISTORY_FILE = DATA_DIR / "run_history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler_state.json"

# ---------------------------------------------------------------------------
# Global Run State & Telegram Listener State
# ---------------------------------------------------------------------------

run_state: dict[str, Any] = {
    "running": False,
    "stop_requested": False,
    "thread": None,
    "started_at": None,
    "progress": "",
    "groups_done": 0,
    "groups_total": 0,
    "posts_posted": 0,
    "posts_failed": 0,
    "posts_rewritten": 0,
}

run_logs: list[dict[str, Any]] = []
_run_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Utility: Random / Delay Helpers
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

TIMEZONES = [
    "Africa/Cairo",
    "Asia/Riyadh",
    "Asia/Dubai",
    "Europe/London",
    "America/New_York",
    "Europe/Berlin",
    "Asia/Amman",
]

def human_delay(lo: float = 1.0, hi: float = 3.0) -> float:
    """Return a gaussian-distributed delay clamped between *lo* and *hi* seconds."""
    mu = (lo + hi) / 2
    sigma = (hi - lo) / 4
    return max(lo, min(hi, random.gauss(mu, sigma)))

def human_sleep(lo: float = 1.0, hi: float = 3.0) -> None:
    """Sleep for a human-like random duration."""
    time.sleep(human_delay(lo, hi))

# ---------------------------------------------------------------------------
# Telegram Bot Integration
# ---------------------------------------------------------------------------

def send_telegram(text: str) -> bool:
    """Send a notification to Telegram if configured."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    token = settings.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = settings.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram message sent successfully.")
            return True
        else:
            logger.warning("Telegram API returned %s: %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

def _get_session_path() -> Path:
    """Return the resolved session file path from settings."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    raw = settings.get("session_file", DEFAULT_SETTINGS["session_file"])
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p

def check_session_valid() -> dict[str, Any]:
    """Check if fb_session.json exists and cookies haven't expired."""
    session_path = _get_session_path()
    result: dict[str, Any] = {
        "valid": False,
        "expires_in": 0,
        "missing_cookies": [],
        "path": str(session_path),
    }

    if not session_path.exists():
        result["missing_cookies"] = ["c_user", "xs"]
        result["error"] = "Session file not found"
        result["status"] = "not_found"
        result["file_path"] = str(session_path)
        result["cookies"] = {}
        return result

    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result["error"] = f"Cannot read session file: {exc}"
        result["missing_cookies"] = ["c_user", "xs"]
        result["status"] = "not_found"
        result["file_path"] = str(session_path)
        result["cookies"] = {}
        return result

    cookies: list[dict] = []
    if isinstance(data, list):
        cookies = data
    elif isinstance(data, dict):
        cookies = data.get("cookies", data.get("data", []))
        if isinstance(cookies, dict):
            cookies = [cookies]

    cookie_map: dict[str, dict] = {}
    for c in cookies:
        if isinstance(c, dict):
            name = c.get("name", "")
            if name:
                cookie_map[name] = c

    required = ["c_user", "xs"]
    missing = [r for r in required if r not in cookie_map]
    result["missing_cookies"] = missing

    cookie_map_out = {}
    for req_name in ["c_user", "xs", "datr", "fr"]:
        if req_name in cookie_map:
            c = cookie_map[req_name]
            exp = c.get("expires", c.get("expirationDate", 0))
            try:
                exp = float(exp)
                if exp > 0:
                    exp_str = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                else:
                    exp_str = "Session"
            except (TypeError, ValueError):
                exp_str = "Unknown"
            cookie_map_out[req_name] = {"expiry": exp_str}

    result["cookies"] = cookie_map_out
    result["file_path"] = str(session_path)

    if missing:
        result["error"] = f"Missing required cookies: {', '.join(missing)}"
        result["status"] = "expired"
        return result

    now_ts = time.time()
    min_expiry = float("inf")
    for req_name in required:
        cookie = cookie_map[req_name]
        exp = cookie.get("expires", cookie.get("expirationDate", 0))
        try:
            exp = float(exp)
        except (TypeError, ValueError):
            exp = 0
        if exp > 0:
            min_expiry = min(min_expiry, exp)

    if min_expiry == float("inf"):
        result["valid"] = True
        result["status"] = "valid"
        result["expires_in"] = -1
    elif min_expiry > now_ts:
        result["valid"] = True
        result["status"] = "valid"
        result["expires_in"] = int(min_expiry - now_ts)
    else:
        result["valid"] = False
        result["status"] = "expired"
        result["expires_in"] = 0
        result["error"] = "Session cookies have expired"

    return result

# ---------------------------------------------------------------------------
# Browser Setup (Playwright)
# ---------------------------------------------------------------------------

STEALTH_JS = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5], });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'ar'], });
    delete window.__playwright;
    delete window.__pw_manual;
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""

def create_browser_context(playwright: Any) -> tuple[Any, Any, Any]:
    """Create a stealth Playwright browser context with anti-detection measures."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    headless = settings.get("headless", True)

    user_agent = random.choice(USER_AGENTS)
    tz = random.choice(TIMEZONES)
    vp_width = random.randint(1280, 1920)
    vp_height = random.randint(800, 1080)

    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-extensions",
        ],
    )

    session_path = _get_session_path()
    storage_state: dict | None = None
    if session_path.exists():
        try:
            raw = json.loads(session_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "cookies" in raw:
                storage_state = raw
            elif isinstance(raw, list):
                storage_state = {"cookies": raw, "origins": []}
            else:
                storage_state = {"cookies": [], "origins": []}
        except Exception as exc:
            logger.warning("Could not load session file: %s", exc)

    ctx_kwargs: dict[str, Any] = {
        "user_agent": user_agent,
        "viewport": {"width": vp_width, "height": vp_height},
        "locale": "en-US",
        "timezone_id": tz,
        "ignore_https_errors": True,
    }
    if storage_state:
        ctx_kwargs["storage_state"] = storage_state

    context = browser.new_context(**ctx_kwargs)

    # Removed context.route entirely to prevent blocking Facebook's internal image upload requests (which use fetch/websocket/'other' types)

    page = context.new_page()
    context.add_init_script(STEALTH_JS)

    return browser, context, page

def _is_logged_in(page) -> bool:
    url = page.url
    if any(x in url for x in ["/login", "login.php", "r.php?"]): return False
    if "two_step_verification" in url:
        try:
            still_on_2fa = page.evaluate("!!(document.querySelector('input[name=\"approvals_code\"]') || document.querySelector('input[id=\"approvals_code\"]') || document.querySelector('button[name=\"submit[Continue]\"]') || document.querySelector('form[id=\"login_approvals_form\"]'))")
            return not still_on_2fa
        except Exception:
            return False
    if "/checkpoint" in url: return False
    if "facebook.com" in url: return True
    return False

# ---------------------------------------------------------------------------
# Telegram Listener (Long-polling)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AI Rewriter (OpenAI API)
# ---------------------------------------------------------------------------

def rewrite_post(original_text: str, note: str = "", log_cb: Callable | None = None) -> str:
    """Rewrite or generate a post using the user's own OpenAI API key from settings."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    api_key = settings.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    model = settings.get("openai_model", "gpt-4o-mini")
    style = settings.get("rewrite_style", "professional")

    if not api_key:
        if log_cb: log_cb("⚠ No OpenAI API key set. Go to Settings → AI Rewriting to add your key.", "warning")
        return original_text

    try:
        from openai import OpenAI
    except ImportError:
        if log_cb: log_cb("OpenAI python package not installed. Run: pip install openai", "warning")
        return original_text

    # Build style-specific system prompt
    style_prompts = {
        "professional": "Write in a professional, polished, and trustworthy tone.",
        "casual": "Write in a casual, friendly, and conversational tone.",
        "creative": "Write in a creative, imaginative, and visually engaging tone.",
        "viral": "Write in a punchy, viral, hook-first style that grabs attention instantly.",
        "arabic_real_estate": (
            "أنت خبير تسويق عقاري مصري. اكتب منشوراً جذاباً ومقنعاً باللغة العربية "
            "يستهدف المشترين والمستثمرين العقاريين. استخدم أسلوباً مقنعاً يبرز الفرصة "
            "ويشجع على التواصل الفوري. أضف هاشتاقات عقارية مصرية مناسبة."
        ),
    }
    style_instruction = style_prompts.get(style, style_prompts["professional"])

    try:
        client = OpenAI(api_key=api_key)

        if style == "arabic_real_estate":
            prompt = f"""{style_instruction}

المحتوى الأصلي / الفكرة:
{original_text}"""
        else:
            prompt = f"""You are an expert social media manager. I will give you either a full draft of a post, or a short idea for a post.
Your job is to write a highly engaging, complete social media post based on it.

- If it's a short idea, flesh it out into a proper engaging post.
- If it's a full draft, rewrite it to make it unique and engaging while keeping the core intent.
- Style: {style_instruction}
- If the input is in Arabic, write the post in Arabic.
- Return ONLY the final post text, nothing else.

Draft/Idea:
{original_text}"""

        if note:
            prompt += f"\n\nCRITICAL USER INSTRUCTIONS:\n{note}"

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.8,
        )
        rewritten = response.choices[0].message.content.strip()
        if log_cb: log_cb("✓ AI rewrite successful", "info")
        return rewritten
    except Exception as e:
        if log_cb: log_cb(f"OpenAI API error: {e}", "error")
        return original_text


# ---------------------------------------------------------------------------
# Facebook Poster Automation
# ---------------------------------------------------------------------------

def _try_click(page, selectors: list, label: str, timeout_ms=4000, log_cb=None) -> bool:
    """Try each CSS selector in order; return True on first successful click."""
    from playwright.sync_api import TimeoutError as PWTimeout
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout_ms)
            if el:
                el.scroll_into_view_if_needed()
                time.sleep(0.3)
                el.click()
                if log_cb: log_cb(f"  [{label}] clicked via: {sel}", "debug")
                return True
        except (PWTimeout, Exception):
            continue
    return False

def _js_click_by_text(page, texts: list, role="button", label="element", log_cb=None) -> bool:
    """JS fallback: click first element whose innerText/aria-label matches any text."""
    texts_json = json.dumps(texts)
    try:
        result = page.evaluate(f"""
            (function() {{
                const candidates = document.querySelectorAll('[role="{role}"], button, div[tabindex]');
                const targets = {texts_json};
                for (const el of candidates) {{
                    const txt = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    for (const t of targets) {{
                        if (txt === t || txt.toLowerCase().includes(t.toLowerCase())) {{
                            el.click();
                            return txt;
                        }}
                    }}
                }}
                return null;
            }})()
        """)
        if result:
            if log_cb: log_cb(f"  [{label}] JS click matched: '{result}'", "debug")
            return True
    except Exception as e:
        if log_cb: log_cb(f"  [{label}] JS click failed: {e}", "debug")
    return False

def post_to_group(page, group_url: str, post_text: str, image_path: str = None, log_cb=None) -> dict:
    """Post text (and optionally an image) to a Facebook group using a given page."""
    try:
        if log_cb: log_cb(f"Loading group page: {group_url}", "info")
        page.goto(group_url, wait_until="domcontentloaded", timeout=40000)
        time.sleep(random.uniform(4, 6))
        
        if not _is_logged_in(page):
            msg = "Session expired or not logged in."
            if log_cb: log_cb(msg, "error")
            return {"success": False, "message": msg}

        if log_cb: log_cb("Looking for composer placeholder...", "info")
        composer_selectors = [
            '[aria-label="Write something..."]', '[aria-label="What\'s on your mind?"]',
            '[aria-label="Create a public post…"]', '[aria-label="Create a public post..."]',
            '[aria-label="اكتب شيئًا..."]', '[aria-label="اكتب شيئاً..."]',
            '[aria-label="بماذا تفكر؟"]', '[aria-label="أنشئ منشورًا عامًا…"]',
            '[data-testid="group-composer-entry-point"]', '[data-testid="react-composer-root"]',
            'div[role="button"]:has-text("Write something")', 'div[role="button"]:has-text("What\'s on your mind")',
            'div[role="button"]:has-text("اكتب شيئًا")', 'div[role="button"]:has-text("بماذا تفكر")',
            '[data-pagelet="GroupInlineComposer"] div[role="button"]', '[data-pagelet="GroupComposer"] div[role="button"]',
        ]
        
        clicked = _try_click(page, composer_selectors, "composer", log_cb=log_cb)
        if not clicked:
            clicked = _js_click_by_text(page, ["Write something...", "What's on your mind?", "اكتب شيئًا", "بماذا تفكر", "Create a public post", "أنشئ منشورًا"], label="composer", log_cb=log_cb)
            
        if not clicked:
            msg = "Could not find post composer"
            if log_cb: log_cb(msg, "error")
            return {"success": False, "message": msg}
            
        time.sleep(random.uniform(2, 3))
        
        if image_path and os.path.exists(image_path):
            if log_cb: log_cb(f"Starting image upload: {image_path}", "info")
            uploaded = False
            photo_button_selectors = [
                '[aria-label="Photo/video"]', '[aria-label="Photo/Video"]', '[aria-label="Photo or video"]',
                '[aria-label="صورة/فيديو"]', '[aria-label="صورة أو فيديو"]',
                'div[role="button"]:has-text("Photo/video")', 'div[role="button"]:has-text("Photo")',
                '[data-testid="photo-video-composer-button"]', '[data-testid="media-sprout-open-button"]',
            ]
            
            # Strategy A: click the photo button and catch the file chooser
            for photo_sel in photo_button_selectors:
                try:
                    with page.expect_file_chooser(timeout=8000) as fc_info:
                        page.click(photo_sel, timeout=4000)
                    fc_info.value.set_files(image_path)
                    uploaded = True
                    if log_cb: log_cb(f"  Image uploaded via strategy A: {photo_sel}", "debug")
                    break
                except Exception:
                    pass

            # Strategy B: JS click then catch file chooser
            if not uploaded:
                try:
                    with page.expect_file_chooser(timeout=8000) as fc_info:
                        _js_click_by_text(page, ["Photo/video", "Photo", "Video", "صورة/فيديو", "صورة"], label="photo-btn")
                    fc_info.value.set_files(image_path)
                    uploaded = True
                    if log_cb: log_cb("  Image uploaded via strategy B: JS file chooser", "debug")
                except Exception:
                    pass

            # Strategy C: set files directly on a hidden file input (bypasses the button entirely)
            if not uploaded:
                try:
                    file_input = (
                        page.query_selector('input[type="file"][accept*="image"]')
                        or page.query_selector('input[type="file"]')
                    )
                    if file_input:
                        file_input.set_input_files(image_path)
                        uploaded = True
                        if log_cb: log_cb("  Image uploaded via strategy C: direct file input", "debug")
                except Exception:
                    pass

            if uploaded:
                # Wait for Facebook to process and show the image preview before typing text
                time.sleep(random.uniform(8, 12))
                
                # Re-focus the text editor because Facebook replaces the UI after image upload
                try:
                    page.click('div[contenteditable="true"][role="textbox"]', timeout=5000)
                    if log_cb: log_cb("  Re-focused text editor after image upload.", "debug")
                except Exception:
                    pass
            else:
                if log_cb: log_cb("Image upload completely failed — continuing with text-only post.", "warning")
                
        if log_cb: log_cb("Looking for text editor...", "info")
        typed = False
        editor_selectors = [
            'div[contenteditable="true"][aria-label*="caption" i]',
            'div[contenteditable="true"][aria-label*="something" i]',
            'div[contenteditable="true"][aria-label*="mind" i]',
            'div[contenteditable="true"][aria-label*="بماذا" i]',
            'div[contenteditable="true"][aria-label*="اكتب" i]',
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"][aria-label]',
            'div[contenteditable="true"][aria-multiline="true"]',
            'div[contenteditable="true"]',
        ]
        
        for sel in editor_selectors:
            try:
                editors = page.query_selector_all(sel)
                best, best_size = None, 0
                for ed in editors:
                    box = ed.bounding_box()
                    if box and box["width"] > 100 and box["height"] > 10:
                        size = box["width"] * box["height"]
                        if size > best_size:
                            best_size, best = size, ed
                if best:
                    best.click()
                    time.sleep(0.8)
                    page.keyboard.type(post_text, delay=random.randint(40, 90))
                    typed = True
                    break
            except Exception:
                continue
                
        if not typed:
            try:
                page.keyboard.type(post_text, delay=random.randint(40, 90))
                typed = True
            except Exception as e:
                msg = f"Direct keyboard type failed: {e}"
                if log_cb: log_cb(msg, "error")
                
        if not typed:
            msg = "Could not type into text editor"
            if log_cb: log_cb(msg, "error")
            return {"success": False, "message": msg}
            
        time.sleep(random.uniform(1.5, 2.5))
        
        # DEBUG SCREENSHOT: After typing
        debug_dir = BASE_DIR / "data" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(debug_dir / f"debug_typed_{post_text[:10].replace(' ', '_')}.png"))
        
        if log_cb: log_cb("Looking for Post button...", "info")
        posted = False
        post_btn_selectors = [
            '[aria-label="Post"]', '[aria-label="Publish"]', '[aria-label="Share"]',
            '[aria-label="نشر"]', '[aria-label="مشاركة"]',
            'div[role="dialog"] [aria-label="Post"]', 'div[role="dialog"] [aria-label="نشر"]',
            'div[role="button"]:has-text("Post"):not([aria-disabled="true"])',
            'div[role="button"]:has-text("Publish"):not([aria-disabled="true"])',
        ]
        
        def _post_btn_enabled() -> bool:
            try:
                return page.evaluate(" (function() { const candidates = document.querySelectorAll('[role=\"button\"]'); for (const el of candidates) { const lbl = el.getAttribute('aria-label') || ''; const txt = el.innerText || ''; if (lbl === 'Post' || lbl === 'نشر' || txt.trim() === 'Post' || txt.trim() === 'نشر') { return el.getAttribute('aria-disabled') !== 'true' && !el.classList.contains('disabled'); } } return false; })() ")
            except Exception:
                return True
                
        for _ in range(10):
            if _post_btn_enabled(): break
            time.sleep(0.5)
            
        posted = _try_click(page, post_btn_selectors, "post-button", log_cb=log_cb)
        if not posted:
            posted = _js_click_by_text(page, ["Post", "Publish", "Share", "نشر", "مشاركة"], label="post-button", log_cb=log_cb)
            
        if not posted:
            if log_cb: log_cb("Using Ctrl+Enter keyboard fallback...", "warning")
            page.keyboard.press("Control+Return")
            posted = True
            
        if log_cb: log_cb("Waiting 15-20 seconds for Facebook to finish processing the upload...", "info")
        time.sleep(random.uniform(15, 20))
        
        # DEBUG SCREENSHOT: After posting
        page.screenshot(path=str(debug_dir / f"debug_posted_{post_text[:10].replace(' ', '_')}.png"))
        
        msg = f"Successfully posted to {group_url}"
        if log_cb: log_cb(msg, "info")
        return {"success": True, "message": msg}
        
    except Exception as e:
        msg = f"Unexpected error during posting: {e}"
        if log_cb: log_cb(msg, "error")
        return {"success": False, "message": msg}

# ---------------------------------------------------------------------------
# Session Keeper Thread
# ---------------------------------------------------------------------------

def _session_keeper_thread():
    """Background thread that refreshes Facebook session periodically."""
    logger.info("Session keeper thread started.")
    while True:
        try:
            settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
            refresh_hours = float(settings.get("session_refresh_hours", 1.0))
            
            if check_session_valid().get("valid"):
                logger.info("Refreshing Facebook session...")
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser, context, page = create_browser_context(pw)
                    try:
                        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                        time.sleep(random.uniform(4, 7))
                        if _is_logged_in(page):
                            for _ in range(random.randint(3, 6)):
                                scroll_amount = random.randint(300, 800)
                                page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                                time.sleep(random.uniform(1.5, 3.5))
                            page.goto("https://www.facebook.com/groups/feed/", wait_until="domcontentloaded", timeout=20000)
                            time.sleep(random.uniform(3, 5))
                            for _ in range(random.randint(2, 4)):
                                page.evaluate(f"window.scrollBy(0, {random.randint(200, 600)})")
                                time.sleep(random.uniform(1, 2.5))
                            context.storage_state(path=_get_session_path())
                            logger.info("Session refreshed and saved successfully")
                    except Exception as e:
                        logger.error(f"Refresh error: {e}")
                    finally:
                        browser.close()
        except Exception as e:
            logger.error(f"Session keeper error: {e}")
            
        # sleep N hours
        time.sleep(refresh_hours * 3600)

# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(posts_data: list, groups_data: list, settings: dict, log_cb: Callable) -> dict:
    """Main pipeline: rewrite posts → post to groups → notify."""
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "groups_processed": 0,
        "posts_rewritten": 0,
        "posts_posted": 0,
        "posts_failed": 0,
        "errors": []
    }
    
    active_groups = [g for g in groups_data if g.get("active", True)]
    
    require_approval = settings.get("require_manual_approval", False)
    if require_approval:
        allowed_statuses = ("approved", "failed")
    else:
        allowed_statuses = ("new", "rewritten", "approved", "failed")
        
    pending_posts = [p for p in posts_data if p.get("status") in allowed_statuses]
    
    max_posts = settings.get("max_posts_per_run", 5)
    pending_posts = pending_posts[:max_posts]
    
    if not active_groups:
        log_cb("No active groups configured.", "warning")
        return summary
    if not pending_posts:
        log_cb("No pending posts to process.", "info")
        return summary
        
    run_state["groups_total"] = len(active_groups)
    min_delay = settings.get("posting_delay_min", 60)
    max_delay = settings.get("posting_delay_max", 300)
    
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as pw:
        browser = context = page = None
        try:
            browser, context, page = create_browser_context(pw)
            log_cb("Browser launched.", "info")
            
            for post_idx, post in enumerate(pending_posts):
                if run_state["stop_requested"]:
                    break
                    
                log_cb(f"\n{'='*60}\nProcessing Post {post_idx+1}/{len(pending_posts)}: {post['original_text'][:50]}...", "info")
                
                # Mark as processing
                post["status"] = "posting"
                save_json(POSTS_FILE, posts_data)
                
                post_success_count = 0
                post_fail_count = 0
                
                post_results = post.setdefault("post_results", {})
                
                if not post.get("rewritten_text"):
                    log_cb("Rewriting post using AI...", "info")
                    run_state["posts_rewritten"] += 1
                    summary["posts_rewritten"] += 1
                    post["rewritten_text"] = rewrite_post(post["original_text"], log_cb)
                    save_json(POSTS_FILE, posts_data)
                
                final_text = post["rewritten_text"]
                
                for g_idx, group in enumerate(active_groups):
                    if run_state["stop_requested"]:
                        break
                        
                    group_id = group.get("id")
                    group_url = group.get("url")
                    group_name = group.get("name", group_url)
                    
                    run_state["progress"] = f"Post {post_idx+1} -> Group {g_idx+1}: {group_name}"
                    
                    # skip if already posted successfully to this group
                    if post_results.get(group_id, {}).get("status") == "success":
                        log_cb(f"Skipping group {group_name} (already posted).", "info")
                        continue
                    
                    # 2. Post to Facebook
                    log_cb(f"Posting to: {group_name}", "info")
                    res = post_to_group(page, group_url, final_text, post.get("image_path"), log_cb)
                    
                    if res["success"]:
                        post_success_count += 1
                        run_state["posts_posted"] += 1
                        summary["posts_posted"] += 1
                        post_results[group_id] = {"status": "success", "message": res["message"]}
                    else:
                        post_fail_count += 1
                        run_state["posts_failed"] += 1
                        summary["posts_failed"] += 1
                        post_results[group_id] = {"status": "failed", "message": res["message"]}
                        summary["errors"].append(f"{group_name}: {res['message']}")
                        
                    save_json(POSTS_FILE, posts_data)
                    
                    # 3. Delay
                    if g_idx < len(active_groups) - 1 and not run_state["stop_requested"]:
                        delay = human_delay(min_delay, max_delay)
                        log_cb(f"Waiting {delay:.0f}s before next group...", "info")
                        time.sleep(delay)
                        
                # Update final post status
                if post_success_count > 0 and post_fail_count == 0:
                    post["status"] = "posted"
                elif post_success_count > 0 and post_fail_count > 0:
                    post["status"] = "posted" # partially posted
                else:
                    post["status"] = "failed"
                    
                post["posted_at"] = datetime.now(timezone.utc).isoformat()
                save_json(POSTS_FILE, posts_data)
                
                summary["groups_processed"] = max(summary["groups_processed"], g_idx + 1)
                run_state["groups_done"] = summary["groups_processed"]
                
        except Exception as exc:
            msg = f"Fatal error in pipeline: {exc}"
            log_cb(msg, "error")
            summary["errors"].append(msg)
            logger.exception(msg)
        finally:
            try:
                if browser: browser.close()
            except Exception:
                pass
                
    summary["ended_at"] = datetime.now(timezone.utc).isoformat()
    log_cb(f"\nPipeline complete — {summary['posts_posted']} posted, {summary['posts_failed']} failed.", "info")
    
    send_telegram(
        f"📊 <b>Pipeline Complete</b>\n"
        f"Rewritten: {summary['posts_rewritten']}\n"
        f"Posted: {summary['posts_posted']}\n"
        f"Failed: {summary['posts_failed']}"
    )
    
    return summary

def _run_thread():
    """Background thread to run the pipeline."""
    run_logs.clear()
    run_state.update({
        "running": True,
        "stop_requested": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "groups_done": 0,
        "groups_total": 0,
        "posts_posted": 0,
        "posts_failed": 0,
        "posts_rewritten": 0,
        "progress": "Initialising…",
    })
    
    def log_cb(message: str, level: str = "info"):
        entry = {"ts": datetime.now().isoformat(), "level": level, "msg": message}
        run_logs.append(entry)
        
    try:
        posts = load_json(POSTS_FILE, [])
        groups = load_json(GROUPS_FILE, [])
        settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        summary = run_pipeline(posts, groups, settings, log_cb)
        
        history = load_json(HISTORY_FILE, [])
        summary["id"] = uuid.uuid4().hex[:12]
        history.insert(0, summary)
        save_json(HISTORY_FILE, history[:100])
        
    except Exception as exc:
        log_cb(f"Run thread crashed: {exc}", "error")
        logger.exception("Run thread crashed")
    finally:
        run_state["running"] = False
        run_state["progress"] = "Idle"

# ---------------------------------------------------------------------------
# Flask API Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

# --- POSTS ---
@app.route("/api/generate", methods=["POST"])
def api_generate_post():
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    note = body.get("note", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    
    try:
        generated = rewrite_post(text, note=note)
        return jsonify({"generated_text": generated})
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return jsonify({"error": "Failed to generate text"}), 500

@app.route("/api/posts", methods=["GET"])
def api_posts_list():
    status_filter = request.args.get("status")
    data = load_json(POSTS_FILE, [])
    if status_filter:
        data = [p for p in data if p.get("status") == status_filter]
    return jsonify(data)

@app.route("/api/posts", methods=["POST"])
def api_posts_create():
    # Support multipart/form-data (with file upload) OR JSON
    if request.content_type and "multipart/form-data" in request.content_type:
        text = request.form.get("text", "").strip()
        skip_ai = request.form.get("skip_ai", "false").lower() == "true"
        image_path = ""
        
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename:
                file.seek(0, 2)
                size = file.tell()
                file.seek(0)
                if size <= 10 * 1024 * 1024:
                    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "jpg"
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    
                    uploads_dir = BASE_DIR / "data" / "uploads"
                    uploads_dir.mkdir(parents=True, exist_ok=True)
                    
                    save_path = uploads_dir / filename
                    file.save(str(save_path))
                    image_path = str(save_path)
                else:
                    return jsonify({"error": "Image exceeds 10 MB limit"}), 400
    else:
        body = request.get_json(silent=True) or {}
        text = body.get("text", "").strip()
        image_path = body.get("image_path", "").strip().strip('"').strip("'")
        skip_ai = body.get("skip_ai", False)
        
    if not text:
        return jsonify({"error": "text is required"}), 400
        
    rewritten_text = ""
    status = "new"
    
    if skip_ai:
        rewritten_text = text
        status = "approved"
        
    entry = {
        "id": uuid.uuid4().hex[:12],
        "source": "manual",
        "original_text": text,
        "image_path": image_path,
        "has_image": bool(image_path),
        "rewritten_text": rewritten_text,
        "status": status,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "posted_at": None,
        "post_results": {}
    }
    data = load_json(POSTS_FILE, [])
    data.insert(0, entry)
    save_json(POSTS_FILE, data)
    return jsonify(entry), 201

@app.route("/api/posts/<string:pid>", methods=["DELETE"])
def api_posts_delete(pid: str):
    data = load_json(POSTS_FILE, [])
    new_data = [p for p in data if p.get("id") != pid]
    if len(new_data) == len(data):
        return jsonify({"error": "Not found"}), 404
    save_json(POSTS_FILE, new_data)
    return jsonify({"deleted": pid})

@app.route("/api/posts/<string:pid>", methods=["PUT"])
def api_posts_update(pid: str):
    data = load_json(POSTS_FILE, [])
    target_idx = None
    for i, p in enumerate(data):
        if p.get("id") == pid:
            target_idx = i
            break
            
    if target_idx is None:
        return jsonify({"error": "Not found"}), 404
        
    p = data[target_idx]
    
    if request.content_type and "multipart/form-data" in request.content_type:
        if "original_text" in request.form: p["original_text"] = request.form["original_text"].strip()
        if "text" in request.form: p["original_text"] = request.form["text"].strip()
        if "rewritten_text" in request.form: p["rewritten_text"] = request.form["rewritten_text"].strip()
        if "status" in request.form: p["status"] = request.form["status"]
            
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename:
                file.seek(0, 2)
                size = file.tell()
                file.seek(0)
                if size <= 10 * 1024 * 1024:
                    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "jpg"
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    uploads_dir = BASE_DIR / "data" / "uploads"
                    uploads_dir.mkdir(parents=True, exist_ok=True)
                    save_path = uploads_dir / filename
                    file.save(str(save_path))
                    p["image_path"] = str(save_path)
                    p["has_image"] = True
                else:
                    return jsonify({"error": "Image exceeds 10 MB limit"}), 400
        elif "image_path" in request.form:
            p["image_path"] = request.form["image_path"].strip()
            p["has_image"] = bool(p["image_path"])
    else:
        body = request.get_json(silent=True) or {}
        if "original_text" in body: p["original_text"] = body["original_text"].strip()
        if "image_path" in body: 
            p["image_path"] = body["image_path"].strip().strip('"').strip("'")
            p["has_image"] = bool(p["image_path"])
        if "rewritten_text" in body: p["rewritten_text"] = body["rewritten_text"]
        if "status" in body: p["status"] = body["status"]
        
    save_json(POSTS_FILE, data)
    return jsonify(p)

@app.route("/api/posts/<string:pid>/rewrite", methods=["POST"])
def api_posts_rewrite_single(pid: str):
    data = load_json(POSTS_FILE, [])
    body = request.get_json(silent=True) or {}
    note = body.get("note", "").strip()
    
    target_post = next((p for p in data if p.get("id") == pid), None)
    
    if not target_post:
        return jsonify({"error": "Not found"}), 404
        
    new_text = rewrite_post(target_post.get("original_text", ""), note=note)
    
    target_post["rewritten_text"] = new_text
    if target_post["status"] in ("new", "failed"):
        target_post["status"] = "rewritten"
        
    save_json(POSTS_FILE, data)
    return jsonify({"rewritten_text": new_text, "post": target_post})

# --- GROUPS ---
@app.route("/api/groups", methods=["GET"])
def api_groups_list():
    return jsonify(load_json(GROUPS_FILE, []))

@app.route("/api/groups", methods=["POST"])
def api_groups_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    url = body.get("url", "").strip()
    if not url: return jsonify({"error": "url is required"}), 400
    entry = {"id": uuid.uuid4().hex[:12], "name": name or url, "url": url, "active": body.get("active", True)}
    data = load_json(GROUPS_FILE, [])
    data.append(entry)
    save_json(GROUPS_FILE, data)
    return jsonify(entry), 201

@app.route("/api/groups/<string:gid>", methods=["PUT"])
def api_groups_update(gid: str):
    body = request.get_json(silent=True) or {}
    data = load_json(GROUPS_FILE, [])
    for item in data:
        if item.get("id") == gid:
            if "name" in body: item["name"] = body["name"].strip()
            if "url" in body: item["url"] = body["url"].strip()
            if "active" in body: item["active"] = bool(body["active"])
            save_json(GROUPS_FILE, data)
            return jsonify(item)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/groups/<string:gid>", methods=["DELETE"])
def api_groups_delete(gid: str):
    data = load_json(GROUPS_FILE, [])
    new_data = [item for item in data if item.get("id") != gid]
    if len(new_data) == len(data): return jsonify({"error": "Not found"}), 404
    save_json(GROUPS_FILE, new_data)
    return jsonify({"deleted": gid})

@app.route("/api/groups/<string:gid>/toggle", methods=["PATCH"])
def api_groups_toggle(gid: str):
    data = load_json(GROUPS_FILE, [])
    for item in data:
        if item.get("id") == gid:
            item["active"] = not item.get("active", True)
            save_json(GROUPS_FILE, data)
            return jsonify(item)
    return jsonify({"error": "Not found"}), 404

# --- SESSION ---
@app.route("/api/session/status", methods=["GET"])
def api_session_status():
    return jsonify(check_session_valid())

@app.route("/api/session/upload", methods=["POST"])
def api_session_upload():
    """Upload Facebook cookies as JSON to create a session (for headless/Docker environments)."""
    body = request.get_json(silent=True) or {}
    cookies = body.get("cookies", [])
    if not cookies:
        return jsonify({"error": "No cookies provided. Send {cookies: [{name, value, domain, ...}]}"}), 400

    # Validate required cookies
    cookie_names = {c.get("name") for c in cookies}
    required = {"c_user", "xs", "datr", "fr"}
    missing = required - cookie_names
    if missing:
        return jsonify({"error": f"Missing required cookies: {', '.join(missing)}"}), 400

    session_path = Path(settings.get("session_file", str(BASE_DIR / "data" / "fb_session.json")))
    session_path.parent.mkdir(parents=True, exist_ok=True)

    import time as _time
    session_data = {
        "cookies": cookies,
        "created_at": _time.time(),
        "expires_at": _time.time() + 86400 * 7,
    }
    with open(session_path, "w") as f:
        json.dump(session_data, f, indent=2)

    return jsonify({"success": True, "message": f"Saved {len(cookies)} cookies", "valid": True})

@app.route("/api/session/remote-login/start", methods=["POST"])
def api_remote_login_start():
    """Boot a real, visible Chrome on a virtual display + VNC so a human can log in."""
    result = remote_login.start_remote_login()
    status = 200 if result.get("success") else 500
    return jsonify(result), status


@app.route("/api/session/remote-login/finish", methods=["POST"])
def api_remote_login_finish():
    """Pull cookies out of the still-open remote browser and save the session."""
    session_path = _get_session_path()
    result = remote_login.finish_remote_login(session_path)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@app.route("/api/session/remote-login/stop", methods=["POST"])
def api_remote_login_stop():
    return jsonify(remote_login.stop_remote_login())


@app.route("/api/session/remote-login/status", methods=["GET"])
def api_remote_login_status():
    return jsonify({"running": remote_login.is_running()})


@app.route("/api/session/refresh", methods=["POST"])
def api_session_refresh():
    login_script = BASE_DIR / "login.py"
    if not login_script.exists(): return jsonify({"error": "login.py not found"}), 404
    import subprocess
    try:
        import os
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, str(login_script)], cwd=str(BASE_DIR), capture_output=True, text=True, encoding='utf-8', timeout=240, env=env)
        return jsonify({"success": result.returncode == 0, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:], "returncode": result.returncode})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

# --- RUN / PIPELINE ---
@app.route("/api/run/start", methods=["POST"])
def api_run_start():
    with _run_lock:
        if run_state["running"]: return jsonify({"error": "Run already in progress"}), 409
        sess = check_session_valid()
        if not sess.get("valid"): return jsonify({"error": "Session invalid", "session": sess}), 400
        thread = threading.Thread(target=_run_thread, daemon=True, name="pipeline-run")
        run_state["thread"] = thread
        thread.start()
    return jsonify({"status": "started"})

@app.route("/api/run/stop", methods=["POST"])
def api_run_stop():
    if not run_state["running"]: return jsonify({"error": "No active run"}), 400
    run_state["stop_requested"] = True
    return jsonify({"status": "stop_requested"})

@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    return jsonify({
        "running": run_state["running"],
        "stop_requested": run_state["stop_requested"],
        "started_at": run_state["started_at"],
        "progress": run_state["progress"],
        "groups_done": run_state["groups_done"],
        "groups_total": run_state["groups_total"],
        "posts_posted": run_state["posts_posted"],
        "posts_failed": run_state["posts_failed"],
        "posts_rewritten": run_state["posts_rewritten"],
    })

@app.route("/api/run/history", methods=["GET"])
def api_run_history():
    return jsonify(load_json(HISTORY_FILE, []))

@app.route("/api/run/stream")
def api_run_stream():
    def generate():
        idx = 0
        heartbeat = 0
        while True:
            while idx < len(run_logs):
                yield f"data: {json.dumps(run_logs[idx], ensure_ascii=False)}\n\n"
                idx += 1
            heartbeat += 1
            if heartbeat >= 30:
                yield ": heartbeat\n\n"
                heartbeat = 0
            time.sleep(0.5)
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --- SETTINGS ---
@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    return jsonify({**DEFAULT_SETTINGS, **settings})

@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    body = request.get_json(silent=True) or {}
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    settings.update(body)
    save_json(SETTINGS_FILE, settings)
    return jsonify(settings)


@app.route("/api/schedule/status", methods=["GET"])
def api_schedule_status():
    """Return current schedule configuration and next run info."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    state    = load_json(SCHEDULER_STATE_FILE, {"last_run_time": 0.0})

    enabled    = settings.get("auto_schedule_enabled", False)
    raw_times  = settings.get("schedule_times", "").strip()
    interval_h = float(settings.get("auto_schedule_interval_hours", 4.0))
    last_run   = state.get("last_run_time", 0.0)

    burst_enabled = settings.get("schedule_burst_enabled", False)
    burst_count   = int(settings.get("schedule_burst_count", 4))
    burst_interval_min = float(settings.get("schedule_burst_interval_minutes", 120))
    burst_start   = settings.get("schedule_burst_start_time", "09:00").strip() or "09:00"

    next_runs: list[str] = []
    mode = "burst" if burst_enabled else ("times" if raw_times else "interval")

    if enabled:
        now_dt = datetime.now()
        if mode == "burst":
            slots = _compute_burst_slots(burst_start, burst_count, burst_interval_min)
            triggered = state.get("burst_triggered_today", [])
            today_key = now_dt.strftime("%Y-%m-%d")
            if state.get("burst_day_key") != today_key:
                triggered = []
            remaining = 0
            for slot_str in slots:
                if slot_str not in triggered:
                    remaining += 1
                    next_runs.append(f"{today_key} {slot_str}")
            next_runs = next_runs[:5]
        elif mode == "times":
            parsed = _parse_schedule_times(raw_times)
            for (h, m) in sorted(parsed):
                candidate = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate <= now_dt:
                    candidate = candidate.replace(day=candidate.day + 1) if candidate.month == now_dt.month else candidate
                next_runs.append(candidate.strftime("%H:%M"))
            next_runs = sorted(next_runs)[:5]
        else:
            next_ts   = last_run + interval_h * 3600
            next_dt   = datetime.fromtimestamp(next_ts)
            next_runs = [next_dt.strftime("%Y-%m-%d %H:%M")]

    return jsonify({
        "enabled":   enabled,
        "mode":      mode,
        "times":     raw_times,
        "interval_hours": interval_h,
        "burst_enabled": burst_enabled,
        "burst_count": burst_count,
        "burst_interval_minutes": burst_interval_min,
        "burst_start_time": burst_start,
        "burst_remaining": remaining if mode == "burst" and enabled else None,
        "last_run":  datetime.fromtimestamp(last_run).strftime("%Y-%m-%d %H:%M") if last_run else None,
        "next_runs": next_runs,
        "running":   run_state["running"],
    })


@app.route("/api/openai/test", methods=["POST"])
def api_openai_test():
    """Test an OpenAI API key by listing available models."""
    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return jsonify({"valid": False, "error": "No API key provided"}), 400
    try:
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            model_ids = sorted([m["id"] for m in models if "gpt" in m.get("id", "")])[:5]
            return jsonify({"valid": True, "model": ", ".join(model_ids)})
        elif resp.status_code == 401:
            return jsonify({"valid": False, "error": "Invalid API key (401 Unauthorized)"})
        else:
            return jsonify({"valid": False, "error": f"OpenAI returned HTTP {resp.status_code}"})
    except requests.RequestException as exc:
        return jsonify({"valid": False, "error": f"Connection error: {exc}"})


# ---------------------------------------------------------------------------
# Background Scheduler
# ---------------------------------------------------------------------------

def _parse_schedule_times(raw: str) -> list[tuple[int, int]]:
    """Parse 'HH:MM,HH:MM,...' into list of (hour, minute) tuples."""
    result = []
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            try:
                h, m = part.split(":", 1)
                result.append((int(h), int(m)))
            except ValueError:
                pass
    return result


def _compute_burst_slots(start_time: str, count: int, interval_minutes: float) -> list[str]:
    """Compute daily burst time slots as HH:MM strings.

    Example: start="09:00", count=4, interval=120 → ["09:00","11:00","13:00","15:00"]
    """
    try:
        parts = start_time.strip().split(":")
        start_h, start_m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        start_h, start_m = 9, 0

    total_minutes = start_h * 60 + start_m
    slots = []
    for i in range(max(count, 1)):
        m = int(total_minutes + i * interval_minutes)
        h = (m // 60) % 24
        mm = m % 60
        slots.append(f"{h:02d}:{mm:02d}")
    return slots


def _scheduler_loop():
    """Background scheduler: supports time-of-day, interval, and burst modes."""
    _triggered_today: set[tuple[int, int]] = set()
    _last_calendar_day: int = -1

    while True:
        try:
            settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
            if settings.get("auto_schedule_enabled"):
                now_ts = time.time()
                now_dt = datetime.fromtimestamp(now_ts)
                today = now_dt.timetuple().tm_yday

                # Reset daily trigger set each new day
                nonlocal_day = _scheduler_loop.__dict__.setdefault("_day", -1)
                if today != nonlocal_day:
                    _triggered_today.clear()
                    _scheduler_loop.__dict__["_day"] = today

                state = load_json(SCHEDULER_STATE_FILE, {"last_run_time": 0.0})

                should_run = False
                now_secs = now_dt.hour * 3600 + now_dt.minute * 60

                # --- Mode 0: burst (daily repeating N runs at computed slots) ---
                burst_enabled = settings.get("schedule_burst_enabled", False)
                if burst_enabled:
                    burst_count = int(settings.get("schedule_burst_count", 4))
                    burst_interval = float(settings.get("schedule_burst_interval_minutes", 120))
                    burst_start = settings.get("schedule_burst_start_time", "09:00").strip() or "09:00"
                    slots = _compute_burst_slots(burst_start, burst_count, burst_interval)

                    # Track which burst slots triggered today
                    today_key = now_dt.strftime("%Y-%m-%d")
                    if state.get("burst_day_key") != today_key:
                        state["burst_triggered_today"] = []
                        state["burst_day_key"] = today_key

                    triggered = set(state.get("burst_triggered_today", []))
                    for slot_str in slots:
                        if slot_str in triggered:
                            continue
                        try:
                            sh, sm = slot_str.split(":")
                            slot_secs = int(sh) * 3600 + int(sm) * 60
                        except ValueError:
                            continue
                        if 0 <= (now_secs - slot_secs) < 60:
                            triggered.add(slot_str)
                            state["burst_triggered_today"] = list(triggered)
                            should_run = True
                            logger.info("Scheduler: Burst trigger at %s (%d/%d)", slot_str, len(triggered), burst_count)
                            break

                # --- Mode 1: specific times of day ---
                if not should_run and not burst_enabled:
                    raw_times = settings.get("schedule_times", "").strip()
                    if raw_times:
                        for (h, m) in _parse_schedule_times(raw_times):
                            slot = (h, m)
                            if slot not in _triggered_today:
                                slot_secs = h * 3600 + m * 60
                                if 0 <= (now_secs - slot_secs) < 60:
                                    _triggered_today.add(slot)
                                    should_run = True
                                    logger.info("Scheduler: Time-of-day trigger at %02d:%02d", h, m)
                                    break
                    else:
                        # --- Mode 2: every N hours ---
                        interval = float(settings.get("auto_schedule_interval_hours", 4.0)) * 3600
                        if now_ts - state.get("last_run_time", 0.0) >= interval:
                            should_run = True

                if should_run:
                    with _run_lock:
                        if not run_state["running"]:
                            sess = check_session_valid()
                            if sess.get("valid"):
                                logger.info("Scheduler: Triggering posting run.")
                                state["last_run_time"] = now_ts
                                save_json(SCHEDULER_STATE_FILE, state)
                                t = threading.Thread(target=_run_thread, daemon=True, name="scheduler-run")
                                run_state["thread"] = t
                                t.start()
                            else:
                                logger.warning("Scheduler: Session invalid — skipping run.")
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        time.sleep(30)   # check every 30 s for accurate time-of-day matching

threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler-loop").start()

# Start session keeper thread
threading.Thread(target=_session_keeper_thread, daemon=True, name="session-keeper").start()

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    logger.info("FB Auto Poster starting on http://localhost:5000")
    

    # webbrowser.open("http://localhost:5000")
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", 5000)))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

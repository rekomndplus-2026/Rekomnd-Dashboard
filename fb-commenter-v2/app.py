"""
FB Commenter V2 — Flask Backend
================================
A Facebook group auto-commenter that scans groups for posts matching keywords
and posts comments using Playwright browser automation.

All data is stored locally in JSON files under the data/ directory.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import string
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from flask import Flask, Response, jsonify, render_template, request
try:
    from flask_cors import CORS as _CORS
except ImportError:
    _CORS = None

# ---------------------------------------------------------------------------
# App & Logging Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"

from flask_cors import CORS
app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
CORS(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", uuid.uuid4().hex)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fb-commenter")

# ---------------------------------------------------------------------------
# Default Settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "comment_min_delay": 30,
    "comment_max_delay": 90,
    "max_posts_per_group": 10,
    "search_comments": True,
    "comment_depth": 3,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "session_file": "data/fb_session.json",
    "headless": True,
    "auto_schedule_enabled": False,
    "auto_schedule_interval_hours": 6.0,
    "schedule_times": "",   # comma-separated HH:MM e.g. "09:00,15:00,21:00"
    "schedule_burst_enabled": False,
    "schedule_burst_count": 4,
    "schedule_burst_interval_minutes": 120,
    "schedule_burst_start_time": "09:00",
}

# ---------------------------------------------------------------------------
# Global Run State
# ---------------------------------------------------------------------------

run_state: dict[str, Any] = {
    "running": False,
    "stop_requested": False,
    "thread": None,
    "started_at": None,
    "progress": "",
    "groups_done": 0,
    "groups_total": 0,
    "comments_posted": 0,
    "comments_failed": 0,
    "posts_scanned": 0,
    "posts_matched": 0,
}

run_logs: list[dict[str, str]] = []
_run_lock = threading.Lock()

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


def _ensure_data_files() -> None:
    """Create the data/ directory and seed default files if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    defaults: dict[str, Any] = {
        "keywords.json": [],
        "groups.json": [],
        "run_history.json": [],
        "settings.json": DEFAULT_SETTINGS,
    }
    for name, default_value in defaults.items():
        fp = DATA_DIR / name
        if not fp.exists():
            save_json(fp, default_value)
            logger.info("Created default data file: %s", fp)


_ensure_data_files()

# Convenience paths
KEYWORDS_FILE = DATA_DIR / "keywords.json"
GROUPS_FILE = DATA_DIR / "groups.json"
HISTORY_FILE = DATA_DIR / "run_history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler_state.json"

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
# Arabic / Text Normalisation Helpers
# ---------------------------------------------------------------------------

_ARABIC_ALEF_VARIANTS = re.compile("[\u0622\u0623\u0625\u0671]")  # آأإٱ
_ARABIC_DIACRITICS = re.compile(
    "[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]"
)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text: strip diacritics, unify alef/ta-marbuta/ya."""
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _ARABIC_ALEF_VARIANTS.sub("\u0627", text)  # → ا
    text = text.replace("\u0629", "\u0647")  # ة → ه
    text = text.replace("\u0649", "\u064A")  # ى → ي
    return text


def normalize_text(text: str) -> str:
    """Lowercase, strip accents / diacritics, collapse whitespace."""
    text = text.lower().strip()
    text = normalize_arabic(text)
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\s+", " ", text)
    return text


def levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def keyword_matches(post_text: str, keyword: str) -> bool:
    """
    Multi-strategy keyword matching.

    Strategies (tried in order):
    1. Exact normalised substring
    2. All keyword words present in post
    3. Arabic-normalised substring
    4. Word-boundary regex match
    5. Fuzzy Levenshtein for short keywords (≤12 chars, threshold 2)
    """
    norm_post = normalize_text(post_text)
    norm_kw = normalize_text(keyword)

    # 1 — Exact normalised substring
    if norm_kw in norm_post:
        return True

    # 2 — All words present
    kw_words = norm_kw.split()
    if kw_words and all(w in norm_post for w in kw_words):
        return True

    # 3 — Arabic-normalised substring (extra pass)
    ar_post = normalize_arabic(post_text)
    ar_kw = normalize_arabic(keyword)
    if ar_kw.strip() and ar_kw.strip() in ar_post:
        return True

    # 4 — Word boundary regex
    try:
        pattern = r"(?:^|\s|[^\w])" + re.escape(norm_kw) + r"(?:$|\s|[^\w])"
        if re.search(pattern, norm_post):
            return True
    except re.error:
        pass

    # 5 — Fuzzy match for short keywords
    if len(norm_kw) <= 12:
        post_words = norm_post.split()
        for pw in post_words:
            if levenshtein(pw, norm_kw) <= 2:
                return True

    return False


# ---------------------------------------------------------------------------
# Telegram Integration
# ---------------------------------------------------------------------------


def send_telegram(text: str) -> bool:
    """Send a notification to Telegram if configured. Returns True on success."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    token = settings.get("telegram_bot_token", "")
    chat_id = settings.get("telegram_chat_id", "")
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
    """
    Check if fb_session.json exists and cookies haven't expired.

    Returns a dict:
        {valid: bool, expires_in: int (seconds), missing_cookies: list[str]}
    """
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

    # Map out the cookies for the frontend
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

    # Check expiry
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
        # Session cookies (no explicit expiry) — treat as valid
        result["valid"] = True
        result["status"] = "valid"
        result["expires_in"] = -1  # unknown
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
    // Hide webdriver property
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Overwrite plugins to look normal
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Overwrite languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en', 'ar'],
    });

    // Remove automation-related properties
    delete window.__playwright;
    delete window.__pw_manual;

    // Chrome runtime mock
    window.chrome = { runtime: {} };

    // Permissions mock
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}
"""


def create_browser_context(playwright: Any) -> tuple[Any, Any, Any]:
    """
    Create a stealth Playwright browser context with anti-detection measures.

    Returns (browser, context, page).
    """
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

    # Load session cookies
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
                logger.warning("Session file format unrecognised; proceeding without cookies.")
        except (json.JSONDecodeError, OSError) as exc:
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

    # Block unnecessary resources
    context.route(
        "**/*",
        lambda route: (
            route.abort()
            if route.request.resource_type
            in ("font", "media", "websocket", "manifest", "other")
            or any(
                d in route.request.url
                for d in [
                    "google-analytics.com",
                    "googletagmanager.com",
                    "doubleclick.net",
                    "facebook.com/tr",
                    "connect.facebook.net/signals",
                ]
            )
            else route.continue_()
        ),
    )

    page = context.new_page()

    # Inject stealth JS on every navigation
    context.add_init_script(STEALTH_JS)

    return browser, context, page


# ---------------------------------------------------------------------------
# Commenting Engine — Helpers
# ---------------------------------------------------------------------------


def _log(msg: str, level: str = "info", callback: Callable | None = None) -> None:
    """Log a message and optionally call *callback*."""
    getattr(logger, level, logger.info)(msg)
    if callback:
        callback(msg, level)


def _random_scroll(page: Any, times: int = 3) -> None:
    """Scroll the page in a human-like manner."""
    for _ in range(times):
        distance = random.randint(300, 900)
        page.evaluate(f"window.scrollBy(0, {distance})")
        human_sleep(0.8, 2.5)


def _check_rate_limit(page: Any) -> bool:
    """
    Return True if the page shows signs of rate-limiting or a block.
    """
    signals = [
        "you're temporarily blocked",
        "temporarily restricted",
        "try again later",
        "we limit how often",
        "suspicious activity",
        "تم تقييدك مؤقتًا",
        "حاول مرة أخرى لاحقًا",
    ]
    try:
        body_text = page.evaluate("document.body.innerText").lower()
        for sig in signals:
            if sig.lower() in body_text:
                return True
    except Exception:
        pass
    return False


def _expand_comments_deep(page: Any, post_element: Any, max_expansions: int = 3) -> int:
    """
    Aggressively expand comments on a post:
      - Click initial 'X comments' button
      - Click 'View more comments'
      - Click 'View replies'
      - Click 'See more' in comment bodies
    Returns total number of clicks made.
    """
    if max_expansions <= 0:
        return 0

    # Expand the comment section if it's completely hidden
    try:
        comment_summary_btns = post_element.query_selector_all(
            'div[role="button"]:has-text("comment"), div[role="button"]:has-text("تعليق")'
        )
        for btn in comment_summary_btns:
            txt = (btn.inner_text() or "").lower()
            if "comment" in txt or "تعليق" in txt:
                box = btn.bounding_box()
                if box and box["height"] > 5:
                    btn.click()
                    time.sleep(1)
                    break
    except Exception:
        pass

    view_more_selectors = [
        'div[role="button"]:has-text("View more comments")',
        'div[role="button"]:has-text("View more")',
        'span:has-text("View more comments")',
        'div[role="button"]:has-text("عرض المزيد من التعليقات")',
        'div[role="button"]:has-text("عرض المزيد")',
        '[role="button"]:has-text("more comment")',
    ]
    reply_selectors = [
        'div[role="button"]:has-text("reply")',
        'div[role="button"]:has-text("replies")',
        'div[role="button"]:has-text("View 1 reply")',
        'div[role="button"]:has-text("تعليق")',
        'div[role="button"]:has-text("ردود")',
        'div[role="button"]:has-text("عرض الردود")',
        'span:has-text("replies")',
    ]
    see_more_selectors = [
        'div[role="button"]:has-text("See more")',
        'div[role="button"]:has-text("عرض المزيد")',
        'span:has-text("See more")',
    ]

    total_clicks = 0

    # Phase 1: View more comments
    for _ in range(max_expansions):
        clicked_any = False
        for sel in view_more_selectors:
            try:
                btns = post_element.query_selector_all(sel)
                for btn in btns[:2]:
                    box = btn.bounding_box()
                    if box and box["height"] > 5:
                        btn.click()
                        time.sleep(random.uniform(0.8, 1.4))
                        total_clicks += 1
                        clicked_any = True
            except Exception:
                pass
        if not clicked_any:
            break

    # Phase 2: View replies
    for sel in reply_selectors:
        try:
            btns = post_element.query_selector_all(sel)
            for btn in btns[:3]:
                box = btn.bounding_box()
                if box and box["height"] > 5:
                    btn.click()
                    time.sleep(random.uniform(0.5, 1.0))
                    total_clicks += 1
        except Exception:
            pass

    # Phase 3: See more in text
    for sel in see_more_selectors:
        try:
            btns = post_element.query_selector_all(sel)
            for btn in btns[:5]:
                box = btn.bounding_box()
                if box and box["height"] > 5:
                    btn.click()
                    time.sleep(0.3)
                    total_clicks += 1
        except Exception:
            pass

    return total_clicks


def _open_comment_section(page: Any, article: Any, log_cb: Callable | None = None) -> bool:
    """
    Attempt to open the comment input for *article* using multiple strategies.

    Returns True if a contenteditable input was found, False otherwise.
    """
    strategies = [
        # Strategy 1 — aria-label button
        lambda: article.query_selector('[aria-label*="Comment" i], [aria-label*="تعليق"]'),
        # Strategy 2 — span/div with text
        lambda: article.evaluate_handle(
            """el => {
                const nodes = el.querySelectorAll('span, div');
                for (const n of nodes) {
                    const txt = (n.textContent || '').trim().toLowerCase();
                    if (txt === 'comment' || txt === 'تعليق' || txt === 'comments') {
                        return n;
                    }
                }
                return null;
            }"""
        ),
        # Strategy 3 — JS click
        lambda: article.evaluate_handle(
            """el => {
                const btns = el.querySelectorAll('[role="button"]');
                for (const b of btns) {
                    const txt = (b.textContent || '').toLowerCase();
                    if (txt.includes('comment') || txt.includes('تعليق')) {
                        return b;
                    }
                }
                return null;
            }"""
        ),
    ]

    for idx, strategy in enumerate(strategies, start=1):
        try:
            handle = strategy()
            if handle and not _is_js_null(handle):
                _log(f"  → Comment button found via strategy {idx}", "debug", log_cb)
                try:
                    handle.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                handle.click(timeout=3000, force=True)
                human_sleep(1.0, 2.0)
                return True
        except Exception as exc:
            _log(f"  → Strategy {idx} failed: {exc}", "debug", log_cb)

    # Strategy 4 — page-wide fallback
    try:
        btn = page.query_selector('[aria-label*="Comment" i], [aria-label*="تعليق"]')
        if btn:
            btn.scroll_into_view_if_needed(timeout=3000)
            btn.click(timeout=3000, force=True)
            human_sleep(1.0, 2.0)
            return True
    except Exception:
        pass

    return False


def _is_js_null(handle: Any) -> bool:
    """Return True if a JSHandle represents null / undefined."""
    try:
        val = handle.json_value()
        return val is None
    except Exception:
        return True


def _find_comment_input(page: Any) -> Any | None:
    """Locate the comment text input on the page (contenteditable)."""
    selectors = [
        '[contenteditable="true"][aria-label*="comment" i]',
        '[contenteditable="true"][aria-label*="Write"]',
        '[contenteditable="true"][aria-label*="تعليق"]',
        '[contenteditable="true"][aria-label*="اكتب"]',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=5000, state="visible")
            if el:
                return el
        except Exception:
            continue
    return None


def _post_comment(page: Any, comment_text: str, log_cb: Callable | None = None) -> bool:
    """
    Type and submit a comment, then verify it appeared.

    Returns True on success.
    """
    inp = _find_comment_input(page)
    if not inp:
        _log("  ✗ Could not find comment input.", "warning", log_cb)
        return False

    try:
        inp.click(timeout=3000, force=True)
        human_sleep(0.3, 0.8)

        # Verify focus
        is_focused = page.evaluate(
            "document.activeElement && document.activeElement.getAttribute('contenteditable') === 'true'"
        )
        if not is_focused:
            _log("  ⚠ Input not focused, clicking again…", "debug", log_cb)
            inp.click(timeout=2000, force=True)
            human_sleep(0.3, 0.6)

        # Type with human-like delays
        for ch in comment_text:
            page.keyboard.type(ch, delay=random.randint(30, 120))
            # Occasional micro-pause
            if random.random() < 0.05:
                human_sleep(0.1, 0.4)

        human_sleep(0.5, 1.5)

        # Submit
        page.keyboard.press("Enter")
        _log("  ⏎ Pressed Enter to submit comment.", "debug", log_cb)

        # Wait and verify
        human_sleep(2.0, 3.5)

        snippet = comment_text[:40]
        found = page.evaluate(
            f"document.body.innerText.includes({json.dumps(snippet)})"
        )
        if found:
            _log("  ✓ Comment verified in DOM.", "info", log_cb)
            return True
        else:
            _log("  ⚠ Comment text not found in DOM after posting.", "warning", log_cb)
            # Take screenshot for debugging
            try:
                ss_dir = DATA_DIR / "screenshots"
                ss_dir.mkdir(exist_ok=True)
                ss_path = ss_dir / f"fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                page.screenshot(path=str(ss_path))
                _log(f"  📸 Screenshot saved: {ss_path}", "info", log_cb)
            except Exception:
                pass
            return False
    except Exception as exc:
        _log(f"  ✗ Error posting comment: {exc}", "error", log_cb)
        return False


# ---------------------------------------------------------------------------
# Commenting Engine — Main Run Loop
# ---------------------------------------------------------------------------


def run_commenter(
    groups: list[dict],
    keywords: list[dict],
    settings: dict,
    log_callback: Callable[[str, str], None],
) -> dict[str, Any]:
    """
    Main commenting run loop.

    For each active group × active keyword pair:
    1. Navigate to the group
    2. Scroll and collect posts
    3. Match posts against the keyword
    4. For matching posts, open comment section and post the response
    5. Log results and check for rate limits

    Returns a summary dict.
    """
    from playwright.sync_api import sync_playwright  # local import to avoid import at module level if not installed

    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "groups_processed": 0,
        "posts_scanned": 0,
        "posts_matched": 0,
        "comments_posted": 0,
        "comments_failed": 0,
        "errors": [],
    }

    min_delay = settings.get("comment_min_delay", 30)
    max_delay = settings.get("comment_max_delay", 90)
    max_posts = settings.get("max_posts_per_group", 10)

    active_groups = [g for g in groups if g.get("active", True)]
    active_keywords = [k for k in keywords if k.get("active", True)]

    if not active_groups:
        log_callback("No active groups configured.", "warning")
        return summary
    if not active_keywords:
        log_callback("No active keywords configured.", "warning")
        return summary

    run_state["groups_total"] = len(active_groups)

    log_callback(
        f"Starting run: {len(active_groups)} groups × {len(active_keywords)} keywords",
        "info",
    )

    with sync_playwright() as pw:
        browser = context = page = None
        try:
            browser, context, page = create_browser_context(pw)
            log_callback("Browser launched.", "info")

            for g_idx, group in enumerate(active_groups):
                if run_state["stop_requested"]:
                    log_callback("⛔ Stop requested — aborting run.", "warning")
                    break

                group_url = group.get("url", "")
                group_name = group.get("name", group_url)
                log_callback(f"\n{'='*60}", "info")
                log_callback(
                    f"[{g_idx+1}/{len(active_groups)}] Navigating to group: {group_name}",
                    "info",
                )
                run_state["progress"] = f"Group {g_idx+1}/{len(active_groups)}: {group_name}"

                try:
                    page.goto(group_url, wait_until="domcontentloaded", timeout=30000)
                    human_sleep(2.0, 4.0)
                except Exception as exc:
                    msg = f"Failed to load group {group_name}: {exc}"
                    log_callback(msg, "error")
                    summary["errors"].append(msg)
                    continue

                # Rate-limit check
                if _check_rate_limit(page):
                    log_callback("⚠ Rate limit detected! Cooling down 5-10 min…", "warning")
                    send_telegram(f"⚠ Rate limit detected on group: {group_name}")
                    cooldown = random.randint(300, 600)
                    log_callback(f"  Sleeping {cooldown}s…", "info")
                    time.sleep(cooldown)
                    continue

                # Scroll to load posts
                scroll_rounds = max(3, max_posts // 3)
                log_callback(f"  Scrolling {scroll_rounds} times to load posts…", "info")
                _random_scroll(page, times=scroll_rounds)

                # Collect post articles
                articles = page.query_selector_all(
                    'div[role="article"], div[data-ad-preview], div[class*="userContentWrapper"]'
                )
                if not articles:
                    # Fallback selector
                    articles = page.query_selector_all(
                        'div[data-pagelet*="FeedUnit"], div[class*="x1yztbdb"]'
                    )

                articles = articles[:max_posts]
                log_callback(f"  Found {len(articles)} posts (capped at {max_posts}).", "info")
                summary["posts_scanned"] += len(articles)
                run_state["posts_scanned"] += len(articles)

                for p_idx, article in enumerate(articles):
                    if run_state["stop_requested"]:
                        break

                    if settings.get("search_comments", True):
                        depth = settings.get("comment_depth", 3)
                        _expand_comments_deep(page, article, max_expansions=depth)

                    try:
                        # Scroll it into view to ensure lazy rendering
                        try:
                            page.evaluate("(el) => el.scrollIntoView({block:'center'})", article)
                            time.sleep(0.5)
                        except Exception:
                            pass

                        post_text = article.inner_text(timeout=5000)
                        
                        # Fallback to textContent to catch hidden/unrendered comments
                        try:
                            hidden_text = page.evaluate("(el) => el.textContent || ''", article)
                            post_text += " \n " + hidden_text
                        except Exception:
                            pass
                    except Exception:
                        try:
                            post_text = page.evaluate("(el) => el.textContent || ''", article)
                        except Exception:
                            post_text = ""

                    if not post_text.strip():
                        continue

                    # Match against each keyword
                    for kw_entry in active_keywords:
                        if run_state["stop_requested"]:
                            break

                        kw = kw_entry.get("keyword", "")
                        response = kw_entry.get("response", "")
                        if not kw or not response:
                            continue

                        if keyword_matches(post_text, kw):
                            summary["posts_matched"] += 1
                            run_state["posts_matched"] += 1
                            snippet = post_text[:80].replace("\n", " ")
                            log_callback(
                                f'  ★ Post {p_idx+1} matched keyword "{kw}": "{snippet}…"',
                                "info",
                            )

                            # Scroll article into view
                            try:
                                article.scroll_into_view_if_needed(timeout=3000)
                            except Exception:
                                pass
                            human_sleep(0.5, 1.5)

                            # Open comment section
                            if not _open_comment_section(page, article, log_callback):
                                log_callback("  ✗ Could not open comment section.", "warning")
                                summary["comments_failed"] += 1
                                run_state["comments_failed"] += 1
                                continue

                            # Post the comment
                            if _post_comment(page, response, log_callback):
                                summary["comments_posted"] += 1
                                run_state["comments_posted"] += 1
                                log_callback(f'  ✓ Comment posted: "{response[:50]}…"', "info")
                                send_telegram(
                                    f'✅ Comment posted in <b>{group_name}</b>\n'
                                    f'Keyword: {kw}\nResponse: {response[:100]}'
                                )
                            else:
                                summary["comments_failed"] += 1
                                run_state["comments_failed"] += 1

                            # Delay between comments
                            delay = human_delay(min_delay, max_delay)
                            log_callback(f"  ⏱ Waiting {delay:.0f}s before next action…", "info")
                            time.sleep(delay)

                            # Re-check rate limit
                            if _check_rate_limit(page):
                                log_callback("⚠ Rate limit detected after comment!", "warning")
                                cooldown = random.randint(300, 600)
                                log_callback(f"  Cooling down {cooldown}s…", "info")
                                time.sleep(cooldown)
                                break  # move to next group

                            # Continue to next keyword (allow multiple comments per post)

                    # Close any modals that might have opened during comment expansion/posting
                    try:
                        page.keyboard.press("Escape")
                        time.sleep(0.5)
                        page.keyboard.press("Escape")
                        time.sleep(0.5)
                        close_btn = page.query_selector('div[aria-label="Close" i], div[aria-label="إغلاق"]')
                        if close_btn:
                            close_btn.click(timeout=2000, force=True)
                            time.sleep(0.5)
                    except Exception:
                        pass

                summary["groups_processed"] += 1
                run_state["groups_done"] = g_idx + 1

                # Short break between groups
                if g_idx < len(active_groups) - 1 and not run_state["stop_requested"]:
                    between = human_delay(5, 15)
                    log_callback(f"  ⏱ Break between groups: {between:.0f}s", "info")
                    time.sleep(between)

        except Exception as exc:
            msg = f"Fatal error in commenter: {exc}"
            log_callback(msg, "error")
            summary["errors"].append(msg)
            logger.exception(msg)
        finally:
            try:
                if browser:
                    browser.close()
                    log_callback("Browser closed.", "info")
            except Exception:
                pass

    summary["ended_at"] = datetime.now(timezone.utc).isoformat()
    log_callback(
        f"\n{'='*60}\n"
        f"Run complete — {summary['comments_posted']} posted, "
        f"{summary['comments_failed']} failed, "
        f"{summary['posts_scanned']} scanned, "
        f"{summary['posts_matched']} matched.",
        "info",
    )

    # Telegram summary
    send_telegram(
        f"📊 <b>Run Complete</b>\n"
        f"Groups: {summary['groups_processed']}\n"
        f"Scanned: {summary['posts_scanned']}\n"
        f"Matched: {summary['posts_matched']}\n"
        f"Posted: {summary['comments_posted']}\n"
        f"Failed: {summary['comments_failed']}"
    )

    return summary


# ---------------------------------------------------------------------------
# Background Run Thread
# ---------------------------------------------------------------------------


def _run_thread() -> None:
    """Entry point for the background commenter thread."""
    global run_logs

    run_logs.clear()
    run_state.update(
        {
            "running": True,
            "stop_requested": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "groups_done": 0,
            "groups_total": 0,
            "comments_posted": 0,
            "comments_failed": 0,
            "posts_scanned": 0,
            "posts_matched": 0,
            "progress": "Initialising…",
        }
    )

    def log_cb(message: str, level: str = "info") -> None:
        entry = {"ts": datetime.now().isoformat(), "level": level, "msg": message}
        run_logs.append(entry)

    try:
        groups = load_json(GROUPS_FILE, [])
        keywords = load_json(KEYWORDS_FILE, [])
        settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)

        summary = run_commenter(groups, keywords, settings, log_cb)

        # Persist to history
        history = load_json(HISTORY_FILE, [])
        summary["id"] = uuid.uuid4().hex[:12]
        history.insert(0, summary)
        # Keep last 100 runs
        save_json(HISTORY_FILE, history[:100])

    except Exception as exc:
        log_cb(f"Run thread crashed: {exc}", "error")
        logger.exception("Run thread crashed")
    finally:
        run_state["running"] = False
        run_state["progress"] = "Idle"


# ---------------------------------------------------------------------------
# Flask API Routes — Keywords CRUD
# ---------------------------------------------------------------------------


@app.route("/api/keywords", methods=["GET"])
def api_keywords_list():
    """List all keywords."""
    data = load_json(KEYWORDS_FILE, [])
    return jsonify(data)


@app.route("/api/keywords", methods=["POST"])
def api_keywords_create():
    """Add a new keyword entry."""
    body = request.get_json(silent=True) or {}
    keyword = body.get("keyword", "").strip()
    response_text = body.get("response", "").strip()

    if not keyword:
        return jsonify({"error": "keyword is required"}), 400
    if not response_text:
        return jsonify({"error": "response is required"}), 400

    entry = {
        "id": uuid.uuid4().hex[:12],
        "keyword": keyword,
        "response": response_text,
        "active": body.get("active", True),
    }

    data = load_json(KEYWORDS_FILE, [])
    data.append(entry)
    save_json(KEYWORDS_FILE, data)
    logger.info("Keyword added: %s", keyword)
    return jsonify(entry), 201


@app.route("/api/keywords/<string:kid>", methods=["PUT"])
def api_keywords_update(kid: str):
    """Update an existing keyword by ID."""
    body = request.get_json(silent=True) or {}
    data = load_json(KEYWORDS_FILE, [])

    for item in data:
        if item.get("id") == kid:
            if "keyword" in body:
                item["keyword"] = body["keyword"].strip()
            if "response" in body:
                item["response"] = body["response"].strip()
            if "active" in body:
                item["active"] = bool(body["active"])
            save_json(KEYWORDS_FILE, data)
            return jsonify(item)

    return jsonify({"error": "Keyword not found"}), 404


@app.route("/api/keywords/<string:kid>", methods=["DELETE"])
def api_keywords_delete(kid: str):
    """Delete a keyword by ID."""
    data = load_json(KEYWORDS_FILE, [])
    new_data = [item for item in data if item.get("id") != kid]

    if len(new_data) == len(data):
        return jsonify({"error": "Keyword not found"}), 404

    save_json(KEYWORDS_FILE, new_data)
    logger.info("Keyword deleted: %s", kid)
    return jsonify({"deleted": kid})


@app.route("/api/keywords/<string:kid>/toggle", methods=["PATCH"])
def api_keywords_toggle(kid: str):
    """Toggle a keyword's active/inactive state."""
    data = load_json(KEYWORDS_FILE, [])

    for item in data:
        if item.get("id") == kid:
            item["active"] = not item.get("active", True)
            save_json(KEYWORDS_FILE, data)
            return jsonify(item)

    return jsonify({"error": "Keyword not found"}), 404


@app.route("/api/keywords/bulk", methods=["POST"])
def api_keywords_bulk():
    """Add multiple keywords sharing the same response.

    Body: {"keywords": ["kw1","kw2",...], "response": "shared response"}
    """
    body = request.get_json(silent=True) or {}
    keywords = body.get("keywords", [])
    response_text = body.get("response", "").strip()

    if not keywords:
        return jsonify({"error": "keywords list is required"}), 400
    if not response_text:
        return jsonify({"error": "response is required"}), 400

    data = load_json(KEYWORDS_FILE, [])
    created = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        entry = {
            "id": uuid.uuid4().hex[:12],
            "keyword": kw,
            "response": response_text,
            "active": True,
        }
        data.append(entry)
        created.append(entry)

    save_json(KEYWORDS_FILE, data)
    logger.info("Bulk keywords added: %d entries", len(created))
    return jsonify({"created": len(created), "entries": created}), 201


# ---------------------------------------------------------------------------
# Flask API Routes — Comment Templates
# ---------------------------------------------------------------------------

COMMENTS_FILE = DATA_DIR / "comments.json"


@app.route("/api/comments", methods=["GET"])
def api_comments_list():
    """List all comment templates."""
    data = load_json(COMMENTS_FILE, [])
    return jsonify(data)


@app.route("/api/comments", methods=["POST"])
def api_comments_save():
    """Save comment templates (full replacement)."""
    body = request.get_json(silent=True) or {}
    comments = body.get("comments", [])

    entries = []
    for item in comments:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = item.get("text", "").strip()
        else:
            continue
        if text:
            entries.append({"id": uuid.uuid4().hex[:12], "text": text})

    save_json(COMMENTS_FILE, entries)
    return jsonify({"saved": len(entries)})


# ---------------------------------------------------------------------------
# Flask API Routes — Groups CRUD
# ---------------------------------------------------------------------------


@app.route("/api/groups", methods=["GET"])
def api_groups_list():
    """List all groups."""
    data = load_json(GROUPS_FILE, [])
    return jsonify(data)


@app.route("/api/groups", methods=["POST"])
def api_groups_create():
    """Add a new group."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    url = body.get("url", "").strip()

    if not url:
        return jsonify({"error": "url is required"}), 400

    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name or url,
        "url": url,
        "active": body.get("active", True),
    }

    data = load_json(GROUPS_FILE, [])
    data.append(entry)
    save_json(GROUPS_FILE, data)
    logger.info("Group added: %s", name or url)
    return jsonify(entry), 201


@app.route("/api/groups/<string:gid>", methods=["PUT"])
def api_groups_update(gid: str):
    """Update a group by ID."""
    body = request.get_json(silent=True) or {}
    data = load_json(GROUPS_FILE, [])

    for item in data:
        if item.get("id") == gid:
            if "name" in body:
                item["name"] = body["name"].strip()
            if "url" in body:
                item["url"] = body["url"].strip()
            if "active" in body:
                item["active"] = bool(body["active"])
            save_json(GROUPS_FILE, data)
            return jsonify(item)

    return jsonify({"error": "Group not found"}), 404


@app.route("/api/groups/<string:gid>", methods=["DELETE"])
def api_groups_delete(gid: str):
    """Delete a group by ID."""
    data = load_json(GROUPS_FILE, [])
    new_data = [item for item in data if item.get("id") != gid]

    if len(new_data) == len(data):
        return jsonify({"error": "Group not found"}), 404

    save_json(GROUPS_FILE, new_data)
    logger.info("Group deleted: %s", gid)
    return jsonify({"deleted": gid})


@app.route("/api/groups/<string:gid>/toggle", methods=["PATCH"])
def api_groups_toggle(gid: str):
    """Toggle a group's active/inactive state."""
    data = load_json(GROUPS_FILE, [])

    for item in data:
        if item.get("id") == gid:
            item["active"] = not item.get("active", True)
            save_json(GROUPS_FILE, data)
            return jsonify(item)

    return jsonify({"error": "Group not found"}), 404


# ---------------------------------------------------------------------------
# Flask API Routes — Session Management
# ---------------------------------------------------------------------------


@app.route("/api/session/status", methods=["GET"])
def api_session_status():
    """Check if the session file exists and cookies are valid."""
    result = check_session_valid()
    return jsonify(result)


@app.route("/api/session/upload", methods=["POST"])
def api_session_upload():
    """Upload Facebook cookies as JSON to create a session (for headless/Docker environments)."""
    body = request.get_json(silent=True) or {}
    cookies = body.get("cookies", [])
    if not cookies:
        return jsonify({"error": "No cookies provided. Send {cookies: [{name, value, domain, ...}]}"}), 400

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


@app.route("/api/session/refresh", methods=["POST"])
def api_session_refresh():
    """Trigger the login.py script to refresh the Facebook session."""
    login_script = BASE_DIR / "login.py"
    if not login_script.exists():
        return jsonify({"error": "login.py not found", "path": str(login_script)}), 404

    try:
        result = subprocess.run(
            [sys.executable, str(login_script)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return jsonify(
            {
                "success": result.returncode == 0,
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else "",
                "returncode": result.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "login.py timed out after 120s"}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Flask API Routes — Run Management
# ---------------------------------------------------------------------------


@app.route("/api/run/start", methods=["POST"])
def api_run_start():
    """Start a commenting run in a background thread."""
    with _run_lock:
        if run_state["running"]:
            return jsonify({"error": "A run is already in progress"}), 409

        # Validate session first
        session_info = check_session_valid()
        if not session_info.get("valid"):
            return (
                jsonify(
                    {
                        "error": "Session is not valid. Please refresh your session first.",
                        "session": session_info,
                    }
                ),
                400,
            )

        thread = threading.Thread(target=_run_thread, daemon=True, name="commenter-run")
        run_state["thread"] = thread
        thread.start()

    return jsonify({"status": "started"})


@app.route("/api/run/stop", methods=["POST"])
def api_run_stop():
    """Request the current run to stop."""
    if not run_state["running"]:
        return jsonify({"error": "No run is currently active"}), 400

    run_state["stop_requested"] = True
    logger.info("Stop requested by user.")
    return jsonify({"status": "stop_requested"})


@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    """Get current run status and progress."""
    return jsonify(
        {
            "running": run_state["running"],
            "stop_requested": run_state["stop_requested"],
            "started_at": run_state["started_at"],
            "progress": run_state["progress"],
            "groups_done": run_state["groups_done"],
            "groups_total": run_state["groups_total"],
            "comments_posted": run_state["comments_posted"],
            "comments_failed": run_state["comments_failed"],
            "posts_scanned": run_state["posts_scanned"],
            "posts_matched": run_state["posts_matched"],
        }
    )


@app.route("/api/run/history", methods=["GET"])
def api_run_history():
    """Get past run results."""
    history = load_json(HISTORY_FILE, [])
    return jsonify(history)


@app.route("/api/run/stream")
def api_run_stream():
    """SSE endpoint for real-time log streaming during a run."""

    def generate():
        idx = 0
        heartbeat = 0
        while True:
            while idx < len(run_logs):
                entry = run_logs[idx]
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                idx += 1
            # Send a heartbeat comment every ~15s to keep the connection alive
            heartbeat += 1
            if heartbeat >= 30:
                yield ": heartbeat\n\n"
                heartbeat = 0
            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Flask API Routes — Settings
# ---------------------------------------------------------------------------


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Get current application settings."""
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    # Merge with defaults so new keys are always present
    merged = {**DEFAULT_SETTINGS, **settings}
    return jsonify(merged)


@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    """Update application settings (partial or full)."""
    body = request.get_json(silent=True) or {}
    settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    settings.update(body)
    save_json(SETTINGS_FILE, settings)
    logger.info("Settings updated.")
    return jsonify(settings)


@app.route("/api/schedule/status", methods=["GET"])
def api_schedule_status():
    """Return current schedule configuration and next run info."""
    settings  = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    state     = load_json(SCHEDULER_STATE_FILE, {"last_run_time": 0.0})

    enabled    = settings.get("auto_schedule_enabled", False)
    raw_times  = settings.get("schedule_times", "").strip()
    interval_h = float(settings.get("auto_schedule_interval_hours", 6.0))
    last_run   = state.get("last_run_time", 0.0)

    burst_enabled = settings.get("schedule_burst_enabled", False)
    burst_count   = int(settings.get("schedule_burst_count", 4))
    burst_interval_min = float(settings.get("schedule_burst_interval_minutes", 120))
    burst_start   = settings.get("schedule_burst_start_time", "09:00").strip() or "09:00"

    next_runs: list[str] = []
    mode = "burst" if burst_enabled else ("times" if raw_times else "interval")
    remaining = None

    if enabled:
        now_dt = datetime.now()
        if mode == "burst":
            slots = _compute_burst_slots(burst_start, burst_count, burst_interval_min)
            today_key = now_dt.strftime("%Y-%m-%d")
            triggered = set(state.get("burst_triggered_today", []))
            if state.get("burst_day_key") != today_key:
                triggered = set()
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
        "enabled":        enabled,
        "mode":           mode,
        "times":          raw_times,
        "interval_hours": interval_h,
        "burst_enabled": burst_enabled,
        "burst_count": burst_count,
        "burst_interval_minutes": burst_interval_min,
        "burst_start_time": burst_start,
        "burst_remaining": remaining,
        "last_run":       datetime.fromtimestamp(last_run).strftime("%Y-%m-%d %H:%M") if last_run else None,
        "next_runs":      next_runs,
        "running":        run_state["running"],
    })



# ---------------------------------------------------------------------------
# Flask Routes — Dashboard
# ---------------------------------------------------------------------------


@app.route("/")
def dashboard():
    """Serve the main dashboard page."""
    try:
        return render_template("dashboard.html")
    except Exception:
        return (
            "<h1>FB Commenter V2</h1>"
            "<p>Dashboard template not found. Place <code>dashboard.html</code> "
            "in the <code>templates/</code> directory.</p>"
            "<p>API is running — try <a href='/api/run/status'>/api/run/status</a></p>"
        ), 200


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
    """Compute daily burst time slots as HH:MM strings."""
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

    while True:
        try:
            settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
            if settings.get("auto_schedule_enabled"):
                now_ts = time.time()
                now_dt = datetime.fromtimestamp(now_ts)
                today  = now_dt.timetuple().tm_yday

                # Reset daily trigger set on new calendar day
                if today != _scheduler_loop.__dict__.setdefault("_day", -1):
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
                        interval_hours = float(settings.get("auto_schedule_interval_hours", 6.0))
                        if now_ts - state.get("last_run_time", 0.0) >= interval_hours * 3600:
                            should_run = True

                if should_run:
                    with _run_lock:
                        if not run_state["running"]:
                            session_info = check_session_valid()
                            if session_info.get("valid"):
                                logger.info("Scheduler: Triggering automatic run.")
                                state["last_run_time"] = now_ts
                                save_json(SCHEDULER_STATE_FILE, state)
                                thread = threading.Thread(target=_run_thread, daemon=True, name="scheduler-run")
                                run_state["thread"] = thread
                                thread.start()
                            else:
                                logger.warning("Scheduler: Session invalid — skipping run.")
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        time.sleep(30)   # 30 s tick for accurate time-of-day matching

# Start scheduler thread
threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler-loop").start()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser

    logger.info("FB Commenter V2 starting on http://localhost:5001")
    # webbrowser.open("http://localhost:5001")
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", 5001)))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

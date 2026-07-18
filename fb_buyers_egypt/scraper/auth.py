"""
Facebook Authentication with Human-like Behavior & Easy Session Refresh
========================================================================
"""

import os
import time
import json
import random
import logging
import subprocess
import shutil
from datetime import datetime, timezone
from playwright.sync_api import Page, sync_playwright
from scraper.human import (
    human_type, move_mouse_to, move_mouse_to_element,
    natural_delay, random_idle,
)

logger = logging.getLogger(__name__)


class FacebookAuth:

    def __init__(self, page: Page, email: str,
                 password: str, session_file: str):
        self.page         = page
        self.email        = email
        self.password     = password
        self.session_file = session_file

    # ── Public API ────────────────────────────────────────────────────────

    def ensure_logged_in(self) -> bool:
        """Check session, login if needed. Returns True on success."""
        if self._session_is_valid():
            logger.info("✅ Session active — already logged in.")
            return True
        logger.info("🔄 Session expired or not found — logging in ...")
        return self._login()

    def check_session_health(self) -> dict:
        """
        Returns session status dict for the team:
        {
            "valid": bool,
            "age": str,
            "email": str,
            "checked_at": str,
        }
        """
        valid = self._session_is_valid()
        age = self._get_session_age()
        return {
            "valid":      valid,
            "age":        age,
            "email":      self.email[:3] + "***" if self.email else "",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def refresh_session(self) -> bool:
        """
        Force re-login and save a fresh session.
        Call this when the team notices stale data.
        """
        logger.info("🔄 Force-refreshing session ...")
        # Delete old session
        for f in [self.session_file, self.session_file + ".meta"]:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"  🗑️  Removed old: {f}")
        return self._login()

    # ── Session validation ────────────────────────────────────────────────

    def _session_is_valid(self) -> bool:
        """Navigate to Facebook and check if we're logged in."""
        try:
            self.page.goto("https://www.facebook.com",
                           wait_until="domcontentloaded", timeout=20_000)
            time.sleep(random.uniform(2, 4))

            # Check URL
            if "login" in self.page.url or "checkpoint" in self.page.url:
                return False

            # Check for logged-in indicators
            for sel in ['[aria-label="Your profile"]',
                        '[aria-label="ملفك الشخصي"]',
                        '[aria-label="Account"]',
                        '[aria-label="الحساب"]',
                        'div[role="navigation"]']:
                try:
                    if self.page.query_selector(sel):
                        return True
                except Exception:
                    pass

            # Fallback: if not on login page, likely logged in
            return "facebook.com" in self.page.url and "login" not in self.page.url

        except Exception as e:
            logger.warning(f"Session check error: {e}")
            return False

    def _get_session_age(self) -> str:
        meta_path = self.session_file + ".meta"
        try:
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                saved = datetime.fromisoformat(meta["saved_at"])
                age = datetime.now(timezone.utc) - saved
                hours = age.total_seconds() / 3600
                if hours < 1:
                    return f"{int(age.total_seconds() / 60)}m"
                return f"{hours:.1f}h"
        except Exception:
            pass
        return "unknown"

    # ── Login flow ────────────────────────────────────────────────────────

    def _login(self) -> bool:
        logger.error("❌ Session is invalid. Please run 'python main.py --login' to log in manually.")
        return False

    def _dismiss_cookies(self):
        for sel in ['[data-cookiebanner="accept_button"]',
                    'button[title="Allow all cookies"]',
                    'button[title="السماح بجميع ملفات تعريف الارتباط"]']:
            try:
                b = self.page.query_selector(sel)
                if b:
                    b.click()
                    time.sleep(random.uniform(0.5, 1))
                    break
            except Exception:
                pass

    def _save_session(self):
        """Save session + metadata."""
        os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
        self.page.context.storage_state(path=self.session_file)

        meta = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "email":    self.email[:3] + "***",
        }
        with open(self.session_file + ".meta", "w") as f:
            json.dump(meta, f, indent=2)

        logger.info(f"  💾 Session saved → {self.session_file}")

# ─────────────────────────────────────────────────────────────────────────────
#  Subprocess Chrome Login
# ─────────────────────────────────────────────────────────────────────────────

def find_chrome() -> str | None:
    """Find Chrome executable on Windows."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def login_and_save_session(session_file: str, wait_callback=None) -> bool:
    """
    Open Chrome → user logs in → extract cookies → save to session_file.
    Returns True on success.
    """
    chrome_exe = find_chrome()
    if not chrome_exe:
        print("❌ Chrome not found! Please install Chrome or update the path.")
        return False

    print(f"✅ Chrome found: {chrome_exe}")

    temp_profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_chrome_temp_profile")
    os.makedirs(temp_profile, exist_ok=True)

    print("\n" + "=" * 60)
    print("  STEP 1 — Log into Facebook")
    print("=" * 60)
    print("  A Chrome window will open. Please:")
    print("    1. Log in with your email and password")
    print("    2. Complete any verification (phone code, puzzle, etc.)")
    print("    3. Wait until your Facebook FEED is fully loaded")
    print("    4. Come back here and press ENTER")
    print("=" * 60 + "\n")

    chrome_cmd = [
        chrome_exe,
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.facebook.com/login",
    ]

    print("→ Launching Chrome...")
    proc = subprocess.Popen(chrome_cmd)
    
    if wait_callback:
        print("\n⏳ Waiting for API signal (user clicking 'Finished')...\n")
        wait_callback()
    else:
        input("\n⏳ Press ENTER here AFTER you see your Facebook feed...\n")

    print("→ Closing Chrome to release profile lock...")
    proc.terminate()
    time.sleep(3)

    print("\n" + "=" * 60)
    print("  STEP 2 — Extracting session cookies")
    print("=" * 60)

    success = False

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=temp_profile,
            headless=False,
            executable_path=chrome_exe,
            slow_mo=200,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        print("→ Loading Facebook to verify login...")
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        time.sleep(4)

        current_url = page.url
        
        login_form = page.query_selector('input[name="email"]')
        if login_form or "login" in current_url:
            print("\n⚠️  Still not logged in. Waiting up to 3 minutes...")
            for i in range(180):
                time.sleep(1)
                url = page.url
                lf = page.query_selector('input[name="email"]')
                if "login" not in url and not lf:
                    print(f"\n✅ Login detected at: {url}")
                    time.sleep(5)
                    break

        all_cookies = browser.cookies([
            "https://www.facebook.com",
            "https://web.facebook.com",
        ])

        fb_cookies = [c for c in all_cookies if "facebook" in c.get("domain", "")]
        print(f"  Facebook cookies found: {len(fb_cookies)}")

        storage_state = {
            "cookies": all_cookies,
            "origins": [],
        }

        os.makedirs(os.path.dirname(os.path.abspath(session_file)), exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, ensure_ascii=False, indent=2)

        meta = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "email": "manual_login"
        }
        with open(session_file + ".meta", "w") as f:
            json.dump(meta, f, indent=2)

        key_cookies = ["c_user", "xs", "datr", "fr"]
        found = [c["name"] for c in all_cookies if c["name"] in key_cookies]
        if all(k in found for k in key_cookies):
            print("  ✅ All key cookies present!")
            success = True
        else:
            print("  ❌ Missing key cookies. Session may not work.")

        browser.close()

    print("\n→ Cleaning up temp profile...")
    try:
        shutil.rmtree(temp_profile, ignore_errors=True)
        print("  ✅ Cleaned up")
    except Exception as e:
        print(f"  ⚠️  Could not clean up: {e} (safe to ignore)")

    if success:
        print("\n✅ SESSION SAVED successfully!\n")
    return success

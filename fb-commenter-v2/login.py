"""
Facebook Session Login Script
==============================
Opens a real Chrome browser for you to log into Facebook,
then saves the session cookies for the commenter to use.

Usage:
  python login.py
  python login.py --session-file path/to/session.json
"""

import os
import sys
import json
import time
import subprocess
import shutil
import argparse

# ─────────────────────────────────────────────────────────────────────────────
#  Find Chrome
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


# ─────────────────────────────────────────────────────────────────────────────
#  Login flow
# ─────────────────────────────────────────────────────────────────────────────

def login_and_save_session(session_file: str) -> bool:
    """
    Open Chrome → user logs in → extract cookies → save to session_file.
    Returns True on success.
    """
    chrome_exe = find_chrome()
    if not chrome_exe:
        print("❌ Chrome not found! Please install Chrome or update the path.")
        return False

    print(f"✅ Chrome found: {chrome_exe}")

    # Temp profile for clean login
    temp_profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_chrome_temp_profile")
    os.makedirs(temp_profile, exist_ok=True)

    print()
    print("=" * 60)
    print("  STEP 1 — Log into Facebook")
    print("=" * 60)
    print()
    print("  A Chrome window will open. Please:")
    print("    1. Go to facebook.com/login (it should auto-navigate)")
    print("    2. Log in with your email and password")
    print("    3. Complete any verification (phone code, puzzle, etc.)")
    print("    4. Wait until your Facebook FEED is fully loaded")
    print("    5. Come back here and press ENTER")
    print()
    print("=" * 60)

    # Launch Chrome
    chrome_cmd = [
        chrome_exe,
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.facebook.com/login",
    ]

    print("\n→ Launching Chrome...")
    proc = subprocess.Popen(chrome_cmd)
    input("\n⏳ Press ENTER here AFTER you see your Facebook feed...\n")

    print("→ Closing Chrome to release profile lock...")
    proc.terminate()
    time.sleep(3)

    # ── Extract cookies with Playwright ───────────────────────────────────────
    print()
    print("=" * 60)
    print("  STEP 2 — Extracting session cookies")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

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
        print(f"  Current URL: {current_url}")

        # Check if still on login page
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
                if i % 15 == 0:
                    print(f"  Waiting... {180 - i}s remaining")

        # ── Save cookies ──────────────────────────────────────────────────────
        all_cookies = browser.cookies([
            "https://www.facebook.com",
            "https://web.facebook.com",
        ])

        fb_cookies = [c for c in all_cookies if "facebook" in c.get("domain", "")]

        print(f"\n  Total cookies found : {len(all_cookies)}")
        print(f"  Facebook cookies    : {len(fb_cookies)}")

        # Save as Playwright storage_state format
        storage_state = {
            "cookies": all_cookies,
            "origins": [],
        }

        os.makedirs(os.path.dirname(os.path.abspath(session_file)), exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(storage_state, f, ensure_ascii=False, indent=2)

        # Verify key cookies
        key_cookies = ["c_user", "xs", "datr", "fr"]
        found = [c["name"] for c in all_cookies if c["name"] in key_cookies]
        missing = [k for k in key_cookies if k not in found]

        print(f"\n  Key cookies found: {found}")

        if missing:
            print(f"  ❌ Missing: {missing}")
            print("     Session may not work — try logging in again")
        else:
            print("  ✅ All key cookies present!")
            success = True

        browser.close()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    print("\n→ Cleaning up temp profile...")
    try:
        shutil.rmtree(temp_profile, ignore_errors=True)
        print("  ✅ Cleaned up")
    except Exception as e:
        print(f"  ⚠️  Could not clean up: {e} (safe to ignore)")

    if success:
        print()
        print("=" * 60)
        print(f"  ✅ SESSION SAVED to: {session_file}")
        print("=" * 60)
        print()
        print("  Now run:  python app.py")
        print("  Then open http://localhost:5000 in your browser")
        print()
    else:
        print()
        print("  ❌ Session save may have failed. Try again.")
        print()

    return success


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Facebook Login — Save Session")
    parser.add_argument(
        "--session-file",
        default="data/fb_session.json",
        help="Path to save the session file (default: data/fb_session.json)",
    )
    args = parser.parse_args()

    ok = login_and_save_session(args.session_file)
    sys.exit(0 if ok else 1)

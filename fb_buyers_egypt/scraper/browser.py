"""
Browser Manager with Enhanced Stealth & Session Support
=======================================================
"""

import os
import time
import json
import random
import logging
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)


class BrowserManager:

    _VIEWPORTS = [
        {"width": 1366, "height": 768},
        {"width": 1440, "height": 900},
        {"width": 1536, "height": 864},
        {"width": 1920, "height": 1080},
        {"width": 1600, "height": 900},
    ]

    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    ]

    def __init__(self, headless: bool = False, session_file: str = None):
        self.headless     = headless
        self.session_file = session_file
        self._pw          = None
        self._browser     = None
        self._context: BrowserContext = None
        self.page: Page   = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> Page:
        logger.info("🌐 Starting browser ...")
        self._pw = sync_playwright().start()

        vp = random.choice(self._VIEWPORTS)
        ua = random.choice(self._USER_AGENTS)

        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-background-networking",
                "--disable-extensions",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
            ],
        )

        ctx_kwargs = dict(
            viewport=vp,
            user_agent=ua,
            locale="ar-EG",
            timezone_id="Africa/Cairo",
            geolocation={"longitude": 31.2357, "latitude": 30.0444},
            permissions=["geolocation"],
            color_scheme="light",
            reduced_motion="no-preference",
        )

        # Load saved session if exists
        if self.session_file and os.path.exists(self.session_file):
            try:
                ctx_kwargs["storage_state"] = self.session_file
                logger.info(f"  📂 Loaded session: {self.session_file}")
                logger.info(f"  📅 Session age: {self.get_session_age()}")
            except Exception as e:
                logger.warning(f"  ⚠️ Could not load session: {e}")

        self._context = self._browser.new_context(**ctx_kwargs)
        self._inject_stealth()
        self.page = self._context.new_page()
        self.page.set_default_timeout(30_000)
        logger.info(f"  ✅ Browser ready | headless={self.headless} | viewport={vp['width']}x{vp['height']}")
        return self.page

    def save_session(self, path: str = None):
        """Save current session (cookies + localStorage) to JSON file."""
        path = path or self.session_file
        if not path:
            logger.warning("No session path specified")
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._context.storage_state(path=path)

        # Save metadata alongside
        meta_path = path + ".meta"
        meta = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "user_agent": self._context._options.get("user_agent", "") if hasattr(self._context, '_options') else "",
        }
        try:
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass

        logger.info(f"  💾 Session saved → {path}")

    def get_session_age(self) -> str:
        """Return human-readable session age."""
        if not self.session_file:
            return "no session file"
        meta_path = self.session_file + ".meta"
        try:
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                saved = datetime.fromisoformat(meta["saved_at"])
                age = datetime.now(timezone.utc) - saved
                hours = age.total_seconds() / 3600
                if hours < 1:
                    return f"{int(age.total_seconds() / 60)} minutes"
                elif hours < 24:
                    return f"{hours:.1f} hours"
                else:
                    return f"{hours / 24:.1f} days"
            elif os.path.exists(self.session_file):
                mtime = os.path.getmtime(self.session_file)
                age_h = (time.time() - mtime) / 3600
                return f"~{age_h:.1f} hours (from file mtime)"
        except Exception:
            pass
        return "unknown"

    def stop(self):
        try:
            if self._browser:  self._browser.close()
            if self._pw:       self._pw.stop()
            logger.info("  🛑 Browser stopped")
        except Exception as e:
            logger.warning(f"Browser stop error: {e}")

    # ── Stealth ───────────────────────────────────────────────────────────

    def _inject_stealth(self):
        """Inject anti-detection scripts into every page."""
        self._context.add_init_script("""
            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Fake plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const arr = [1,2,3,4,5];
                    arr.item = (i) => arr[i];
                    arr.namedItem = () => null;
                    arr.refresh = () => {};
                    return arr;
                }
            });

            // Languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ar-EG', 'ar', 'en-US', 'en']
            });

            // Chrome object
            window.chrome = {
                runtime: {
                    connect: () => {},
                    sendMessage: () => {},
                    onMessage: { addListener: () => {} },
                },
                loadTimes: function() { return {}; },
                csi: function() { return {}; },
                app: { isInstalled: false },
            };

            // Permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (params) => {
                if (params.name === 'notifications') {
                    return Promise.resolve({state: 'denied'});
                }
                return originalQuery(params);
            };

            // WebGL vendor/renderer
            const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(param) {
                if (param === 37445) return 'Intel Inc.';
                if (param === 37446) return 'Intel Iris OpenGL Engine';
                return getParameterOrig.call(this, param);
            };

            // Canvas fingerprint noise
            const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type) {
                const ctx = this.getContext('2d');
                if (ctx) {
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 100) {
                        imageData.data[i] = imageData.data[i] ^ 1;
                    }
                    ctx.putImageData(imageData, 0, 0);
                }
                return origToDataURL.apply(this, arguments);
            };

            // Track mouse position for Bezier moves
            window._mouseX = 0;
            window._mouseY = 0;
            document.addEventListener('mousemove', (e) => {
                window._mouseX = e.clientX;
                window._mouseY = e.clientY;
            });
        """)

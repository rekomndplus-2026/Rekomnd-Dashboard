import os
from dotenv import load_dotenv

# Project root = parent directory of this settings.py file
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from project root so it works from any working directory
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


class Config:
    FB_EMAIL    = os.getenv("FB_EMAIL", "")
    FB_PASSWORD = os.getenv("FB_PASSWORD", "")

    HEADLESS         = os.getenv("HEADLESS", "true").lower() == "true"
    DELAY_MIN        = float(os.getenv("DELAY_MIN", "3"))
    DELAY_MAX        = float(os.getenv("DELAY_MAX", "8"))
    SCROLL_PAUSE_MIN = 2.0
    SCROLL_PAUSE_MAX = 4.5
    MAX_SCROLLS      = int(os.getenv("MAX_SCROLLS", "40"))
    NO_NEW_THRESHOLD = 4
    PAGE_LOAD_TIMEOUT = 30_000

    MAX_POSTS_PER_SESSION  = 500
    MAX_GROUPS_PER_SESSION = 15

    SESSION_INTERVAL_HOURS = int(os.getenv("SESSION_INTERVAL_HOURS", "4"))
    SESSION_FILE = os.path.join(_PROJECT_ROOT, "config", "session.json")

    DB_URL     = os.getenv("DB_URL", f"sqlite:///{os.path.join(_PROJECT_ROOT, 'egypt_buyers.db')}")
    LOG_FILE   = os.path.join(_PROJECT_ROOT, "logs", "buyers_scraper.log")
    LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
    EXPORT_DIR = os.path.join(_PROJECT_ROOT, "exports")

    @classmethod
    def validate(cls):
        missing = []
        if not cls.FB_EMAIL:    missing.append("FB_EMAIL")
        if not cls.FB_PASSWORD: missing.append("FB_PASSWORD")
        if missing:
            raise EnvironmentError(
                f"Missing in .env: {', '.join(missing)}"
            )

#!/usr/bin/env python3
"""
==========================================
  Egypt Real Estate — Buyer Lead Scraper
==========================================

Usage:
  python main.py --login             Login & save session
  python main.py --check-session     Check if session is valid
  python main.py --refresh-session   Force re-login
  python main.py --scrape            Scrape all enabled groups
  python main.py --scrape-group URL  Scrape a single group
  python main.py --scrape-post URL   Scrape comments from a single post
  python main.py --export            Export leads to Excel
  python main.py --dashboard         Launch Streamlit dashboard
  python main.py --stats             Show quick stats
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime

# Enforce UTF-8 for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# ── Setup logging ─────────────────────────────────────────────────────────

def setup_logging(log_file: str = "logs/buyers_scraper.log",
                  level: str = "INFO"):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Console handler with colors
    try:
        from colorlog import ColoredFormatter
        console_fmt = ColoredFormatter(
            "%(log_color)s%(asctime)s %(levelname)-8s%(reset)s %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG":    "cyan",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "red,bg_white",
            },
        )
    except ImportError:
        console_fmt = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
        )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_fmt)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = []
    root.addHandler(console_handler)
    root.addHandler(file_handler)


logger = logging.getLogger(__name__)


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_login(config):
    """Interactive login — saves session for the team."""
    from scraper.auth import login_and_save_session

    print("\n" + "=" * 55)
    print("  🔐 Facebook Manual Login — Session Saver")
    print("=" * 55)
    print(f"  Session file: {config.SESSION_FILE}")
    print("=" * 55 + "\n")

    ok = login_and_save_session(config.SESSION_FILE)
    if ok:
        print("\n   Next: python main.py --scrape\n")


def cmd_check_session(config):
    """Check session health without opening browser."""
    print("\n" + "=" * 55)
    print("  🔍 Session Health Check")
    print("=" * 55)

    session_file = config.SESSION_FILE
    meta_file = session_file + ".meta"

    if not os.path.exists(session_file):
        print("\n  ❌ No session file found!")
        print(f"     Expected: {os.path.abspath(session_file)}")
        print("     Run: python main.py --login")
        print()
        return

    print(f"\n  📂 Session file: {os.path.abspath(session_file)}")
    size = os.path.getsize(session_file)
    print(f"  📦 Size: {size:,} bytes")

    if os.path.exists(meta_file):
        with open(meta_file) as f:
            meta = json.load(f)
        print(f"  📅 Saved at: {meta.get('saved_at', 'unknown')}")
        print(f"  📧 Account: {meta.get('email', 'unknown')}")

        # Calculate age
        from datetime import timezone
        try:
            saved = datetime.fromisoformat(meta["saved_at"])
            age = datetime.now(timezone.utc) - saved
            hours = age.total_seconds() / 3600
            if hours < 24:
                print(f"  ⏱️  Age: {hours:.1f} hours ✅")
            elif hours < 72:
                print(f"  ⏱️  Age: {hours:.1f} hours ⚠️  (consider refreshing)")
            else:
                print(f"  ⏱️  Age: {hours/24:.1f} days ❌ (stale — refresh now!)")
        except Exception:
            pass
    else:
        print("  ⚠️  No metadata file — age unknown")

    # Validate by opening browser briefly
    print("\n  🌐 Validating session online ...")
    from scraper.browser import BrowserManager
    from scraper.auth import FacebookAuth

    browser = BrowserManager(
        headless=True,
        session_file=config.SESSION_FILE,
    )
    try:
        page = browser.start()
        auth = FacebookAuth(page, config.FB_EMAIL,
                           config.FB_PASSWORD, config.SESSION_FILE)
        health = auth.check_session_health()

        if health["valid"]:
            print("  ✅ Session is VALID — ready to scrape!")
        else:
            print("  ❌ Session is EXPIRED — run: python main.py --refresh-session")
    except Exception as e:
        print(f"  ⚠️  Could not validate: {e}")
    finally:
        browser.stop()

    print()


def cmd_refresh_session(config):
    """Force re-login and save new session."""
    from scraper.browser import BrowserManager
    from scraper.auth import FacebookAuth

    print("\n🔄 Force-refreshing session ...\n")

    # Delete old session
    for f in [config.SESSION_FILE, config.SESSION_FILE + ".meta"]:
        if os.path.exists(f):
            os.remove(f)
            print(f"  🗑️  Removed: {f}")

    browser = BrowserManager(
        headless=False,
        session_file=None,  # Don't load old session
    )
    try:
        page = browser.start()
        auth = FacebookAuth(page, config.FB_EMAIL,
                           config.FB_PASSWORD, config.SESSION_FILE)

        if auth.refresh_session():
            browser.save_session(config.SESSION_FILE)
            print("\n✅ Fresh session saved!")
        else:
            print("\n❌ Refresh failed.")
    finally:
        browser.stop()


def cmd_scrape(config, group_url: str = None):
    """Run the scraper."""
    from scraper.browser import BrowserManager
    from scraper.auth import FacebookAuth
    from scraper.group_scraper import GroupScraper
    from scraper.human import session_warmup, between_groups_delay
    from database.db import DatabaseManager

    print("\n" + "=" * 55)
    print("  🚀 Egypt RE Buyer Scraper")
    print("=" * 55)

    db = DatabaseManager(config.DB_URL)

    # Determine groups to scrape
    if group_url:
        groups = [{"name": "Custom", "url": group_url,
                   "region": "custom", "enabled": True}]
    else:
        import json
        groups_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "groups.json")
        try:
            with open(groups_path, "r", encoding="utf-8") as f:
                all_groups = json.load(f)
            active_groups = [g for g in all_groups if g.get("enabled", True)]
            groups = active_groups[:config.MAX_GROUPS_PER_SESSION]
        except Exception as e:
            logger.error(f"Failed to load groups.json: {e}")
            return

    print(f"  Groups: {len(groups)}")
    print(f"  Max scrolls/group: {config.MAX_SCROLLS}")
    print("=" * 55 + "\n")

    browser = BrowserManager(
        headless=config.HEADLESS,
        session_file=config.SESSION_FILE,
    )

    try:
        page = browser.start()

        # Login check
        auth = FacebookAuth(page, config.FB_EMAIL,
                           config.FB_PASSWORD, config.SESSION_FILE)
        if not auth.ensure_logged_in():
            print("❌ Not logged in. Run: python main.py --login")
            return

        # Save session after successful login check
        browser.save_session(config.SESSION_FILE)

        # Warmup — act natural before scraping
        session_warmup(page)

        # Scrape groups
        scraper = GroupScraper(page, config)
        total_leads = []

        for i, group in enumerate(groups, 1):
            logger.info(f"\n{'═' * 55}")
            logger.info(f"  Group {i}/{len(groups)}")
            logger.info(f"{'═' * 55}")

            leads = scraper.scrape_group(group)

            if leads:
                stats = db.save_leads(leads)
                total_leads.extend(leads)
                logger.info(f"  📊 Batch saved: {stats}")

            # Pause between groups
            if i < len(groups):
                between_groups_delay()

        # Final stats
        print("\n" + "=" * 55)
        print(f"  ✅ SCRAPE COMPLETE")
        print(f"  Total leads found: {len(total_leads)}")
        print(f"  DB stats: {db.get_stats()}")
        print("=" * 55 + "\n")

        # Auto-export
        os.makedirs(config.EXPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        export_path = os.path.join(config.EXPORT_DIR, f"leads_{ts}.xlsx")
        db.export_to_excel(export_path)
        print(f"  📊 Auto-exported to: {export_path}\n")

    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"Scrape error: {e}", exc_info=True)
    finally:
        try:
            browser.save_session(config.SESSION_FILE)
        except Exception as e:
            logger.debug(f"Could not save session on exit: {e}")
        browser.stop()

def cmd_scrape_post(config, post_url: str):
    """Run the post scraper."""
    from scraper.browser import BrowserManager
    from scraper.auth import FacebookAuth
    from scraper.post_scraper import PostScraper
    from scraper.human import session_warmup
    from database.db import DatabaseManager

    logger.info("\n" + "=" * 55)
    logger.info("  🚀 Egypt RE Buyer Scraper (Post Scrape)")
    logger.info("=" * 55)
    logger.info(f"  Post URL: {post_url}")
    logger.info("=" * 55 + "\n")

    db = DatabaseManager(config.DB_URL)

    browser = BrowserManager(
        headless=config.HEADLESS,
        session_file=config.SESSION_FILE,
    )

    try:
        page = browser.start()

        # Login check
        auth = FacebookAuth(page, config.FB_EMAIL,
                           config.FB_PASSWORD, config.SESSION_FILE)
        if not auth.ensure_logged_in():
            print("❌ Not logged in. Run: python main.py --login")
            return

        # Save session after successful login check
        browser.save_session(config.SESSION_FILE)

        # Warmup — act natural before scraping
        session_warmup(page)

        # Scrape post
        scraper = PostScraper(page, config)
        leads = scraper.scrape_post(post_url)

        if leads:
            stats = db.save_leads(leads)
            logger.info(f"  📊 Batch saved: {stats}")

        # Final stats
        logger.info("\n" + "=" * 55)
        logger.info(f"  ✅ POST SCRAPE COMPLETE")
        logger.info(f"  Total leads found: {len(leads)}")
        logger.info(f"  DB stats: {db.get_stats()}")
        logger.info("=" * 55 + "\n")

        # Auto-export
        os.makedirs(config.EXPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        export_path = os.path.join(config.EXPORT_DIR, f"leads_{ts}.xlsx")
        db.export_to_excel(export_path)
        logger.info(f"  📊 Auto-exported to: {export_path}\n")

    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"Scrape error: {e}", exc_info=True)
    finally:
        try:
            browser.save_session(config.SESSION_FILE)
        except Exception as e:
            logger.debug(f"Could not save session on exit: {e}")
        browser.stop()


def cmd_export(config):
    """Export leads to Excel."""
    from database.db import DatabaseManager

    db = DatabaseManager(config.DB_URL)
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(config.EXPORT_DIR, f"leads_{ts}.xlsx")
    db.export_to_excel(path)
    print(f"\n✅ Exported to: {path}\n")


def cmd_stats(config):
    """Quick stats."""
    from database.db import DatabaseManager

    db = DatabaseManager(config.DB_URL)
    stats = db.get_stats()

    print("\n" + "=" * 40)
    print("  📊 Lead Stats")
    print("=" * 40)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("=" * 40 + "\n")


def cmd_dashboard():
    """Launch Streamlit dashboard."""
    import subprocess
    dashboard_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "dashboard", "app.py"
    )
    print("\n🚀 Launching dashboard ...")
    print(f"   File: {dashboard_path}")
    print("   Press Ctrl+C to stop\n")
    subprocess.run([sys.executable, "-m", "streamlit", "run",
                    dashboard_path, "--server.headless", "true"])


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Egypt Real Estate — Buyer Lead Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --login              # Login & save session
  python main.py --check-session      # Is session still valid?
  python main.py --refresh-session    # Force re-login
  python main.py --scrape             # Scrape all enabled groups
  python main.py --scrape-group URL   # Scrape one group
  python main.py --scrape-post URL    # Scrape comments from one post
  python main.py --export             # Export leads to Excel
  python main.py --dashboard          # Open team dashboard
  python main.py --stats              # Quick stats
"""
    )

    parser.add_argument("--login", action="store_true",
                       help="Login to Facebook & save session")
    parser.add_argument("--check-session", action="store_true",
                       help="Check if session is valid")
    parser.add_argument("--refresh-session", action="store_true",
                       help="Force re-login & save new session")
    parser.add_argument("--scrape", action="store_true",
                       help="Scrape all enabled groups")
    parser.add_argument("--scrape-group", type=str, metavar="URL",
                       help="Scrape a single group by URL")
    parser.add_argument("--scrape-post", type=str, metavar="URL",
                       help="Scrape comments from a specific post URL")
    parser.add_argument("--export", action="store_true",
                       help="Export leads to Excel")
    parser.add_argument("--dashboard", action="store_true",
                       help="Launch Streamlit dashboard")
    parser.add_argument("--stats", action="store_true",
                       help="Show quick stats")

    args = parser.parse_args()

    # Handle dashboard separately (no config validation needed)
    if args.dashboard:
        cmd_dashboard()
        return

    # Load config
    from config.settings import Config
    setup_logging(Config.LOG_FILE, Config.LOG_LEVEL)

    # Route commands
    if args.login:
        Config.validate()
        cmd_login(Config)
    elif args.check_session:
        cmd_check_session(Config)
    elif args.refresh_session:
        Config.validate()
        cmd_refresh_session(Config)
    elif args.scrape:
        Config.validate()
        cmd_scrape(Config)
    elif args.scrape_group:
        Config.validate()
        cmd_scrape(Config, group_url=args.scrape_group)
    elif args.scrape_post:
        Config.validate()
        cmd_scrape_post(Config, post_url=args.scrape_post)
    elif args.export:
        cmd_export(Config)
    elif args.stats:
        cmd_stats(Config)
    else:
        parser.print_help()
        print("\n💡 Quick start:")
        print("   1. Edit .env with your Facebook credentials")
        print("   2. python main.py --login")
        print("   3. python main.py --scrape")
        print("   4. python main.py --dashboard\n")


if __name__ == "__main__":
    main()

"""
Group Scraper — ENHANCED
==========================
Scrolls Facebook groups and harvests buyer leads with ALL data.
Uses human behavior patterns and mines comments for extra contacts.
"""

import time
import random
import logging
from typing import List
from playwright.sync_api import Page
from scraper.post_parser import PostParser
from scraper.profile_scraper import ProfileScraper
from database.db import DatabaseManager
from scraper.human import (
    human_scroll, scroll_feed, random_idle,
    natural_delay, between_groups_delay, long_break,
    move_mouse_to,
)

logger = logging.getLogger(__name__)

FEED_SELECTORS = [
    'div[data-pagelet^="GroupFeed"] div[role="article"]',
    'div[role="feed"] > div[role="article"]',
    'div[role="article"]',
]


class GroupScraper:

    def __init__(self, page: Page, config):
        self.page   = page
        self.config = config
        self.parser = PostParser()
        self.profile_scraper = ProfileScraper(page.context)

    def scrape_group(self, group: dict) -> List[dict]:
        """Scrape a single group for buyer leads with full data extraction."""
        logger.info(f"{'─' * 60}")
        logger.info(f"📂 {group['name']}")
        logger.info(f"   Region: {group['region']} | URL: {group['url']}")

        if not self._navigate(group["url"]):
            return []

        buyers = self._scroll_and_harvest()

        for b in buyers:
            b["group_name"]   = group["name"]
            b["group_region"] = group["region"]
            b["group_url"]    = group["url"]

        # Summary stats for this group
        phones_found = sum(len(b.get("phone_numbers", [])) for b in buyers)
        hot_count = sum(1 for b in buyers if b.get("lead_score", 0) >= 60)
        logger.info(f"  👥 {len(buyers)} buyer leads | "
                    f"🔥 {hot_count} hot | "
                    f"📱 {phones_found} phone numbers")
        return buyers

    # ── Navigation ────────────────────────────────────────────────────────

    def _navigate(self, url: str) -> bool:
        """Navigate to group URL with human-like behavior."""
        try:
            self.page.goto(url, wait_until="domcontentloaded",
                           timeout=self.config.PAGE_LOAD_TIMEOUT)
            natural_delay(2, 4)

            if "login" in self.page.url:
                logger.error("❌ Redirected to login — session expired!")
                return False

            if self._group_needs_join():
                logger.warning("⚠️ Group requires membership — skipping.")
                return False

            # Random idle on group page (act natural)
            if random.random() < 0.4:
                random_idle(self.page)

            self._sort_by_new()
            return True
        except Exception as exc:
            logger.error(f"Navigate error: {exc}")
            return False

    def _group_needs_join(self) -> bool:
        """Check if we need to join the group first."""
        for txt in ["Join Group", "انضم إلى المجموعة", "Request to Join",
                     "انضمام إلى المجموعة", "طلب الانضمام"]:
            try:
                if self.page.query_selector(
                    f'div[role="button"]:has-text("{txt}")'
                ):
                    return True
            except Exception:
                pass
        return False

    def _sort_by_new(self):
        """Try to sort the group feed by newest posts."""
        for txt in ["New Posts", "المنشورات الجديدة", "Recent Activity",
                     "النشاط الأخير", "الأحدث", "New Activity"]:
            try:
                btn = self.page.query_selector(
                    f'div[role="button"]:has-text("{txt}")'
                )
                if btn:
                    btn.click()
                    natural_delay(1.5, 3)
                    return
            except Exception:
                pass

    # ── Scroll & harvest ──────────────────────────────────────────────────

    def _scroll_and_harvest(self) -> List[dict]:
        """
        Main scraping loop with full data extraction:
        1. Get visible post elements
        2. Parse each for buyer signals + mine comments
        3. Human-like scroll down
        4. Repeat until max scrolls or no new content
        """
        results     = []
        seen_hashes = set()
        empty_runs  = 0
        scroll_n    = 0

        while (scroll_n < self.config.MAX_SCROLLS and
               len(results) < self.config.MAX_POSTS_PER_SESSION):

            elements  = self._get_elements()
            new_count = 0

            for el in elements:
                try:
                    preview = el.inner_text()[:120]
                    uid     = hash(preview)
                    if uid in seen_hashes:
                        continue
                    seen_hashes.add(uid)

                    # Parse with comment mining enabled
                    posts = self.parser.parse(
                        el, self.page, scrape_comments=True
                    )
                    
                    if posts:
                        for lead in posts:
                            # ── Profile Deep Scraping ──
                            # Always scrape for warm/hot leads (40+)
                            # Also scrape if no phone found regardless of score
                            should_scrape = (
                                lead.get("profile_url")
                                and (
                                    lead.get("lead_score", 0) >= 40
                                    or not lead.get("phone_numbers")
                                )
                            )

                            if should_scrape:
                                profile_data = self.profile_scraper.scrape_profile(
                                    lead["profile_url"]
                                )

                                # Merge phone numbers (dedup)
                                existing_phones = lead.get("phone_numbers", [])
                                new_phones = profile_data.get("phone_numbers", [])
                                merged_phones = list(dict.fromkeys(
                                    existing_phones + new_phones
                                ))
                                lead["phone_numbers"] = merged_phones

                                # Merge all enriched fields
                                for field in [
                                    "emails", "whatsapp_links", "websites",
                                    "lives_in", "hometown",
                                    "work_title", "work_company",
                                    "bio", "is_broker", "profile_scraped",
                                ]:
                                    val = profile_data.get(field)
                                    if val:  # only overwrite if profile returned data
                                        lead[field] = val

                            results.append(lead)
                            new_count += 1
                            self._log_lead(lead)
                            # Save in real-time
                            try:
                                db = DatabaseManager(self.config.DB_URL)
                                db.save_leads([lead])
                            except Exception as e:
                                logger.error(f"Failed to save lead real-time: {e}")

                except Exception as exc:
                    logger.debug(f"Element error: {exc}")

            # Human-like scrolling (not uniform window.scrollBy)
            scroll_feed(self.page, pause_to_read=True)

            scroll_n += 1
            logger.info(
                f"  ↓ Scroll {scroll_n}/{self.config.MAX_SCROLLS} | "
                f"Leads: {len(results)}"
            )

            # Occasional random idle (hover, mouse wander)
            if random.random() < 0.15:
                random_idle(self.page)

            # Occasional long pause every ~10 scrolls
            if scroll_n % 10 == 0 and scroll_n > 0:
                pause = random.uniform(15, 45)
                logger.info(f"  😴 Extended pause: {pause:.0f}s")
                time.sleep(pause)

        return results

    def _get_elements(self) -> list:
        """Get all visible post article elements from the feed."""
        for sel in FEED_SELECTORS:
            try:
                els = self.page.query_selector_all(sel)
                if els:
                    return els
            except Exception:
                pass
        return []

    def _log_lead(self, post: dict):
        """Log a found lead with ALL key info."""
        budget = post.get("budget_max")
        budget_str = f"{budget:,.0f}" if budget else "N/A"
        loc = post.get("locations", [])
        loc_str = ", ".join(loc[:2]) if loc else "?"
        phones = post.get("phone_numbers", [])
        wa = post.get("whatsapp_numbers", [])
        comment_ph = post.get("comment_phones", [])
        emails = post.get("emails", [])
        grade = post.get("lead_grade", "")
        name = post.get("buyer_name", "?")
        urgency = post.get("urgency", "")
        payment = post.get("payment_method", "")
        lives_in = post.get("lives_in", "")
        work = post.get("work_company", "")
        broker = post.get("is_broker", False)

        logger.info(
            f"  {'─' * 50}\n"
            f"  💰 LEAD {grade}{'  ⚠️ BROKER' if broker else ''}\n"
            f"     Name:     {name}\n"
            f"     Score:    {post.get('lead_score', 0)}/100\n"
            f"     Intent:   {post.get('intent', '?')}\n"
            f"     Type:     {post.get('property_type', '?')}\n"
            f"     Location: {loc_str}\n"
            f"     Budget:   {budget_str} EGP\n"
            f"     Phones:   {phones}\n"
            f"     Emails:   {emails}\n"
            f"     WhatsApp: {wa}\n"
            f"     Comment#: {comment_ph}\n"
            f"     Payment:  {payment or 'N/A'}\n"
            f"     Urgency:  {urgency or 'N/A'}\n"
            f"     Rooms:    {post.get('bedrooms', '?')} bed / {post.get('bathrooms', '?')} bath\n"
            f"     Area:     {post.get('area_max', 'N/A')} m²\n"
            f"     Lives in: {lives_in or 'N/A'}\n"
            f"     Work:     {work or 'N/A'}"
        )

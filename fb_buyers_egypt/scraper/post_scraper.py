"""
Post Scraper — Scrapes comments from a specific Facebook post for buyer leads.
"""

import time
import logging
from typing import List
from playwright.sync_api import Page
from scraper.post_parser import PostParser
from scraper.profile_scraper import ProfileScraper
from scraper.human import natural_delay, scroll_feed, random_idle
from database.db import DatabaseManager

logger = logging.getLogger(__name__)

class PostScraper:
    def __init__(self, page: Page, config):
        self.page = page
        self.config = config
        self.parser = PostParser()
        self.profile_scraper = ProfileScraper(page.context)

    def scrape_post(self, post_url: str) -> List[dict]:
        """Navigate to a post URL, expand all comments, and scrape buyers."""
        logger.info(f"{'─' * 60}")
        logger.info(f"📄 Scraping Post: {post_url}")
        
        if not self._navigate(post_url):
            return []
            
        self._expand_all_comments()
        
        # We look for the main article wrapper for the post
        # In a single post view, the main post is usually the first main role="article"
        try:
            main_article = self.page.query_selector('div[role="main"] div[role="article"]')
            if not main_article:
                main_article = self.page.query_selector('div[role="article"]')
                
            if not main_article:
                logger.error("Could not find post article element on the page.")
                return []
                
            logger.info("Extracting post and comments...")
            
            # PostParser handles the main post and its comments if scrape_comments=True
            leads = self.parser.parse(main_article, self.page, scrape_comments=True, all_comments_are_leads=True, is_single_post=True)
            
            enriched_leads = []
            
            for lead in leads:
                # Add source context
                lead["group_name"] = "Specific Post Scrape"
                lead["group_region"] = "custom"
                lead["group_url"] = post_url
                
                # Profile Deep Scraping
                should_scrape = (
                    lead.get("profile_url")
                    and (
                        lead.get("lead_score", 0) >= 40
                        or not lead.get("phone_numbers")
                    )
                )

                if should_scrape:
                    logger.info(f"Scraping profile for: {lead.get('buyer_name')}")
                    profile_data = self.profile_scraper.scrape_profile(
                        lead["profile_url"]
                    )

                    # Merge phone numbers
                    existing_phones = lead.get("phone_numbers", [])
                    new_phones = profile_data.get("phone_numbers", [])
                    merged_phones = list(dict.fromkeys(existing_phones + new_phones))
                    lead["phone_numbers"] = merged_phones

                    # Merge all enriched fields
                    for field in [
                        "emails", "whatsapp_links", "websites",
                        "lives_in", "hometown",
                        "work_title", "work_company",
                        "bio", "is_broker", "profile_scraped",
                    ]:
                        val = profile_data.get(field)
                        if val:
                            lead[field] = val

                enriched_leads.append(lead)
                
                # Save in real-time
                try:
                    db = DatabaseManager(self.config.DB_URL)
                    db.save_leads([lead])
                except Exception as e:
                    logger.error(f"Failed to save lead real-time: {e}")
                
            phones_found = sum(len(b.get("phone_numbers", [])) for b in enriched_leads)
            hot_count = sum(1 for b in enriched_leads if b.get("lead_score", 0) >= 60)
            logger.info(f"  👥 {len(enriched_leads)} buyer leads found | "
                        f"🔥 {hot_count} hot | "
                        f"📱 {phones_found} phone numbers")
                        
            return enriched_leads
            
        except Exception as e:
            logger.error(f"Error scraping post: {e}")
            return []

    def _navigate(self, url: str) -> bool:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.config.PAGE_LOAD_TIMEOUT)
            natural_delay(3, 5)

            if "login" in self.page.url:
                logger.error("❌ Redirected to login — session expired!")
                return False

            return True
        except Exception as exc:
            logger.error(f"Navigate error: {exc}")
            return False

    def _expand_all_comments(self):
        """Click 'View more comments' multiple times to load as many as possible."""
        logger.info("Expanding comments...")
        expand_labels = [
            "View more comments", "عرض المزيد من التعليقات",
            "View all comments", "عرض كل التعليقات",
            "View previous comments", "عرض التعليقات السابقة",
            "View more replies", "عرض المزيد من الردود"
        ]
        
        max_expands = 10
        expanded = 0
        
        # We might need to select "All comments" in the filter dropdown
        try:
            filter_btn = self.page.query_selector('div[role="button"]:has-text("Most relevant")') or \
                         self.page.query_selector('div[role="button"]:has-text("الأكثر ملاءمة")')
            if filter_btn:
                filter_btn.click()
                natural_delay(1, 2)
                all_comments_btn = self.page.query_selector('div[role="menuitem"]:has-text("All comments")') or \
                                   self.page.query_selector('div[role="menuitem"]:has-text("كل التعليقات")')
                if all_comments_btn:
                    all_comments_btn.click()
                    natural_delay(2, 3)
        except Exception:
            pass

        while expanded < max_expands:
            found_button = False
            for label in expand_labels:
                try:
                    btns = self.page.query_selector_all(f'div[role="button"]:has-text("{label}")')
                    for btn in btns:
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            found_button = True
                            natural_delay(1.5, 3)
                except Exception:
                    pass
                    
            if not found_button:
                # scroll down a bit to see if more comments load
                scroll_feed(self.page, pause_to_read=False)
                natural_delay(1, 2)
                # Check again if any buttons appeared
                for label in expand_labels:
                    try:
                        if self.page.query_selector(f'div[role="button"]:has-text("{label}")'):
                            found_button = True
                            break
                    except Exception:
                        pass
                        
                if not found_button:
                    break # No more buttons found after scrolling
                    
            expanded += 1

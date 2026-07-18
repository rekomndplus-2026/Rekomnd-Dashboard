"""
Post Parser — ENHANCED
========================
Extracts ALL available data from Facebook post DOM elements:
- Author name (from multiple DOM selectors)
- Profile URL
- Post URL + timestamp
- Full expanded text
- Images
- Comment mining for extra phone numbers & data
- Engagement metrics (reactions, comments count)
- Author profile picture URL
"""

import re
import time
import random
import logging
from typing import Optional, List
from playwright.sync_api import ElementHandle, Page
from scraper.buyer_detector import BuyerDetector

logger   = logging.getLogger(__name__)
detector = BuyerDetector()


class PostParser:

    def parse(self, element: ElementHandle, page: Page,
              scrape_comments: bool = True, all_comments_are_leads: bool = False,
              is_single_post: bool = False) -> List[dict]:
        """
        Parse a single post element and extract ALL buyer data.
        Returns a list of leads (from the main post + any buyer comments).
        """
        leads = []
        try:
            self._expand_text(element)
            raw_text = element.inner_text().strip()

            main_post_url = self._get_post_url(element)
            main_timestamp = self._get_timestamp(element)

            # Clean raw text and try to extract author fallback
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            clean_lines = []
            fallback_author = ""
            if lines:
                author_candidate = lines[0].split('·')[0].split(' is with ')[0].strip()
                if 2 < len(author_candidate) < 50:
                    fallback_author = author_candidate

            for line in lines:
                # Skip common FB UI noise
                if line in ["Like", "Reply", "Share", "Follow", "Top fan", "Author", "إعجاب", "رد", "مشاركة", "Send message"] or re.match(r'^\d+[mhdwys]$', line):
                    continue
                # Clean "Name · Follow" or inline stuff from the text
                clean_line = re.sub(r'^.*?·\s*Follow\s*', '', line)
                if clean_line:
                    clean_lines.append(clean_line)
            
            clean_raw_text = "\n".join(clean_lines)

            if clean_raw_text and len(clean_raw_text) >= 15:
                # Run buyer analysis on main post
                analysis = detector.analyse(clean_raw_text)
                if analysis.get("is_buyer"):
                    author = self._get_author(element) or fallback_author
                    profile_url = self._get_profile_url(element)
                    
                    analysis.update({
                        "author":           author,
                        "buyer_name":       analysis.get("buyer_name") or author,
                        "timestamp":        main_timestamp,
                        "post_url":         main_post_url,
                        "images":           self._get_images(element),
                        "profile_url":      profile_url,
                        "profile_pic":      self._get_profile_pic(element),
                        "reactions":        self._get_reaction_count(element),
                        "comment_count":    self._get_comment_count(element),
                        "shares":           self._get_share_count(element),
                        "raw_text":         clean_raw_text,
                    })
                    leads.append(analysis)

            # ── Scrape comments for extra leads ───────────────────────────
            if scrape_comments:
                self._expand_comments(element)
                
                comment_els = []
                if is_single_post:
                    # In single post view, comments can be outside the main post element
                    try:
                        els = page.query_selector_all('div[role="article"]')
                        if els and len(els) > 1:
                            comment_els = els[1:] # Skip first one (the main post)
                    except Exception:
                        pass
                        
                if not comment_els:
                    comment_sels = [
                        'div[role="article"] div[role="article"]',
                        'ul li div[data-testid="UFI2Comment/body"]',
                        'div[class*="comment"]',
                    ]
                    for sel in comment_sels:
                        try:
                            els = element.query_selector_all(sel)
                            if els:
                                comment_els = els
                                break
                        except Exception:
                            pass
                
                # Mine up to 30 comments
                for cel in comment_els[:30]:
                    try:
                        raw_ctext = cel.inner_text().strip()
                        if not raw_ctext or len(raw_ctext) < 5:
                            continue
                            
                        lines = [line.strip() for line in raw_ctext.split('\n') if line.strip()]
                        if not lines:
                            continue
                            
                        clean_author = lines[0]
                        clean_body_lines = []
                        
                        for line in lines[1:]:
                            # Skip common Facebook UI elements and timestamps
                            if line in ["Like", "Reply", "Share", "Top fan", "Author", "إعجاب", "رد", "مشاركة"] or re.match(r'^\d+[mhdwys]$', line) or line.endswith('m') or line.endswith('h') or line.endswith('d'):
                                continue
                            clean_body_lines.append(line)
                            
                        clean_body = "\n".join(clean_body_lines)
                        if not clean_body:
                            clean_body = raw_ctext
                            
                        # Treat commenter as a potential independent lead
                        c_analysis = detector.analyse(
                            clean_body, 
                            is_comment=True, 
                            force_lead=all_comments_are_leads
                        )
                        
                        if c_analysis.get("is_buyer"):
                            c_author = self._get_author(cel)
                            if not c_author or re.match(r'^\d+[mhdwys]$', c_author) or len(c_author) < 2:
                                c_author = clean_author
                                
                            c_profile_url = self._get_profile_url(cel)
                            
                            c_analysis.update({
                                "author": c_author,
                                "buyer_name": c_analysis.get("buyer_name") or c_author,
                                "timestamp": main_timestamp,
                                "post_url": main_post_url,
                                "profile_url": c_profile_url,
                                "profile_pic": self._get_profile_pic(cel),
                                "notes": f"Extracted from comment section. Snippet: {raw_ctext[:50]}...",
                            })
                            leads.append(c_analysis)
                    except Exception as e:
                        logger.debug(f"Comment parsing error: {e}")

        except Exception as exc:
            logger.debug(f"parse error: {exc}")
            
        return leads

    def _expand_comments(self, element: ElementHandle):
        """Click 'View more comments' buttons."""
        expand_labels = [
            "View more comments", "عرض المزيد من التعليقات",
            "View all", "عرض الكل",
            "View previous comments", "عرض التعليقات السابقة",
        ]
        for label in expand_labels:
            try:
                btn = element.query_selector(
                    f'div[role="button"]:has-text("{label}")'
                )
                if btn:
                    btn.click()
                    time.sleep(random.uniform(0.8, 1.5))
                    break
            except Exception:
                pass

    # ── Engagement Metrics ────────────────────────────────────────────────

    def _get_reaction_count(self, element: ElementHandle) -> int:
        """Extract reaction/like count."""
        for sel in ['span[aria-label*="reaction"]',
                    'span[aria-label*="تفاعل"]',
                    'span[aria-label*="like"]',
                    'span[aria-label*="إعجاب"]']:
            try:
                el = element.query_selector(sel)
                if el:
                    label = el.get_attribute("aria-label") or ""
                    nums = re.findall(r"[\d,]+", label)
                    if nums:
                        return int(nums[0].replace(",", ""))
            except Exception:
                pass
        return 0

    def _get_comment_count(self, element: ElementHandle) -> int:
        """Extract comment count."""
        for sel in ['a[href*="comment"]', 'span:has-text("comment")',
                    'span:has-text("تعليق")']:
            try:
                el = element.query_selector(sel)
                if el:
                    text = el.inner_text()
                    nums = re.findall(r"[\d,]+", text)
                    if nums:
                        return int(nums[0].replace(",", ""))
            except Exception:
                pass
        return 0

    def _get_share_count(self, element: ElementHandle) -> int:
        """Extract share count."""
        for sel in ['span:has-text("share")', 'span:has-text("مشاركة")']:
            try:
                el = element.query_selector(sel)
                if el:
                    text = el.inner_text()
                    nums = re.findall(r"[\d,]+", text)
                    if nums:
                        return int(nums[0].replace(",", ""))
            except Exception:
                pass
        return 0

    # ── DOM helpers ───────────────────────────────────────────────────────

    def _expand_text(self, element: ElementHandle):
        """Click 'See more' to expand truncated post text."""
        for label in ["رؤية المزيد", "See more", "See More",
                       "عرض المزيد", "المزيد", "...more"]:
            try:
                btn = element.query_selector(
                    f'div[role="button"]:has-text("{label}")'
                )
                if btn:
                    btn.click()
                    time.sleep(random.uniform(0.3, 0.7))
                    break
            except Exception:
                pass

    def _get_author(self, element: ElementHandle) -> str:
        """Extract post author name from DOM — tries many selectors."""
        for sel in ["h2 a strong span", "h2 a strong", "h2 a span", "h2 a",
                    "h3 a strong span", "h3 a strong", "h3 a span", "h3 a",
                    "h4 a strong", "h4 a",
                    '[data-ad-rendering-role="profile_name"] span',
                    '[data-ad-rendering-role="profile_name"]',
                    "strong a span", "strong a", "a[role='link']", "a"]:
            try:
                el = element.query_selector(sel)
                if el:
                    name = el.inner_text().strip()
                    # Filter out garbage
                    if (name and len(name) > 1 and len(name) < 80
                            and not name.startswith("http")
                            and "\n" not in name):
                        return name
            except Exception:
                pass
        return ""

    def _get_profile_url(self, element: ElementHandle) -> str:
        """Extract the author's Facebook profile URL."""
        for sel in ["h2 a", "h3 a",
                    '[data-ad-rendering-role="profile_name"] a',
                    "strong a", "a[role='link']", "a"]:
            try:
                el = element.query_selector(sel)
                if el:
                    href = el.get_attribute("href") or ""
                    clean = href.split("?")[0]
                    if "facebook.com" in clean or clean.startswith("/"):
                        if clean.startswith("/"):
                            clean = "https://www.facebook.com" + clean
                        return clean
            except Exception:
                pass
        return ""

    def _get_profile_pic(self, element: ElementHandle) -> str:
        """Extract author's profile picture URL."""
        try:
            # Profile pics are usually the first small circular image
            for sel in ['image', 'svg image', 'a img[src*="scontent"]']:
                el = element.query_selector(sel)
                if el:
                    src = (el.get_attribute("xlink:href") or
                           el.get_attribute("src") or "")
                    if src and "scontent" in src:
                        return src
        except Exception:
            pass
        return ""

    def _get_timestamp(self, element: ElementHandle) -> str:
        """Extract post timestamp from multiple possible locations."""
        for sel in ['abbr[data-utime]', 'abbr', 'time',
                    'a[role="link"] span[id]',
                    'span[id] a[role="link"]',
                    'a[href*="/posts/"]',
                    'a[href*="story_fbid"]']:
            try:
                el = element.query_selector(sel)
                if el:
                    v = (el.get_attribute("data-utime") or
                         el.get_attribute("title") or
                         el.get_attribute("aria-label") or
                         el.inner_text())
                    if v and len(v.strip()) > 0:
                        return v.strip()
            except Exception:
                pass
        return ""

    def _get_post_url(self, element: ElementHandle) -> str:
        """Extract the permalink of the post."""
        for sel in ['a[href*="/posts/"]',
                    'a[href*="story_fbid"]',
                    'a[href*="/permalink/"]',
                    'a[href*="pcb."]']:
            try:
                el = element.query_selector(sel)
                if el:
                    href = el.get_attribute("href") or ""
                    clean = href.split("?")[0]
                    if clean:
                        return clean
            except Exception:
                pass
        return ""

    def _get_images(self, element: ElementHandle) -> list:
        """Extract image URLs from the post."""
        try:
            imgs = element.query_selector_all('img[src*="scontent"]')
            # Filter out profile pics (usually small)
            result = []
            for img in imgs:
                src = img.get_attribute("src") or ""
                if not src:
                    continue
                # Try to get dimensions to filter profile pics
                try:
                    width = img.get_attribute("width")
                    if width and int(width) < 50:
                        continue
                except (TypeError, ValueError):
                    pass
                result.append(src)
                if len(result) >= 6:
                    break
            return result
        except Exception:
            return []

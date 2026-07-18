"""
Profile Scraper — DEEP ENRICHMENT
====================================
Visits multiple Facebook profile 'About' sub-tabs to extract:
  • Phone numbers (mobile + landline + international)
  • Emails
  • WhatsApp links  (wa.me / api.whatsapp.com)
  • Websites & social links (Instagram, LinkedIn, etc.)
  • Location: lives in / hometown
  • Work: job title + company
  • Bio / intro text
  • Broker detection (real-estate keywords in work info)

Implements caching so profiles aren't re-scraped within 7 days.
"""

import time
import random
import re
import logging
from datetime import datetime, timezone, timedelta
from playwright.sync_api import BrowserContext

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  BROKER DETECTION KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────

BROKER_KEYWORDS = [
    # Arabic
    "عقارات", "سمسار", "وسيط عقاري", "مستشار عقاري",
    "تسويق عقاري", "شركة عقارية", "مكتب عقاري",
    "بيع وشراء", "إدارة عقارات", "وكيل عقاري",
    "عقاري", "تطوير عقاري", "استثمار عقاري",
    "سيلز", "مبيعات", "sales", "بروكر",
    # English
    "real estate", "broker", "realtor", "property",
    "sales consultant", "sales manager", "marketing",
    "realestate", "properties", "agent",
]


class ProfileScraper:
    """
    Deep-scrapes Facebook profiles to extract contacts, location,
    work info, and social links.
    """

    def __init__(self, context: BrowserContext):
        self.context = context
        # Cache: profile_url → (timestamp, result_dict)
        self._cache: dict[str, tuple[datetime, dict]] = {}
        self._CACHE_TTL = timedelta(days=7)

    # ══════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    def scrape_profile(self, profile_url: str) -> dict:
        """
        Full profile enrichment. Returns a dict with all extracted data.
        Uses cache to avoid re-scraping within 7 days.

        Returns:
            {
                "phone_numbers": [...],
                "emails": [...],
                "whatsapp_links": [...],
                "websites": [...],
                "lives_in": str,
                "hometown": str,
                "work_title": str,
                "work_company": str,
                "bio": str,
                "is_broker": bool,
                "profile_scraped": True,
            }
        """
        if not profile_url or "facebook.com" not in profile_url:
            return self._empty()

        # ── Cache check ──────────────────────────────────────────────
        clean_key = profile_url.split("?")[0].rstrip("/")
        if clean_key in self._cache:
            cached_time, cached_result = self._cache[clean_key]
            if datetime.now(timezone.utc) - cached_time < self._CACHE_TTL:
                logger.info("    📋 Profile cached — skipping re-scrape")
                return cached_result

        logger.info("    🔍 Deep-scraping profile...")

        result = {
            "phone_numbers": [],
            "emails": [],
            "whatsapp_links": [],
            "websites": [],
            "lives_in": "",
            "hometown": "",
            "work_title": "",
            "work_company": "",
            "bio": "",
            "is_broker": False,
            "profile_scraped": True,
        }

        # Build sub-tab URLs
        base_url = self._build_base_url(profile_url)
        tabs = {
            "contact": self._build_about_url(base_url, "about_contact_and_basic_info"),
            "overview": self._build_about_url(base_url, "about_overview"),
            "work":    self._build_about_url(base_url, "about_work_and_education"),
        }

        page = self.context.new_page()

        try:
            # ── Tab 1: Contact & Basic Info ───────────────────────────
            self._scrape_contact_tab(page, tabs["contact"], result)

            # ── Tab 2: Overview ──────────────────────────────────────
            self._scrape_overview_tab(page, tabs["overview"], result)

            # ── Tab 3: Work & Education ──────────────────────────────
            self._scrape_work_tab(page, tabs["work"], result)

            # ── Bio / intro text from main profile ───────────────────
            self._scrape_bio(page, base_url, result)

            # ── Broker detection ─────────────────────────────────────
            result["is_broker"] = self._detect_broker(result)

            # ── Summary log ──────────────────────────────────────────
            self._log_results(result)

        except Exception as e:
            logger.debug(f"Profile scrape error: {e}")
        finally:
            page.close()

        # Cache the result
        self._cache[clean_key] = (datetime.now(timezone.utc), result)
        return result

    def extract_contact_info(self, profile_url: str) -> dict:
        """
        Backward-compatible wrapper. Returns the same format as before
        plus the new enriched fields.
        """
        return self.scrape_profile(profile_url)

    # ══════════════════════════════════════════════════════════════════════
    #  TAB SCRAPERS
    # ══════════════════════════════════════════════════════════════════════

    def _scrape_contact_tab(self, page, url: str, result: dict):
        """Scrape the Contact & Basic Info tab for phones, emails, links."""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            time.sleep(random.uniform(2, 4))

            body_text = page.inner_text("body")

            # ── Phones ───────────────────────────────────────────────
            result["phone_numbers"] = self._extract_phones(body_text)

            # ── Emails ───────────────────────────────────────────────
            result["emails"] = self._extract_emails(body_text)

            # ── WhatsApp links from href attributes ──────────────────
            wa_links = self._extract_whatsapp_links(page)
            result["whatsapp_links"] = wa_links
            # Also extract phone numbers from wa.me links
            for link in wa_links:
                phone = self._phone_from_wa_link(link)
                if phone and phone not in result["phone_numbers"]:
                    result["phone_numbers"].append(phone)

            # ── Websites & social links from href attributes ─────────
            result["websites"] = self._extract_websites(page)

            # ── Location from contact page (lives in / from) ─────────
            self._extract_location_from_text(body_text, result)

        except Exception as e:
            logger.debug(f"Contact tab error: {e}")

    def _scrape_overview_tab(self, page, url: str, result: dict):
        """Scrape Overview tab for work, education, location summary."""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(random.uniform(1.5, 3))

            body_text = page.inner_text("body")

            # ── Location (if not already found) ──────────────────────
            if not result["lives_in"]:
                self._extract_location_from_text(body_text, result)

            # ── Work info (if not already found) ─────────────────────
            if not result["work_title"] and not result["work_company"]:
                self._extract_work_from_text(body_text, result)

            # ── Extra phones in overview text ────────────────────────
            extra_phones = self._extract_phones(body_text)
            for p in extra_phones:
                if p not in result["phone_numbers"]:
                    result["phone_numbers"].append(p)

        except Exception as e:
            logger.debug(f"Overview tab error: {e}")

    def _scrape_work_tab(self, page, url: str, result: dict):
        """Scrape Work & Education tab for job details."""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(random.uniform(1.5, 3))

            body_text = page.inner_text("body")

            # ── Work info ────────────────────────────────────────────
            self._extract_work_from_text(body_text, result)

        except Exception as e:
            logger.debug(f"Work tab error: {e}")

    def _scrape_bio(self, page, base_url: str, result: dict):
        """Scrape the main profile page for the bio/intro section."""
        if result.get("bio"):
            return  # Already found

        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(random.uniform(1.5, 3))

            # Bio is usually in the intro section
            for sel in [
                'div[data-pagelet="ProfileTilesFeed_0"]',
                'div[class*="intro"]',
                'div:has-text("Intro") + div',
                'div:has-text("نبذة") + div',
            ]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        text = el.inner_text().strip()
                        if text and 5 < len(text) < 500:
                            # Clean up: remove "Intro" / "نبذة" header
                            text = re.sub(r"^(Intro|نبذة|المقدمة)\s*\n?", "", text).strip()
                            if text:
                                result["bio"] = text[:500]
                                break
                except Exception:
                    pass

            # ── Also mine the main profile page for phones ───────────
            body_text = page.inner_text("body")
            extra_phones = self._extract_phones(body_text)
            for p in extra_phones:
                if p not in result["phone_numbers"]:
                    result["phone_numbers"].append(p)

        except Exception as e:
            logger.debug(f"Bio scrape error: {e}")

    # ══════════════════════════════════════════════════════════════════════
    #  EXTRACTORS
    # ══════════════════════════════════════════════════════════════════════

    def _extract_phones(self, text: str) -> list:
        """Extract all Egyptian phone numbers (mobile + landline)."""
        patterns = [
            # Mobile: 01X XXXX XXXX
            r"\b(01[0125]\d{8})\b",
            r"\b(01[0125][\s\-]?\d{4}[\s\-]?\d{4})\b",
            r"\+20\s?(1[0125]\d{8})",
            # Landline: 02X / 03X (Cairo / Alex)
            r"\b(0[23]\d{8})\b",
            r"\b(0[23][\s\-]?\d{4}[\s\-]?\d{4})\b",
            # Numbers with dots or spaces
            r"\b(01[0125][\.]\d{4}[\.]\d{4})\b",
            # Arabic-Eastern numerals  ٠١٢...
            r"(٠١[٠١٢٥][\s\-]?[٠-٩]{4}[\s\-]?[٠-٩]{4})",
            # International +20 format
            r"\+20[\s\-]?(1[0125][\s\-]?\d{4}[\s\-]?\d{4})",
            r"\+20[\s\-]?([23]\d{8})",
            # Contextual: keyword followed by number
            r"(?:تواصل|موبايل|تليفون|واتساب|whatsapp|واتس|رقم|موبيل|تلفون|جوال|هاتف|فون|phone|call|tel)[:\s]+([\d][\d\s\-]{8,})",
        ]
        found, seen = [], set()
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                raw = re.sub(r"[\s\-\.]", "", m.group(1))
                # Convert Arabic-Eastern numerals to Western
                eastern = "٠١٢٣٤٥٦٧٨٩"
                for i, c in enumerate(eastern):
                    raw = raw.replace(c, str(i))
                if 10 <= len(raw) <= 13 and raw not in seen:
                    seen.add(raw)
                    found.append(raw)
        return found[:8]

    def _extract_emails(self, text: str) -> list:
        """Extract email addresses from text."""
        emails = re.findall(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b",
            text,
        )
        # Filter out common Facebook-internal addresses
        filtered = [
            e for e in emails
            if not e.endswith("@facebook.com")
            and not e.endswith("@fb.com")
            and not e.endswith("@tfbnw.net")
        ]
        return list(set(filtered))[:5]

    def _extract_whatsapp_links(self, page) -> list:
        """Extract WhatsApp link URLs from the page's <a> elements."""
        wa_links = []
        try:
            anchors = page.query_selector_all("a[href]")
            for a in anchors:
                href = a.get_attribute("href") or ""
                if "wa.me/" in href or "api.whatsapp.com" in href:
                    if href not in wa_links:
                        wa_links.append(href)
        except Exception:
            pass
        return wa_links[:5]

    def _phone_from_wa_link(self, link: str) -> str:
        """Extract phone number from a wa.me/20XXXXXXXXXX link."""
        m = re.search(r"wa\.me/(\d{10,15})", link)
        if m:
            raw = m.group(1)
            # Normalize: strip leading 20 (Egypt country code)
            if raw.startswith("20") and len(raw) >= 12:
                raw = "0" + raw[2:]
            return raw
        m2 = re.search(r"phone=(\d{10,15})", link)
        if m2:
            raw = m2.group(1)
            if raw.startswith("20") and len(raw) >= 12:
                raw = "0" + raw[2:]
            return raw
        return ""

    def _extract_websites(self, page) -> list:
        """Extract personal websites and social media links from the page."""
        social_domains = [
            "instagram.com", "linkedin.com", "twitter.com", "x.com",
            "tiktok.com", "youtube.com", "t.me", "telegram.me",
            "snapchat.com", "pinterest.com",
        ]
        websites = []
        try:
            anchors = page.query_selector_all("a[href]")
            for a in anchors:
                href = a.get_attribute("href") or ""
                # Skip Facebook internal links
                if (
                    not href
                    or "facebook.com" in href
                    or "fbcdn.net" in href
                    or href.startswith("#")
                    or href.startswith("javascript:")
                    or "wa.me" in href  # already captured separately
                ):
                    continue

                # Check for social profiles or personal websites
                is_social = any(d in href for d in social_domains)
                is_website = href.startswith("http") and "l.facebook.com/l.php" not in href

                # Facebook wraps external links through l.facebook.com
                if "l.facebook.com/l.php" in href:
                    # Extract the actual URL from the redirect
                    m = re.search(r"u=([^&]+)", href)
                    if m:
                        from urllib.parse import unquote
                        actual = unquote(m.group(1))
                        if actual not in websites:
                            websites.append(actual)
                        continue

                if (is_social or is_website) and href not in websites:
                    websites.append(href)

        except Exception:
            pass
        return websites[:10]

    def _extract_location_from_text(self, text: str, result: dict):
        """Extract 'Lives in' and 'From' location from About page text."""
        # "Lives in" patterns
        lives_patterns = [
            r"(?:Lives in|يعيش في|يقيم في|تعيش في|مقيم في|السكن في)\s+([^\n\r]{3,50})",
            r"(?:Current city|المدينة الحالية)[:\s]+([^\n\r]{3,50})",
        ]
        for pat in lives_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m and not result["lives_in"]:
                result["lives_in"] = m.group(1).strip()[:100]
                break

        # "From" / hometown patterns
        from_patterns = [
            r"(?:From|من|Hometown|مسقط الرأس|المدينة الأصلية)[:\s]+([^\n\r]{3,50})",
        ]
        for pat in from_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m and not result["hometown"]:
                result["hometown"] = m.group(1).strip()[:100]
                break

    def _extract_work_from_text(self, text: str, result: dict):
        """Extract work title and company from About page text."""
        # Common patterns on Facebook About pages
        work_patterns = [
            # "Works at COMPANY"
            r"(?:Works at|يعمل في|يعمل لدى|تعمل في|تعمل لدى|يعمل بـ)\s+([^\n\r]{3,60})",
            # "TITLE at COMPANY"
            r"([^\n\r]{3,40})\s+(?:at|في|لدى|بـ)\s+([^\n\r]{3,60})",
            # "Workplace" section
            r"(?:Workplace|مكان العمل)[:\s]+([^\n\r]{3,60})",
        ]

        for pat in work_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                groups = m.groups()
                if len(groups) == 2 and not result["work_title"]:
                    result["work_title"] = groups[0].strip()[:100]
                    result["work_company"] = groups[1].strip()[:100]
                    return
                elif len(groups) == 1 and not result["work_company"]:
                    result["work_company"] = groups[0].strip()[:100]
                    return

        # Job title patterns
        title_patterns = [
            r"(?:Job title|المسمى الوظيفي|الوظيفة)[:\s]+([^\n\r]{3,60})",
            r"(?:Position|المنصب)[:\s]+([^\n\r]{3,60})",
        ]
        for pat in title_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m and not result["work_title"]:
                result["work_title"] = m.group(1).strip()[:100]
                break

    # ══════════════════════════════════════════════════════════════════════
    #  BROKER DETECTION
    # ══════════════════════════════════════════════════════════════════════

    def _detect_broker(self, result: dict) -> bool:
        """
        Detect if the profile likely belongs to a real estate broker/agent.
        Checks work info, bio, and company name against broker keywords.
        """
        texts_to_check = [
            result.get("work_title", ""),
            result.get("work_company", ""),
            result.get("bio", ""),
        ]
        combined = " ".join(texts_to_check).lower()

        if not combined.strip():
            return False

        hits = sum(1 for kw in BROKER_KEYWORDS if kw in combined)
        return hits >= 1

    # ══════════════════════════════════════════════════════════════════════
    #  URL BUILDERS
    # ══════════════════════════════════════════════════════════════════════

    def _build_base_url(self, profile_url: str) -> str:
        """Normalize profile URL to its base form."""
        clean = profile_url.split("?")[0].rstrip("/")
        if "profile.php" in profile_url:
            try:
                user_id = profile_url.split("id=")[1].split("&")[0]
                return f"https://www.facebook.com/profile.php?id={user_id}"
            except IndexError:
                pass
        return clean

    def _build_about_url(self, base_url: str, tab: str) -> str:
        """Build an About sub-tab URL from a base profile URL."""
        if "profile.php" in base_url:
            sep = "&" if "?" in base_url else "?"
            return f"{base_url}{sep}sk={tab}"
        else:
            return f"{base_url}/{tab}"

    # ══════════════════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _log_results(self, result: dict):
        """Log a summary of what was found."""
        phones = result.get("phone_numbers", [])
        emails = result.get("emails", [])
        wa = result.get("whatsapp_links", [])
        sites = result.get("websites", [])
        location = result.get("lives_in", "")
        work = result.get("work_company", "")
        broker = result.get("is_broker", False)

        parts = []
        if phones:  parts.append(f"📱 {len(phones)} phones")
        if emails:  parts.append(f"📧 {len(emails)} emails")
        if wa:      parts.append(f"💬 {len(wa)} WhatsApp")
        if sites:   parts.append(f"🌐 {len(sites)} links")
        if location: parts.append(f"📍 {location}")
        if work:    parts.append(f"🏢 {work}")
        if broker:  parts.append("⚠️ BROKER")

        if parts:
            logger.info(f"      ✅ Profile: {' | '.join(parts)}")
        else:
            logger.info("      ❌ No additional data found on profile")

    @staticmethod
    def _empty() -> dict:
        """Return an empty result dict."""
        return {
            "phone_numbers": [],
            "emails": [],
            "whatsapp_links": [],
            "websites": [],
            "lives_in": "",
            "hometown": "",
            "work_title": "",
            "work_company": "",
            "bio": "",
            "is_broker": False,
            "profile_scraped": False,
        }

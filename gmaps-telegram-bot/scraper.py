import asyncio
import re
import logging
from dataclasses import dataclass, field
from typing import Optional, AsyncGenerator
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Review:
    author: str
    rating: int          # 1-5
    text: str
    date: str
    likes: int = 0

@dataclass
class BusinessInfo:
    name: str
    rating: float
    review_count: int
    address: str
    phone: str
    website: str
    category: str
    hours: dict          # {"Monday": "9 AM–5 PM", ...}
    reviews: list[Review] = field(default_factory=list)
    maps_url: str = ""
    price_level: str = ""
    # Derived stats (populated after scrape)
    avg_rating: float = 0.0
    rating_distribution: dict = field(default_factory=dict)  # {"5": 42, "4": 18, ...}
    error: str = ""

# ── Selectors ─────────────────────────────────────────────────────────────────

SEARCH_RESULT_SELECTOR   = 'a[href*="/maps/place/"]'
NAME_SELECTOR            = 'h1.DUwDvf'
RATING_SELECTOR          = 'div.F7nice span[aria-hidden="true"]'
REVIEW_COUNT_SELECTOR    = 'div.F7nice span[aria-label*="reviews"], div.F7nice span[aria-label*="مراجعة"]'
ADDRESS_SELECTOR         = 'button[data-item-id="address"]'
PHONE_SELECTOR           = 'button[data-item-id*="phone"]'
WEBSITE_SELECTOR         = 'a[data-item-id="authority"]'
CATEGORY_SELECTOR        = 'button.DkEaL'
HOURS_BUTTON_SELECTOR    = 'div[jsaction*="openhours"]'
HOURS_TABLE_SELECTOR     = 'tr.y0skZc'
REVIEW_ITEM_SELECTOR     = 'div[data-review-id]'
REVIEW_AUTHOR_SELECTOR   = 'div.d4r55'
REVIEW_TEXT_SELECTOR     = 'span.wiI7pd'
REVIEW_DATE_SELECTOR     = 'span.rsqaWe'
REVIEW_LIKES_SELECTOR    = 'span.pkWtMe'
RATING_HIST_SELECTOR     = 'table.u6RJpf tr'

def clean_text(text: str) -> str:
    """Removes newlines and Google Material icon characters."""
    if not text:
        return ""
    text = re.sub(r'[\ue000-\uf8ff]', '', text)
    return text.replace('\n', ' ').strip()

# ── Core scraper ──────────────────────────────────────────────────────────────

class GoogleMapsScraper:
    def __init__(self, max_reviews: int = 30, headless: bool = True):
        self.max_reviews = max_reviews
        self.headless    = headless

    async def search_multiple(self, query: str, max_businesses: int = 200) -> AsyncGenerator[BusinessInfo, None]:
        """
        Searches for a query, extracts multiple business links from the results feed,
        visits each one, and yields the scraped BusinessInfo.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                locale="ar-EG", # Defaulting to Arabic locale to ensure consistency with user searches
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                logger.info("Navigating to %s", search_url)
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(3_000)

                # Check if Google Maps went directly to a single business page
                is_direct = False
                try:
                    await page.wait_for_selector(NAME_SELECTOR, timeout=5000)
                    is_direct = True
                except Exception:
                    pass

                business_links = []

                if is_direct:
                    business_links.append(page.url)
                else:
                    # It's a feed of multiple results. Scroll to load all of them.
                    scroll_panel = page.locator('div[role="feed"]').first
                    if await scroll_panel.count() > 0:
                        previous_count = 0
                        # Scroll continuously to load all results (Google usually caps around 100-120 results)
                        for _ in range(60): 
                            await scroll_panel.evaluate("el => el.scrollBy(0, 5000)")
                            await page.wait_for_timeout(1500)
                            
                            # Check if the number of rendered links has stopped increasing
                            current_count = await page.evaluate('''() => document.querySelectorAll('a[href*="/maps/place/"]').length''')
                            if current_count == previous_count:
                                # Wait a bit longer to check if it was just a slow network loading
                                await page.wait_for_timeout(2000)
                                current_count = await page.evaluate('''() => document.querySelectorAll('a[href*="/maps/place/"]').length''')
                                if current_count == previous_count:
                                    break # Reached the end of the feed
                            previous_count = current_count

                    # Extract all hrefs from the results
                    hrefs = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href*="/maps/place/"]')).map(a => a.href);
                    }''')
                    
                    # Deduplicate links (Maps often has 2 links per business item)
                    for h in hrefs:
                        if h not in business_links:
                            business_links.append(h)

                # Limit the number of businesses to scrape to a very high ceiling for safety
                target_links = business_links[:max_businesses]
                logger.info(f"Found {len(business_links)} businesses. Scraping top {len(target_links)}...")

                if not target_links:
                    yield BusinessInfo(name="Error", rating=0, review_count=0, address="", phone="", website="", category="", hours={}, error="Could not find any businesses for this query.")
                    return

                # Visit each link and scrape
                for link in target_links:
                    await page.goto(link, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(2_000)
                    
                    try:
                        await page.wait_for_selector(NAME_SELECTOR, timeout=8000)
                        info = await self._do_scrape(page, query)
                        info.maps_url = link
                        yield info
                    except Exception as e:
                        logger.error(f"Failed to scrape business at {link}: {e}")
                        continue

            except Exception as exc:
                logger.exception("Scraper error for query=%r: %s", query, exc)
                yield BusinessInfo(name="Error", rating=0, review_count=0, address="", phone="", website="", category="", hours={}, error=str(exc))
            finally:
                await browser.close()

    async def _do_scrape(self, page: Page, query: str) -> BusinessInfo:
        # ── Basic info ──
        name         = clean_text(await self._text(page, NAME_SELECTOR, "Unknown"))
        rating_str   = clean_text(await self._text(page, RATING_SELECTOR, "0"))
        rating       = float(rating_str.replace(",", ".")) if rating_str else 0.0
        review_count = await self._parse_review_count(page)
        address      = clean_text(await self._button_text(page, ADDRESS_SELECTOR))
        phone        = clean_text(await self._button_text(page, PHONE_SELECTOR))
        website      = clean_text(await self._link_href(page, WEBSITE_SELECTOR))
        category     = clean_text(await self._text(page, CATEGORY_SELECTOR, ""))
        hours        = await self._scrape_hours(page)
        rating_dist  = await self._scrape_rating_distribution(page)
        price_level  = await self._scrape_price_level(page)

        # ── Reviews ──
        reviews = await self._scrape_reviews(page)

        info = BusinessInfo(
            name=name,
            rating=rating,
            review_count=review_count,
            address=address,
            phone=phone,
            website=website,
            category=category,
            hours=hours,
            reviews=reviews,
            maps_url=page.url,
            price_level=price_level,
            rating_distribution=rating_dist,
        )
        # Compute average from scraped reviews (cross-check)
        if reviews:
            info.avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 2)

        return info

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _text(self, page: Page, selector: str, default: str = "") -> str:
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=4_000)
            return await el.inner_text()
        except Exception:
            return default

    async def _button_text(self, page: Page, selector: str) -> str:
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=4_000)
            return await el.inner_text()
        except Exception:
            return ""

    async def _link_href(self, page: Page, selector: str) -> str:
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=4_000)
            return (await el.get_attribute("href")) or ""
        except Exception:
            return ""

    async def _parse_review_count(self, page: Page) -> int:
        try:
            el = page.locator(REVIEW_COUNT_SELECTOR).first
            label = await el.get_attribute("aria-label") or ""
            match = re.search(r"([\d,]+)", label)
            if match:
                return int(match.group(1).replace(",", ""))
            
            inner = await el.inner_text()
            match = re.search(r"\(([\d,]+)\)", inner)
            if match:
                return int(match.group(1).replace(",", ""))
        except Exception:
            pass
        return 0

    async def _scrape_price_level(self, page: Page) -> str:
        try:
            spans = page.locator('span[aria-label*="Price"]')
            if await spans.count() > 0:
                return (await spans.first.get_attribute("aria-label")) or ""
        except Exception:
            pass
        return ""

    async def _scrape_hours(self, page: Page) -> dict:
        hours = {}
        try:
            btn = page.locator(HOURS_BUTTON_SELECTOR).first
            await btn.wait_for(state="visible", timeout=4_000)
            await btn.click()
            await page.wait_for_timeout(1_000)
            rows = page.locator(HOURS_TABLE_SELECTOR)
            count = await rows.count()
            for i in range(count):
                row = rows.nth(i)
                cells = row.locator("td")
                if await cells.count() >= 2:
                    day  = clean_text(await cells.nth(0).inner_text())
                    time = clean_text(await cells.nth(1).inner_text())
                    hours[day] = time
        except Exception as e:
            logger.debug("Hours scrape failed: %s", e)
        return hours

    async def _scrape_rating_distribution(self, page: Page) -> dict:
        dist = {}
        try:
            rows = page.locator(RATING_HIST_SELECTOR)
            count = await rows.count()
            for i in range(count):
                row = rows.nth(i)
                label = await row.get_attribute("aria-label") or ""
                m = re.match(r"(\d)\s*(?:star|نجمة).*?([\d,]+)\s*(?:review|تعليق)", label, re.I)
                if m:
                    dist[m.group(1)] = int(m.group(2).replace(",", ""))
        except Exception as e:
            logger.debug("Rating distribution scrape failed: %s", e)
        return dist

    async def _scrape_reviews(self, page: Page) -> list[Review]:
        reviews = []
        seen_hashes = set() # To prevent duplicates
        try:
            # Click "Reviews" tab
            tab_locator = page.locator('button[role="tab"]').filter(has_text=re.compile(r"Reviews|المراجعات", re.IGNORECASE))
            if await tab_locator.count() > 0:
                await tab_locator.first.click()
                await page.wait_for_selector('div.MyEned', timeout=5000)

                # Sort by "Newest"
                sort_btn = page.locator('button[data-value="Sort"], button[aria-label*="ترتيب"], button:has-text("Sort"), button:has-text("ترتيب")').first
                if await sort_btn.count() > 0:
                    await sort_btn.click()
                    await page.wait_for_timeout(800)
                    newest = page.locator('li[role="menuitemradio"], div[role="menuitem"]').filter(has_text=re.compile(r"Newest|الأحدث", re.IGNORECASE))
                    if await newest.count() > 0:
                        await newest.first.click()
                        await page.wait_for_timeout(2000)

                # Scroll to load more reviews
                scroll_panel = page.locator('div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde').first
                if await scroll_panel.count() == 0:
                     scroll_panel = page.locator('div[role="main"]').first
                
                previous_count = 0
                for _ in range(500):  # Scroll enough to hit max_reviews or bottom
                    try:
                        await scroll_panel.evaluate("el => el.scrollBy(0, 2000)")
                        await page.wait_for_timeout(1000)
                        
                        items = page.locator(REVIEW_ITEM_SELECTOR)
                        current_count = await items.count()
                        if current_count >= self.max_reviews or current_count == previous_count:
                            break
                        previous_count = current_count
                    except Exception:
                        await page.mouse.wheel(0, 1500)
                        await page.wait_for_timeout(1000)

                items = page.locator(REVIEW_ITEM_SELECTOR)
                count = await items.count()
                target_count = min(count, self.max_reviews)

                for i in range(target_count):
                    item = items.nth(i)
                    try:
                        # Expand "More"
                        more_btn = item.locator('button[jsaction*="pane.review.expandReview"], button:has-text("More"), button:has-text("المزيد")').first
                        if await more_btn.count() > 0 and await more_btn.is_visible():
                            await more_btn.click()
                            await page.wait_for_timeout(200)

                        author_el = item.locator(REVIEW_AUTHOR_SELECTOR)
                        author    = clean_text(await author_el.inner_text()) if await author_el.count() else "Anonymous"

                        rating_el  = item.locator('span[role="img"][aria-label*="star"], span[role="img"][aria-label*="نجم"]')
                        rating_lbl = (await rating_el.first.get_attribute("aria-label")) if await rating_el.count() else ""
                        rating_match = re.search(r"(\d)", rating_lbl)
                        rating_val = int(rating_match.group(1)) if rating_match else 0

                        text_el = item.locator(REVIEW_TEXT_SELECTOR)
                        text    = clean_text(await text_el.inner_text()) if await text_el.count() else ""

                        date_el = item.locator(REVIEW_DATE_SELECTOR)
                        date    = clean_text(await date_el.inner_text()) if await date_el.count() else ""

                        likes_el = item.locator(REVIEW_LIKES_SELECTOR)
                        likes_str = clean_text(await likes_el.inner_text()) if await likes_el.count() else "0"
                        likes = int(re.sub(r"\D", "", likes_str)) if likes_str else 0

                        # Deduplication Logic
                        review_hash = f"{author}_{date}_{text[:20]}"
                        if review_hash not in seen_hashes:
                            seen_hashes.add(review_hash)
                            reviews.append(Review(
                                author=author,
                                rating=rating_val,
                                text=text,
                                date=date,
                                likes=likes,
                            ))
                    except Exception as e:
                        logger.debug("Failed to parse review %d: %s", i, e)

        except Exception as e:
            logger.debug("Review scrape failed: %s", e)

        return reviews


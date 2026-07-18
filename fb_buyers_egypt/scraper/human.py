"""
Human Behavior Simulation Module
=================================
Makes browser automation indistinguishable from real user activity.

- Bezier-curve mouse movement (not teleporting)
- Realistic typing with variable cadence
- Natural scroll patterns with reading pauses
- Random idle actions
- Session warmup routine
"""

import math
import time
import random
import logging
from typing import Tuple, List, Optional
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  BEZIER MOUSE MOVEMENT
# ---------------------------------------------------------------------------

def _bezier_point(t: float, points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Calculate a point on a Bezier curve at parameter t (0..1)."""
    n = len(points) - 1
    x = 0.0
    y = 0.0
    for i, (px, py) in enumerate(points):
        coeff = _binomial(n, i) * (t ** i) * ((1 - t) ** (n - i))
        x += coeff * px
        y += coeff * py
    return x, y


def _binomial(n: int, k: int) -> int:
    return math.factorial(n) // (math.factorial(k) * math.factorial(n - k))


def _generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int = None,
) -> List[Tuple[float, float]]:
    """
    Generate a smooth curved path from start to end using a cubic Bezier
    with randomized control points so each path looks unique.
    """
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    if steps is None:
        steps = max(15, min(80, int(dist / 8)))

    # Random control points offset perpendicular to the line
    mid_x = (start[0] + end[0]) / 2
    mid_y = (start[1] + end[1]) / 2
    spread = dist * random.uniform(0.15, 0.45)
    angle = math.atan2(end[1] - start[1], end[0] - start[0]) + math.pi / 2

    cp1 = (
        start[0] + (mid_x - start[0]) * random.uniform(0.2, 0.5) + math.cos(angle) * spread * random.choice([-1, 1]),
        start[1] + (mid_y - start[1]) * random.uniform(0.2, 0.5) + math.sin(angle) * spread * random.choice([-1, 1]),
    )
    cp2 = (
        end[0] - (end[0] - mid_x) * random.uniform(0.2, 0.5) + math.cos(angle) * spread * random.uniform(-0.5, 0.5),
        end[1] - (end[1] - mid_y) * random.uniform(0.2, 0.5) + math.sin(angle) * spread * random.uniform(-0.5, 0.5),
    )

    points = [start, cp1, cp2, end]
    path = []
    for i in range(steps + 1):
        t = i / steps
        # Ease-in-out for natural acceleration
        t = t * t * (3.0 - 2.0 * t)
        path.append(_bezier_point(t, points))
    return path


def move_mouse_to(page: Page, x: float, y: float):
    """
    Move mouse to (x, y) along a Bezier curve with human-like speed.
    """
    try:
        current = page.evaluate("() => ({x: window._mouseX || 0, y: window._mouseY || 0})")
        start = (current.get("x", random.randint(100, 400)),
                 current.get("y", random.randint(100, 300)))
    except Exception:
        start = (random.randint(100, 400), random.randint(100, 300))

    path = _generate_bezier_path(start, (x, y))

    for px, py in path:
        page.mouse.move(px, py)
        time.sleep(random.uniform(0.003, 0.018))

    # Track position for next call
    page.evaluate(f"() => {{ window._mouseX = {x}; window._mouseY = {y}; }}")


def move_mouse_to_element(page: Page, selector: str):
    """Move mouse to an element using Bezier curve, then return the element's box."""
    try:
        el = page.query_selector(selector)
        if not el:
            return None
        box = el.bounding_box()
        if not box:
            return None
        # Target a random point within the element (not always center)
        tx = box["x"] + box["width"] * random.uniform(0.2, 0.8)
        ty = box["y"] + box["height"] * random.uniform(0.2, 0.8)
        move_mouse_to(page, tx, ty)
        return box
    except Exception as e:
        logger.debug(f"move_mouse_to_element error: {e}")
        return None


# ---------------------------------------------------------------------------
#  REALISTIC TYPING
# ---------------------------------------------------------------------------

def human_type(page: Page, selector: str, text: str, click_first: bool = True):
    """
    Type text into an input field with human-like cadence:
    - Variable inter-key delay
    - Occasional brief pauses (thinking)
    - Random speed bursts and slowdowns
    """
    if click_first:
        box = move_mouse_to_element(page, selector)
        if box:
            time.sleep(random.uniform(0.1, 0.3))
            page.mouse.click(
                box["x"] + box["width"] * random.uniform(0.3, 0.7),
                box["y"] + box["height"] * random.uniform(0.3, 0.7),
            )
            time.sleep(random.uniform(0.2, 0.5))
        else:
            page.click(selector)
            time.sleep(random.uniform(0.2, 0.4))

    base_delay = random.uniform(0.04, 0.10)

    for i, char in enumerate(text):
        page.keyboard.type(char)

        # Variable delay
        delay = base_delay * random.uniform(0.5, 2.0)

        # Occasional thinking pause (every ~8-15 chars)
        if random.random() < 0.07:
            delay += random.uniform(0.3, 0.8)

        # Slight pause after special chars
        if char in "@._-":
            delay += random.uniform(0.1, 0.3)

        time.sleep(delay)

    # Brief pause after finishing
    time.sleep(random.uniform(0.3, 0.8))


# ---------------------------------------------------------------------------
#  NATURAL SCROLLING
# ---------------------------------------------------------------------------

def human_scroll(page: Page, direction: str = "down", intensity: str = "normal"):
    """
    Scroll with human-like behavior:
    - Variable scroll distance
    - Occasional pauses to 'read'
    - Sometimes scroll back up a tiny bit
    - Speed varies throughout
    """
    intensities = {
        "gentle": (200, 400, 3, 5),
        "normal": (400, 800, 4, 7),
        "fast":   (700, 1200, 5, 9),
    }
    min_dist, max_dist, min_steps, max_steps = intensities.get(
        intensity, intensities["normal"]
    )

    total_distance = random.randint(min_dist, max_dist)
    if direction == "up":
        total_distance = -total_distance

    num_steps = random.randint(min_steps, max_steps)
    step_size = total_distance / num_steps

    for i in range(num_steps):
        # Each step has slight variation
        actual_step = step_size * random.uniform(0.6, 1.4)
        page.evaluate(f"window.scrollBy(0, {int(actual_step)})")

        # Reading pause — more likely in middle of scroll
        if random.random() < 0.15:
            time.sleep(random.uniform(0.8, 2.5))  # reading something
        else:
            time.sleep(random.uniform(0.05, 0.2))

    # Occasionally scroll back up slightly (natural behavior)
    if direction == "down" and random.random() < 0.12:
        backtrack = random.randint(50, 150)
        page.evaluate(f"window.scrollBy(0, {-backtrack})")
        time.sleep(random.uniform(0.5, 1.5))

    # Final reading pause
    time.sleep(random.uniform(0.5, 1.5))


def scroll_feed(page: Page, pause_to_read: bool = True):
    """
    Scroll down the feed one 'page' — simulates a real user browsing.
    Occasionally pauses longer to 'read a post'.
    """
    human_scroll(page, "down", random.choice(["gentle", "normal", "normal", "fast"]))

    if pause_to_read and random.random() < 0.25:
        # Simulate reading a post
        read_time = random.uniform(2.0, 6.0)
        logger.debug(f"  👀 Reading pause: {read_time:.1f}s")
        time.sleep(read_time)


# ---------------------------------------------------------------------------
#  RANDOM IDLE / NATURAL ACTIONS
# ---------------------------------------------------------------------------

def random_idle(page: Page):
    """
    Perform a random 'idle' action that a real user might do:
    - Move mouse aimlessly
    - Hover over a random element
    - Brief pause
    """
    action = random.choice(["mouse_wander", "hover_random", "pause"])

    if action == "mouse_wander":
        viewport = page.viewport_size
        if viewport:
            tx = random.randint(50, viewport["width"] - 50)
            ty = random.randint(50, viewport["height"] - 50)
            move_mouse_to(page, tx, ty)
            time.sleep(random.uniform(0.3, 1.0))

    elif action == "hover_random":
        # Hover over some visible element
        try:
            elements = page.query_selector_all("a, span, div[role='button']")
            if elements:
                el = random.choice(elements[:20])
                box = el.bounding_box()
                if box and box["y"] > 0 and box["y"] < 800:
                    move_mouse_to(
                        page,
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    time.sleep(random.uniform(0.5, 1.5))
        except Exception:
            pass

    else:  # pause
        time.sleep(random.uniform(1.0, 3.0))


# ---------------------------------------------------------------------------
#  SESSION WARMUP
# ---------------------------------------------------------------------------

def session_warmup(page: Page):
    """
    Before scraping, behave like a real user:
    1. Visit Facebook homepage
    2. Scroll the feed briefly
    3. Maybe check notifications
    4. Pause naturally
    """
    logger.info("🔥 Session warmup — acting natural ...")

    try:
        # 1. Home page
        page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=20_000)
        time.sleep(random.uniform(2, 4))

        # 2. Scroll news feed a bit
        for _ in range(random.randint(2, 4)):
            human_scroll(page, "down", "gentle")
            time.sleep(random.uniform(1, 3))

        # 3. Maybe hover over notifications
        if random.random() < 0.5:
            for sel in ['a[href="/notifications"]', '[aria-label="Notifications"]',
                        '[aria-label="الإشعارات"]']:
                try:
                    el = page.query_selector(sel)
                    if el:
                        box = el.bounding_box()
                        if box:
                            move_mouse_to(page, box["x"] + box["width"]/2,
                                         box["y"] + box["height"]/2)
                            time.sleep(random.uniform(1, 2))
                        break
                except Exception:
                    pass

        # 4. Pause
        time.sleep(random.uniform(1, 3))
        logger.info("✅ Warmup complete")

    except Exception as e:
        logger.warning(f"Warmup issue (non-fatal): {e}")


# ---------------------------------------------------------------------------
#  DELAY HELPERS
# ---------------------------------------------------------------------------

def natural_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Sleep for a random duration with human-like distribution."""
    # Use log-normal for more natural pauses (cluster around smaller values)
    mean = (min_s + max_s) / 2
    delay = max(min_s, min(max_s, random.lognormvariate(math.log(mean), 0.3)))
    time.sleep(delay)


def between_groups_delay():
    """Longer pause between groups to look natural."""
    delay = random.uniform(8, 20)
    logger.info(f"  ⏳ Between-groups pause: {delay:.0f}s")
    time.sleep(delay)


def long_break():
    """Occasional long break to avoid detection."""
    delay = random.uniform(30, 90)
    logger.info(f"  😴 Long break: {delay:.0f}s")
    time.sleep(delay)

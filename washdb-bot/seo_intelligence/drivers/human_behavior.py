"""
Human Behavior Simulation Utilities

Provides realistic human-like behavior for browser automation:
- Bezier curve mouse movements
- Natural scrolling patterns
- Safe element clicking
- Human-like typing
- Reading simulation

These utilities help evade bot detection by mimicking real user behavior.
"""

import random
import time
import math
import json
import os
from typing import Any, List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path

from runner.logging_setup import get_logger

logger = get_logger("human_behavior")


# =============================================================================
# Bezier Curve Mouse Movement
# =============================================================================

def _bezier_point(t: float, p0: Tuple[float, float], p1: Tuple[float, float],
                  p2: Tuple[float, float], p3: Tuple[float, float]) -> Tuple[float, float]:
    """
    Calculate a point on a cubic bezier curve.

    Args:
        t: Parameter from 0 to 1
        p0-p3: Control points

    Returns:
        (x, y) point on the curve
    """
    u = 1 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]

    return (x, y)


def generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    num_points: int = 50,
    curve_variance: float = 0.3
) -> List[Tuple[float, float]]:
    """
    Generate a natural-looking mouse path using bezier curves.

    Real mouse movements are never straight lines - they follow curved
    paths with slight overshoots and corrections.

    Args:
        start: Starting (x, y) position
        end: Ending (x, y) position
        num_points: Number of points in the path
        curve_variance: How much the curve can deviate (0-1)

    Returns:
        List of (x, y) points forming the path
    """
    # Calculate distance for scaling
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.sqrt(dx * dx + dy * dy)

    # Generate control points with randomness
    # Control points pull the curve in natural directions
    variance = distance * curve_variance

    # First control point - biased toward start
    cp1 = (
        start[0] + dx * 0.25 + random.uniform(-variance, variance) * 0.5,
        start[1] + dy * 0.25 + random.uniform(-variance, variance) * 0.5
    )

    # Second control point - biased toward end
    cp2 = (
        start[0] + dx * 0.75 + random.uniform(-variance, variance) * 0.5,
        start[1] + dy * 0.75 + random.uniform(-variance, variance) * 0.5
    )

    # Generate path points
    path = []
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 0

        # Add slight noise to simulate hand tremor
        point = _bezier_point(t, start, cp1, cp2, end)

        # Small random jitter (human hands aren't perfectly steady)
        jitter = 0.5 if t > 0.1 and t < 0.9 else 0  # Less jitter at start/end
        point = (
            point[0] + random.uniform(-jitter, jitter),
            point[1] + random.uniform(-jitter, jitter)
        )

        path.append(point)

    return path


def move_mouse_naturally_selenium(driver: Any, target_x: int, target_y: int) -> bool:
    """
    Move mouse to target position using natural bezier curve path (Selenium).

    Args:
        driver: Selenium WebDriver
        target_x: Target X coordinate
        target_y: Target Y coordinate

    Returns:
        True if successful
    """
    try:
        from selenium.webdriver.common.action_chains import ActionChains

        # Get current mouse position (approximate from page center if unknown)
        try:
            current_pos = driver.execute_script("""
                return {
                    x: window.mouseX || window.innerWidth / 2,
                    y: window.mouseY || window.innerHeight / 2
                };
            """)
            start_x = current_pos.get('x', target_x - 100)
            start_y = current_pos.get('y', target_y - 100)
        except Exception:
            # Random starting position near target
            start_x = target_x + random.randint(-200, 200)
            start_y = target_y + random.randint(-200, 200)

        # Generate natural path
        path = generate_bezier_path(
            (start_x, start_y),
            (target_x, target_y),
            num_points=random.randint(25, 40),
            curve_variance=random.uniform(0.15, 0.35)
        )

        # Move along path with varying speed
        actions = ActionChains(driver)

        # Reset to starting position
        actions.move_by_offset(int(start_x - target_x), int(start_y - target_y))

        prev_point = path[0]
        for i, point in enumerate(path[1:], 1):
            dx = int(point[0] - prev_point[0])
            dy = int(point[1] - prev_point[1])

            if dx != 0 or dy != 0:
                actions.move_by_offset(dx, dy)

                # Variable speed - slower at start and end (acceleration curve)
                progress = i / len(path)
                if progress < 0.2 or progress > 0.8:
                    actions.pause(random.uniform(0.01, 0.03))
                else:
                    actions.pause(random.uniform(0.005, 0.015))

            prev_point = point

        actions.perform()

        # Track mouse position for future movements
        driver.execute_script(f"window.mouseX = {target_x}; window.mouseY = {target_y};")

        return True

    except Exception as e:
        logger.debug(f"Natural mouse move failed: {e}")
        return False


def move_mouse_naturally_playwright(page: Any, target_x: int, target_y: int) -> bool:
    """
    Move mouse to target position using natural bezier curve path (Playwright/Camoufox).

    Args:
        page: Playwright page object
        target_x: Target X coordinate
        target_y: Target Y coordinate

    Returns:
        True if successful
    """
    try:
        # Get current mouse position
        try:
            current_pos = page.evaluate("""
                () => ({
                    x: window.mouseX || window.innerWidth / 2,
                    y: window.mouseY || window.innerHeight / 2
                })
            """)
            start_x = current_pos.get('x', target_x - 100)
            start_y = current_pos.get('y', target_y - 100)
        except Exception:
            start_x = target_x + random.randint(-200, 200)
            start_y = target_y + random.randint(-200, 200)

        # Generate natural path
        path = generate_bezier_path(
            (start_x, start_y),
            (target_x, target_y),
            num_points=random.randint(20, 35),
            curve_variance=random.uniform(0.15, 0.35)
        )

        # Move along path
        for i, (x, y) in enumerate(path):
            page.mouse.move(x, y)

            # Variable delays
            progress = i / len(path)
            if progress < 0.2 or progress > 0.8:
                time.sleep(random.uniform(0.008, 0.02))
            else:
                time.sleep(random.uniform(0.003, 0.01))

        # Track position
        page.evaluate(f"() => {{ window.mouseX = {target_x}; window.mouseY = {target_y}; }}")

        return True

    except Exception as e:
        logger.debug(f"Natural mouse move (Playwright) failed: {e}")
        return False


# =============================================================================
# Human-Like Scrolling
# =============================================================================

def scroll_naturally_selenium(
    driver: Any,
    direction: str = "down",
    scroll_back_chance: float = 0.3
) -> None:
    """
    Scroll page with realistic human behavior (Selenium).

    Real users:
    - Scroll in variable amounts
    - Pause to read
    - Sometimes scroll back up
    - Don't scroll at uniform speeds

    Args:
        driver: Selenium WebDriver
        direction: "down" or "up"
        scroll_back_chance: Probability of scrolling back (0-1)
    """
    try:
        page_height = driver.execute_script("return document.body.scrollHeight")
        viewport_height = driver.execute_script("return window.innerHeight")

        if page_height <= viewport_height:
            time.sleep(random.uniform(2, 5))
            return

        current_pos = driver.execute_script("return window.pageYOffset")
        scroll_increments = random.randint(3, 7)

        for i in range(scroll_increments):
            # Variable scroll amount - smaller near top, larger in middle
            base_amount = random.randint(120, 450)
            if i == 0:
                scroll_amount = base_amount * 0.6  # Start slower
            elif i == scroll_increments - 1:
                scroll_amount = base_amount * 0.5  # End slower
            else:
                scroll_amount = base_amount

            if direction == "up":
                scroll_amount = -scroll_amount

            target_pos = current_pos + scroll_amount
            target_pos = max(0, min(target_pos, page_height - viewport_height))

            # Smooth scroll with easing
            driver.execute_script(f"""
                window.scrollTo({{
                    top: {target_pos},
                    behavior: 'smooth'
                }});
            """)
            current_pos = target_pos

            # Variable reading pause
            if i == 0:
                time.sleep(random.uniform(1.5, 3.5))  # Longer initial read
            else:
                time.sleep(random.uniform(0.6, 2.0))

        # Sometimes scroll back up (real users re-read)
        if random.random() < scroll_back_chance:
            scroll_back = random.randint(80, 350)
            driver.execute_script(f"""
                window.scrollBy({{
                    top: -{scroll_back},
                    behavior: 'smooth'
                }});
            """)
            time.sleep(random.uniform(0.8, 2.0))

    except Exception as e:
        logger.debug(f"Natural scroll (Selenium) error: {e}")


def scroll_naturally_playwright(
    page: Any,
    direction: str = "down",
    scroll_back_chance: float = 0.3
) -> None:
    """
    Scroll page with realistic human behavior (Playwright/Camoufox).

    Args:
        page: Playwright page object
        direction: "down" or "up"
        scroll_back_chance: Probability of scrolling back (0-1)
    """
    try:
        page_height = page.evaluate("() => document.body.scrollHeight")
        viewport_height = page.evaluate("() => window.innerHeight")

        if page_height <= viewport_height:
            time.sleep(random.uniform(2, 5))
            return

        scroll_increments = random.randint(3, 7)

        for i in range(scroll_increments):
            # Variable scroll amount
            base_amount = random.randint(120, 450)
            if i == 0:
                scroll_amount = int(base_amount * 0.6)
            elif i == scroll_increments - 1:
                scroll_amount = int(base_amount * 0.5)
            else:
                scroll_amount = base_amount

            if direction == "up":
                scroll_amount = -scroll_amount

            # Use mouse wheel for more natural scrolling
            page.mouse.wheel(0, scroll_amount)

            # Variable reading pause
            if i == 0:
                time.sleep(random.uniform(1.5, 3.5))
            else:
                time.sleep(random.uniform(0.6, 2.0))

        # Sometimes scroll back up
        if random.random() < scroll_back_chance:
            scroll_back = random.randint(80, 350)
            page.mouse.wheel(0, -scroll_back)
            time.sleep(random.uniform(0.8, 2.0))

    except Exception as e:
        logger.debug(f"Natural scroll (Playwright) error: {e}")


# =============================================================================
# Safe Element Clicking
# =============================================================================

SAFE_CLICK_JS = """
() => {
    const safeElements = [];
    const clickables = document.querySelectorAll('a, button, [role="button"], [onclick]');

    for (let el of clickables) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();

        // Must be visible
        if (style.display === 'none' ||
            style.visibility === 'hidden' ||
            style.opacity === '0' ||
            rect.width === 0 ||
            rect.height === 0) {
            continue;
        }

        // Must be in viewport
        if (rect.top < 0 || rect.top > window.innerHeight ||
            rect.left < 0 || rect.left > window.innerWidth) {
            continue;
        }

        // Skip external links (could be traps)
        if (el.tagName === 'A' && el.href) {
            try {
                const url = new URL(el.href, window.location.origin);
                if (url.origin !== window.location.origin) {
                    continue;
                }
            } catch (e) {
                continue;
            }
        }

        // Skip form submissions
        if (el.type === 'submit' || el.closest('form')) {
            continue;
        }

        // Skip honeypots (hidden elements with deceptive positioning)
        if (rect.width < 5 || rect.height < 5) {
            continue;
        }

        // Skip elements with suspicious classes
        const classList = el.className.toLowerCase();
        if (classList.includes('honey') || classList.includes('trap') ||
            classList.includes('bot') || classList.includes('captcha')) {
            continue;
        }

        safeElements.push({
            tag: el.tagName,
            text: (el.textContent || '').trim().substring(0, 50),
            x: rect.x + rect.width / 2,
            y: rect.y + rect.height / 2,
            width: rect.width,
            height: rect.height
        });
    }

    return safeElements.slice(0, 15);
}
"""


def click_safe_element_selenium(driver: Any) -> bool:
    """
    Click a random safe element with natural mouse movement (Selenium).

    Args:
        driver: Selenium WebDriver

    Returns:
        True if clicked successfully
    """
    try:
        safe_elements = driver.execute_script(SAFE_CLICK_JS)

        if not safe_elements:
            return False

        # Pick a random safe element
        element = random.choice(safe_elements)
        logger.debug(f"Clicking safe element: {element['tag']} - {element['text'][:30]}")

        # Move mouse naturally to element
        target_x = int(element['x'] + random.uniform(-3, 3))
        target_y = int(element['y'] + random.uniform(-3, 3))

        if move_mouse_naturally_selenium(driver, target_x, target_y):
            time.sleep(random.uniform(0.1, 0.3))

        # Click with slight delay
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(driver)
        actions.click().perform()

        time.sleep(random.uniform(0.5, 1.5))
        return True

    except Exception as e:
        logger.debug(f"Safe click (Selenium) failed: {e}")
        return False


def click_safe_element_playwright(page: Any) -> bool:
    """
    Click a random safe element with natural mouse movement (Playwright/Camoufox).

    Args:
        page: Playwright page object

    Returns:
        True if clicked successfully
    """
    try:
        safe_elements = page.evaluate(SAFE_CLICK_JS)

        if not safe_elements:
            return False

        # Pick a random safe element
        element = random.choice(safe_elements)
        logger.debug(f"Clicking safe element: {element['tag']} - {element['text'][:30]}")

        # Move mouse naturally to element
        target_x = int(element['x'] + random.uniform(-3, 3))
        target_y = int(element['y'] + random.uniform(-3, 3))

        move_mouse_naturally_playwright(page, target_x, target_y)
        time.sleep(random.uniform(0.1, 0.3))

        # Click
        page.mouse.click(target_x, target_y)

        time.sleep(random.uniform(0.5, 1.5))
        return True

    except Exception as e:
        logger.debug(f"Safe click (Playwright) failed: {e}")
        return False


# =============================================================================
# Human-Like Typing
# =============================================================================

def type_naturally_selenium(driver: Any, element: Any, text: str) -> bool:
    """
    Type text with human-like timing variations (Selenium).

    Real typing:
    - Variable delays between characters
    - Occasional pauses (thinking)
    - Sometimes makes and corrects typos
    - Faster for common words, slower for unusual ones

    Args:
        driver: Selenium WebDriver
        element: Element to type into
        text: Text to type

    Returns:
        True if successful
    """
    try:
        from selenium.webdriver.common.keys import Keys

        # Focus element
        element.click()
        time.sleep(random.uniform(0.1, 0.3))

        i = 0
        while i < len(text):
            char = text[i]

            # Occasional typo (2% chance)
            if random.random() < 0.02 and char.isalpha():
                # Type wrong character
                nearby_keys = _get_nearby_keys(char)
                if nearby_keys:
                    wrong_char = random.choice(nearby_keys)
                    element.send_keys(wrong_char)
                    time.sleep(random.uniform(0.1, 0.3))
                    # Delete and correct
                    element.send_keys(Keys.BACKSPACE)
                    time.sleep(random.uniform(0.05, 0.15))

            # Type the character
            element.send_keys(char)

            # Variable delay based on character type
            if char == ' ':
                # Pause between words
                time.sleep(random.uniform(0.08, 0.25))
            elif char in '.,!?':
                # Longer pause after punctuation
                time.sleep(random.uniform(0.15, 0.4))
            else:
                # Normal character delay
                time.sleep(random.uniform(0.04, 0.12))

            # Occasional thinking pause (1% chance)
            if random.random() < 0.01:
                time.sleep(random.uniform(0.3, 0.8))

            i += 1

        return True

    except Exception as e:
        logger.debug(f"Natural typing (Selenium) failed: {e}")
        return False


def type_naturally_playwright(page: Any, selector: str, text: str) -> bool:
    """
    Type text with human-like timing variations (Playwright/Camoufox).

    Args:
        page: Playwright page object
        selector: Element selector
        text: Text to type

    Returns:
        True if successful
    """
    try:
        element = page.wait_for_selector(selector, timeout=5000)
        if not element:
            return False

        # Focus element
        element.click()
        time.sleep(random.uniform(0.1, 0.3))

        i = 0
        while i < len(text):
            char = text[i]

            # Occasional typo (2% chance)
            if random.random() < 0.02 and char.isalpha():
                nearby_keys = _get_nearby_keys(char)
                if nearby_keys:
                    wrong_char = random.choice(nearby_keys)
                    page.keyboard.type(wrong_char)
                    time.sleep(random.uniform(0.1, 0.3))
                    page.keyboard.press("Backspace")
                    time.sleep(random.uniform(0.05, 0.15))

            # Type the character
            page.keyboard.type(char)

            # Variable delay
            if char == ' ':
                time.sleep(random.uniform(0.08, 0.25))
            elif char in '.,!?':
                time.sleep(random.uniform(0.15, 0.4))
            else:
                time.sleep(random.uniform(0.04, 0.12))

            # Occasional thinking pause
            if random.random() < 0.01:
                time.sleep(random.uniform(0.3, 0.8))

            i += 1

        return True

    except Exception as e:
        logger.debug(f"Natural typing (Playwright) failed: {e}")
        return False


def _get_nearby_keys(char: str) -> List[str]:
    """Get keys that are physically near a given key on QWERTY keyboard."""
    keyboard_neighbors = {
        'q': ['w', 'a'], 'w': ['q', 'e', 's'], 'e': ['w', 'r', 'd'],
        'r': ['e', 't', 'f'], 't': ['r', 'y', 'g'], 'y': ['t', 'u', 'h'],
        'u': ['y', 'i', 'j'], 'i': ['u', 'o', 'k'], 'o': ['i', 'p', 'l'],
        'p': ['o', 'l'], 'a': ['q', 's', 'z'], 's': ['a', 'w', 'd', 'x'],
        'd': ['s', 'e', 'f', 'c'], 'f': ['d', 'r', 'g', 'v'],
        'g': ['f', 't', 'h', 'b'], 'h': ['g', 'y', 'j', 'n'],
        'j': ['h', 'u', 'k', 'm'], 'k': ['j', 'i', 'l'],
        'l': ['k', 'o', 'p'], 'z': ['a', 's', 'x'], 'x': ['z', 's', 'd', 'c'],
        'c': ['x', 'd', 'f', 'v'], 'v': ['c', 'f', 'g', 'b'],
        'b': ['v', 'g', 'h', 'n'], 'n': ['b', 'h', 'j', 'm'],
        'm': ['n', 'j', 'k']
    }
    return keyboard_neighbors.get(char.lower(), [])


# =============================================================================
# Reading Simulation
# =============================================================================

def simulate_reading_selenium(driver: Any, min_time: float = 3, max_time: float = 8) -> None:
    """
    Simulate human reading behavior with realistic scroll and pause patterns.

    Args:
        driver: Selenium WebDriver
        min_time: Minimum time to spend "reading"
        max_time: Maximum time to spend "reading"
    """
    try:
        page_height = driver.execute_script("return document.body.scrollHeight")
        viewport_height = driver.execute_script("return window.innerHeight")

        if page_height <= viewport_height:
            time.sleep(random.uniform(min_time, max_time))
            return

        # Scroll and read
        scroll_naturally_selenium(driver, "down", scroll_back_chance=0.35)

        # Sometimes click something
        if random.random() < 0.2:
            click_safe_element_selenium(driver)

    except Exception as e:
        logger.debug(f"Reading simulation error: {e}")
        time.sleep(random.uniform(min_time, max_time))


def simulate_reading_playwright(page: Any, min_time: float = 3, max_time: float = 8) -> None:
    """
    Simulate human reading behavior (Playwright/Camoufox).

    Args:
        page: Playwright page object
        min_time: Minimum time to spend "reading"
        max_time: Maximum time to spend "reading"
    """
    try:
        page_height = page.evaluate("() => document.body.scrollHeight")
        viewport_height = page.evaluate("() => window.innerHeight")

        if page_height <= viewport_height:
            time.sleep(random.uniform(min_time, max_time))
            return

        # Scroll and read
        scroll_naturally_playwright(page, "down", scroll_back_chance=0.35)

        # Sometimes click something
        if random.random() < 0.2:
            click_safe_element_playwright(page)

    except Exception as e:
        logger.debug(f"Reading simulation (Playwright) error: {e}")
        time.sleep(random.uniform(min_time, max_time))


# =============================================================================
# F-Pattern and Z-Pattern Reading Simulation
# =============================================================================

def simulate_f_pattern_selenium(driver: Any, thorough: bool = True) -> None:
    """
    Simulate F-pattern reading behavior (Selenium).

    The F-pattern is the most common reading pattern on web pages:
    1. Horizontal scan across the top (headline area)
    2. Short horizontal scan in the middle (subheadline/first paragraph)
    3. Vertical scan down the left side (scanning for keywords)

    This mimics how real users scan content-heavy pages like directories.

    Args:
        driver: Selenium WebDriver
        thorough: If True, spend more time on each section
    """
    try:
        viewport_height = driver.execute_script("return window.innerHeight")
        page_height = driver.execute_script("return document.body.scrollHeight")

        # Phase 1: Horizontal scan at top (reading headline)
        driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        time.sleep(random.uniform(1.5, 3.0) if thorough else random.uniform(0.8, 1.5))

        # Simulate eye movement across top with mouse
        try:
            viewport_width = driver.execute_script("return window.innerWidth")
            # Move mouse from left to right across top area
            move_mouse_naturally_selenium(driver, int(viewport_width * 0.2), 150)
            time.sleep(random.uniform(0.3, 0.6))
            move_mouse_naturally_selenium(driver, int(viewport_width * 0.7), 150)
            time.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

        # Phase 2: Scroll down and horizontal scan (first content section)
        scroll_amount = min(300, page_height // 4)
        driver.execute_script(f"window.scrollTo({{top: {scroll_amount}, behavior: 'smooth'}});")
        time.sleep(random.uniform(1.0, 2.0) if thorough else random.uniform(0.5, 1.0))

        # Another horizontal eye movement
        try:
            move_mouse_naturally_selenium(driver, int(viewport_width * 0.15), 200)
            time.sleep(random.uniform(0.2, 0.4))
            move_mouse_naturally_selenium(driver, int(viewport_width * 0.5), 220)
            time.sleep(random.uniform(0.4, 0.8))
        except Exception:
            pass

        # Phase 3: Vertical scan down left side (the "F" stem)
        scan_positions = [
            scroll_amount + viewport_height * 0.3,
            scroll_amount + viewport_height * 0.6,
            scroll_amount + viewport_height * 0.9,
            scroll_amount + viewport_height * 1.2,
        ]

        for i, pos in enumerate(scan_positions):
            if pos >= page_height - viewport_height:
                break

            driver.execute_script(f"window.scrollTo({{top: {int(pos)}, behavior: 'smooth'}});")

            # Vary read time based on position (less time as we go down)
            if i == 0:
                read_time = random.uniform(1.5, 2.5) if thorough else random.uniform(0.8, 1.2)
            else:
                read_time = random.uniform(0.6, 1.2) if thorough else random.uniform(0.3, 0.6)

            time.sleep(read_time)

            # Occasional re-read (scroll back slightly)
            if random.random() < 0.15:
                driver.execute_script(f"window.scrollBy({{top: -{random.randint(50, 150)}, behavior: 'smooth'}});")
                time.sleep(random.uniform(0.5, 1.0))

        logger.debug("Completed F-pattern reading simulation")

    except Exception as e:
        logger.debug(f"F-pattern simulation (Selenium) error: {e}")


def simulate_f_pattern_playwright(page: Any, thorough: bool = True) -> None:
    """
    Simulate F-pattern reading behavior (Playwright/Camoufox).

    Args:
        page: Playwright page object
        thorough: If True, spend more time on each section
    """
    try:
        viewport_height = page.evaluate("() => window.innerHeight")
        viewport_width = page.evaluate("() => window.innerWidth")
        page_height = page.evaluate("() => document.body.scrollHeight")

        # Phase 1: Horizontal scan at top
        page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(random.uniform(1.5, 3.0) if thorough else random.uniform(0.8, 1.5))

        # Mouse movement across top
        try:
            move_mouse_naturally_playwright(page, int(viewport_width * 0.2), 150)
            time.sleep(random.uniform(0.3, 0.6))
            move_mouse_naturally_playwright(page, int(viewport_width * 0.7), 150)
            time.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

        # Phase 2: Scroll and horizontal scan
        scroll_amount = min(300, page_height // 4)
        page.evaluate(f"() => window.scrollTo({{top: {scroll_amount}, behavior: 'smooth'}})")
        time.sleep(random.uniform(1.0, 2.0) if thorough else random.uniform(0.5, 1.0))

        try:
            move_mouse_naturally_playwright(page, int(viewport_width * 0.15), 200)
            time.sleep(random.uniform(0.2, 0.4))
            move_mouse_naturally_playwright(page, int(viewport_width * 0.5), 220)
            time.sleep(random.uniform(0.4, 0.8))
        except Exception:
            pass

        # Phase 3: Vertical scan
        scan_positions = [
            scroll_amount + viewport_height * 0.3,
            scroll_amount + viewport_height * 0.6,
            scroll_amount + viewport_height * 0.9,
            scroll_amount + viewport_height * 1.2,
        ]

        for i, pos in enumerate(scan_positions):
            if pos >= page_height - viewport_height:
                break

            page.evaluate(f"() => window.scrollTo({{top: {int(pos)}, behavior: 'smooth'}})")

            if i == 0:
                read_time = random.uniform(1.5, 2.5) if thorough else random.uniform(0.8, 1.2)
            else:
                read_time = random.uniform(0.6, 1.2) if thorough else random.uniform(0.3, 0.6)

            time.sleep(read_time)

            if random.random() < 0.15:
                page.mouse.wheel(0, -random.randint(50, 150))
                time.sleep(random.uniform(0.5, 1.0))

        logger.debug("Completed F-pattern reading simulation")

    except Exception as e:
        logger.debug(f"F-pattern simulation (Playwright) error: {e}")


def simulate_z_pattern_selenium(driver: Any) -> None:
    """
    Simulate Z-pattern reading behavior (Selenium).

    The Z-pattern is common for pages with less text and more visual elements:
    1. Scan top-left to top-right (header/navigation)
    2. Diagonal scan to bottom-left
    3. Scan bottom-left to bottom-right (CTA area)

    Good for landing pages and simple directory listings.

    Args:
        driver: Selenium WebDriver
    """
    try:
        viewport_width = driver.execute_script("return window.innerWidth")
        viewport_height = driver.execute_script("return window.innerHeight")

        # Start at top
        driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        time.sleep(random.uniform(0.5, 1.0))

        # Z stroke 1: Top-left to top-right
        move_mouse_naturally_selenium(driver, int(viewport_width * 0.1), 100)
        time.sleep(random.uniform(0.3, 0.5))
        move_mouse_naturally_selenium(driver, int(viewport_width * 0.9), 100)
        time.sleep(random.uniform(0.8, 1.5))

        # Z stroke 2: Diagonal to bottom-left
        move_mouse_naturally_selenium(driver, int(viewport_width * 0.1), int(viewport_height * 0.7))
        time.sleep(random.uniform(0.5, 1.0))

        # Z stroke 3: Bottom-left to bottom-right
        move_mouse_naturally_selenium(driver, int(viewport_width * 0.9), int(viewport_height * 0.7))
        time.sleep(random.uniform(0.8, 1.5))

        logger.debug("Completed Z-pattern reading simulation")

    except Exception as e:
        logger.debug(f"Z-pattern simulation (Selenium) error: {e}")


def simulate_z_pattern_playwright(page: Any) -> None:
    """
    Simulate Z-pattern reading behavior (Playwright/Camoufox).

    Args:
        page: Playwright page object
    """
    try:
        viewport_width = page.evaluate("() => window.innerWidth")
        viewport_height = page.evaluate("() => window.innerHeight")

        # Start at top
        page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(random.uniform(0.5, 1.0))

        # Z stroke 1
        move_mouse_naturally_playwright(page, int(viewport_width * 0.1), 100)
        time.sleep(random.uniform(0.3, 0.5))
        move_mouse_naturally_playwright(page, int(viewport_width * 0.9), 100)
        time.sleep(random.uniform(0.8, 1.5))

        # Z stroke 2
        move_mouse_naturally_playwright(page, int(viewport_width * 0.1), int(viewport_height * 0.7))
        time.sleep(random.uniform(0.5, 1.0))

        # Z stroke 3
        move_mouse_naturally_playwright(page, int(viewport_width * 0.9), int(viewport_height * 0.7))
        time.sleep(random.uniform(0.8, 1.5))

        logger.debug("Completed Z-pattern reading simulation")

    except Exception as e:
        logger.debug(f"Z-pattern simulation (Playwright) error: {e}")

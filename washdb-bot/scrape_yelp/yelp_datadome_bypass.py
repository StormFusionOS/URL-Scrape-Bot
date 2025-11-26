#!/usr/bin/env python3
"""
DataDome bypass utilities for Yelp scraping.

DataDome is a sophisticated bot detection service that Yelp uses.
This module implements advanced evasion techniques to bypass DataDome's detection.
"""

import asyncio
import random
import math
from typing import Optional
from playwright.async_api import Page

from runner.logging_setup import get_logger

logger = get_logger("yelp_datadome_bypass")


class MouseSimulator:
    """Simulate realistic mouse movements to avoid bot detection."""

    @staticmethod
    def bezier_curve(start_x: float, start_y: float, end_x: float, end_y: float, steps: int = 50):
        """
        Generate points along a bezier curve for natural mouse movement.

        Args:
            start_x, start_y: Starting position
            end_x, end_y: Ending position
            steps: Number of steps in the curve

        Returns:
            List of (x, y) coordinate tuples
        """
        # Generate two random control points for the bezier curve
        control1_x = start_x + (end_x - start_x) * random.uniform(0.2, 0.4)
        control1_y = start_y + (end_y - start_y) * random.uniform(-0.3, 0.3)

        control2_x = start_x + (end_x - start_x) * random.uniform(0.6, 0.8)
        control2_y = start_y + (end_y - start_y) * random.uniform(-0.3, 0.3)

        points = []
        for i in range(steps):
            t = i / steps

            # Cubic bezier curve formula
            x = (1-t)**3 * start_x + 3*(1-t)**2*t * control1_x + 3*(1-t)*t**2 * control2_x + t**3 * end_x
            y = (1-t)**3 * start_y + 3*(1-t)**2*t * control1_y + 3*(1-t)*t**2 * control2_y + t**3 * end_y

            points.append((x, y))

        return points

    @staticmethod
    async def move_mouse_naturally(page: Page, from_x: int, from_y: int, to_x: int, to_y: int):
        """
        Move mouse cursor naturally along a bezier curve.

        Args:
            page: Playwright page
            from_x, from_y: Starting position
            to_x, to_y: Ending position
        """
        try:
            points = MouseSimulator.bezier_curve(from_x, from_y, to_x, to_y)

            for x, y in points:
                await page.mouse.move(x, y)
                # Small random delay to simulate human movement speed
                await asyncio.sleep(random.uniform(0.001, 0.003))

        except Exception as e:
            logger.debug(f"Error in mouse movement: {e}")

    @staticmethod
    async def random_mouse_movements(page: Page, num_movements: int = 3):
        """
        Perform random mouse movements on the page to simulate human behavior.

        Args:
            page: Playwright page
            num_movements: Number of random movements to perform
        """
        try:
            viewport_size = page.viewport_size
            if not viewport_size:
                return

            width = viewport_size['width']
            height = viewport_size['height']

            current_x = random.randint(width // 4, 3 * width // 4)
            current_y = random.randint(height // 4, 3 * height // 4)

            for _ in range(num_movements):
                # Generate random target position
                target_x = random.randint(50, width - 50)
                target_y = random.randint(50, height - 50)

                await MouseSimulator.move_mouse_naturally(page, current_x, current_y, target_x, target_y)

                # Pause at destination
                await asyncio.sleep(random.uniform(0.1, 0.3))

                current_x, current_y = target_x, target_y

        except Exception as e:
            logger.debug(f"Error in random mouse movements: {e}")

    @staticmethod
    async def hover_element(page: Page, selector: str):
        """
        Hover over an element with natural mouse movement.

        Args:
            page: Playwright page
            selector: CSS selector of element to hover
        """
        try:
            element = await page.query_selector(selector)
            if element:
                box = await element.bounding_box()
                if box:
                    # Get current mouse position (approximate center of viewport)
                    viewport = page.viewport_size
                    if viewport:
                        from_x = viewport['width'] // 2
                        from_y = viewport['height'] // 2

                        # Target center of element with slight random offset
                        to_x = box['x'] + box['width'] / 2 + random.randint(-5, 5)
                        to_y = box['y'] + box['height'] / 2 + random.randint(-5, 5)

                        await MouseSimulator.move_mouse_naturally(page, from_x, from_y, int(to_x), int(to_y))
                        await asyncio.sleep(random.uniform(0.05, 0.15))

        except Exception as e:
            logger.debug(f"Error hovering element: {e}")


class DataDomeBypass:
    """Advanced techniques to bypass DataDome bot detection."""

    @staticmethod
    async def simulate_human_page_load(page: Page):
        """
        Simulate human-like behavior when a page loads.

        Args:
            page: Playwright page
        """
        try:
            # Wait for page to be fully loaded
            await asyncio.sleep(random.uniform(0.5, 1.0))

            # Perform random mouse movements
            await MouseSimulator.random_mouse_movements(page, num_movements=random.randint(2, 4))

            # Scroll a bit
            scroll_amount = random.randint(100, 300)
            await page.evaluate(f'window.scrollBy(0, {scroll_amount})')
            await asyncio.sleep(random.uniform(0.3, 0.6))

            # Scroll back up slightly
            scroll_back = random.randint(50, 150)
            await page.evaluate(f'window.scrollBy(0, -{scroll_back})')
            await asyncio.sleep(random.uniform(0.2, 0.4))

            logger.debug("Human-like page load simulation completed")

        except Exception as e:
            logger.warning(f"Error simulating human behavior: {e}")

    @staticmethod
    async def simulate_reading_page(page: Page, duration: float = None):
        """
        Simulate a human reading the page with occasional mouse movements and scrolls.

        Args:
            page: Playwright page
            duration: How long to simulate reading (seconds). If None, uses random duration.
        """
        try:
            if duration is None:
                duration = random.uniform(2.0, 5.0)

            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < duration:
                action = random.choice(['scroll', 'mouse_move', 'pause'])

                if action == 'scroll':
                    # Scroll down or up
                    direction = random.choice([1, -1])
                    amount = random.randint(50, 200)
                    await page.evaluate(f'window.scrollBy(0, {direction * amount})')
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                elif action == 'mouse_move':
                    # Random mouse movement
                    await MouseSimulator.random_mouse_movements(page, num_movements=1)
                    await asyncio.sleep(random.uniform(0.3, 0.8))

                else:  # pause
                    # Just pause, simulating reading
                    await asyncio.sleep(random.uniform(1.0, 2.0))

            logger.debug(f"Simulated reading page for {duration:.2f} seconds")

        except Exception as e:
            logger.warning(f"Error simulating reading: {e}")

    @staticmethod
    async def handle_datadome_challenge(page: Page, max_wait: int = 30) -> bool:
        """
        Attempt to detect and wait for DataDome challenge to complete.

        Args:
            page: Playwright page
            max_wait: Maximum seconds to wait for challenge

        Returns:
            True if challenge appears to be passed, False otherwise
        """
        try:
            logger.info("Checking for DataDome challenge...")

            # Check if we're on a DataDome challenge page
            html = await page.content()

            if 'datadome' in html.lower() or 'captcha-delivery.com' in html:
                logger.warning("DataDome challenge detected! Waiting for resolution...")

                # Simulate human-like waiting behavior
                for _ in range(max_wait):
                    await asyncio.sleep(1)

                    # Perform occasional mouse movements
                    if random.random() < 0.3:
                        await MouseSimulator.random_mouse_movements(page, num_movements=1)

                    # Check if we've moved past the challenge
                    current_html = await page.content()
                    if 'datadome' not in current_html.lower() and 'captcha-delivery.com' not in current_html:
                        logger.info("DataDome challenge appears to be resolved!")
                        return True

                logger.error("DataDome challenge did not resolve within timeout")
                return False

            return True  # No challenge detected

        except Exception as e:
            logger.error(f"Error handling DataDome challenge: {e}")
            return False

    @staticmethod
    def get_enhanced_chrome_args():
        """
        Get enhanced Chrome arguments for better DataDome evasion.

        Returns:
            List of Chrome arguments
        """
        return [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--allow-running-insecure-content',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--disable-hang-monitor',
            '--metrics-recording-only',
            '--no-first-run',
            '--safebrowsing-disable-auto-update',
            '--enable-features=NetworkService,NetworkServiceInProcess',
            '--disable-sync',
            '--disable-breakpad',
            '--disable-component-update',
            '--disable-domain-reliability',
            '--disable-features=AudioServiceOutOfProcess',
            '--disable-software-rasterizer',
            '--mute-audio',
        ]

    @staticmethod
    def get_enhanced_headers():
        """
        Get enhanced HTTP headers that look more like a real browser.

        Returns:
            Dict of HTTP headers
        """
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
        }

    @staticmethod
    async def inject_datadome_evasion_scripts(page: Page):
        """
        Inject JavaScript to further evade DataDome detection.

        Args:
            page: Playwright page
        """
        try:
            # Override navigator.webdriver
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # Add realistic plugins
            await page.add_init_script("""
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' }
                    ]
                });
            """)

            # Mock permissions
            await page.add_init_script("""
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)

            # Add realistic chrome runtime
            await page.add_init_script("""
                window.chrome = {
                    runtime: {}
                };
            """)

            logger.debug("DataDome evasion scripts injected")

        except Exception as e:
            logger.warning(f"Error injecting evasion scripts: {e}")

#!/usr/bin/env python3
"""
HomeAdvisor browser automation using Playwright with stealth mode.

This module provides browser-based scraping for HomeAdvisor since they use
JavaScript to dynamically load business listings. Uses anti-detection
techniques to bypass Cloudflare bot protection.
"""
from __future__ import annotations
import time
import os
import random
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
from playwright_stealth.stealth import Stealth

from runner.logging_setup import get_logger

logger = get_logger("ha_browser")


class HomeAdvisorBrowser:
    """
    Browser automation for HomeAdvisor scraping.

    Uses Playwright to load pages and wait for JavaScript-rendered content.
    """

    def __init__(self, headless: bool = True, timeout: int = 60000):
        """
        Initialize browser automation with anti-detection.

        Args:
            headless: Run browser in headless mode
            timeout: Page load timeout in milliseconds (default 60s for Cloudflare)
        """
        self.headless = headless
        self.timeout = timeout
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context = None
        self.pages_loaded = 0

        # Session persistence directory
        self.session_dir = Path(__file__).parent.parent / "data" / "browser_sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        """Context manager entry - start browser."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close browser."""
        self.close()

    def start(self):
        """Start Playwright with stealth mode and persistent session."""
        if self.playwright is None:
            logger.info("[Browser] Starting Playwright with stealth mode")
            self.playwright = sync_playwright().start()

            # Enhanced browser args to avoid detection
            browser_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-setuid-sandbox',
                '--no-first-run',
                '--no-default-browser-check',
                '--password-store=basic',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
            ]

            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=browser_args
            )

            # Create persistent context with cookies/session
            self.context = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York',
                permissions=['geolocation'],
                geolocation={'latitude': 47.6062, 'longitude': -122.3321},  # Seattle coords
                color_scheme='light',
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                }
            )

            logger.info("[Browser] Browser launched with anti-detection")

    def close(self):
        """Close browser context and Playwright."""
        if self.context:
            self.context.close()
            self.context = None
        if self.browser:
            logger.info(f"[Browser] Closing browser (loaded {self.pages_loaded} pages)")
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None

    def fetch_page(self, url: str, wait_for_selector: str = None, delay: int = 2) -> Optional[str]:
        """
        Fetch a page using Playwright with stealth mode and return the HTML after JavaScript execution.

        Args:
            url: URL to fetch
            wait_for_selector: CSS selector to wait for before extracting HTML
            delay: Additional delay in seconds after page load (default 2s for faster crawling)

        Returns:
            Page HTML content or None if failed
        """
        if not self.context:
            self.start()

        page: Page = None
        try:
            # Create new page from context
            page = self.context.new_page()

            # Apply stealth mode to hide automation
            stealth = Stealth()
            stealth.apply_stealth_sync(page)

            logger.info(f"[Browser] Loading {url}")

            # Random delay before navigation (human-like behavior)
            time.sleep(random.uniform(0.5, 1.5))

            # Navigate to URL with longer timeout for Cloudflare
            page.goto(url, wait_until='domcontentloaded', timeout=self.timeout)

            # Wait for Cloudflare challenge to complete
            logger.debug("[Browser] Waiting for Cloudflare challenge...")
            time.sleep(random.uniform(2.5, 4))  # Reduced delay for faster crawling

            # Wait for specific selector if provided
            if wait_for_selector:
                try:
                    logger.debug(f"[Browser] Waiting for selector: {wait_for_selector}")
                    page.wait_for_selector(wait_for_selector, timeout=15000)
                    logger.debug(f"[Browser] Selector found: {wait_for_selector}")
                except PlaywrightTimeout:
                    logger.warning(f"[Browser] Timeout waiting for selector: {wait_for_selector}")
                    # Continue anyway - page might have loaded

            # Additional delay to ensure JavaScript has executed
            if delay > 0:
                time.sleep(random.uniform(delay - 1, delay + 1))

            # Extract HTML
            html = page.content()
            self.pages_loaded += 1

            logger.info(f"[Browser] Page loaded successfully ({len(html)} chars)")
            return html

        except PlaywrightTimeout as e:
            logger.error(f"[Browser] Timeout loading {url}: {e}")
            if page:
                # Try to get HTML even if timeout
                try:
                    html = page.content()
                    if len(html) > 1000:
                        logger.info(f"[Browser] Partial page loaded ({len(html)} chars)")
                        return html
                except:
                    pass
            return None
        except Exception as e:
            logger.error(f"[Browser] Error loading {url}: {e}", exc_info=True)
            return None
        finally:
            if page:
                page.close()


# Global browser instance for reuse across requests
_browser_instance: Optional[HomeAdvisorBrowser] = None


def get_browser() -> HomeAdvisorBrowser:
    """Get or create global browser instance."""
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = HomeAdvisorBrowser(headless=True)
        _browser_instance.start()
    return _browser_instance


def close_global_browser():
    """Close the global browser instance."""
    global _browser_instance
    if _browser_instance:
        _browser_instance.close()
        _browser_instance = None

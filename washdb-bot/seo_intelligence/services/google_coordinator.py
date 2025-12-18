"""
Google Request Coordinator

Centralizes all Google requests to:
1. Prevent simultaneous requests from multiple scrapers
2. Optionally share a single browser session
3. Enforce proper delays between requests
4. Respect domain quarantine globally

This solves the problem of multiple SEO modules (SERP, Autocomplete, KeywordIntelligence)
hitting Google in quick succession with separate browser sessions, which triggers CAPTCHAs.
"""

import threading
import time
import random
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

from seo_intelligence.services.rate_limiter import get_rate_limiter
from seo_intelligence.services.domain_quarantine import get_domain_quarantine
from seo_intelligence.drivers import get_driver_for_site
from runner.logging_setup import get_logger

logger = get_logger("google_coordinator")

GOOGLE_DOMAIN = "www.google.com"
MIN_DELAY_BETWEEN_REQUESTS = 15.0  # seconds
MAX_DELAY_BETWEEN_REQUESTS = 30.0  # seconds


@dataclass(order=True)
class GoogleRequest:
    """A queued Google request with priority."""
    priority: int
    request_type: str = field(compare=False)
    callback: Callable = field(compare=False)
    created_at: float = field(default_factory=time.time, compare=False)


class GoogleCoordinator:
    """
    Coordinates all Google requests across SEO modules.

    Ensures only one request hits Google at a time with proper delays.
    Optionally shares a single browser session across all modules.
    """

    def __init__(self, share_browser: bool = True):
        """
        Initialize the Google Coordinator.

        Args:
            share_browser: If True, share a single browser session for all Google requests.
                          If False, create a new browser for each request.
        """
        self.share_browser = share_browser
        self.rate_limiter = get_rate_limiter()
        self.quarantine = get_domain_quarantine()

        self._browser = None
        self._browser_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_time = 0.0

        # Set Google to Tier A (strictest rate limiting)
        self.rate_limiter.set_domain_tier(GOOGLE_DOMAIN, "A")

        logger.info(f"GoogleCoordinator initialized (share_browser={share_browser})")

    def is_quarantined(self) -> bool:
        """Check if Google is currently quarantined due to CAPTCHA detection."""
        return self.quarantine.is_quarantined(GOOGLE_DOMAIN)

    def get_quarantine_info(self) -> Optional[dict]:
        """Get quarantine information for Google if quarantined."""
        if self.is_quarantined():
            return self.quarantine.get_quarantine_info(GOOGLE_DOMAIN)
        return None

    def _get_delay(self) -> float:
        """Get randomized delay for next request (15-30s)."""
        return random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)

    def _ensure_delay(self):
        """Ensure minimum delay since last request."""
        if self._last_request_time == 0.0:
            # First request, no delay needed
            return

        elapsed = time.time() - self._last_request_time
        delay_needed = self._get_delay()

        if elapsed < delay_needed:
            wait_time = delay_needed - elapsed
            logger.debug(f"Waiting {wait_time:.1f}s before next Google request")
            time.sleep(wait_time)

    @contextmanager
    def _get_browser(self):
        """
        Get browser session (shared or new).

        Yields:
            Browser driver instance
        """
        if self.share_browser:
            with self._browser_lock:
                if self._browser is None:
                    logger.info("Creating shared Google browser session")
                    self._browser = get_driver_for_site(
                        site="google",
                        headless=True,
                        use_proxy=True,
                    )
                yield self._browser
        else:
            # Create new browser for this request
            logger.debug("Creating new browser for Google request")
            browser = get_driver_for_site(site="google", headless=True, use_proxy=True)
            try:
                yield browser
            finally:
                if browser:
                    try:
                        browser.quit()
                    except Exception:
                        pass

    def execute(
        self,
        request_type: str,
        callback: Callable[[Any], Any],
        priority: int = 5
    ) -> Any:
        """
        Execute a Google request with coordination.

        Args:
            request_type: Type of request ("serp", "autocomplete", "keyword", etc.)
            callback: Function that takes a browser driver and returns result
            priority: Request priority (1=highest, 10=lowest) - for future queue implementation

        Returns:
            Result from callback function, or None if quarantined/failed
        """
        # Check quarantine first
        if self.is_quarantined():
            info = self.get_quarantine_info()
            logger.warning(
                f"Google is quarantined, skipping {request_type} request. "
                f"Reason: {info.get('reason') if info else 'unknown'}"
            )
            return None

        # Serialize all Google requests
        with self._request_lock:
            # Ensure delay between requests
            self._ensure_delay()

            # Acquire rate limit token
            if not self.rate_limiter.acquire(GOOGLE_DOMAIN, wait=True, max_wait=120.0):
                logger.warning("Failed to acquire rate limit token for Google")
                return None

            try:
                with self._get_browser() as browser:
                    if browser is None:
                        logger.error("Failed to get browser for Google request")
                        return None

                    logger.debug(f"Executing {request_type} request via GoogleCoordinator")
                    result = callback(browser)

                    # Update last request time
                    self._last_request_time = time.time()

                    return result

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Google {request_type} request failed: {e}")

                # Check if CAPTCHA and quarantine
                if "captcha" in error_str or "unusual traffic" in error_str or "blocked" in error_str:
                    logger.warning("CAPTCHA/block detected, quarantining Google")
                    self.quarantine.quarantine_domain(
                        domain=GOOGLE_DOMAIN,
                        reason="CAPTCHA_DETECTED",
                        duration_minutes=60
                    )

                raise

    def execute_with_own_browser(
        self,
        request_type: str,
        scraper_method: Callable[[], Any],
        priority: int = 5
    ) -> Any:
        """
        Execute a request that uses its own browser, but with coordination.

        Use this when the scraper needs to manage its own browser lifecycle
        but still needs rate limiting and serialization.

        Args:
            request_type: Type of request ("serp", "autocomplete", etc.)
            scraper_method: Method to call (uses its own browser internally)
            priority: Request priority

        Returns:
            Result from scraper_method, or None if quarantined/failed
        """
        # Check quarantine first
        if self.is_quarantined():
            info = self.get_quarantine_info()
            logger.warning(
                f"Google is quarantined, skipping {request_type} request. "
                f"Reason: {info.get('reason') if info else 'unknown'}"
            )
            return None

        # Serialize all Google requests
        with self._request_lock:
            # Ensure delay between requests
            self._ensure_delay()

            # Acquire rate limit token
            if not self.rate_limiter.acquire(GOOGLE_DOMAIN, wait=True, max_wait=120.0):
                logger.warning("Failed to acquire rate limit token for Google")
                return None

            try:
                logger.debug(f"Executing {request_type} request (own browser) via GoogleCoordinator")
                result = scraper_method()

                # Update last request time
                self._last_request_time = time.time()

                return result

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Google {request_type} request failed: {e}")

                # Check if CAPTCHA and quarantine
                if "captcha" in error_str or "unusual traffic" in error_str or "blocked" in error_str:
                    logger.warning("CAPTCHA/block detected, quarantining Google")
                    self.quarantine.quarantine_domain(
                        domain=GOOGLE_DOMAIN,
                        reason="CAPTCHA_DETECTED",
                        duration_minutes=60
                    )

                raise

    def refresh_browser(self):
        """Force refresh of the shared browser session."""
        with self._browser_lock:
            if self._browser:
                try:
                    self._browser.quit()
                except Exception:
                    pass
                self._browser = None
        logger.info("Shared Google browser session refreshed")

    def close(self):
        """Close shared browser session and cleanup."""
        with self._browser_lock:
            if self._browser:
                try:
                    self._browser.quit()
                except Exception:
                    pass
                self._browser = None
        logger.info("GoogleCoordinator closed")

    def get_stats(self) -> dict:
        """Get coordinator statistics."""
        return {
            "share_browser": self.share_browser,
            "browser_active": self._browser is not None,
            "is_quarantined": self.is_quarantined(),
            "quarantine_info": self.get_quarantine_info(),
            "last_request_time": self._last_request_time,
            "seconds_since_last_request": time.time() - self._last_request_time if self._last_request_time > 0 else None,
            "min_delay": MIN_DELAY_BETWEEN_REQUESTS,
            "max_delay": MAX_DELAY_BETWEEN_REQUESTS,
        }


# Singleton instance
_coordinator_instance = None
_coordinator_lock = threading.Lock()


def get_google_coordinator(share_browser: bool = True) -> GoogleCoordinator:
    """
    Get or create the singleton GoogleCoordinator.

    Args:
        share_browser: If True, share browser session (only used on first call)

    Returns:
        GoogleCoordinator singleton instance
    """
    global _coordinator_instance

    with _coordinator_lock:
        if _coordinator_instance is None:
            _coordinator_instance = GoogleCoordinator(share_browser=share_browser)

    return _coordinator_instance


def reset_google_coordinator():
    """Reset the singleton coordinator (for testing)."""
    global _coordinator_instance

    with _coordinator_lock:
        if _coordinator_instance:
            _coordinator_instance.close()
        _coordinator_instance = None


if __name__ == "__main__":
    # Quick test
    coordinator = get_google_coordinator()
    print(f"Coordinator stats: {coordinator.get_stats()}")
    print(f"Is quarantined: {coordinator.is_quarantined()}")
    coordinator.close()

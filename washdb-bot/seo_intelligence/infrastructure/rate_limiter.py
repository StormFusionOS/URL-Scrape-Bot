"""
Rate limiter with per-domain throttling and retry logic.

Implements conservative rate limiting as specified:
- Global concurrency limits (max 3 sites, 5 pages each in flight)
- Per-domain delays with jitter (3-6 seconds + jitter)
- Respect robots.txt crawl-delay directives
- Exponential backoff for errors and 429s
- CAPTCHA/403 detection and 24h quarantine
"""
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, Optional
from urllib.parse import urlparse

from .robots_parser import get_crawl_delay

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Per-domain rate limiter with throttling, backoff, and quarantine.

    Features:
    - Per-domain request tracking with last_request_time
    - Configurable base delay (3-6 seconds) + random jitter
    - Honors robots.txt crawl-delay
    - Exponential backoff for retries (2^attempt * base_delay)
    - 24h quarantine for CAPTCHA/403 responses
    - 429 Retry-After header respect
    """

    def __init__(
        self,
        base_delay: float = 3.0,
        max_delay: float = 6.0,
        jitter: float = 1.0,
        quarantine_hours: int = 24
    ):
        """
        Initialize rate limiter.

        Args:
            base_delay: Minimum delay between requests in seconds (default: 3.0)
            max_delay: Maximum base delay in seconds (default: 6.0)
            jitter: Maximum random jitter to add in seconds (default: 1.0)
            quarantine_hours: Hours to quarantine domain after CAPTCHA/403 (default: 24)
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.quarantine_hours = quarantine_hours

        # Per-domain tracking
        self._last_request: Dict[str, float] = {}
        self._quarantined: Dict[str, datetime] = {}
        self._retry_delays: Dict[str, float] = defaultdict(lambda: self.base_delay)
        self._lock = Lock()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_delay(self, domain: str, attempt: int = 0) -> float:
        """
        Calculate delay for a domain.

        Args:
            domain: Domain to check
            attempt: Retry attempt number (0 = first request)

        Returns:
            Delay in seconds
        """
        # Check robots.txt crawl-delay
        crawl_delay = get_crawl_delay(domain)

        if crawl_delay is not None:
            # Honor robots.txt crawl-delay
            base = crawl_delay
        else:
            # Use configured base delay with randomization
            base = random.uniform(self.base_delay, self.max_delay)

        # Apply exponential backoff for retries
        if attempt > 0:
            base = base * (2 ** attempt)

        # Add jitter
        delay = base + random.uniform(0, self.jitter)

        return delay

    def is_quarantined(self, url: str) -> bool:
        """
        Check if domain is quarantined.

        Args:
            url: URL to check

        Returns:
            True if quarantined, False otherwise
        """
        domain = self._get_domain(url)

        with self._lock:
            if domain in self._quarantined:
                quarantine_end = self._quarantined[domain]
                if datetime.now() < quarantine_end:
                    remaining = (quarantine_end - datetime.now()).total_seconds() / 3600
                    logger.warning(
                        f"Domain {domain} is quarantined for {remaining:.1f} more hours"
                    )
                    return True
                else:
                    # Quarantine expired, remove it
                    del self._quarantined[domain]
                    logger.info(f"Domain {domain} quarantine expired")

        return False

    def quarantine(self, url: str, reason: str = "CAPTCHA/403"):
        """
        Quarantine a domain for 24 hours.

        Args:
            url: URL that triggered quarantine
            reason: Reason for quarantine (default: "CAPTCHA/403")
        """
        domain = self._get_domain(url)
        quarantine_end = datetime.now() + timedelta(hours=self.quarantine_hours)

        with self._lock:
            self._quarantined[domain] = quarantine_end

        logger.warning(
            f"Domain {domain} quarantined until {quarantine_end} (reason: {reason})"
        )

    def wait(self, url: str, attempt: int = 0):
        """
        Wait appropriate delay before making request.

        Args:
            url: URL to request
            attempt: Retry attempt number (0 = first request)

        Raises:
            Exception: If domain is quarantined
        """
        # Check if quarantined
        if self.is_quarantined(url):
            raise Exception(f"Domain is quarantined: {self._get_domain(url)}")

        domain = self._get_domain(url)

        with self._lock:
            # Calculate required delay
            delay = self._get_delay(domain, attempt)

            # Check last request time
            if domain in self._last_request:
                last_request_time = self._last_request[domain]
                time_since_last = time.time() - last_request_time
                remaining_delay = delay - time_since_last

                if remaining_delay > 0:
                    logger.debug(
                        f"Rate limiting {domain}: waiting {remaining_delay:.2f}s "
                        f"(delay={delay:.2f}s, attempt={attempt})"
                    )
                    time.sleep(remaining_delay)

            # Update last request time
            self._last_request[domain] = time.time()

    def handle_429(self, url: str, retry_after: Optional[int] = None):
        """
        Handle 429 Too Many Requests response.

        Args:
            url: URL that returned 429
            retry_after: Retry-After header value in seconds (optional)
        """
        domain = self._get_domain(url)

        if retry_after:
            # Honor Retry-After header
            delay = retry_after
        else:
            # Use aggressive backoff (10 minutes)
            delay = 600

        with self._lock:
            # Set custom delay for this domain
            self._retry_delays[domain] = delay

        logger.warning(
            f"429 Too Many Requests from {domain}, backing off {delay}s"
        )

    def reset_domain(self, url: str):
        """
        Reset rate limiting state for a domain.

        Args:
            url: URL whose domain to reset
        """
        domain = self._get_domain(url)

        with self._lock:
            if domain in self._last_request:
                del self._last_request[domain]
            if domain in self._retry_delays:
                del self._retry_delays[domain]
            if domain in self._quarantined:
                del self._quarantined[domain]

        logger.info(f"Rate limiter state reset for {domain}")


# Global rate limiter instance
rate_limiter = RateLimiter(
    base_delay=3.0,
    max_delay=6.0,
    jitter=1.0,
    quarantine_hours=24
)


# Convenience functions
def wait(url: str, attempt: int = 0):
    """
    Wait appropriate delay before making request.

    Args:
        url: URL to request
        attempt: Retry attempt number (0 = first request)
    """
    rate_limiter.wait(url, attempt)


def is_quarantined(url: str) -> bool:
    """Check if domain is quarantined."""
    return rate_limiter.is_quarantined(url)


def quarantine(url: str, reason: str = "CAPTCHA/403"):
    """Quarantine a domain for 24 hours."""
    rate_limiter.quarantine(url, reason)


def handle_429(url: str, retry_after: Optional[int] = None):
    """Handle 429 Too Many Requests response."""
    rate_limiter.handle_429(url, retry_after)


def reset_domain(url: str):
    """Reset rate limiting state for a domain."""
    rate_limiter.reset_domain(url)

"""
Shared HTTP client with robots.txt checking, rate limiting, and retry logic.

Provides a unified HTTP client that:
- Checks robots.txt before requests
- Applies per-domain rate limiting
- Implements exponential backoff for retries
- Detects and handles CAPTCHA/403/429 responses
- Logs structured metadata for all requests
"""
import logging
from typing import Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .rate_limiter import rate_limiter
from .robots_parser import can_fetch

logger = logging.getLogger(__name__)


class SEOHTTPClient:
    """
    HTTP client with robots checking, rate limiting, and retry logic.

    Usage:
        client = SEOHTTPClient()
        response = client.get("https://example.com")

        # Or with retry logic:
        response = client.get_with_retry("https://example.com", max_retries=3)
    """

    def __init__(
        self,
        user_agent: str = "SEO-Intelligence-Bot/1.0 (compatible; +https://github.com/StormFusionOS/URL-Scrape-Bot)",
        timeout: int = 30,
        max_retries: int = 2
    ):
        """
        Initialize HTTP client.

        Args:
            user_agent: User agent string
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum retry attempts for network errors (default: 2)
        """
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries

        # Create session with retry adapter for network errors
        self.session = requests.Session()

        # Configure retries for network errors and 5xx responses
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1s, 2s, 4s, 8s...
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

    def _check_response(self, response: requests.Response, url: str):
        """
        Check response for CAPTCHA, 403, or 429.

        Args:
            response: Response object
            url: URL that was requested

        Returns:
            Tuple of (reason_code, should_quarantine)
        """
        # Check for 429 Too Many Requests
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    retry_after = int(retry_after)
                except ValueError:
                    retry_after = None

            rate_limiter.handle_429(url, retry_after)
            return "RATE_LIMIT_429", False

        # Check for 403 Forbidden (potential block)
        if response.status_code == 403:
            # Check response content for CAPTCHA indicators
            content_lower = response.text.lower()
            if any(indicator in content_lower for indicator in ['captcha', 'recaptcha', 'hcaptcha']):
                rate_limiter.quarantine(url, "CAPTCHA_DETECTED")
                return "CAPTCHA_DETECTED", True
            else:
                rate_limiter.quarantine(url, "HARD_403")
                return "HARD_403", True

        return None, False

    def get(
        self,
        url: str,
        check_robots: bool = True,
        apply_rate_limit: bool = True,
        **kwargs
    ) -> Optional[requests.Response]:
        """
        Make HTTP GET request with robots checking and rate limiting.

        Args:
            url: URL to fetch
            check_robots: Whether to check robots.txt (default: True)
            apply_rate_limit: Whether to apply rate limiting (default: True)
            **kwargs: Additional arguments to pass to requests.get()

        Returns:
            Response object or None if robots.txt disallows

        Raises:
            Exception: If domain is quarantined or request fails
        """
        # Check robots.txt
        if check_robots and not can_fetch(url):
            logger.warning(f"Robots.txt disallows fetching: {url}")
            return None

        # Apply rate limiting
        if apply_rate_limit:
            rate_limiter.wait(url)

        # Make request
        start_time = requests.utils.default_timer()

        try:
            response = self.session.get(
                url,
                timeout=kwargs.pop('timeout', self.timeout),
                **kwargs
            )

            duration = requests.utils.default_timer() - start_time

            # Check for problematic responses
            reason_code, quarantined = self._check_response(response, url)

            # Log structured metadata
            logger.info(
                f"HTTP {response.status_code} {url} "
                f"({duration:.2f}s, {len(response.content)} bytes"
                f"{', ' + reason_code if reason_code else ''})"
            )

            if quarantined:
                raise Exception(f"Domain quarantined: {reason_code}")

            return response

        except requests.RequestException as e:
            duration = requests.utils.default_timer() - start_time
            logger.error(f"Request failed for {url} ({duration:.2f}s): {e}")
            raise

    def get_with_retry(
        self,
        url: str,
        max_retries: Optional[int] = None,
        check_robots: bool = True,
        **kwargs
    ) -> Optional[requests.Response]:
        """
        Make HTTP GET request with exponential backoff retries.

        Args:
            url: URL to fetch
            max_retries: Maximum retry attempts (default: use client's max_retries)
            check_robots: Whether to check robots.txt (default: True)
            **kwargs: Additional arguments to pass to requests.get()

        Returns:
            Response object or None if all retries failed

        Raises:
            Exception: If domain is quarantined
        """
        max_retries = max_retries or self.max_retries

        for attempt in range(max_retries + 1):
            try:
                response = self.get(
                    url,
                    check_robots=check_robots,
                    apply_rate_limit=True,
                    **kwargs
                )

                # Success
                if response and response.status_code == 200:
                    return response

                # 4xx errors (except 429) - don't retry
                if response and 400 <= response.status_code < 500 and response.status_code != 429:
                    logger.warning(
                        f"Client error {response.status_code} for {url}, not retrying"
                    )
                    return response

                # Retry on 5xx, 429, or other failures
                if attempt < max_retries:
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries + 1}), retrying..."
                    )
                    # Rate limiter will apply exponential backoff via attempt parameter
                    rate_limiter.wait(url, attempt=attempt + 1)
                    continue

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Request exception (attempt {attempt + 1}/{max_retries + 1}): {e}, retrying..."
                    )
                    rate_limiter.wait(url, attempt=attempt + 1)
                    continue
                else:
                    # Final attempt failed
                    raise

        # All retries exhausted
        logger.error(f"All {max_retries + 1} attempts failed for {url}")
        return None


# Global HTTP client instance
http_client = SEOHTTPClient()


# Convenience functions
def get(
    url: str,
    check_robots: bool = True,
    apply_rate_limit: bool = True,
    **kwargs
) -> Optional[requests.Response]:
    """
    Make HTTP GET request with robots checking and rate limiting.

    Args:
        url: URL to fetch
        check_robots: Whether to check robots.txt (default: True)
        apply_rate_limit: Whether to apply rate limiting (default: True)
        **kwargs: Additional arguments to pass to requests.get()

    Returns:
        Response object or None if robots.txt disallows
    """
    return http_client.get(url, check_robots, apply_rate_limit, **kwargs)


def get_with_retry(
    url: str,
    max_retries: Optional[int] = None,
    check_robots: bool = True,
    **kwargs
) -> Optional[requests.Response]:
    """
    Make HTTP GET request with exponential backoff retries.

    Args:
        url: URL to fetch
        max_retries: Maximum retry attempts (default: 2)
        check_robots: Whether to check robots.txt (default: True)
        **kwargs: Additional arguments to pass to requests.get()

    Returns:
        Response object or None if all retries failed
    """
    return http_client.get_with_retry(url, max_retries, check_robots, **kwargs)

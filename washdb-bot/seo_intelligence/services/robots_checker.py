"""
Robots.txt Compliance Checker

Ensures ethical scraping by respecting robots.txt rules.

Features:
- Fetch and parse robots.txt files
- Check if URLs are allowed for specific user agents
- Cache robots.txt files with TTL
- Support for crawl-delay directives
- Thread-safe implementation

Per SCRAPING_NOTES.md:
- "Never crawl paths explicitly disallowed in robots.txt"
- "Respect crawl-delay if present"
- "If robots.txt fetch fails, assume disallowed"
"""

import time
import requests
import threading
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from datetime import datetime, timedelta

from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("robots_checker")


class RobotsTxtCache:
    """Cache for robots.txt files with TTL."""

    def __init__(self, ttl_seconds: int = 86400):  # 24 hours default
        """
        Initialize robots.txt cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default: 86400 = 24 hours)
        """
        self.cache: Dict[str, Tuple[RobotFileParser, datetime]] = {}
        self.lock = threading.Lock()
        self.ttl = timedelta(seconds=ttl_seconds)

        logger.info(f"RobotsTxtCache initialized with TTL={ttl_seconds}s")

    def get(self, domain: str) -> Optional[RobotFileParser]:
        """
        Get cached robots.txt parser for a domain.

        Args:
            domain: Domain name

        Returns:
            RobotFileParser if cached and not expired, None otherwise
        """
        with self.lock:
            if domain in self.cache:
                parser, cached_at = self.cache[domain]
                age = datetime.now() - cached_at

                if age < self.ttl:
                    logger.debug(f"Cache HIT for {domain} (age: {age.total_seconds():.0f}s)")
                    return parser
                else:
                    logger.debug(f"Cache EXPIRED for {domain} (age: {age.total_seconds():.0f}s)")
                    del self.cache[domain]

            logger.debug(f"Cache MISS for {domain}")
            return None

    def set(self, domain: str, parser: RobotFileParser):
        """
        Cache robots.txt parser for a domain.

        Args:
            domain: Domain name
            parser: RobotFileParser instance
        """
        with self.lock:
            self.cache[domain] = (parser, datetime.now())
            logger.debug(f"Cached robots.txt for {domain}")

    def clear(self):
        """Clear all cached entries."""
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            logger.info(f"Cleared {count} cached robots.txt entries")


class RobotsChecker:
    """
    Robots.txt compliance checker.

    Fetches and parses robots.txt files, checks URL permissions,
    and enforces crawl-delay directives.
    """

    def __init__(
        self,
        user_agent: str = "WashbotSEO/1.0",
        cache_ttl: int = 86400,
        request_timeout: int = 10
    ):
        """
        Initialize robots checker.

        Args:
            user_agent: User agent string to identify our crawler
            cache_ttl: Cache TTL in seconds (default: 86400 = 24 hours)
            request_timeout: Timeout for robots.txt fetch in seconds
        """
        self.user_agent = user_agent
        self.request_timeout = request_timeout
        self.cache = RobotsTxtCache(ttl_seconds=cache_ttl)

        logger.info(f"RobotsChecker initialized with user_agent='{user_agent}'")

    def _get_robots_url(self, url: str) -> str:
        """
        Get robots.txt URL for a given URL.

        Args:
            url: URL to check

        Returns:
            str: robots.txt URL for the domain
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _fetch_robots_txt(self, domain: str, robots_url: str) -> Optional[RobotFileParser]:
        """
        Fetch and parse robots.txt file.

        Args:
            domain: Domain name
            robots_url: URL to robots.txt file

        Returns:
            RobotFileParser if successful, None otherwise
        """
        try:
            logger.debug(f"Fetching robots.txt from {robots_url}")

            # Fetch robots.txt with timeout
            response = requests.get(
                robots_url,
                headers={'User-Agent': self.user_agent},
                timeout=self.request_timeout,
                allow_redirects=True
            )

            # Handle different status codes
            if response.status_code == 404:
                logger.info(f"No robots.txt found for {domain} (404) - assuming allowed")
                # Create empty parser (allows all)
                parser = RobotFileParser()
                parser.parse([])
                return parser

            elif response.status_code == 200:
                logger.debug(f"Successfully fetched robots.txt for {domain}")

                # Parse robots.txt content
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                return parser

            else:
                logger.warning(
                    f"Unexpected status {response.status_code} for {robots_url} - assuming disallowed"
                )
                return None

        except requests.Timeout:
            logger.warning(f"Timeout fetching robots.txt from {robots_url} - assuming disallowed")
            return None

        except requests.RequestException as e:
            logger.error(f"Error fetching robots.txt from {robots_url}: {e} - assuming disallowed")
            return None

        except Exception as e:
            logger.error(f"Unexpected error parsing robots.txt from {robots_url}: {e}", exc_info=True)
            return None

    def _get_parser(self, url: str) -> Optional[RobotFileParser]:
        """
        Get RobotFileParser for a URL (cached or fetched).

        Args:
            url: URL to check

        Returns:
            RobotFileParser if available, None otherwise
        """
        parsed = urlparse(url)
        domain = parsed.netloc
        robots_url = self._get_robots_url(url)

        # Check cache first
        parser = self.cache.get(domain)
        if parser:
            return parser

        # Fetch and cache
        parser = self._fetch_robots_txt(domain, robots_url)
        if parser:
            self.cache.set(domain, parser)

        return parser

    def is_allowed(self, url: str, user_agent: Optional[str] = None) -> bool:
        """
        Check if URL is allowed by robots.txt.

        Per SCRAPING_NOTES.md: "If robots.txt fetch fails, assume disallowed"

        Args:
            url: URL to check
            user_agent: User agent to check (default: use instance user_agent)

        Returns:
            bool: True if allowed, False if disallowed or error
        """
        if user_agent is None:
            user_agent = self.user_agent

        parser = self._get_parser(url)

        if parser is None:
            # Fetch failed - assume disallowed per spec
            logger.warning(f"Could not fetch robots.txt for {url} - DISALLOWED")
            return False

        allowed = parser.can_fetch(user_agent, url)
        logger.debug(f"Robots.txt check for {url}: {'ALLOWED' if allowed else 'DISALLOWED'}")

        return allowed

    def get_crawl_delay(self, url: str, user_agent: Optional[str] = None) -> Optional[float]:
        """
        Get crawl delay specified in robots.txt.

        Args:
            url: URL to check
            user_agent: User agent to check (default: use instance user_agent)

        Returns:
            float: Crawl delay in seconds, or None if not specified
        """
        if user_agent is None:
            user_agent = self.user_agent

        parser = self._get_parser(url)

        if parser is None:
            return None

        try:
            delay = parser.crawl_delay(user_agent)
            if delay is not None:
                logger.info(f"Crawl delay for {urlparse(url).netloc}: {delay}s")
            return delay

        except Exception as e:
            logger.error(f"Error getting crawl delay for {url}: {e}")
            return None

    def get_request_rate(self, url: str, user_agent: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """
        Get request rate specified in robots.txt.

        Args:
            url: URL to check
            user_agent: User agent to check (default: use instance user_agent)

        Returns:
            Tuple of (requests, seconds) or None if not specified
            Example: (1, 3) means 1 request per 3 seconds
        """
        if user_agent is None:
            user_agent = self.user_agent

        parser = self._get_parser(url)

        if parser is None:
            return None

        try:
            rate = parser.request_rate(user_agent)
            if rate is not None:
                logger.info(f"Request rate for {urlparse(url).netloc}: {rate}")
            return rate

        except Exception as e:
            logger.error(f"Error getting request rate for {url}: {e}")
            return None

    def clear_cache(self):
        """Clear robots.txt cache."""
        self.cache.clear()

    def get_stats(self) -> Dict:
        """
        Get statistics about cached robots.txt files.

        Returns:
            dict: Statistics including cache size, user agent, etc.
        """
        with self.cache.lock:
            return {
                'user_agent': self.user_agent,
                'cache_size': len(self.cache.cache),
                'cache_ttl_seconds': self.cache.ttl.total_seconds(),
                'request_timeout': self.request_timeout,
            }


# Module-level singleton
_robots_checker_instance = None


def get_robots_checker(user_agent: str = "WashbotSEO/1.0") -> RobotsChecker:
    """Get or create the singleton RobotsChecker instance."""
    global _robots_checker_instance

    if _robots_checker_instance is None:
        _robots_checker_instance = RobotsChecker(user_agent=user_agent)

    return _robots_checker_instance


def main():
    """Demo: Test robots.txt checking."""
    logger.info("=" * 60)
    logger.info("Robots.txt Checker Demo")
    logger.info("=" * 60)
    logger.info("")

    checker = get_robots_checker(user_agent="WashbotSEO/1.0")

    # Test URLs
    test_urls = [
        "https://www.google.com/search",
        "https://www.google.com/",
        "https://example.com/page",
        "https://github.com/anthropics",
        "https://www.yelp.com/biz/some-business",
    ]

    logger.info("Test 1: Check URL permissions")
    for url in test_urls:
        allowed = checker.is_allowed(url)
        logger.info(f"  {url}")
        logger.info(f"    Allowed: {'✓' if allowed else '✗'}")

        # Check crawl delay
        delay = checker.get_crawl_delay(url)
        if delay:
            logger.info(f"    Crawl delay: {delay}s")

        logger.info("")

    # Test 2: Cache stats
    logger.info("Test 2: Cache statistics")
    stats = checker.get_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("")

    # Test 3: Re-check (should use cache)
    logger.info("Test 3: Re-check (cache hit)")
    allowed = checker.is_allowed("https://www.google.com/search")
    logger.info(f"  Google search allowed: {'✓' if allowed else '✗'}")
    logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

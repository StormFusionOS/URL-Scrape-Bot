"""
Robots.txt parser and cache for respecting crawler directives.

Parses and caches robots.txt per host, honoring Disallow/Allow rules
and crawl-delay directives as specified in the scraper requirements.
"""
import logging
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)


class RobotsCache:
    """
    Cache for robots.txt files with TTL and respect for crawl directives.

    Features:
    - Caches robots.txt per host with 24-hour TTL
    - Honors Disallow/Allow rules
    - Respects Crawl-delay directives
    - Returns crawl-delay value for rate limiting
    """

    def __init__(self, ttl_seconds: int = 86400, user_agent: str = "SEO-Intelligence-Bot"):
        """
        Initialize robots cache.

        Args:
            ttl_seconds: Time-to-live for cached robots.txt (default: 24 hours)
            user_agent: User agent string to check rules for
        """
        self.ttl_seconds = ttl_seconds
        self.user_agent = user_agent
        self._cache: Dict[str, Tuple[RobotFileParser, float, Optional[float]]] = {}

    def _get_robots_url(self, url: str) -> str:
        """
        Get robots.txt URL for a given URL.

        Args:
            url: Any URL on the domain

        Returns:
            robots.txt URL (e.g., https://example.com/robots.txt)
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _fetch_robots(self, robots_url: str) -> Tuple[RobotFileParser, Optional[float]]:
        """
        Fetch and parse robots.txt file.

        Args:
            robots_url: URL to robots.txt

        Returns:
            Tuple of (RobotFileParser, crawl_delay)
            crawl_delay is None if not specified
        """
        parser = RobotFileParser()
        parser.set_url(robots_url)

        try:
            # Fetch robots.txt content
            response = requests.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=10
            )

            if response.status_code == 200:
                # Parse the content
                lines = response.text.splitlines()
                parser.parse(lines)

                # Extract crawl-delay if present
                crawl_delay = None
                current_user_agent = None
                for line in lines:
                    line = line.strip()
                    if line.lower().startswith('user-agent:'):
                        current_user_agent = line.split(':', 1)[1].strip()
                    elif line.lower().startswith('crawl-delay:'):
                        # Check if this applies to our user agent or *
                        if current_user_agent in ('*', self.user_agent):
                            try:
                                crawl_delay = float(line.split(':', 1)[1].strip())
                            except (ValueError, IndexError):
                                pass

                logger.info(f"Fetched robots.txt from {robots_url} (crawl-delay: {crawl_delay}s)")
                return parser, crawl_delay

            elif response.status_code == 404:
                # No robots.txt = allow all
                logger.info(f"No robots.txt found at {robots_url}, allowing all")
                parser.allow_all = True
                return parser, None

            else:
                # Error fetching = allow all (fail open)
                logger.warning(
                    f"Error fetching robots.txt from {robots_url} "
                    f"(status {response.status_code}), allowing all"
                )
                parser.allow_all = True
                return parser, None

        except Exception as e:
            # Network error = allow all (fail open)
            logger.warning(f"Exception fetching robots.txt from {robots_url}: {e}, allowing all")
            parser.allow_all = True
            return parser, None

    def can_fetch(self, url: str) -> bool:
        """
        Check if URL can be fetched according to robots.txt.

        Args:
            url: URL to check

        Returns:
            True if allowed, False if disallowed
        """
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = self._get_robots_url(url)

        # Check cache
        if host in self._cache:
            parser, cache_time, crawl_delay = self._cache[host]
            # Check if cache is still valid
            if time.time() - cache_time < self.ttl_seconds:
                return parser.can_fetch(self.user_agent, url)
            else:
                # Cache expired, remove it
                del self._cache[host]

        # Fetch and cache robots.txt
        parser, crawl_delay = self._fetch_robots(robots_url)
        self._cache[host] = (parser, time.time(), crawl_delay)

        return parser.can_fetch(self.user_agent, url)

    def get_crawl_delay(self, url: str) -> Optional[float]:
        """
        Get crawl-delay for a URL from robots.txt.

        Args:
            url: URL to check

        Returns:
            Crawl delay in seconds, or None if not specified
        """
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = self._get_robots_url(url)

        # Check cache
        if host in self._cache:
            parser, cache_time, crawl_delay = self._cache[host]
            # Check if cache is still valid
            if time.time() - cache_time < self.ttl_seconds:
                return crawl_delay
            else:
                # Cache expired, remove it
                del self._cache[host]

        # Fetch and cache robots.txt
        parser, crawl_delay = self._fetch_robots(robots_url)
        self._cache[host] = (parser, time.time(), crawl_delay)

        return crawl_delay

    def clear_cache(self):
        """Clear the robots.txt cache."""
        self._cache.clear()
        logger.info("Robots cache cleared")


# Global robots cache instance
robots_cache = RobotsCache(
    user_agent="SEO-Intelligence-Bot/1.0 (compatible; +https://github.com/StormFusionOS/URL-Scrape-Bot)"
)


# Convenience functions
def can_fetch(url: str) -> bool:
    """
    Check if URL can be fetched according to robots.txt.

    Args:
        url: URL to check

    Returns:
        True if allowed, False if disallowed
    """
    return robots_cache.can_fetch(url)


def get_crawl_delay(url: str) -> Optional[float]:
    """
    Get crawl-delay for a URL from robots.txt.

    Args:
        url: URL to check

    Returns:
        Crawl delay in seconds, or None if not specified
    """
    return robots_cache.get_crawl_delay(url)


def clear_robots_cache():
    """Clear the robots.txt cache."""
    robots_cache.clear_cache()

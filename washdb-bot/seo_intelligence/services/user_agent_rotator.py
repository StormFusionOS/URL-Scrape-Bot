"""
User Agent Rotator Service

Provides rotating user agent strings for anti-detection.

Features:
- Pool of realistic user agent strings
- Random rotation
- Weighted selection (prefer common browsers)
- Support for different device types (desktop, mobile, tablet)
- Thread-safe implementation

Per SCRAPING_NOTES.md:
- "Rotate user agents to avoid fingerprinting"
- "Use realistic, common user agent strings"
- "Prefer recent browser versions"
"""

import random
import threading
from typing import List, Optional
from enum import Enum

from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("user_agent_rotator")


class DeviceType(Enum):
    """Device type for user agent selection."""
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"
    ANY = "any"


# Realistic user agent strings (recent versions as of 2024-2025)
DESKTOP_USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",

    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",

    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",

    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",

    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

MOBILE_USER_AGENTS = [
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",

    # Safari on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",

    # Firefox on Android
    "Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0",
]

TABLET_USER_AGENTS = [
    # Safari on iPad
    "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",

    # Chrome on Android Tablet
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Safari/537.36",
]

# Custom crawler user agent (identifies us as a bot)
CRAWLER_USER_AGENT = "WashbotSEO/1.0 (+https://washbot.com/seo-bot)"


class UserAgentRotator:
    """
    Service for rotating user agent strings.

    Provides random selection from a pool of realistic user agents
    with optional device type filtering.
    """

    def __init__(
        self,
        use_custom_crawler_ua: bool = False,
        device_weights: Optional[dict] = None
    ):
        """
        Initialize user agent rotator.

        Args:
            use_custom_crawler_ua: If True, always use custom crawler UA
            device_weights: Weights for device type selection
                           (default: {'desktop': 0.7, 'mobile': 0.25, 'tablet': 0.05})
        """
        self.use_custom_crawler_ua = use_custom_crawler_ua

        if device_weights is None:
            device_weights = {
                'desktop': 0.7,
                'mobile': 0.25,
                'tablet': 0.05
            }

        self.device_weights = device_weights
        self.lock = threading.Lock()

        # Build combined pool with weights
        self.user_agents = {
            DeviceType.DESKTOP: DESKTOP_USER_AGENTS,
            DeviceType.MOBILE: MOBILE_USER_AGENTS,
            DeviceType.TABLET: TABLET_USER_AGENTS,
        }

        logger.info(
            f"UserAgentRotator initialized: "
            f"{len(DESKTOP_USER_AGENTS)} desktop, "
            f"{len(MOBILE_USER_AGENTS)} mobile, "
            f"{len(TABLET_USER_AGENTS)} tablet UAs"
        )

    def get_random(self, device_type: DeviceType = DeviceType.ANY) -> str:
        """
        Get a random user agent string.

        Args:
            device_type: Device type to select from (default: ANY)

        Returns:
            str: Random user agent string
        """
        # Use custom crawler UA if enabled
        if self.use_custom_crawler_ua:
            logger.debug("Using custom crawler user agent")
            return CRAWLER_USER_AGENT

        with self.lock:
            if device_type == DeviceType.ANY:
                # Weighted random selection across device types
                device_type = random.choices(
                    population=[DeviceType.DESKTOP, DeviceType.MOBILE, DeviceType.TABLET],
                    weights=[
                        self.device_weights['desktop'],
                        self.device_weights['mobile'],
                        self.device_weights['tablet']
                    ],
                    k=1
                )[0]

            # Select random UA from chosen device type
            user_agents = self.user_agents[device_type]
            user_agent = random.choice(user_agents)

            logger.debug(f"Selected {device_type.value} user agent: {user_agent[:50]}...")
            return user_agent

    def get_desktop(self) -> str:
        """Get a random desktop user agent."""
        return self.get_random(DeviceType.DESKTOP)

    def get_mobile(self) -> str:
        """Get a random mobile user agent."""
        return self.get_random(DeviceType.MOBILE)

    def get_tablet(self) -> str:
        """Get a random tablet user agent."""
        return self.get_random(DeviceType.TABLET)

    def get_crawler(self) -> str:
        """Get the custom crawler user agent (identifies as bot)."""
        return CRAWLER_USER_AGENT

    def get_all(self, device_type: DeviceType = DeviceType.ANY) -> List[str]:
        """
        Get all available user agents for a device type.

        Args:
            device_type: Device type to filter by

        Returns:
            list: All user agent strings for the device type
        """
        if device_type == DeviceType.ANY:
            return DESKTOP_USER_AGENTS + MOBILE_USER_AGENTS + TABLET_USER_AGENTS
        else:
            return self.user_agents[device_type]

    def get_stats(self) -> dict:
        """
        Get statistics about user agent pool.

        Returns:
            dict: Statistics including counts and weights
        """
        return {
            'total_user_agents': len(DESKTOP_USER_AGENTS) + len(MOBILE_USER_AGENTS) + len(TABLET_USER_AGENTS),
            'desktop_count': len(DESKTOP_USER_AGENTS),
            'mobile_count': len(MOBILE_USER_AGENTS),
            'tablet_count': len(TABLET_USER_AGENTS),
            'device_weights': self.device_weights,
            'use_custom_crawler_ua': self.use_custom_crawler_ua,
            'crawler_ua': CRAWLER_USER_AGENT,
        }


# Module-level singleton
_user_agent_rotator_instance = None


def get_user_agent_rotator(use_custom_crawler_ua: bool = False) -> UserAgentRotator:
    """Get or create the singleton UserAgentRotator instance."""
    global _user_agent_rotator_instance

    if _user_agent_rotator_instance is None:
        _user_agent_rotator_instance = UserAgentRotator(use_custom_crawler_ua=use_custom_crawler_ua)

    return _user_agent_rotator_instance


def main():
    """Demo: Test user agent rotation."""
    logger.info("=" * 60)
    logger.info("User Agent Rotator Demo")
    logger.info("=" * 60)
    logger.info("")

    rotator = get_user_agent_rotator()

    # Test 1: Random user agents
    logger.info("Test 1: Random user agents (ANY device)")
    for i in range(5):
        ua = rotator.get_random()
        logger.info(f"  {i+1}. {ua}")
    logger.info("")

    # Test 2: Desktop only
    logger.info("Test 2: Desktop user agents")
    for i in range(3):
        ua = rotator.get_desktop()
        logger.info(f"  {i+1}. {ua}")
    logger.info("")

    # Test 3: Mobile only
    logger.info("Test 3: Mobile user agents")
    for i in range(3):
        ua = rotator.get_mobile()
        logger.info(f"  {i+1}. {ua}")
    logger.info("")

    # Test 4: Tablet only
    logger.info("Test 4: Tablet user agents")
    for i in range(2):
        ua = rotator.get_tablet()
        logger.info(f"  {i+1}. {ua}")
    logger.info("")

    # Test 5: Crawler UA
    logger.info("Test 5: Crawler user agent")
    crawler_ua = rotator.get_crawler()
    logger.info(f"  {crawler_ua}")
    logger.info("")

    # Test 6: Statistics
    logger.info("Test 6: Statistics")
    stats = rotator.get_stats()
    logger.info(f"  Total UAs: {stats['total_user_agents']}")
    logger.info(f"  Desktop: {stats['desktop_count']}")
    logger.info(f"  Mobile: {stats['mobile_count']}")
    logger.info(f"  Tablet: {stats['tablet_count']}")
    logger.info(f"  Device weights: {stats['device_weights']}")
    logger.info("")

    # Test 7: Custom crawler mode
    logger.info("Test 7: Custom crawler mode")
    rotator_crawler = UserAgentRotator(use_custom_crawler_ua=True)
    for i in range(3):
        ua = rotator_crawler.get_random()
        logger.info(f"  {i+1}. {ua}")
    logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

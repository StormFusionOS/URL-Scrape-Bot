"""
Bing Local Search Scraper - Configuration Management

Centralized configuration for Bing Local Search scraping with extreme caution.
Adapted from Google scraper config with Bing-specific settings.

Features:
- Conservative rate limiting (45-90s delays)
- Playwright browser settings
- Anti-detection configurations
- Quality thresholds
- Database settings

Author: washdb-bot
Date: 2025-11-18
"""

import os
import random
from typing import Dict, List
from dataclasses import dataclass, field

# Import shared configs from Google (they work for Bing too)
from scrape_google.google_config import (
    RateLimitConfig,
    PlaywrightConfig,
    ScrapingConfig,
    StealthConfig,
    QualityConfig,
    DatabaseConfig
)


@dataclass
class BingConfig:
    """
    Master configuration for Bing Local Search Scraper.

    Combines all sub-configurations with sensible defaults for
    extremely cautious, undetectable scraping without proxies.
    """

    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    playwright: PlaywrightConfig = field(default_factory=PlaywrightConfig)
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    stealth: StealthConfig = field(default_factory=StealthConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # Logging
    log_dir: str = "logs"
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Bing-specific URLs
    bing_local_url: str = "https://www.bing.com/local"
    bing_search_url: str = "https://www.bing.com/search"

    @classmethod
    def from_env(cls) -> "BingConfig":
        """
        Create configuration from environment variables.

        Returns:
            BingConfig instance
        """
        config = cls()

        # Override with environment variables if present
        if os.getenv("BING_SCRAPER_HEADLESS"):
            config.playwright.headless = os.getenv("BING_SCRAPER_HEADLESS").lower() == "true"

        if os.getenv("BING_SCRAPER_MIN_DELAY"):
            config.rate_limit.min_delay = int(os.getenv("BING_SCRAPER_MIN_DELAY"))

        if os.getenv("BING_SCRAPER_MAX_DELAY"):
            config.rate_limit.max_delay = int(os.getenv("BING_SCRAPER_MAX_DELAY"))

        if os.getenv("BING_SCRAPER_LOG_LEVEL"):
            config.log_level = os.getenv("BING_SCRAPER_LOG_LEVEL")

        return config

    def validate(self) -> bool:
        """
        Validate configuration.

        Returns:
            True if valid, False otherwise
        """
        # Check rate limiting makes sense
        if self.rate_limit.min_delay > self.rate_limit.max_delay:
            return False

        # Check quality thresholds are in valid range
        if not (0.0 <= self.quality.min_completeness <= 1.0):
            return False
        if not (0.0 <= self.quality.min_confidence <= 1.0):
            return False

        # Check database connection details
        if not all([
            self.database.host,
            self.database.database,
            self.database.user,
            self.database.password
        ]):
            return False

        return True

    def summary(self) -> Dict[str, any]:
        """
        Get configuration summary for logging.

        Returns:
            Dictionary with key configuration values
        """
        return {
            "rate_limit": {
                "delay_range": f"{self.rate_limit.min_delay}-{self.rate_limit.max_delay}s",
                "max_per_session": self.rate_limit.max_requests_per_session
            },
            "playwright": {
                "browser": self.playwright.browser_type,
                "headless": self.playwright.headless
            },
            "scraping": {
                "max_results": self.scraping.max_results_per_search,
                "simulate_human": self.scraping.simulate_mouse_movement
            },
            "stealth": {
                "enabled": self.stealth.enabled,
                "randomize_ua": self.stealth.randomize_user_agent,
                "mask_webdriver": self.stealth.mask_webdriver,
                "human_behavior": self.stealth.simulate_mouse_movements
            },
            "quality": {
                "min_completeness": self.quality.min_completeness,
                "min_confidence": self.quality.min_confidence
            },
            "database": {
                "host": self.database.host,
                "database": self.database.database
            }
        }


# Convenience function for getting default config
def get_config() -> BingConfig:
    """
    Get BingConfig instance with environment overrides.

    Returns:
        BingConfig instance
    """
    return BingConfig.from_env()

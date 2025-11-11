"""
Google Business Scraper - Configuration Management

Centralized configuration for Google Maps/Business scraping with extreme caution.

Features:
- Conservative rate limiting (30-60s delays, no proxies)
- Playwright browser settings
- Anti-detection configurations
- Quality thresholds
- Database settings

Author: washdb-bot
Date: 2025-11-10
"""

import os
import random
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    """Rate limiting configuration - extremely conservative to avoid detection."""

    # Base delay between requests (seconds) - EXTREMELY CONSERVATIVE
    min_delay: int = 45  # Increased from 30 to reduce detection
    max_delay: int = 90  # Increased from 60 to reduce detection

    # Delay after page load (seconds)
    min_page_load_delay: int = 2
    max_page_load_delay: int = 5

    # Delay after clicking/interacting (seconds)
    min_interaction_delay: int = 1
    max_interaction_delay: int = 3

    # Delay between scrolls (seconds)
    min_scroll_delay: float = 0.5
    max_scroll_delay: float = 1.5

    # Max requests per session before taking a break
    max_requests_per_session: int = 20

    # Session break duration (seconds)
    session_break_min: int = 300  # 5 minutes
    session_break_max: int = 600  # 10 minutes

    def get_request_delay(self) -> int:
        """Get randomized delay between requests."""
        return random.randint(self.min_delay, self.max_delay)

    def get_page_load_delay(self) -> int:
        """Get randomized delay after page load."""
        return random.randint(self.min_page_load_delay, self.max_page_load_delay)

    def get_interaction_delay(self) -> int:
        """Get randomized delay after interaction."""
        return random.randint(self.min_interaction_delay, self.max_interaction_delay)

    def get_scroll_delay(self) -> float:
        """Get randomized delay between scrolls."""
        return random.uniform(self.min_scroll_delay, self.max_scroll_delay)

    def get_session_break(self) -> int:
        """Get randomized session break duration."""
        return random.randint(self.session_break_min, self.session_break_max)


@dataclass
class PlaywrightConfig:
    """Playwright browser configuration."""

    # Browser type
    browser_type: str = "chromium"  # chromium, firefox, or webkit

    # Headless mode (False = visible browser, True = headless)
    headless: bool = True  # Use headless mode for servers without display

    # Persistent browser profile (helps avoid detection by maintaining cookies/state)
    use_persistent_profile: bool = True  # Save and reuse browser profile
    profile_dir: str = "./data/browser_profile"  # Directory for browser profile

    # Browser launch arguments
    browser_args: List[str] = field(default_factory=lambda: [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process"
    ])

    # Viewport size (randomize for anti-detection)
    viewport_width: int = 1920
    viewport_height: int = 1080

    # Navigation timeout (ms)
    navigation_timeout: int = 60000  # 60 seconds

    # Default timeout for actions (ms)
    default_timeout: int = 30000  # 30 seconds

    # Page load wait strategy
    wait_until: str = "domcontentloaded"  # "load", "domcontentloaded", "networkidle"

    # User agent rotation
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ])

    # Geolocation (optional - set based on search location)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Locale
    locale: str = "en-US"
    timezone: str = "America/New_York"

    def get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(self.user_agents)

    def get_randomized_viewport(self) -> Dict[str, int]:
        """Get slightly randomized viewport size."""
        return {
            "width": self.viewport_width + random.randint(-50, 50),
            "height": self.viewport_height + random.randint(-50, 50)
        }


@dataclass
class ScrapingConfig:
    """Scraping behavior configuration."""

    # Max results to scrape per search
    max_results_per_search: int = 20

    # Max retries for failed requests
    max_retries: int = 3

    # Retry delay (seconds)
    retry_delay: int = 10

    # Scroll behavior
    enable_scrolling: bool = True
    scroll_pause_time: float = 1.0
    max_scrolls: int = 10

    # Screenshot on error (for debugging)
    screenshot_on_error: bool = True
    screenshot_dir: str = "logs/screenshots"

    # Human behavior simulation
    simulate_mouse_movement: bool = True
    simulate_reading_time: bool = True
    min_reading_time: int = 3  # seconds
    max_reading_time: int = 7  # seconds

    # Field extraction (what to scrape)
    extract_fields: List[str] = field(default_factory=lambda: [
        "name",
        "address",
        "phone",
        "website",
        "rating",
        "reviews_count",
        "category",
        "hours",
        "place_id",
        "google_url"
    ])

    def get_reading_time(self) -> int:
        """Get randomized reading time."""
        return random.randint(self.min_reading_time, self.max_reading_time)


@dataclass
class StealthConfig:
    """Anti-detection and stealth configuration."""

    # Enable stealth mode (applies all anti-detection measures)
    enabled: bool = True

    # Randomize user agent for each session
    randomize_user_agent: bool = True

    # Randomize viewport size for each session
    randomize_viewport: bool = True

    # Randomize timezone for each session
    randomize_timezone: bool = True

    # Enable browser fingerprinting countermeasures
    mask_webdriver: bool = True
    mask_plugins: bool = True
    mask_permissions: bool = True

    # Human-like behavior simulation
    simulate_mouse_movements: bool = True
    simulate_random_scrolling: bool = True
    simulate_typing_delays: bool = True
    simulate_reading_delays: bool = True

    # Random delays and jitter
    enable_random_jitter: bool = True
    jitter_factor: float = 0.2  # 20% variance

    # Session management
    clear_cookies_between_searches: bool = False  # Can be too aggressive
    vary_request_timing: bool = True

    # CAPTCHA detection
    detect_captcha: bool = True
    pause_on_captcha: bool = True

    # Behavioral randomization ranges (milliseconds)
    mouse_movement_delay_min: int = 100
    mouse_movement_delay_max: int = 500

    typing_delay_min: int = 80
    typing_delay_max: int = 200

    reading_delay_min: int = 2000  # 2 seconds
    reading_delay_max: int = 5000  # 5 seconds


@dataclass
class QualityConfig:
    """Data quality thresholds and scoring."""

    # Minimum completeness score (0.0 - 1.0) to accept a record
    min_completeness: float = 0.4

    # Minimum confidence score (0.0 - 1.0)
    min_confidence: float = 0.5

    # Field weights for completeness calculation
    field_weights: Dict[str, float] = field(default_factory=lambda: {
        "name": 1.0,  # Critical
        "phone": 0.9,  # Very important
        "address": 0.9,  # Very important
        "website": 0.7,  # Important
        "category": 0.6,  # Useful
        "rating": 0.5,  # Nice to have
        "reviews_count": 0.4,  # Nice to have
        "hours": 0.5,  # Nice to have
        "place_id": 1.0,  # Critical for deduplication
        "google_url": 0.8  # Very important for reference
    })

    # Required fields (must have at least one)
    required_fields: List[str] = field(default_factory=lambda: ["name", "place_id"])

    def calculate_completeness(self, extracted_fields: Dict[str, any]) -> float:
        """
        Calculate completeness score based on field weights.

        Args:
            extracted_fields: Dictionary of extracted field values

        Returns:
            Completeness score (0.0 - 1.0)
        """
        total_weight = sum(self.field_weights.values())
        achieved_weight = 0.0

        for field, weight in self.field_weights.items():
            if field in extracted_fields and extracted_fields[field]:
                achieved_weight += weight

        return achieved_weight / total_weight if total_weight > 0 else 0.0

    def validate_required_fields(self, extracted_fields: Dict[str, any]) -> bool:
        """
        Check if required fields are present.

        Args:
            extracted_fields: Dictionary of extracted field values

        Returns:
            True if valid, False otherwise
        """
        return all(
            field in extracted_fields and extracted_fields[field]
            for field in self.required_fields
        )


@dataclass
class DatabaseConfig:
    """Database connection configuration."""

    # Connection details (loaded from environment)
    host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("DB_NAME", "washbot_db"))
    user: str = field(default_factory=lambda: os.getenv("DB_USER", "washbot"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", "Washdb123"))

    # Connection pool settings
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30

    # Table name
    companies_table: str = "companies"
    scrape_logs_table: str = "scrape_logs"

    def get_connection_string(self) -> str:
        """Get PostgreSQL connection string."""
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class GoogleConfig:
    """
    Master configuration for Google Business Scraper.

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

    # Google Maps specific URLs
    google_maps_url: str = "https://www.google.com/maps"
    google_search_url: str = "https://www.google.com/search"

    @classmethod
    def from_env(cls) -> "GoogleConfig":
        """
        Create configuration from environment variables.

        Returns:
            GoogleConfig instance
        """
        config = cls()

        # Override with environment variables if present
        if os.getenv("GOOGLE_SCRAPER_HEADLESS"):
            config.playwright.headless = os.getenv("GOOGLE_SCRAPER_HEADLESS").lower() == "true"

        if os.getenv("GOOGLE_SCRAPER_MIN_DELAY"):
            config.rate_limit.min_delay = int(os.getenv("GOOGLE_SCRAPER_MIN_DELAY"))

        if os.getenv("GOOGLE_SCRAPER_MAX_DELAY"):
            config.rate_limit.max_delay = int(os.getenv("GOOGLE_SCRAPER_MAX_DELAY"))

        if os.getenv("GOOGLE_SCRAPER_LOG_LEVEL"):
            config.log_level = os.getenv("GOOGLE_SCRAPER_LOG_LEVEL")

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
def get_config() -> GoogleConfig:
    """
    Get GoogleConfig instance with environment overrides.

    Returns:
        GoogleConfig instance
    """
    return GoogleConfig.from_env()

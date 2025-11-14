"""
Worker configuration for parallel Yellow Pages scraping.

Centralizes all settings for worker pool, proxies, delays, and database.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class WorkerConfig:
    """Configuration for parallel worker system."""

    # ===== WORKER SETTINGS =====

    # Number of parallel workers (30-35 recommended for balanced speed/safety)
    WORKER_COUNT = int(os.getenv("WORKER_COUNT", "35"))

    # Maximum targets to process before restarting browser (prevents memory leaks)
    MAX_TARGETS_PER_BROWSER = int(os.getenv("MAX_TARGETS_PER_BROWSER", "100"))

    # Whether to restart workers on failure
    WORKER_RESTART_ON_FAILURE = os.getenv("WORKER_RESTART_ON_FAILURE", "true").lower() == "true"

    # Maximum worker restarts before giving up
    MAX_WORKER_RESTARTS = int(os.getenv("MAX_WORKER_RESTARTS", "5"))

    # Worker heartbeat interval (seconds)
    WORKER_HEARTBEAT_INTERVAL = int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "30"))

    # ===== PROXY SETTINGS =====

    # Path to proxy file (Webshare format: host:port:username:password)
    PROXY_FILE = os.getenv("PROXY_FILE", "/home/rivercityscrape/Downloads/Webshare 50 proxies.txt")

    # Enable proxy rotation on failures
    PROXY_ROTATION_ENABLED = os.getenv("PROXY_ROTATION_ENABLED", "true").lower() == "true"

    # Proxy selection strategy: 'round_robin' or 'health_based'
    PROXY_SELECTION_STRATEGY = os.getenv("PROXY_SELECTION_STRATEGY", "round_robin")

    # Number of consecutive failures before blacklisting proxy
    PROXY_BLACKLIST_THRESHOLD = int(os.getenv("PROXY_BLACKLIST_THRESHOLD", "10"))

    # How long to blacklist a proxy (minutes)
    PROXY_BLACKLIST_DURATION_MINUTES = int(os.getenv("PROXY_BLACKLIST_DURATION_MINUTES", "60"))

    # Test proxies before starting workers
    PROXY_TEST_ON_STARTUP = os.getenv("PROXY_TEST_ON_STARTUP", "true").lower() == "true"

    # Maximum number of proxies to test concurrently
    PROXY_TEST_MAX_CONCURRENT = int(os.getenv("PROXY_TEST_MAX_CONCURRENT", "5"))

    # ===== DELAY & RATE LIMITING SETTINGS =====

    # Minimum delay between targets per worker (seconds)
    MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", "5.0"))

    # Maximum delay between targets per worker (seconds)
    MAX_DELAY_SECONDS = float(os.getenv("MAX_DELAY_SECONDS", "15.0"))

    # Add randomization to delays (prevents pattern detection)
    DELAY_RANDOMIZATION = os.getenv("DELAY_RANDOMIZATION", "true").lower() == "true"

    # Session break settings (inherited from existing system)
    SESSION_BREAK_ENABLED = os.getenv("SESSION_BREAK_ENABLED", "true").lower() == "true"
    SESSION_BREAK_REQUESTS_PER_SESSION = int(os.getenv("SESSION_BREAK_REQUESTS_PER_SESSION", "50"))
    SESSION_BREAK_MIN_DURATION = int(os.getenv("SESSION_BREAK_MIN_DURATION", "30"))
    SESSION_BREAK_MAX_DURATION = int(os.getenv("SESSION_BREAK_MAX_DURATION", "90"))

    # ===== DATABASE SETTINGS =====

    # Database URL
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Connection pool size (should be >= WORKER_COUNT)
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", str(WORKER_COUNT + 10)))

    # Max overflow connections
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))

    # Target acquisition timeout (seconds)
    TARGET_ACQUISITION_TIMEOUT = int(os.getenv("TARGET_ACQUISITION_TIMEOUT", "30"))

    # How long a target can stay "in_progress" before being reset (minutes)
    TARGET_TIMEOUT_MINUTES = int(os.getenv("TARGET_TIMEOUT_MINUTES", "30"))

    # ===== RETRY & ERROR HANDLING =====

    # Maximum retry attempts per target before marking as failed
    MAX_TARGET_RETRY_ATTEMPTS = int(os.getenv("MAX_TARGET_RETRY_ATTEMPTS", "3"))

    # Mark target as 'parked' after N total attempts (across all workers)
    MAX_TARGET_TOTAL_ATTEMPTS = int(os.getenv("MAX_TARGET_TOTAL_ATTEMPTS", "5"))

    # Retry delay multiplier (exponential backoff)
    RETRY_DELAY_MULTIPLIER = float(os.getenv("RETRY_DELAY_MULTIPLIER", "2.0"))

    # Maximum retry delay (seconds)
    MAX_RETRY_DELAY = int(os.getenv("MAX_RETRY_DELAY", "300"))

    # ===== BROWSER SETTINGS =====

    # Use headless browser
    BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    # Browser timeout (milliseconds)
    BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))

    # Keep browser open between targets (more efficient)
    BROWSER_PERSISTENT = os.getenv("BROWSER_PERSISTENT", "true").lower() == "true"

    # ===== ANTI-DETECTION SETTINGS =====

    # Enable anti-detection features (from yp_stealth.py)
    ANTI_DETECTION_ENABLED = os.getenv("ANTI_DETECTION_ENABLED", "true").lower() == "true"

    # Randomize user agents
    RANDOMIZE_USER_AGENT = os.getenv("RANDOMIZE_USER_AGENT", "true").lower() == "true"

    # Randomize viewport sizes
    RANDOMIZE_VIEWPORT = os.getenv("RANDOMIZE_VIEWPORT", "true").lower() == "true"

    # Enable adaptive rate limiting (slows down on errors)
    ADAPTIVE_RATE_LIMITING = os.getenv("ADAPTIVE_RATE_LIMITING", "true").lower() == "true"

    # ===== MONITORING & LOGGING =====

    # Log level (DEBUG, INFO, WARNING, ERROR)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Enable worker metrics tracking
    METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"

    # Metrics update interval (seconds)
    METRICS_UPDATE_INTERVAL = int(os.getenv("METRICS_UPDATE_INTERVAL", "60"))

    # Log file for worker pool
    WORKER_POOL_LOG_FILE = os.getenv("WORKER_POOL_LOG_FILE", "logs/worker_pool.log")

    # Individual worker log pattern (worker_id will be inserted)
    WORKER_LOG_FILE_PATTERN = os.getenv("WORKER_LOG_FILE_PATTERN", "logs/worker_{worker_id}.log")

    # ===== FILTERING SETTINGS =====

    # Minimum confidence score (0-100)
    MIN_CONFIDENCE_SCORE = float(os.getenv("MIN_CONFIDENCE_SCORE", "50.0"))

    # Include sponsored/ad listings
    INCLUDE_SPONSORED = os.getenv("INCLUDE_SPONSORED", "false").lower() == "true"

    # Maximum pages to crawl per target (from target.max_pages)
    # This is stored in database, but can be overridden
    MAX_PAGES_PER_TARGET_OVERRIDE = os.getenv("MAX_PAGES_PER_TARGET_OVERRIDE")

    # ===== TARGET SELECTION =====

    # States to scrape (comma-separated, or 'ALL' for all states)
    TARGET_STATES = os.getenv("TARGET_STATES", "ALL")

    # Limit number of targets to process (for testing)
    MAX_TOTAL_TARGETS = os.getenv("MAX_TOTAL_TARGETS")  # None = unlimited

    # Target priority order: 'priority_asc' (high priority first) or 'id_asc' (sequential)
    TARGET_ORDER = os.getenv("TARGET_ORDER", "priority_asc")

    @classmethod
    def validate(cls) -> bool:
        """
        Validate configuration.

        Returns:
            True if valid, raises ValueError otherwise
        """
        errors = []

        # Check database URL
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL not set in environment")

        # Check proxy file exists
        if not os.path.exists(cls.PROXY_FILE):
            errors.append(f"Proxy file not found: {cls.PROXY_FILE}")

        # Check worker count
        if cls.WORKER_COUNT < 1:
            errors.append(f"WORKER_COUNT must be >= 1, got {cls.WORKER_COUNT}")

        if cls.WORKER_COUNT > 100:
            errors.append(f"WORKER_COUNT suspiciously high: {cls.WORKER_COUNT} (max recommended: 50)")

        # Check delays
        if cls.MIN_DELAY_SECONDS < 0:
            errors.append(f"MIN_DELAY_SECONDS must be >= 0, got {cls.MIN_DELAY_SECONDS}")

        if cls.MAX_DELAY_SECONDS < cls.MIN_DELAY_SECONDS:
            errors.append(f"MAX_DELAY_SECONDS ({cls.MAX_DELAY_SECONDS}) < MIN_DELAY_SECONDS ({cls.MIN_DELAY_SECONDS})")

        # Check DB pool
        if cls.DB_POOL_SIZE < cls.WORKER_COUNT:
            errors.append(
                f"DB_POOL_SIZE ({cls.DB_POOL_SIZE}) should be >= WORKER_COUNT ({cls.WORKER_COUNT}) "
                f"to avoid connection starvation"
            )

        if errors:
            raise ValueError("Configuration validation failed:\n  - " + "\n  - ".join(errors))

        return True

    @classmethod
    def print_summary(cls):
        """Print configuration summary."""
        print("=" * 60)
        print("Worker Configuration Summary")
        print("=" * 60)
        print(f"Workers: {cls.WORKER_COUNT}")
        print(f"Proxy file: {cls.PROXY_FILE}")
        print(f"Proxy strategy: {cls.PROXY_SELECTION_STRATEGY}")
        print(f"Delay range: {cls.MIN_DELAY_SECONDS}-{cls.MAX_DELAY_SECONDS}s")
        print(f"Database pool: {cls.DB_POOL_SIZE} connections")
        print(f"Target timeout: {cls.TARGET_TIMEOUT_MINUTES} minutes")
        print(f"Max retries per target: {cls.MAX_TARGET_RETRY_ATTEMPTS}")
        print(f"Browser: {'Headless' if cls.BROWSER_HEADLESS else 'Visible'} + Persistent={cls.BROWSER_PERSISTENT}")
        print(f"Anti-detection: {'Enabled' if cls.ANTI_DETECTION_ENABLED else 'Disabled'}")
        print(f"Session breaks: {'Enabled' if cls.SESSION_BREAK_ENABLED else 'Disabled'}")
        print("=" * 60)


def main():
    """Demo: Validate and print configuration."""
    try:
        WorkerConfig.validate()
        print("✓ Configuration is valid\n")
        WorkerConfig.print_summary()
    except ValueError as e:
        print(f"✗ Configuration validation failed:\n{e}")


if __name__ == "__main__":
    main()

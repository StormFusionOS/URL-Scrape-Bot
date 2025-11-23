"""
Safety mechanisms and kill switches for scrapers.

This module provides safety limits to prevent runaway scraping behavior
during development and production. All limits are configurable via environment
variables.
"""

import os
from typing import Optional
from runner.logging_setup import get_logger

logger = get_logger(__name__)


class SafetyLimits:
    """
    Safety limits and kill switches for scraper operations.

    Prevents runaway behavior by enforcing maximum pages per run,
    maximum consecutive failures, and other safety constraints.
    """

    def __init__(
        self,
        max_pages: Optional[int] = None,
        max_failures: Optional[int] = None,
        enable_kill_switch: bool = True,
    ):
        """
        Initialize safety limits.

        Args:
            max_pages: Maximum pages to scrape (None = unlimited)
            max_failures: Maximum consecutive failures before abort (None = unlimited)
            enable_kill_switch: Whether to enable kill switch functionality
        """
        # Load from environment or use provided values
        self.max_pages = max_pages or self._get_env_int("DEV_MAX_PAGES", None)
        self.max_failures = max_failures or self._get_env_int("DEV_MAX_FAILURES", 10)
        self.enable_kill_switch = enable_kill_switch and self._get_env_bool(
            "DEV_ENABLE_KILL_SWITCH", True
        )

        # Counters
        self.pages_processed = 0
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_successes = 0

        # State
        self.should_stop = False
        self._stop_reason: Optional[str] = None

        # Log configuration
        if self.max_pages:
            logger.info(f"Safety limit: Maximum {self.max_pages} pages per run")
        if self.max_failures:
            logger.info(f"Safety limit: Maximum {self.max_failures} consecutive failures")
        if self.enable_kill_switch:
            logger.debug("Kill switch enabled")

    @staticmethod
    def _get_env_int(key: str, default: Optional[int]) -> Optional[int]:
        """Get integer from environment variable."""
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid integer for {key}: {value}, using default: {default}")
            return default

    @staticmethod
    def _get_env_bool(key: str, default: bool) -> bool:
        """Get boolean from environment variable."""
        value = os.getenv(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        elif value in ("false", "0", "no", "off"):
            return False
        return default

    def check_should_continue(self) -> bool:
        """
        Check if scraping should continue.

        Returns:
            True if scraping should continue, False if should stop
        """
        if not self.enable_kill_switch:
            return True

        if self.should_stop:
            return False

        # Check max pages
        if self.max_pages and self.pages_processed >= self.max_pages:
            self._stop_reason = f"Reached maximum pages limit: {self.max_pages}"
            self.should_stop = True
            logger.warning(self._stop_reason)
            return False

        # Check max consecutive failures
        if self.max_failures and self.consecutive_failures >= self.max_failures:
            self._stop_reason = (
                f"Reached maximum consecutive failures: {self.max_failures}"
            )
            self.should_stop = True
            logger.error(self._stop_reason)
            return False

        return True

    def record_page_processed(self):
        """Record that a page was processed."""
        self.pages_processed += 1

        # Log progress periodically
        if self.pages_processed % 10 == 0:
            logger.info(
                f"Progress: {self.pages_processed} pages processed "
                f"({self.total_successes} successes, {self.total_failures} failures)"
            )

    def record_success(self):
        """Record a successful operation."""
        self.total_successes += 1
        self.consecutive_failures = 0  # Reset consecutive failure counter

    def record_failure(self, error: Optional[str] = None):
        """
        Record a failed operation.

        Args:
            error: Optional error message to log
        """
        self.total_failures += 1
        self.consecutive_failures += 1

        if error:
            logger.warning(
                f"Operation failed ({self.consecutive_failures} consecutive failures): {error}"
            )
        else:
            logger.warning(f"Operation failed ({self.consecutive_failures} consecutive failures)")

    def manual_stop(self, reason: str = "Manual stop requested"):
        """
        Manually trigger a stop.

        Args:
            reason: Reason for stopping
        """
        self._stop_reason = reason
        self.should_stop = True
        logger.warning(f"Manual stop: {reason}")

    def get_summary(self) -> dict:
        """
        Get summary statistics.

        Returns:
            Dictionary with summary statistics
        """
        return {
            "pages_processed": self.pages_processed,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "stopped": self.should_stop,
            "stop_reason": self._stop_reason,
        }

    def log_summary(self):
        """Log summary statistics."""
        summary = self.get_summary()
        logger.info("=" * 60)
        logger.info("Safety Limits Summary:")
        logger.info(f"  Pages processed: {summary['pages_processed']}")
        logger.info(f"  Successes: {summary['total_successes']}")
        logger.info(f"  Failures: {summary['total_failures']}")
        logger.info(f"  Consecutive failures: {summary['consecutive_failures']}")
        if summary["stopped"]:
            logger.info(f"  Stopped: {summary['stop_reason']}")
        logger.info("=" * 60)


class RateLimiter:
    """
    Adaptive rate limiter to prevent overwhelming target servers.

    Increases delays when failures are detected and decreases when
    operations are successful.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 1.5,
        recovery_factor: float = 0.9,
    ):
        """
        Initialize rate limiter.

        Args:
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            backoff_factor: Multiplier for increasing delay on failure
            recovery_factor: Multiplier for decreasing delay on success
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.recovery_factor = recovery_factor

        self.current_delay = base_delay
        self.consecutive_successes = 0

        logger.debug(
            f"Rate limiter initialized: base={base_delay}s, max={max_delay}s"
        )

    def get_delay(self) -> float:
        """Get current delay in seconds."""
        return self.current_delay

    def record_success(self):
        """Record successful operation and potentially decrease delay."""
        self.consecutive_successes += 1

        # After several successes, decrease delay
        if self.consecutive_successes >= 3:
            old_delay = self.current_delay
            self.current_delay = max(
                self.base_delay,
                self.current_delay * self.recovery_factor
            )
            if self.current_delay < old_delay:
                logger.debug(
                    f"Rate limit decreased: {old_delay:.1f}s → {self.current_delay:.1f}s"
                )
            self.consecutive_successes = 0

    def record_failure(self):
        """Record failed operation and increase delay."""
        self.consecutive_successes = 0
        old_delay = self.current_delay
        self.current_delay = min(
            self.max_delay,
            self.current_delay * self.backoff_factor
        )
        if self.current_delay > old_delay:
            logger.warning(
                f"Rate limit increased: {old_delay:.1f}s → {self.current_delay:.1f}s"
            )

    def reset(self):
        """Reset to base delay."""
        self.current_delay = self.base_delay
        self.consecutive_successes = 0


def create_safety_limits_from_env() -> SafetyLimits:
    """
    Create SafetyLimits instance from environment variables.

    Returns:
        SafetyLimits instance configured from environment
    """
    return SafetyLimits()


def create_rate_limiter_from_env() -> RateLimiter:
    """
    Create RateLimiter instance from environment variables.

    Returns:
        RateLimiter instance configured from environment
    """
    base_delay = float(os.getenv("MIN_DELAY_SECONDS", "2.0"))
    max_delay = float(os.getenv("MAX_DELAY_SECONDS", "30.0"))

    return RateLimiter(
        base_delay=base_delay,
        max_delay=max_delay,
    )

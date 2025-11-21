"""
Rate Limiter Service

Implements token bucket algorithm for tier-based rate limiting.

Tiers (based on SCRAPING_NOTES.md):
- Tier A: High-value targets (15-30s delay, 2-4 req/min)
- Tier B: Medium-value targets (10-20s delay, 3-6 req/min)
- Tier C: Standard targets (8-15s delay, 4-7 req/min)
- Tier D: Low-priority (5-10s delay, 6-12 req/min)
- Tier E: Citation directories (3-8s delay, 7-20 req/min)
- Tier F: Backlink sources (2-5s delay, 12-30 req/min)
- Tier G: Own sites (1-3s delay, 20-60 req/min)

Features:
- Token bucket algorithm with configurable refill rates
- Per-domain rate limiting
- Tier-based configuration
- Thread-safe implementation
- Automatic token refill
"""

import time
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from runner.logging_setup import get_logger

# Initialize logger
logger = get_logger("rate_limiter")


@dataclass
class TierConfig:
    """Configuration for a rate limiting tier."""
    min_delay_seconds: float
    max_delay_seconds: float
    tokens_per_minute: float
    bucket_size: int  # Maximum tokens that can accumulate

    def __str__(self):
        return f"TierConfig(delay={self.min_delay_seconds}-{self.max_delay_seconds}s, rate={self.tokens_per_minute}/min)"


# Tier configurations based on SCRAPING_NOTES.md
TIER_CONFIGS = {
    'A': TierConfig(min_delay_seconds=15.0, max_delay_seconds=30.0, tokens_per_minute=2.5, bucket_size=5),
    'B': TierConfig(min_delay_seconds=10.0, max_delay_seconds=20.0, tokens_per_minute=4.0, bucket_size=8),
    'C': TierConfig(min_delay_seconds=8.0, max_delay_seconds=15.0, tokens_per_minute=5.0, bucket_size=10),
    'D': TierConfig(min_delay_seconds=5.0, max_delay_seconds=10.0, tokens_per_minute=8.0, bucket_size=15),
    'E': TierConfig(min_delay_seconds=3.0, max_delay_seconds=8.0, tokens_per_minute=12.0, bucket_size=20),
    'F': TierConfig(min_delay_seconds=2.0, max_delay_seconds=5.0, tokens_per_minute=20.0, bucket_size=30),
    'G': TierConfig(min_delay_seconds=1.0, max_delay_seconds=3.0, tokens_per_minute=40.0, bucket_size=60),
}


class TokenBucket:
    """
    Thread-safe token bucket implementation.

    The token bucket algorithm allows burst traffic while maintaining
    a sustained rate limit over time.
    """

    def __init__(self, tier_config: TierConfig):
        """
        Initialize token bucket.

        Args:
            tier_config: Tier configuration with rate limits
        """
        self.config = tier_config
        self.tokens = float(tier_config.bucket_size)  # Start with full bucket
        self.last_refill = time.time()
        self.lock = threading.Lock()

        logger.debug(f"Initialized TokenBucket: {tier_config}")

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate tokens to add based on elapsed time
        tokens_to_add = (elapsed / 60.0) * self.config.tokens_per_minute

        if tokens_to_add > 0:
            self.tokens = min(
                self.config.bucket_size,
                self.tokens + tokens_to_add
            )
            self.last_refill = now

    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """
        Attempt to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume (default: 1)

        Returns:
            Tuple of (success, wait_time)
            - success: True if tokens were consumed, False if insufficient
            - wait_time: Time to wait (in seconds) before tokens are available
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                logger.debug(f"Consumed {tokens} token(s), {self.tokens:.2f} remaining")
                return True, 0.0
            else:
                # Calculate wait time until enough tokens are available
                tokens_needed = tokens - self.tokens
                wait_time = (tokens_needed / self.config.tokens_per_minute) * 60.0

                logger.debug(
                    f"Insufficient tokens ({self.tokens:.2f}/{tokens}), "
                    f"wait {wait_time:.2f}s"
                )
                return False, wait_time

    def wait_and_consume(self, tokens: int = 1, max_wait: Optional[float] = None) -> bool:
        """
        Wait for tokens to be available and consume them.

        Args:
            tokens: Number of tokens to consume
            max_wait: Maximum time to wait (seconds). If None, wait indefinitely.

        Returns:
            bool: True if tokens were consumed, False if max_wait exceeded
        """
        start_time = time.time()

        while True:
            success, wait_time = self.consume(tokens)

            if success:
                return True

            # Check max_wait constraint
            if max_wait is not None:
                elapsed = time.time() - start_time
                if elapsed + wait_time > max_wait:
                    logger.warning(f"Max wait time ({max_wait}s) would be exceeded")
                    return False

            # Wait for tokens to refill
            logger.debug(f"Waiting {wait_time:.2f}s for tokens to refill...")
            time.sleep(wait_time)

    def get_available_tokens(self) -> float:
        """Get current number of available tokens."""
        with self.lock:
            self._refill()
            return self.tokens


class RateLimiter:
    """
    Per-domain rate limiter with tier-based configuration.

    Manages separate token buckets for each domain to ensure
    respectful scraping rates.
    """

    def __init__(self):
        """Initialize the rate limiter."""
        self.buckets: Dict[str, TokenBucket] = {}
        self.domain_tiers: Dict[str, str] = {}  # domain -> tier mapping
        self.lock = threading.Lock()

        logger.info("RateLimiter initialized")

    def set_domain_tier(self, domain: str, tier: str):
        """
        Set the tier for a specific domain.

        Args:
            domain: Domain name (e.g., 'google.com')
            tier: Tier letter ('A'-'G')

        Raises:
            ValueError: If tier is invalid
        """
        if tier not in TIER_CONFIGS:
            raise ValueError(f"Invalid tier '{tier}'. Must be one of: {list(TIER_CONFIGS.keys())}")

        with self.lock:
            self.domain_tiers[domain] = tier

            # Create or replace bucket for this domain
            tier_config = TIER_CONFIGS[tier]
            self.buckets[domain] = TokenBucket(tier_config)

            logger.info(f"Set domain '{domain}' to tier {tier}: {tier_config}")

    def get_domain_tier(self, domain: str) -> str:
        """
        Get the tier for a domain (defaults to 'C' if not set).

        Args:
            domain: Domain name

        Returns:
            str: Tier letter
        """
        return self.domain_tiers.get(domain, 'C')  # Default to tier C

    def _get_bucket(self, domain: str) -> TokenBucket:
        """Get or create token bucket for a domain."""
        with self.lock:
            if domain not in self.buckets:
                # Create bucket with default tier (C)
                tier = self.get_domain_tier(domain)
                tier_config = TIER_CONFIGS[tier]
                self.buckets[domain] = TokenBucket(tier_config)
                logger.debug(f"Created bucket for domain '{domain}' with tier {tier}")

            return self.buckets[domain]

    def acquire(self, domain: str, tokens: int = 1, wait: bool = True, max_wait: Optional[float] = None) -> bool:
        """
        Acquire tokens for a domain.

        Args:
            domain: Domain name
            tokens: Number of tokens to acquire (default: 1)
            wait: Whether to wait for tokens if unavailable (default: True)
            max_wait: Maximum time to wait in seconds (default: None = wait indefinitely)

        Returns:
            bool: True if tokens acquired, False otherwise
        """
        bucket = self._get_bucket(domain)

        if wait:
            return bucket.wait_and_consume(tokens, max_wait)
        else:
            success, _ = bucket.consume(tokens)
            return success

    def get_delay(self, domain: str) -> float:
        """
        Get the recommended delay for a domain based on its tier.

        Returns the minimum delay for the domain's tier.

        Args:
            domain: Domain name

        Returns:
            float: Delay in seconds
        """
        tier = self.get_domain_tier(domain)
        config = TIER_CONFIGS[tier]
        return config.min_delay_seconds

    def get_stats(self, domain: str) -> Dict:
        """
        Get rate limiting statistics for a domain.

        Args:
            domain: Domain name

        Returns:
            dict: Statistics including tier, available tokens, config
        """
        bucket = self._get_bucket(domain)
        tier = self.get_domain_tier(domain)
        config = TIER_CONFIGS[tier]

        return {
            'domain': domain,
            'tier': tier,
            'available_tokens': bucket.get_available_tokens(),
            'bucket_size': config.bucket_size,
            'tokens_per_minute': config.tokens_per_minute,
            'min_delay_seconds': config.min_delay_seconds,
            'max_delay_seconds': config.max_delay_seconds,
        }

    def reset_domain(self, domain: str):
        """
        Reset rate limiting for a domain (refill bucket to full).

        Args:
            domain: Domain name
        """
        with self.lock:
            if domain in self.buckets:
                tier = self.get_domain_tier(domain)
                config = TIER_CONFIGS[tier]
                self.buckets[domain] = TokenBucket(config)
                logger.info(f"Reset rate limiter for domain '{domain}'")


# Module-level singleton
_rate_limiter_instance = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the singleton RateLimiter instance."""
    global _rate_limiter_instance

    if _rate_limiter_instance is None:
        _rate_limiter_instance = RateLimiter()

    return _rate_limiter_instance


def main():
    """Demo: Test rate limiting."""
    logger.info("=" * 60)
    logger.info("Rate Limiter Demo")
    logger.info("=" * 60)
    logger.info("")

    limiter = get_rate_limiter()

    # Test 1: Set different tiers
    logger.info("Test 1: Setting domain tiers")
    limiter.set_domain_tier("google.com", "A")  # High-value
    limiter.set_domain_tier("competitor.com", "B")  # Medium-value
    limiter.set_domain_tier("citation-directory.com", "E")  # Citation
    limiter.set_domain_tier("our-site.com", "G")  # Own site
    logger.info("")

    # Test 2: Check stats
    logger.info("Test 2: Domain statistics")
    for domain in ["google.com", "competitor.com", "citation-directory.com", "our-site.com"]:
        stats = limiter.get_stats(domain)
        logger.info(f"{domain}:")
        logger.info(f"  Tier: {stats['tier']}")
        logger.info(f"  Rate: {stats['tokens_per_minute']:.1f} req/min")
        logger.info(f"  Delay: {stats['min_delay_seconds']}-{stats['max_delay_seconds']}s")
        logger.info(f"  Available: {stats['available_tokens']:.2f}/{stats['bucket_size']} tokens")
        logger.info("")

    # Test 3: Acquire tokens (fast tier)
    logger.info("Test 3: Rapid requests to fast tier (our-site.com)")
    start = time.time()
    for i in range(5):
        success = limiter.acquire("our-site.com", wait=True)
        logger.info(f"  Request {i+1}: {'✓' if success else '✗'} ({time.time() - start:.2f}s elapsed)")
    logger.info("")

    # Test 4: Acquire tokens (slow tier)
    logger.info("Test 4: Requests to slow tier (google.com)")
    start = time.time()
    for i in range(3):
        success = limiter.acquire("google.com", wait=True, max_wait=10.0)
        logger.info(f"  Request {i+1}: {'✓' if success else '✗'} ({time.time() - start:.2f}s elapsed)")
    logger.info("")

    # Test 5: Non-blocking acquire
    logger.info("Test 5: Non-blocking acquire")
    limiter.reset_domain("test.com")
    success1 = limiter.acquire("test.com", wait=False)
    success2 = limiter.acquire("test.com", wait=False)
    logger.info(f"  First request: {'✓' if success1 else '✗'}")
    logger.info(f"  Immediate second request: {'✓' if success2 else '✗'}")
    logger.info("")

    logger.info("=" * 60)
    logger.info("Demo complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

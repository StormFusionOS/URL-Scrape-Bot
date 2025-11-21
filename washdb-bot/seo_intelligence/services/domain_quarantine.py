"""
Domain Quarantine Service

Implements Task 11 from Phase 2: Ethical Crawling Controls

Features:
- Domain quarantine for problematic sites (403, 429, CAPTCHA)
- Exponential backoff (5s → 30s → 5m → 60m)
- Retry-After header support
- Quarantine expiration tracking
- Reason code tracking (403_FORBIDDEN, CAPTCHA_DETECTED, RATE_LIMITED, etc.)

Quarantine Rules (per SCRAPING_NOTES.md §4):
- 403 Forbidden: 60-minute quarantine (permanent block)
- Repeated 429 (3+ in 1 hour): 60-minute quarantine with exponential backoff
- CAPTCHA detected: 60-minute quarantine (anti-bot protection)
- Server errors (5xx, 3+ in 10 minutes): 30-minute quarantine

Exponential Backoff Schedule:
- Attempt 1: 5 seconds
- Attempt 2: 30 seconds
- Attempt 3: 5 minutes (300 seconds)
- Attempt 4+: 60 minutes (3600 seconds)

Usage:
    from seo_intelligence.services.domain_quarantine import get_domain_quarantine

    quarantine = get_domain_quarantine()

    # Check if domain is quarantined
    if quarantine.is_quarantined("example.com"):
        print(f"Domain is quarantined until {quarantine.get_quarantine_end('example.com')}")
        return

    # Quarantine a domain due to 403
    quarantine.quarantine_domain(
        domain="example.com",
        reason="403_FORBIDDEN",
        duration_minutes=60
    )

    # Handle rate limiting with backoff
    attempt = quarantine.get_retry_attempt("example.com")
    backoff_seconds = quarantine.get_backoff_delay(attempt)
    time.sleep(backoff_seconds)
"""

import time
import threading
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from runner.logging_setup import get_logger


# Singleton instance
_domain_quarantine = None


class QuarantineReason(Enum):
    """Reasons for domain quarantine."""

    # HTTP error codes
    FORBIDDEN_403 = "403_FORBIDDEN"  # Access forbidden
    TOO_MANY_REQUESTS_429 = "429_TOO_MANY_REQUESTS"  # Rate limited
    SERVER_ERROR_5XX = "5XX_SERVER_ERROR"  # Server errors

    # Detection-based blocks
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"  # CAPTCHA challenge
    BOT_DETECTED = "BOT_DETECTED"  # Bot detection page
    CLOUDFLARE_CHALLENGE = "CLOUDFLARE_CHALLENGE"  # Cloudflare challenge

    # Manual quarantine
    MANUAL = "MANUAL"  # Manually quarantined


@dataclass
class QuarantineEntry:
    """Represents a quarantined domain."""

    domain: str
    reason: QuarantineReason
    quarantined_at: datetime
    expires_at: datetime
    retry_attempt: int  # For exponential backoff
    retry_after_seconds: Optional[int]  # From Retry-After header
    metadata: Dict[str, Any]  # Additional context


@dataclass
class BackoffSchedule:
    """Exponential backoff schedule configuration."""

    # Exponential backoff delays (seconds)
    attempt_1: int = 5  # 5 seconds
    attempt_2: int = 30  # 30 seconds
    attempt_3: int = 300  # 5 minutes
    attempt_4_plus: int = 3600  # 60 minutes

    # Quarantine durations (minutes)
    duration_403: int = 60  # 403 Forbidden: 60 minutes
    duration_429: int = 60  # Repeated 429: 60 minutes
    duration_captcha: int = 60  # CAPTCHA: 60 minutes
    duration_5xx: int = 30  # Server errors: 30 minutes
    duration_manual: int = 120  # Manual: 2 hours


class DomainQuarantine:
    """
    Domain quarantine service for ethical crawling.

    Tracks problematic domains and enforces exponential backoff.

    Thread-safe: Uses threading.Lock for concurrent access.
    """

    def __init__(self, backoff_schedule: Optional[BackoffSchedule] = None):
        """
        Initialize domain quarantine service.

        Args:
            backoff_schedule: Custom backoff schedule (uses default if None)
        """
        self.backoff_schedule = backoff_schedule or BackoffSchedule()
        self.logger = get_logger("domain_quarantine")

        # Quarantine storage: domain -> QuarantineEntry
        self._quarantined: Dict[str, QuarantineEntry] = {}

        # Retry attempt tracking: domain -> attempt_count
        self._retry_attempts: Dict[str, int] = {}

        # Rate limit event tracking: domain -> [(timestamp, reason), ...]
        # Used to detect repeated 429s or 5xxs
        self._error_events: Dict[str, List[tuple[datetime, str]]] = {}

        # Thread lock for concurrent access
        self._lock = threading.Lock()

        self.logger.info("DomainQuarantine initialized")

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain (lowercase, strip www)."""
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain

    def _cleanup_expired_quarantines(self):
        """Remove expired quarantine entries (called internally)."""
        now = datetime.now()
        expired = [
            domain for domain, entry in self._quarantined.items()
            if entry.expires_at <= now
        ]

        for domain in expired:
            del self._quarantined[domain]
            # Reset retry attempt counter on expiration
            self._retry_attempts.pop(domain, None)
            self.logger.info(f"Quarantine expired for {domain}")

    def _cleanup_old_error_events(self, domain: str, window_minutes: int = 60):
        """Remove error events older than window_minutes."""
        if domain not in self._error_events:
            return

        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        self._error_events[domain] = [
            (ts, reason) for ts, reason in self._error_events[domain]
            if ts >= cutoff
        ]

        # Remove empty lists
        if not self._error_events[domain]:
            del self._error_events[domain]

    def is_quarantined(self, domain: str) -> bool:
        """
        Check if a domain is currently quarantined.

        Args:
            domain: Domain to check

        Returns:
            True if quarantined, False otherwise
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            self._cleanup_expired_quarantines()
            return domain in self._quarantined

    def get_quarantine_entry(self, domain: str) -> Optional[QuarantineEntry]:
        """
        Get quarantine entry for a domain.

        Args:
            domain: Domain to query

        Returns:
            QuarantineEntry if quarantined, None otherwise
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            self._cleanup_expired_quarantines()
            return self._quarantined.get(domain)

    def get_quarantine_end(self, domain: str) -> Optional[datetime]:
        """
        Get quarantine expiration time for a domain.

        Args:
            domain: Domain to query

        Returns:
            Datetime when quarantine expires, or None if not quarantined
        """
        entry = self.get_quarantine_entry(domain)
        return entry.expires_at if entry else None

    def get_retry_attempt(self, domain: str) -> int:
        """
        Get current retry attempt count for a domain.

        Args:
            domain: Domain to query

        Returns:
            Retry attempt count (0 = first attempt, 1 = first retry, etc.)
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            return self._retry_attempts.get(domain, 0)

    def get_backoff_delay(self, attempt: int) -> int:
        """
        Get exponential backoff delay in seconds for given attempt.

        Args:
            attempt: Retry attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        if attempt == 0:
            return 0  # No delay on first attempt
        elif attempt == 1:
            return self.backoff_schedule.attempt_1  # 5s
        elif attempt == 2:
            return self.backoff_schedule.attempt_2  # 30s
        elif attempt == 3:
            return self.backoff_schedule.attempt_3  # 5m
        else:
            return self.backoff_schedule.attempt_4_plus  # 60m

    def quarantine_domain(
        self,
        domain: str,
        reason: str,
        duration_minutes: Optional[int] = None,
        retry_after_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Quarantine a domain.

        Args:
            domain: Domain to quarantine
            reason: Reason code (QuarantineReason enum value or string)
            duration_minutes: Quarantine duration in minutes (uses default if None)
            retry_after_seconds: Retry-After header value (overrides duration if larger)
            metadata: Additional context
        """
        domain = self._normalize_domain(domain)

        # Parse reason
        try:
            reason_enum = QuarantineReason(reason)
        except ValueError:
            # If not a known reason, default to MANUAL
            reason_enum = QuarantineReason.MANUAL
            self.logger.warning(f"Unknown quarantine reason: {reason}, using MANUAL")

        # Determine duration
        if duration_minutes is None:
            # Use default duration based on reason
            if reason_enum == QuarantineReason.FORBIDDEN_403:
                duration_minutes = self.backoff_schedule.duration_403
            elif reason_enum == QuarantineReason.TOO_MANY_REQUESTS_429:
                duration_minutes = self.backoff_schedule.duration_429
            elif reason_enum == QuarantineReason.CAPTCHA_DETECTED:
                duration_minutes = self.backoff_schedule.duration_captcha
            elif reason_enum == QuarantineReason.SERVER_ERROR_5XX:
                duration_minutes = self.backoff_schedule.duration_5xx
            else:
                duration_minutes = self.backoff_schedule.duration_manual

        # Respect Retry-After header if longer than default
        if retry_after_seconds and retry_after_seconds > (duration_minutes * 60):
            duration_minutes = retry_after_seconds // 60
            self.logger.info(
                f"Using Retry-After {retry_after_seconds}s "
                f"({duration_minutes}m) for {domain}"
            )

        with self._lock:
            # Get current retry attempt
            attempt = self._retry_attempts.get(domain, 0)

            # Create quarantine entry
            now = datetime.now()
            expires_at = now + timedelta(minutes=duration_minutes)

            entry = QuarantineEntry(
                domain=domain,
                reason=reason_enum,
                quarantined_at=now,
                expires_at=expires_at,
                retry_attempt=attempt,
                retry_after_seconds=retry_after_seconds,
                metadata=metadata or {}
            )

            self._quarantined[domain] = entry

            # Increment retry attempt
            self._retry_attempts[domain] = attempt + 1

            self.logger.warning(
                f"Quarantined {domain} for {duration_minutes}m "
                f"(reason: {reason_enum.value}, attempt: {attempt})"
            )

    def record_error_event(self, domain: str, reason: str):
        """
        Record an error event (429, 5xx) for pattern detection.

        Used to detect repeated errors that should trigger quarantine.

        Args:
            domain: Domain that errored
            reason: Error reason code
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            # Cleanup old events (keep 60-minute window)
            self._cleanup_old_error_events(domain, window_minutes=60)

            # Add new event
            if domain not in self._error_events:
                self._error_events[domain] = []

            self._error_events[domain].append((datetime.now(), reason))

            # Check for repeated 429s (3+ in 1 hour)
            if reason == "429":
                recent_429s = [
                    (ts, r) for ts, r in self._error_events[domain]
                    if r == "429" and ts >= datetime.now() - timedelta(hours=1)
                ]

                if len(recent_429s) >= 3:
                    self.logger.warning(
                        f"Detected {len(recent_429s)} 429s for {domain} in last hour, "
                        "triggering quarantine"
                    )
                    self.quarantine_domain(
                        domain=domain,
                        reason=QuarantineReason.TOO_MANY_REQUESTS_429.value,
                        duration_minutes=self.backoff_schedule.duration_429,
                        metadata={"error_count": len(recent_429s)}
                    )

            # Check for repeated 5xxs (3+ in 10 minutes)
            if reason.startswith("5"):
                recent_5xxs = [
                    (ts, r) for ts, r in self._error_events[domain]
                    if r.startswith("5") and ts >= datetime.now() - timedelta(minutes=10)
                ]

                if len(recent_5xxs) >= 3:
                    self.logger.warning(
                        f"Detected {len(recent_5xxs)} 5xx errors for {domain} in last 10 minutes, "
                        "triggering quarantine"
                    )
                    self.quarantine_domain(
                        domain=domain,
                        reason=QuarantineReason.SERVER_ERROR_5XX.value,
                        duration_minutes=self.backoff_schedule.duration_5xx,
                        metadata={"error_count": len(recent_5xxs)}
                    )

    def release_quarantine(self, domain: str):
        """
        Manually release a domain from quarantine.

        Args:
            domain: Domain to release
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            if domain in self._quarantined:
                del self._quarantined[domain]
                self._retry_attempts.pop(domain, None)
                self.logger.info(f"Released quarantine for {domain}")
            else:
                self.logger.warning(f"Domain not quarantined: {domain}")

    def reset_retry_attempts(self, domain: str):
        """
        Reset retry attempt counter for a domain.

        Useful after successful request to reset exponential backoff.

        Args:
            domain: Domain to reset
        """
        domain = self._normalize_domain(domain)

        with self._lock:
            if domain in self._retry_attempts:
                del self._retry_attempts[domain]
                self.logger.debug(f"Reset retry attempts for {domain}")

    def get_quarantined_domains(self) -> List[QuarantineEntry]:
        """
        Get all currently quarantined domains.

        Returns:
            List of QuarantineEntry objects
        """
        with self._lock:
            self._cleanup_expired_quarantines()
            return list(self._quarantined.values())

    def get_stats(self) -> Dict[str, Any]:
        """
        Get quarantine statistics.

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            self._cleanup_expired_quarantines()

            # Count by reason
            reason_counts = {}
            for entry in self._quarantined.values():
                reason = entry.reason.value
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            return {
                "total_quarantined": len(self._quarantined),
                "by_reason": reason_counts,
                "domains_with_retries": len(self._retry_attempts),
                "domains_with_errors": len(self._error_events),
            }

    def clear_all(self):
        """Clear all quarantine data (for testing/reset)."""
        with self._lock:
            self._quarantined.clear()
            self._retry_attempts.clear()
            self._error_events.clear()
            self.logger.info("Cleared all quarantine data")


def get_domain_quarantine() -> DomainQuarantine:
    """
    Get singleton DomainQuarantine instance.

    Returns:
        DomainQuarantine instance
    """
    global _domain_quarantine

    if _domain_quarantine is None:
        _domain_quarantine = DomainQuarantine()

    return _domain_quarantine

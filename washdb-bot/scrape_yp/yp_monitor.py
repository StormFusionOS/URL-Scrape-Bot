#!/usr/bin/env python3
"""
Monitoring and health check module for Yellow Pages scraping.

This module provides:
- Success/error rate tracking
- CAPTCHA detection
- Adaptive rate limiting
- Health check system
- Real-time metrics and alerts
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ScraperMetrics:
    """Container for scraper metrics."""

    # Counters
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    captcha_detected: int = 0
    blocked_requests: int = 0

    # Results
    total_results_found: int = 0
    total_results_accepted: int = 0
    total_results_filtered: int = 0

    # Timing
    start_time: Optional[datetime] = None
    last_request_time: Optional[datetime] = None

    # Recent history (for rate calculations)
    recent_successes: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_failures: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_captchas: deque = field(default_factory=lambda: deque(maxlen=100))

    def success_rate(self) -> float:
        """Calculate overall success rate (0-100)."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    def recent_success_rate(self) -> float:
        """Calculate success rate over last 100 requests (0-100)."""
        total = len(self.recent_successes) + len(self.recent_failures)
        if total == 0:
            return 0.0
        return (len(self.recent_successes) / total) * 100

    def recent_captcha_rate(self) -> float:
        """Calculate CAPTCHA rate over last 100 requests (0-100)."""
        total = len(self.recent_successes) + len(self.recent_failures)
        if total == 0:
            return 0.0
        return (len(self.recent_captchas) / total) * 100

    def acceptance_rate(self) -> float:
        """Calculate result acceptance rate (0-100)."""
        if self.total_results_found == 0:
            return 0.0
        return (self.total_results_accepted / self.total_results_found) * 100

    def requests_per_minute(self) -> float:
        """Calculate requests per minute."""
        if not self.start_time:
            return 0.0

        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed == 0:
            return 0.0

        return (self.total_requests / elapsed) * 60

    def uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()


def detect_captcha(html: str) -> Tuple[bool, str]:
    """
    Detect if HTML contains a CAPTCHA challenge.

    Args:
        html: HTML content to check

    Returns:
        Tuple of (is_captcha, captcha_type)
    """
    if not html:
        return False, ""

    html_lower = html.lower()

    # Common CAPTCHA indicators
    captcha_indicators = [
        # reCAPTCHA
        ('recaptcha', 'reCAPTCHA'),
        ('g-recaptcha', 'reCAPTCHA'),
        ('grecaptcha', 'reCAPTCHA'),

        # hCaptcha
        ('hcaptcha', 'hCaptcha'),
        ('h-captcha', 'hCaptcha'),

        # Cloudflare
        ('cf-challenge', 'Cloudflare Challenge'),
        ('challenge-form', 'Cloudflare Challenge'),
        ('cloudflare', 'Cloudflare'),

        # Generic
        ('captcha', 'Generic CAPTCHA'),
        ('verify you are human', 'Human Verification'),
        ('prove you are not a robot', 'Bot Check'),
        ('security check', 'Security Check'),
        ('unusual traffic', 'Rate Limit Warning'),
    ]

    for indicator, captcha_type in captcha_indicators:
        if indicator in html_lower:
            return True, captcha_type

    return False, ""


def detect_blocking(html: str, status_code: Optional[int] = None) -> Tuple[bool, str]:
    """
    Detect if request was blocked or rate limited.

    Args:
        html: HTML content
        status_code: HTTP status code

    Returns:
        Tuple of (is_blocked, block_reason)
    """
    # Check status codes
    if status_code:
        if status_code == 403:
            return True, "403 Forbidden"
        elif status_code == 429:
            return True, "429 Too Many Requests"
        elif status_code in (503, 504):
            return True, f"{status_code} Service Unavailable"

    # Check HTML content
    if html:
        html_lower = html.lower()

        blocking_indicators = [
            'access denied',
            'blocked',
            'banned',
            'too many requests',
            'rate limit',
            'temporarily unavailable',
        ]

        for indicator in blocking_indicators:
            if indicator in html_lower:
                return True, f"Content indicates: {indicator}"

    return False, ""


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts delays based on error rates.

    Automatically slows down when error rates increase to avoid bans.
    """

    def __init__(
        self,
        base_delay: float = 5.0,
        min_delay: float = 2.0,
        max_delay: float = 30.0,
        error_threshold: float = 20.0,
        captcha_threshold: float = 5.0
    ):
        """
        Initialize adaptive rate limiter.

        Args:
            base_delay: Starting delay between requests (seconds)
            min_delay: Minimum delay (seconds)
            max_delay: Maximum delay (seconds)
            error_threshold: Error rate % that triggers slowdown
            captcha_threshold: CAPTCHA rate % that triggers slowdown
        """
        self.base_delay = base_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.error_threshold = error_threshold
        self.captcha_threshold = captcha_threshold

        self.current_delay = base_delay
        self.last_adjustment_time = datetime.now()
        self.adjustment_count = 0

    def get_delay(self, metrics: ScraperMetrics) -> float:
        """
        Get current delay based on recent metrics.

        Args:
            metrics: Current scraper metrics

        Returns:
            Delay in seconds
        """
        # Check if we should adjust (max once per 60 seconds)
        now = datetime.now()
        if (now - self.last_adjustment_time).total_seconds() < 60:
            return self.current_delay

        # Get recent rates
        recent_success_rate = metrics.recent_success_rate()
        recent_captcha_rate = metrics.recent_captcha_rate()
        recent_error_rate = 100 - recent_success_rate

        # Decision logic
        should_slow_down = (
            recent_error_rate > self.error_threshold or
            recent_captcha_rate > self.captcha_threshold
        )

        should_speed_up = (
            recent_success_rate > 95.0 and
            recent_captcha_rate < 1.0 and
            self.current_delay > self.base_delay
        )

        if should_slow_down:
            # Increase delay by 50%
            self.current_delay = min(self.current_delay * 1.5, self.max_delay)
            self.adjustment_count += 1
            self.last_adjustment_time = now

            # Log adjustment
            try:
                from runner.logging_setup import get_logger
                logger = get_logger("rate_limiter")
                logger.warning(
                    f"Slowing down: error_rate={recent_error_rate:.1f}%, "
                    f"captcha_rate={recent_captcha_rate:.1f}%, "
                    f"new_delay={self.current_delay:.1f}s"
                )
            except Exception:
                pass

        elif should_speed_up:
            # Decrease delay by 25%
            self.current_delay = max(self.current_delay * 0.75, self.min_delay)
            self.adjustment_count += 1
            self.last_adjustment_time = now

            # Log adjustment
            try:
                from runner.logging_setup import get_logger
                logger = get_logger("rate_limiter")
                logger.info(
                    f"Speeding up: success_rate={recent_success_rate:.1f}%, "
                    f"new_delay={self.current_delay:.1f}s"
                )
            except Exception:
                pass

        return self.current_delay

    def reset(self):
        """Reset to base delay."""
        self.current_delay = self.base_delay
        self.last_adjustment_time = datetime.now()


class HealthChecker:
    """
    Health check system for the scraper.

    Monitors overall health and provides status/alerts.
    """

    def __init__(self):
        """Initialize health checker."""
        self.last_check_time = datetime.now()
        self.health_history: List[Tuple[datetime, str]] = []

    def check_health(self, metrics: ScraperMetrics) -> Tuple[str, List[str]]:
        """
        Check overall scraper health.

        Args:
            metrics: Current scraper metrics

        Returns:
            Tuple of (health_status, issues_list)
            - health_status: 'healthy', 'degraded', 'unhealthy', 'critical'
            - issues_list: List of issue descriptions
        """
        issues = []

        # Check 1: Success rate
        recent_success = metrics.recent_success_rate()
        if recent_success < 50:
            issues.append(f"Very low success rate: {recent_success:.1f}%")
        elif recent_success < 75:
            issues.append(f"Low success rate: {recent_success:.1f}%")

        # Check 2: CAPTCHA rate
        captcha_rate = metrics.recent_captcha_rate()
        if captcha_rate > 10:
            issues.append(f"High CAPTCHA rate: {captcha_rate:.1f}%")
        elif captcha_rate > 5:
            issues.append(f"Elevated CAPTCHA rate: {captcha_rate:.1f}%")

        # Check 3: Block rate
        if metrics.blocked_requests > 0:
            block_rate = (metrics.blocked_requests / metrics.total_requests) * 100
            if block_rate > 10:
                issues.append(f"High block rate: {block_rate:.1f}%")

        # Check 4: Results acceptance rate
        acceptance = metrics.acceptance_rate()
        if acceptance < 30 and metrics.total_results_found > 100:
            issues.append(f"Low acceptance rate: {acceptance:.1f}% (filter may be too strict)")

        # Check 5: Request rate
        rpm = metrics.requests_per_minute()
        if rpm > 20:
            issues.append(f"High request rate: {rpm:.1f} req/min (risk of ban)")

        # Check 6: Uptime without success
        if metrics.total_requests > 50 and metrics.successful_requests == 0:
            issues.append("No successful requests yet after 50 attempts")

        # Determine overall health status
        if not issues:
            status = "healthy"
        elif len(issues) == 1:
            status = "degraded"
        elif len(issues) <= 3:
            status = "unhealthy"
        else:
            status = "critical"

        # Record health check
        self.health_history.append((datetime.now(), status))
        self.last_check_time = datetime.now()

        return status, issues

    def get_recommendations(self, metrics: ScraperMetrics, issues: List[str]) -> List[str]:
        """
        Get recommendations based on current issues.

        Args:
            metrics: Current metrics
            issues: List of current issues

        Returns:
            List of recommendation strings
        """
        recommendations = []

        for issue in issues:
            if "success rate" in issue.lower():
                recommendations.append("→ Increase delays between requests")
                recommendations.append("→ Check if site structure has changed")

            elif "captcha" in issue.lower():
                recommendations.append("→ Take a longer break (session break)")
                recommendations.append("→ Rotate user agents more frequently")
                recommendations.append("→ Consider manual intervention")

            elif "block rate" in issue.lower():
                recommendations.append("→ Stop scraping immediately")
                recommendations.append("→ Wait 1-2 hours before resuming")
                recommendations.append("→ Increase delays significantly")

            elif "acceptance rate" in issue.lower():
                recommendations.append("→ Review filter settings")
                recommendations.append("→ Check if categories are too restrictive")

            elif "request rate" in issue.lower():
                recommendations.append("→ Enable session breaks")
                recommendations.append("→ Increase base delay between requests")

        # Deduplicate recommendations
        return list(dict.fromkeys(recommendations))


class ScraperMonitor:
    """
    Comprehensive monitoring system for the scraper.

    Combines metrics, rate limiting, and health checks.
    """

    def __init__(
        self,
        enable_adaptive_rate_limiting: bool = True,
        base_delay: float = 5.0
    ):
        """
        Initialize scraper monitor.

        Args:
            enable_adaptive_rate_limiting: Enable adaptive rate limiting
            base_delay: Base delay between requests
        """
        self.metrics = ScraperMetrics()
        self.metrics.start_time = datetime.now()

        self.rate_limiter = AdaptiveRateLimiter(base_delay=base_delay) if enable_adaptive_rate_limiting else None
        self.health_checker = HealthChecker()

        self.alerts_sent: List[Tuple[datetime, str]] = []

    def record_request(self, success: bool, html: str = "", status_code: Optional[int] = None):
        """
        Record a request and its outcome.

        Args:
            success: Whether request succeeded
            html: HTML content (for CAPTCHA/block detection)
            status_code: HTTP status code
        """
        self.metrics.total_requests += 1
        self.metrics.last_request_time = datetime.now()

        if success:
            self.metrics.successful_requests += 1
            self.metrics.recent_successes.append(datetime.now())
        else:
            self.metrics.failed_requests += 1
            self.metrics.recent_failures.append(datetime.now())

        # Check for CAPTCHA
        is_captcha, captcha_type = detect_captcha(html)
        if is_captcha:
            self.metrics.captcha_detected += 1
            self.metrics.recent_captchas.append(datetime.now())
            self._send_alert(f"CAPTCHA detected: {captcha_type}")

        # Check for blocking
        is_blocked, block_reason = detect_blocking(html, status_code)
        if is_blocked:
            self.metrics.blocked_requests += 1
            self._send_alert(f"Request blocked: {block_reason}")

    def record_results(self, found: int, accepted: int, filtered: int):
        """
        Record results from parsing.

        Args:
            found: Number of results found
            accepted: Number of results accepted
            filtered: Number of results filtered out
        """
        self.metrics.total_results_found += found
        self.metrics.total_results_accepted += accepted
        self.metrics.total_results_filtered += filtered

    def get_delay(self) -> float:
        """Get current recommended delay between requests."""
        if self.rate_limiter:
            return self.rate_limiter.get_delay(self.metrics)
        return 5.0  # Default delay

    def check_health(self) -> Tuple[str, List[str], List[str]]:
        """
        Check scraper health and get recommendations.

        Returns:
            Tuple of (status, issues, recommendations)
        """
        status, issues = self.health_checker.check_health(self.metrics)
        recommendations = self.health_checker.get_recommendations(self.metrics, issues)

        return status, issues, recommendations

    def get_summary(self) -> Dict:
        """
        Get comprehensive summary of metrics.

        Returns:
            Dict with all metrics and status
        """
        status, issues, recommendations = self.check_health()

        return {
            'status': status,
            'uptime_seconds': self.metrics.uptime_seconds(),
            'total_requests': self.metrics.total_requests,
            'success_rate': self.metrics.success_rate(),
            'recent_success_rate': self.metrics.recent_success_rate(),
            'captcha_rate': self.metrics.recent_captcha_rate(),
            'acceptance_rate': self.metrics.acceptance_rate(),
            'requests_per_minute': self.metrics.requests_per_minute(),
            'results_found': self.metrics.total_results_found,
            'results_accepted': self.metrics.total_results_accepted,
            'current_delay': self.get_delay() if self.rate_limiter else None,
            'issues': issues,
            'recommendations': recommendations,
        }

    def _send_alert(self, message: str):
        """Send an alert (logged for now, could email/slack later)."""
        # Deduplicate alerts (don't send same alert within 5 minutes)
        now = datetime.now()
        recent_alerts = [
            (ts, msg) for ts, msg in self.alerts_sent
            if (now - ts).total_seconds() < 300
        ]

        if any(msg == message for _, msg in recent_alerts):
            return  # Already sent recently

        # Log alert
        try:
            from runner.logging_setup import get_logger
            logger = get_logger("monitor")
            logger.warning(f"ALERT: {message}")
        except Exception:
            pass

        # Record alert
        self.alerts_sent.append((now, message))

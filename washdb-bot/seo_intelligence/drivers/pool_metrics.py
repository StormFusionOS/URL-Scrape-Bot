"""
Browser Pool Metrics and Observability

Provides comprehensive metrics tracking for the Enterprise Browser Pool:
- Session state distribution
- Lease duration statistics (p50, p95, p99)
- Success/failure rates by target group
- CAPTCHA rates by domain
- Warmup success rates
- Recycle counts by reason
- Browser type distribution
"""

import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from runner.logging_setup import get_logger

logger = get_logger("pool_metrics")


@dataclass
class LeaseMetrics:
    """Metrics for a single lease lifecycle."""
    lease_id: str
    session_id: str
    target_domain: str
    target_group: str
    requester: str
    browser_type: str
    proxy_location: Optional[str] = None

    # Timing
    acquired_at: datetime = field(default_factory=datetime.now)
    released_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Outcome
    success: bool = True
    blocked: bool = False
    captcha: bool = False
    error: Optional[str] = None

    # Navigation
    pages_visited: int = 0

    def finalize(self, success: bool = True, blocked: bool = False,
                 captcha: bool = False, error: str = None):
        """Finalize metrics when lease is released."""
        self.released_at = datetime.now()
        self.duration_seconds = (self.released_at - self.acquired_at).total_seconds()
        self.success = success
        self.blocked = blocked
        self.captcha = captcha
        self.error = error


@dataclass
class DomainMetrics:
    """Aggregated metrics for a specific domain."""
    domain: str
    total_requests: int = 0
    successful_requests: int = 0
    blocked_requests: int = 0
    captcha_requests: int = 0
    total_duration_seconds: float = 0.0
    last_request_at: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def block_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.blocked_requests / self.total_requests

    @property
    def captcha_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.captcha_requests / self.total_requests

    @property
    def avg_duration_seconds(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_seconds / self.total_requests

    def to_dict(self) -> Dict:
        return {
            "domain": self.domain,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "blocked_requests": self.blocked_requests,
            "captcha_requests": self.captcha_requests,
            "success_rate": round(self.success_rate, 3),
            "block_rate": round(self.block_rate, 3),
            "captcha_rate": round(self.captcha_rate, 3),
            "avg_duration_seconds": round(self.avg_duration_seconds, 2),
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
        }


class PoolMetricsCollector:
    """
    Collects and aggregates metrics for the browser pool.

    Thread-safe metrics collection with rolling windows for
    recent statistics and lifetime aggregates.
    """

    # How long to keep detailed lease metrics (for percentile calculations)
    METRICS_RETENTION_HOURS = 24

    def __init__(self):
        self._lock = threading.RLock()

        # Recent lease metrics (for percentile calculations)
        self._recent_leases: List[LeaseMetrics] = []

        # Domain-level aggregates
        self._domain_metrics: Dict[str, DomainMetrics] = defaultdict(
            lambda: DomainMetrics(domain="")
        )

        # Lifetime counters
        self._total_leases_issued = 0
        self._total_leases_success = 0
        self._total_leases_failed = 0
        self._total_warmups = 0
        self._total_warmups_success = 0
        self._total_recycles = 0
        self._total_escalations = 0

        # Recycle reason counters
        self._recycle_reasons: Dict[str, int] = defaultdict(int)

        # Target group metrics
        self._group_metrics: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"leases": 0, "success": 0, "failed": 0, "captchas": 0}
        )

        # Browser type distribution
        self._browser_type_counts: Dict[str, int] = defaultdict(int)

        # Timestamps
        self._started_at = datetime.now()
        self._last_cleanup_at = datetime.now()

    def record_lease_acquired(
        self,
        lease_id: str,
        session_id: str,
        target_domain: str,
        target_group: str,
        requester: str,
        browser_type: str,
        proxy_location: Optional[str] = None,
    ) -> LeaseMetrics:
        """Record that a lease was acquired."""
        with self._lock:
            metrics = LeaseMetrics(
                lease_id=lease_id,
                session_id=session_id,
                target_domain=target_domain,
                target_group=target_group,
                requester=requester,
                browser_type=browser_type,
                proxy_location=proxy_location,
            )

            self._total_leases_issued += 1
            self._group_metrics[target_group]["leases"] += 1
            self._browser_type_counts[browser_type] += 1

            return metrics

    def record_lease_released(
        self,
        metrics: LeaseMetrics,
        success: bool = True,
        blocked: bool = False,
        captcha: bool = False,
        error: str = None,
        pages_visited: int = 0,
    ):
        """Record that a lease was released."""
        with self._lock:
            metrics.finalize(success, blocked, captcha, error)
            metrics.pages_visited = pages_visited

            # Update counters
            if success:
                self._total_leases_success += 1
                self._group_metrics[metrics.target_group]["success"] += 1
            else:
                self._total_leases_failed += 1
                self._group_metrics[metrics.target_group]["failed"] += 1

            if captcha:
                self._group_metrics[metrics.target_group]["captchas"] += 1

            # Update domain metrics
            domain = metrics.target_domain
            dm = self._domain_metrics[domain]
            dm.domain = domain
            dm.total_requests += 1
            dm.total_duration_seconds += metrics.duration_seconds
            dm.last_request_at = datetime.now()

            if success:
                dm.successful_requests += 1
            if blocked:
                dm.blocked_requests += 1
            if captcha:
                dm.captcha_requests += 1

            # Keep recent leases for percentile calculations
            self._recent_leases.append(metrics)

            # Periodic cleanup
            self._maybe_cleanup()

    def record_warmup(self, success: bool):
        """Record a warmup attempt."""
        with self._lock:
            self._total_warmups += 1
            if success:
                self._total_warmups_success += 1

    def record_recycle(self, reason: str):
        """Record a session recycle."""
        with self._lock:
            self._total_recycles += 1
            self._recycle_reasons[reason] += 1

    def record_escalation(self, from_type: str, to_type: str):
        """Record a browser type escalation."""
        with self._lock:
            self._total_escalations += 1
            logger.info(f"Browser escalation: {from_type} → {to_type}")

    def _maybe_cleanup(self):
        """Clean up old lease metrics to prevent memory growth."""
        now = datetime.now()
        if (now - self._last_cleanup_at).total_seconds() < 3600:  # Every hour
            return

        cutoff = now - timedelta(hours=self.METRICS_RETENTION_HOURS)
        self._recent_leases = [
            m for m in self._recent_leases
            if m.acquired_at > cutoff
        ]
        self._last_cleanup_at = now

    def _calculate_percentiles(self, values: List[float]) -> Dict[str, float]:
        """Calculate p50, p95, p99 for a list of values."""
        if not values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

        sorted_values = sorted(values)
        n = len(sorted_values)

        def percentile(p: float) -> float:
            k = (n - 1) * p / 100
            f = int(k)
            c = f + 1 if f + 1 < n else f
            return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])

        return {
            "p50": round(percentile(50), 2),
            "p95": round(percentile(95), 2),
            "p99": round(percentile(99), 2),
        }

    def get_lease_duration_stats(self) -> Dict[str, Any]:
        """Get lease duration statistics."""
        with self._lock:
            durations = [m.duration_seconds for m in self._recent_leases if m.released_at]

            if not durations:
                return {
                    "count": 0,
                    "avg": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "percentiles": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
                }

            return {
                "count": len(durations),
                "avg": round(statistics.mean(durations), 2),
                "min": round(min(durations), 2),
                "max": round(max(durations), 2),
                "percentiles": self._calculate_percentiles(durations),
            }

    def get_success_rate(self) -> float:
        """Get overall success rate."""
        total = self._total_leases_success + self._total_leases_failed
        if total == 0:
            return 1.0
        return self._total_leases_success / total

    def get_warmup_success_rate(self) -> float:
        """Get warmup success rate."""
        if self._total_warmups == 0:
            return 1.0
        return self._total_warmups_success / self._total_warmups

    def get_domain_metrics(self, domain: str = None) -> Dict[str, Any]:
        """Get metrics for a specific domain or all domains."""
        with self._lock:
            if domain:
                if domain in self._domain_metrics:
                    return self._domain_metrics[domain].to_dict()
                return {}

            return {
                d: m.to_dict()
                for d, m in self._domain_metrics.items()
            }

    def get_top_blocked_domains(self, limit: int = 10) -> List[Dict]:
        """Get domains with highest block rates."""
        with self._lock:
            domains = [
                m.to_dict() for m in self._domain_metrics.values()
                if m.total_requests >= 5  # Minimum sample size
            ]
            return sorted(domains, key=lambda x: x["block_rate"], reverse=True)[:limit]

    def get_group_metrics(self) -> Dict[str, Dict]:
        """Get metrics by target group."""
        with self._lock:
            result = {}
            for group, metrics in self._group_metrics.items():
                total = metrics["leases"]
                result[group] = {
                    "total_leases": total,
                    "success": metrics["success"],
                    "failed": metrics["failed"],
                    "captchas": metrics["captchas"],
                    "success_rate": round(metrics["success"] / total, 3) if total > 0 else 1.0,
                }
            return result

    def get_browser_type_distribution(self) -> Dict[str, int]:
        """Get distribution of browser types used."""
        with self._lock:
            return dict(self._browser_type_counts)

    def get_recycle_breakdown(self) -> Dict[str, int]:
        """Get breakdown of recycle reasons."""
        with self._lock:
            return dict(self._recycle_reasons)

    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary."""
        with self._lock:
            uptime = (datetime.now() - self._started_at).total_seconds()

            return {
                "uptime_seconds": round(uptime, 0),
                "uptime_human": str(timedelta(seconds=int(uptime))),

                # Lease metrics
                "total_leases_issued": self._total_leases_issued,
                "total_leases_success": self._total_leases_success,
                "total_leases_failed": self._total_leases_failed,
                "overall_success_rate": round(self.get_success_rate(), 3),
                "lease_duration_stats": self.get_lease_duration_stats(),

                # Warmup metrics
                "total_warmups": self._total_warmups,
                "warmup_success_rate": round(self.get_warmup_success_rate(), 3),

                # Recycle metrics
                "total_recycles": self._total_recycles,
                "total_escalations": self._total_escalations,
                "recycle_breakdown": self.get_recycle_breakdown(),

                # Group metrics
                "group_metrics": self.get_group_metrics(),

                # Browser distribution
                "browser_type_distribution": self.get_browser_type_distribution(),

                # Domain insights
                "top_blocked_domains": self.get_top_blocked_domains(5),
                "domains_tracked": len(self._domain_metrics),
            }

    def log_summary(self):
        """Log a metrics summary."""
        summary = self.get_summary()

        logger.info(
            f"Pool Metrics Summary: "
            f"uptime={summary['uptime_human']}, "
            f"leases={summary['total_leases_issued']}, "
            f"success_rate={summary['overall_success_rate']:.1%}, "
            f"warmup_rate={summary['warmup_success_rate']:.1%}, "
            f"recycles={summary['total_recycles']}, "
            f"escalations={summary['total_escalations']}"
        )


# Module-level singleton
_metrics_instance: Optional[PoolMetricsCollector] = None
_metrics_lock = threading.Lock()


def get_pool_metrics() -> PoolMetricsCollector:
    """Get the pool metrics collector singleton."""
    global _metrics_instance
    with _metrics_lock:
        if _metrics_instance is None:
            _metrics_instance = PoolMetricsCollector()
        return _metrics_instance


def reset_pool_metrics():
    """Reset the pool metrics collector (for testing)."""
    global _metrics_instance
    with _metrics_lock:
        _metrics_instance = None

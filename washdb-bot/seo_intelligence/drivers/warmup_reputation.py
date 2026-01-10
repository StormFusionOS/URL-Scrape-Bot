"""
Warmup URL Reputation Tracker

Tracks which warmup URLs succeed vs fail and prioritizes successful ones.
This helps build browser reputation faster by visiting sites that don't block us.

Features:
- Tracks success/failure per URL with timestamps
- Calculates rolling success rate
- Prioritizes high-success URLs in warmup plans
- Persists data to disk for reuse across restarts
- Ages out old data (configurable TTL)
"""

import json
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from runner.logging_setup import get_logger

logger = get_logger("warmup_reputation")

# Default storage path
DEFAULT_REPUTATION_FILE = Path(__file__).parent.parent.parent / "data" / "warmup_reputation.json"

# Configuration
REPUTATION_TTL_DAYS = 30  # How long to keep reputation data
MIN_SAMPLES_FOR_CONFIDENCE = 3  # Minimum attempts before trusting success rate
SUCCESS_RATE_BOOST_THRESHOLD = 0.8  # URLs above this rate get priority
FAILURE_RATE_PENALTY_THRESHOLD = 0.6  # URLs below this rate get deprioritized


@dataclass
class URLReputationEntry:
    """Reputation data for a single warmup URL."""
    url: str
    success_count: int = 0
    failure_count: int = 0
    block_count: int = 0  # Specifically blocked (CAPTCHA, access denied)
    timeout_count: int = 0  # Timeouts (may be network issues)
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    last_attempt: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def total_attempts(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.5  # Unknown URLs get neutral score
        return self.success_count / self.total_attempts

    @property
    def confidence(self) -> float:
        """How confident we are in the success rate (0-1)."""
        if self.total_attempts == 0:
            return 0.0
        # More attempts = higher confidence, caps at 1.0
        return min(1.0, self.total_attempts / 10)

    @property
    def weighted_score(self) -> float:
        """
        Score combining success rate and confidence.

        High confidence + high success = best
        Low confidence = neutral (0.5)
        High confidence + low success = worst
        """
        neutral_rate = 0.5
        return neutral_rate + (self.success_rate - neutral_rate) * self.confidence

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'URLReputationEntry':
        return cls(**data)


class WarmupReputationTracker:
    """
    Tracks warmup URL reputation and provides optimized warmup plans.

    Usage:
        tracker = WarmupReputationTracker()

        # Record outcomes
        tracker.record_success("https://example.com/")
        tracker.record_failure("https://blocked-site.com/", blocked=True)

        # Get optimized warmup URLs
        urls = tracker.get_prioritized_warmup_urls(target_group="search_engines", count=10)
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path or DEFAULT_REPUTATION_FILE
        self._reputation: Dict[str, URLReputationEntry] = {}
        self._lock = threading.RLock()
        self._dirty = False  # Track if we need to save
        self._last_save = time.time()
        self._save_interval = 60  # Save every 60 seconds if dirty

        # Load existing data
        self._load()
        logger.info(f"WarmupReputationTracker initialized with {len(self._reputation)} URLs")

    def _load(self) -> None:
        """Load reputation data from disk."""
        try:
            if self._storage_path.exists():
                with open(self._storage_path, 'r') as f:
                    data = json.load(f)

                # Convert to URLReputationEntry objects
                for url, entry_data in data.get('urls', {}).items():
                    try:
                        self._reputation[url] = URLReputationEntry.from_dict(entry_data)
                    except Exception as e:
                        logger.warning(f"Failed to load entry for {url}: {e}")

                # Clean up old entries
                self._cleanup_old_entries()

                logger.info(f"Loaded {len(self._reputation)} URL reputation entries")
        except Exception as e:
            logger.warning(f"Failed to load reputation data: {e}")
            self._reputation = {}

    def _save(self, force: bool = False) -> None:
        """Save reputation data to disk."""
        if not self._dirty and not force:
            return

        # Check if enough time has passed since last save
        if not force and (time.time() - self._last_save) < self._save_interval:
            return

        try:
            # Ensure directory exists
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                data = {
                    'version': 1,
                    'updated_at': datetime.now().isoformat(),
                    'urls': {url: entry.to_dict() for url, entry in self._reputation.items()}
                }

                # Write atomically
                temp_path = self._storage_path.with_suffix('.tmp')
                with open(temp_path, 'w') as f:
                    json.dump(data, f, indent=2)
                temp_path.replace(self._storage_path)

                self._dirty = False
                self._last_save = time.time()

        except Exception as e:
            logger.error(f"Failed to save reputation data: {e}")

    def _cleanup_old_entries(self) -> None:
        """Remove entries that haven't been used in TTL days."""
        cutoff = datetime.now() - timedelta(days=REPUTATION_TTL_DAYS)
        cutoff_str = cutoff.isoformat()

        to_remove = []
        for url, entry in self._reputation.items():
            if entry.last_attempt and entry.last_attempt < cutoff_str:
                to_remove.append(url)

        for url in to_remove:
            del self._reputation[url]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old reputation entries")
            self._dirty = True

    def _get_or_create_entry(self, url: str) -> URLReputationEntry:
        """Get existing entry or create new one."""
        if url not in self._reputation:
            self._reputation[url] = URLReputationEntry(url=url)
            self._dirty = True
        return self._reputation[url]

    def record_success(self, url: str) -> None:
        """Record a successful warmup visit."""
        with self._lock:
            entry = self._get_or_create_entry(url)
            entry.success_count += 1
            entry.last_success = datetime.now().isoformat()
            entry.last_attempt = entry.last_success
            self._dirty = True
            self._save()

        logger.debug(f"Recorded success for {url} (rate: {entry.success_rate:.1%})")

    def record_failure(
        self,
        url: str,
        blocked: bool = False,
        timeout: bool = False,
        reason: str = ""
    ) -> None:
        """
        Record a failed warmup visit.

        Args:
            url: The URL that failed
            blocked: True if blocked by CAPTCHA or access denied
            timeout: True if timed out
            reason: Optional reason string for logging
        """
        with self._lock:
            entry = self._get_or_create_entry(url)
            entry.failure_count += 1
            if blocked:
                entry.block_count += 1
            if timeout:
                entry.timeout_count += 1
            entry.last_failure = datetime.now().isoformat()
            entry.last_attempt = entry.last_failure
            self._dirty = True
            self._save()

        logger.debug(f"Recorded failure for {url} (rate: {entry.success_rate:.1%}, reason: {reason})")

    def get_url_stats(self, url: str) -> Optional[URLReputationEntry]:
        """Get stats for a specific URL."""
        return self._reputation.get(url)

    def get_prioritized_warmup_urls(
        self,
        base_urls: List[Tuple],
        count: int = 10,
        include_new: bool = True
    ) -> List[Tuple]:
        """
        Get warmup URLs sorted by success rate.

        High-success URLs are returned first, followed by unknown URLs,
        then low-success URLs (which may be skipped entirely).

        Args:
            base_urls: List of tuples - can be (url, min_wait, max_wait) or
                      (url, min_wait, max_wait, category) format
            count: Maximum number of URLs to return
            include_new: Whether to include URLs we haven't tried yet

        Returns:
            Sorted list of tuples in the same format as input
        """
        with self._lock:
            scored_urls = []

            for url_tuple in base_urls:
                # Handle both 3-tuple and 4-tuple formats
                url = url_tuple[0]
                entry = self._reputation.get(url)

                if entry:
                    score = entry.weighted_score
                    # Heavily penalize URLs that are frequently blocked
                    if entry.block_count > 2:
                        score *= 0.5
                else:
                    # Unknown URLs get neutral-positive score
                    # (we want to try them to learn)
                    score = 0.55 if include_new else 0.0

                # Store score and original tuple together
                scored_urls.append((score, url_tuple))

            # Sort by score descending
            scored_urls.sort(key=lambda x: x[0], reverse=True)

            # Filter out very low success rates
            result = []
            for score, url_tuple in scored_urls:
                if score >= 0.2:  # Only include URLs with >20% weighted score
                    result.append(url_tuple)
                    if len(result) >= count:
                        break

            # If we don't have enough, add some unknown URLs
            if len(result) < count and include_new:
                for score, url_tuple in scored_urls:
                    if url_tuple not in result:
                        result.append(url_tuple)
                        if len(result) >= count:
                            break

            return result[:count]

    def get_best_urls(self, min_success_rate: float = 0.7, limit: int = 20) -> List[str]:
        """Get URLs with best success rates."""
        with self._lock:
            good_urls = [
                (entry.success_rate, url)
                for url, entry in self._reputation.items()
                if entry.total_attempts >= MIN_SAMPLES_FOR_CONFIDENCE
                   and entry.success_rate >= min_success_rate
            ]
            good_urls.sort(reverse=True)
            return [url for _, url in good_urls[:limit]]

    def get_blocked_urls(self, limit: int = 20) -> List[str]:
        """Get URLs that frequently block us."""
        with self._lock:
            blocked = [
                (entry.block_count, url)
                for url, entry in self._reputation.items()
                if entry.block_count > 0
            ]
            blocked.sort(reverse=True)
            return [url for _, url in blocked[:limit]]

    def get_stats_summary(self) -> Dict:
        """Get overall reputation statistics."""
        with self._lock:
            total_urls = len(self._reputation)
            total_attempts = sum(e.total_attempts for e in self._reputation.values())
            total_successes = sum(e.success_count for e in self._reputation.values())
            total_blocks = sum(e.block_count for e in self._reputation.values())

            high_success = sum(
                1 for e in self._reputation.values()
                if e.total_attempts >= MIN_SAMPLES_FOR_CONFIDENCE
                   and e.success_rate >= SUCCESS_RATE_BOOST_THRESHOLD
            )
            low_success = sum(
                1 for e in self._reputation.values()
                if e.total_attempts >= MIN_SAMPLES_FOR_CONFIDENCE
                   and e.success_rate < FAILURE_RATE_PENALTY_THRESHOLD
            )

            return {
                'total_urls': total_urls,
                'total_attempts': total_attempts,
                'total_successes': total_successes,
                'total_blocks': total_blocks,
                'overall_success_rate': total_successes / total_attempts if total_attempts > 0 else 0,
                'high_success_urls': high_success,
                'low_success_urls': low_success,
                'best_urls': self.get_best_urls(limit=5),
                'worst_urls': self.get_blocked_urls(limit=5)
            }

    def add_discovered_url(
        self,
        url: str,
        min_wait: int = 2,
        max_wait: int = 4,
        target_group: str = "general"
    ) -> None:
        """
        Add a newly discovered good URL to the warmup pool.

        When we find a site that works well for warmup, add it here
        so future sessions can benefit.

        Args:
            url: The URL to add
            min_wait: Minimum wait time after visiting
            max_wait: Maximum wait time after visiting
            target_group: Which target group this URL is good for
        """
        with self._lock:
            if url not in self._reputation:
                self._reputation[url] = URLReputationEntry(url=url)
                # Give it a slight initial boost for being discovered
                self._reputation[url].success_count = 1
                self._dirty = True
                self._save()
                logger.info(f"Added discovered warmup URL: {url} (group: {target_group})")

    def shutdown(self) -> None:
        """Save data and clean up."""
        self._save(force=True)
        logger.info("WarmupReputationTracker shutdown complete")


# Singleton instance
_tracker_instance: Optional[WarmupReputationTracker] = None
_tracker_lock = threading.Lock()


def get_warmup_reputation_tracker() -> WarmupReputationTracker:
    """Get the singleton reputation tracker instance."""
    global _tracker_instance
    with _tracker_lock:
        if _tracker_instance is None:
            _tracker_instance = WarmupReputationTracker()
        return _tracker_instance

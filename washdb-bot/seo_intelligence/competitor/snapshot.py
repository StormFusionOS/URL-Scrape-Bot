"""
HTML snapshot storage for competitor pages.

Saves raw HTML to disk for:
- Historical comparison
- Offline analysis
- Legal compliance (archival)
"""
import gzip
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Manages HTML snapshot storage.

    Features:
    - Organized directory structure (by domain/date)
    - Gzip compression
    - Automatic cleanup of old snapshots
    - Path generation for database storage
    """

    def __init__(
        self,
        base_path: str = "./data/snapshots",
        compress: bool = True,
        max_age_days: Optional[int] = None
    ):
        """
        Initialize snapshot manager.

        Args:
            base_path: Base directory for snapshots (default: ./data/snapshots)
            compress: Whether to gzip compress snapshots (default: True)
            max_age_days: Maximum age of snapshots in days (None = keep all)
        """
        self.base_path = Path(base_path)
        self.compress = compress
        self.max_age_days = max_age_days

        # Create base directory if needed
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_url_hash(self, url: str) -> str:
        """Generate short hash of URL for filename."""
        return hashlib.md5(url.encode('utf-8')).hexdigest()[:12]

    def _get_snapshot_path(
        self,
        url: str,
        timestamp: Optional[datetime] = None
    ) -> Path:
        """
        Generate snapshot file path.

        Args:
            url: Page URL
            timestamp: Snapshot timestamp (default: now)

        Returns:
            Path object for snapshot file
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        # Parse URL
        parsed = urlparse(url)
        domain = parsed.netloc

        # Create subdirectories: base/domain/YYYY-MM-DD/
        date_str = timestamp.strftime('%Y-%m-%d')
        dir_path = self.base_path / domain / date_str

        # Create filename: hash_HHMMSS.html[.gz]
        url_hash = self._get_url_hash(url)
        time_str = timestamp.strftime('%H%M%S')
        filename = f"{url_hash}_{time_str}.html"

        if self.compress:
            filename += '.gz'

        return dir_path / filename

    def save_snapshot(
        self,
        url: str,
        html: str,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Save HTML snapshot to disk.

        Args:
            url: Page URL
            html: Raw HTML content
            timestamp: Snapshot timestamp (default: now)

        Returns:
            Relative path to saved snapshot
        """
        try:
            # Get snapshot path
            snapshot_path = self._get_snapshot_path(url, timestamp)

            # Create directory if needed
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)

            # Write HTML (compressed or plain)
            if self.compress:
                with gzip.open(snapshot_path, 'wt', encoding='utf-8') as f:
                    f.write(html)
            else:
                with open(snapshot_path, 'w', encoding='utf-8') as f:
                    f.write(html)

            # Get relative path for database storage
            relative_path = str(snapshot_path.relative_to(self.base_path))

            logger.info(
                f"Saved snapshot: {relative_path} "
                f"({len(html)} bytes{'  compressed' if self.compress else ''})"
            )

            return relative_path

        except Exception as e:
            logger.error(f"Error saving snapshot for {url}: {e}")
            raise

    def load_snapshot(self, relative_path: str) -> str:
        """
        Load HTML snapshot from disk.

        Args:
            relative_path: Relative path to snapshot

        Returns:
            HTML content
        """
        try:
            snapshot_path = self.base_path / relative_path

            if not snapshot_path.exists():
                raise FileNotFoundError(f"Snapshot not found: {relative_path}")

            # Read HTML (compressed or plain)
            if snapshot_path.suffix == '.gz':
                with gzip.open(snapshot_path, 'rt', encoding='utf-8') as f:
                    html = f.read()
            else:
                with open(snapshot_path, 'r', encoding='utf-8') as f:
                    html = f.read()

            logger.debug(f"Loaded snapshot: {relative_path} ({len(html)} bytes)")
            return html

        except Exception as e:
            logger.error(f"Error loading snapshot {relative_path}: {e}")
            raise

    def cleanup_old_snapshots(self, max_age_days: Optional[int] = None) -> int:
        """
        Delete snapshots older than max_age_days.

        Args:
            max_age_days: Maximum age in days (uses instance default if None)

        Returns:
            Number of files deleted
        """
        if max_age_days is None:
            max_age_days = self.max_age_days

        if max_age_days is None:
            logger.warning("No max_age_days specified, skipping cleanup")
            return 0

        try:
            from datetime import timedelta

            cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
            cutoff_timestamp = cutoff_time.timestamp()

            deleted_count = 0

            # Walk through all snapshot files
            for snapshot_path in self.base_path.rglob('*.html*'):
                if snapshot_path.is_file():
                    # Check file modification time
                    if snapshot_path.stat().st_mtime < cutoff_timestamp:
                        snapshot_path.unlink()
                        deleted_count += 1

            # Clean up empty directories
            for dir_path in sorted(self.base_path.rglob('*'), reverse=True):
                if dir_path.is_dir() and not any(dir_path.iterdir()):
                    dir_path.rmdir()

            logger.info(
                f"Cleaned up {deleted_count} snapshots older than {max_age_days} days"
            )

            return deleted_count

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0

    def get_snapshot_stats(self) -> dict:
        """
        Get statistics about stored snapshots.

        Returns:
            Dict with count, total_size, oldest, newest
        """
        try:
            stats = {
                'count': 0,
                'total_size': 0,
                'oldest': None,
                'newest': None
            }

            oldest_time = None
            newest_time = None

            for snapshot_path in self.base_path.rglob('*.html*'):
                if snapshot_path.is_file():
                    stats['count'] += 1
                    stats['total_size'] += snapshot_path.stat().st_size

                    mtime = snapshot_path.stat().st_mtime
                    if oldest_time is None or mtime < oldest_time:
                        oldest_time = mtime
                        stats['oldest'] = datetime.fromtimestamp(mtime)

                    if newest_time is None or mtime > newest_time:
                        newest_time = mtime
                        stats['newest'] = datetime.fromtimestamp(mtime)

            # Convert size to MB
            stats['total_size_mb'] = stats['total_size'] / (1024 * 1024)

            return stats

        except Exception as e:
            logger.error(f"Error getting snapshot stats: {e}")
            return {}


# Global snapshot manager instance
snapshot_manager = SnapshotManager()


# Convenience functions
def save_snapshot(url: str, html: str, timestamp: Optional[datetime] = None) -> str:
    """Save HTML snapshot to disk."""
    return snapshot_manager.save_snapshot(url, html, timestamp)


def load_snapshot(relative_path: str) -> str:
    """Load HTML snapshot from disk."""
    return snapshot_manager.load_snapshot(relative_path)


def cleanup_old_snapshots(max_age_days: int) -> int:
    """Delete snapshots older than max_age_days."""
    return snapshot_manager.cleanup_old_snapshots(max_age_days)


def get_snapshot_stats() -> dict:
    """Get statistics about stored snapshots."""
    return snapshot_manager.get_snapshot_stats()

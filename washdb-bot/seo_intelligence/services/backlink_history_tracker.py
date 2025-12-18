"""
Backlink History Tracker Service

Provides historical tracking of backlinks with diff detection for:
- Link status changes (gained/lost)
- Anchor text evolution
- Link type changes (dofollow -> nofollow)
- Referring domain changes

This enables trend analysis and alerting on backlink profile changes.
"""

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

load_dotenv()
logger = get_logger("backlink_history_tracker")


class LinkChangeType(Enum):
    """Types of link changes detected."""
    GAINED = "gained"  # New link appeared
    LOST = "lost"  # Link was removed
    ANCHOR_CHANGED = "anchor_changed"  # Anchor text changed
    TYPE_CHANGED = "type_changed"  # Link type changed (dofollow -> nofollow)
    PLACEMENT_CHANGED = "placement_changed"  # Link moved to different section
    STATUS_CHANGED = "status_changed"  # Active status changed


@dataclass
class LinkChange:
    """Represents a single link change event."""
    change_type: LinkChangeType
    source_url: str
    source_domain: str
    target_url: str
    target_domain: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # For changes (not gained/lost)
    old_value: Optional[str] = None
    new_value: Optional[str] = None

    # Metadata
    anchor_text: Optional[str] = None
    link_type: Optional[str] = None
    context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'change_type': self.change_type.value,
            'source_url': self.source_url,
            'source_domain': self.source_domain,
            'target_url': self.target_url,
            'target_domain': self.target_domain,
            'detected_at': self.detected_at.isoformat(),
            'old_value': self.old_value,
            'new_value': self.new_value,
            'anchor_text': self.anchor_text,
            'link_type': self.link_type,
            'context': self.context,
        }


@dataclass
class BacklinkSnapshot:
    """
    Point-in-time snapshot of a domain's backlink profile.

    Used for computing diffs between time periods.
    """
    target_domain: str
    snapshot_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Backlink data
    total_backlinks: int = 0
    dofollow_count: int = 0
    nofollow_count: int = 0
    unique_domains: int = 0

    # Individual links (source_url -> link_data)
    links: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Referring domains (domain -> first_seen, last_seen, link_count)
    referring_domains: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'target_domain': self.target_domain,
            'snapshot_time': self.snapshot_time.isoformat(),
            'total_backlinks': self.total_backlinks,
            'dofollow_count': self.dofollow_count,
            'nofollow_count': self.nofollow_count,
            'unique_domains': self.unique_domains,
            'links': self.links,
            'referring_domains': self.referring_domains,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BacklinkSnapshot':
        snapshot = cls(
            target_domain=data['target_domain'],
            total_backlinks=data.get('total_backlinks', 0),
            dofollow_count=data.get('dofollow_count', 0),
            nofollow_count=data.get('nofollow_count', 0),
            unique_domains=data.get('unique_domains', 0),
            links=data.get('links', {}),
            referring_domains=data.get('referring_domains', {}),
        )
        if isinstance(data.get('snapshot_time'), str):
            snapshot.snapshot_time = datetime.fromisoformat(data['snapshot_time'])
        return snapshot


@dataclass
class BacklinkDiff:
    """
    Diff between two backlink snapshots.

    Contains all changes detected between the snapshots.
    """
    target_domain: str
    from_snapshot_time: datetime
    to_snapshot_time: datetime
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Summary statistics
    links_gained: int = 0
    links_lost: int = 0
    domains_gained: int = 0
    domains_lost: int = 0
    net_change: int = 0

    # Detailed changes
    changes: List[LinkChange] = field(default_factory=list)

    # Links by change type
    gained_links: List[Dict[str, Any]] = field(default_factory=list)
    lost_links: List[Dict[str, Any]] = field(default_factory=list)

    # Domains by change type
    gained_domains: List[str] = field(default_factory=list)
    lost_domains: List[str] = field(default_factory=list)

    # Velocity metrics
    days_between: float = 0.0
    links_per_day: float = 0.0  # Net rate of link acquisition

    def to_dict(self) -> Dict[str, Any]:
        return {
            'target_domain': self.target_domain,
            'from_snapshot_time': self.from_snapshot_time.isoformat(),
            'to_snapshot_time': self.to_snapshot_time.isoformat(),
            'computed_at': self.computed_at.isoformat(),
            'links_gained': self.links_gained,
            'links_lost': self.links_lost,
            'domains_gained': self.domains_gained,
            'domains_lost': self.domains_lost,
            'net_change': self.net_change,
            'changes': [c.to_dict() for c in self.changes],
            'gained_links': self.gained_links,
            'lost_links': self.lost_links,
            'gained_domains': self.gained_domains,
            'lost_domains': self.lost_domains,
            'days_between': self.days_between,
            'links_per_day': self.links_per_day,
        }


class BacklinkHistoryTracker:
    """
    Tracks backlink history and computes diffs over time.

    Provides:
    - Snapshot creation from current database state
    - Snapshot storage and retrieval
    - Diff computation between snapshots
    - Trend analysis and velocity metrics
    - Change alerting
    """

    def __init__(self, storage_dir: str = "data/backlink_history"):
        """
        Initialize the backlink history tracker.

        Args:
            storage_dir: Directory to store snapshot files
        """
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database features disabled")

        logger.info(f"BacklinkHistoryTracker initialized (storage: {storage_dir})")

    def create_snapshot(self, target_domain: str) -> BacklinkSnapshot:
        """
        Create a snapshot of the current backlink profile for a domain.

        Reads from the backlinks and referring_domains tables.

        Args:
            target_domain: Domain to snapshot

        Returns:
            BacklinkSnapshot with current state
        """
        snapshot = BacklinkSnapshot(target_domain=target_domain)

        if not self.engine:
            logger.warning("Database not available - returning empty snapshot")
            return snapshot

        try:
            with Session(self.engine) as session:
                # Get all active backlinks for domain
                result = session.execute(
                    text("""
                        SELECT
                            backlink_id,
                            source_url,
                            source_domain,
                            target_url,
                            anchor_text,
                            link_type,
                            discovered_at,
                            last_seen_at,
                            metadata
                        FROM backlinks
                        WHERE target_domain = :domain
                        AND is_active = TRUE
                        ORDER BY discovered_at DESC
                    """),
                    {"domain": target_domain}
                )

                dofollow_count = 0
                nofollow_count = 0
                referring_domain_set: Set[str] = set()

                for row in result:
                    backlink_id, source_url, source_domain, target_url, anchor_text, \
                        link_type, discovered_at, last_seen_at, metadata = row

                    # Store link data
                    snapshot.links[source_url] = {
                        'backlink_id': backlink_id,
                        'source_domain': source_domain,
                        'target_url': target_url,
                        'anchor_text': anchor_text or '',
                        'link_type': link_type or 'dofollow',
                        'discovered_at': discovered_at.isoformat() if discovered_at else None,
                        'last_seen_at': last_seen_at.isoformat() if last_seen_at else None,
                        'metadata': metadata if isinstance(metadata, dict) else {},
                    }

                    # Count link types
                    if link_type == 'dofollow' or link_type is None:
                        dofollow_count += 1
                    else:
                        nofollow_count += 1

                    # Track referring domains
                    if source_domain:
                        referring_domain_set.add(source_domain)
                        if source_domain not in snapshot.referring_domains:
                            snapshot.referring_domains[source_domain] = {
                                'first_seen': discovered_at.isoformat() if discovered_at else None,
                                'last_seen': last_seen_at.isoformat() if last_seen_at else None,
                                'link_count': 0,
                            }
                        snapshot.referring_domains[source_domain]['link_count'] += 1
                        if last_seen_at:
                            current_last = snapshot.referring_domains[source_domain].get('last_seen')
                            if current_last is None or last_seen_at.isoformat() > current_last:
                                snapshot.referring_domains[source_domain]['last_seen'] = last_seen_at.isoformat()

                snapshot.total_backlinks = len(snapshot.links)
                snapshot.dofollow_count = dofollow_count
                snapshot.nofollow_count = nofollow_count
                snapshot.unique_domains = len(referring_domain_set)

                logger.info(
                    f"Created snapshot for {target_domain}: "
                    f"{snapshot.total_backlinks} links from {snapshot.unique_domains} domains"
                )

        except Exception as e:
            logger.error(f"Error creating snapshot for {target_domain}: {e}")

        return snapshot

    def save_snapshot(self, snapshot: BacklinkSnapshot) -> str:
        """
        Save a snapshot to disk.

        Args:
            snapshot: The snapshot to save

        Returns:
            Path to saved snapshot file
        """
        # Create domain-specific directory
        domain_dir = os.path.join(
            self.storage_dir,
            snapshot.target_domain.replace('.', '_').replace(':', '_')
        )
        os.makedirs(domain_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = snapshot.snapshot_time.strftime('%Y%m%d_%H%M%S')
        filename = f"snapshot_{timestamp}.json"
        filepath = os.path.join(domain_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(snapshot.to_dict(), f, indent=2)

        logger.info(f"Saved snapshot to {filepath}")
        return filepath

    def load_snapshot(self, filepath: str) -> Optional[BacklinkSnapshot]:
        """
        Load a snapshot from disk.

        Args:
            filepath: Path to snapshot file

        Returns:
            BacklinkSnapshot or None if load fails
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return BacklinkSnapshot.from_dict(data)
        except Exception as e:
            logger.error(f"Error loading snapshot from {filepath}: {e}")
            return None

    def get_latest_snapshot(self, target_domain: str) -> Optional[BacklinkSnapshot]:
        """
        Get the most recent snapshot for a domain.

        Args:
            target_domain: Domain to get snapshot for

        Returns:
            Most recent BacklinkSnapshot or None
        """
        domain_dir = os.path.join(
            self.storage_dir,
            target_domain.replace('.', '_').replace(':', '_')
        )

        if not os.path.exists(domain_dir):
            return None

        # Find most recent snapshot file
        snapshot_files = sorted(
            [f for f in os.listdir(domain_dir) if f.startswith('snapshot_') and f.endswith('.json')],
            reverse=True
        )

        if not snapshot_files:
            return None

        return self.load_snapshot(os.path.join(domain_dir, snapshot_files[0]))

    def get_snapshot_at_date(
        self,
        target_domain: str,
        date: datetime,
    ) -> Optional[BacklinkSnapshot]:
        """
        Get the snapshot closest to a specific date.

        Args:
            target_domain: Domain to get snapshot for
            date: Target date

        Returns:
            Closest BacklinkSnapshot or None
        """
        domain_dir = os.path.join(
            self.storage_dir,
            target_domain.replace('.', '_').replace(':', '_')
        )

        if not os.path.exists(domain_dir):
            return None

        # Find closest snapshot
        snapshot_files = sorted(
            [f for f in os.listdir(domain_dir) if f.startswith('snapshot_') and f.endswith('.json')]
        )

        if not snapshot_files:
            return None

        target_str = date.strftime('%Y%m%d_%H%M%S')
        closest_file = None
        closest_diff = None

        for f in snapshot_files:
            timestamp_str = f.replace('snapshot_', '').replace('.json', '')
            try:
                file_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                diff = abs((file_time - date).total_seconds())
                if closest_diff is None or diff < closest_diff:
                    closest_diff = diff
                    closest_file = f
            except ValueError:
                continue

        if closest_file:
            return self.load_snapshot(os.path.join(domain_dir, closest_file))

        return None

    def compute_diff(
        self,
        old_snapshot: BacklinkSnapshot,
        new_snapshot: BacklinkSnapshot,
    ) -> BacklinkDiff:
        """
        Compute the diff between two snapshots.

        Args:
            old_snapshot: Earlier snapshot
            new_snapshot: Later snapshot

        Returns:
            BacklinkDiff with all detected changes
        """
        diff = BacklinkDiff(
            target_domain=new_snapshot.target_domain,
            from_snapshot_time=old_snapshot.snapshot_time,
            to_snapshot_time=new_snapshot.snapshot_time,
        )

        # Calculate time delta
        time_delta = new_snapshot.snapshot_time - old_snapshot.snapshot_time
        diff.days_between = time_delta.total_seconds() / 86400

        old_links = set(old_snapshot.links.keys())
        new_links = set(new_snapshot.links.keys())

        # Find gained links
        gained = new_links - old_links
        for source_url in gained:
            link_data = new_snapshot.links[source_url]
            diff.gained_links.append({
                'source_url': source_url,
                **link_data
            })
            diff.changes.append(LinkChange(
                change_type=LinkChangeType.GAINED,
                source_url=source_url,
                source_domain=link_data.get('source_domain', ''),
                target_url=link_data.get('target_url', ''),
                target_domain=new_snapshot.target_domain,
                anchor_text=link_data.get('anchor_text'),
                link_type=link_data.get('link_type'),
            ))

        # Find lost links
        lost = old_links - new_links
        for source_url in lost:
            link_data = old_snapshot.links[source_url]
            diff.lost_links.append({
                'source_url': source_url,
                **link_data
            })
            diff.changes.append(LinkChange(
                change_type=LinkChangeType.LOST,
                source_url=source_url,
                source_domain=link_data.get('source_domain', ''),
                target_url=link_data.get('target_url', ''),
                target_domain=old_snapshot.target_domain,
                anchor_text=link_data.get('anchor_text'),
                link_type=link_data.get('link_type'),
            ))

        # Find changed links (same source_url but different attributes)
        common = old_links & new_links
        for source_url in common:
            old_data = old_snapshot.links[source_url]
            new_data = new_snapshot.links[source_url]

            # Check anchor text changes
            old_anchor = old_data.get('anchor_text', '')
            new_anchor = new_data.get('anchor_text', '')
            if old_anchor != new_anchor:
                diff.changes.append(LinkChange(
                    change_type=LinkChangeType.ANCHOR_CHANGED,
                    source_url=source_url,
                    source_domain=new_data.get('source_domain', ''),
                    target_url=new_data.get('target_url', ''),
                    target_domain=new_snapshot.target_domain,
                    old_value=old_anchor,
                    new_value=new_anchor,
                    anchor_text=new_anchor,
                    link_type=new_data.get('link_type'),
                ))

            # Check link type changes
            old_type = old_data.get('link_type', 'dofollow')
            new_type = new_data.get('link_type', 'dofollow')
            if old_type != new_type:
                diff.changes.append(LinkChange(
                    change_type=LinkChangeType.TYPE_CHANGED,
                    source_url=source_url,
                    source_domain=new_data.get('source_domain', ''),
                    target_url=new_data.get('target_url', ''),
                    target_domain=new_snapshot.target_domain,
                    old_value=old_type,
                    new_value=new_type,
                    anchor_text=new_data.get('anchor_text'),
                    link_type=new_type,
                ))

        # Calculate domain changes
        old_domains = set(old_snapshot.referring_domains.keys())
        new_domains = set(new_snapshot.referring_domains.keys())

        diff.gained_domains = list(new_domains - old_domains)
        diff.lost_domains = list(old_domains - new_domains)

        # Update summary statistics
        diff.links_gained = len(gained)
        diff.links_lost = len(lost)
        diff.domains_gained = len(diff.gained_domains)
        diff.domains_lost = len(diff.lost_domains)
        diff.net_change = diff.links_gained - diff.links_lost

        # Calculate velocity
        if diff.days_between > 0:
            diff.links_per_day = diff.net_change / diff.days_between

        logger.info(
            f"Computed diff for {new_snapshot.target_domain}: "
            f"+{diff.links_gained} -{diff.links_lost} links, "
            f"+{diff.domains_gained} -{diff.domains_lost} domains, "
            f"velocity={diff.links_per_day:.2f}/day"
        )

        return diff

    def get_weekly_diff(self, target_domain: str) -> Optional[BacklinkDiff]:
        """
        Get diff between current state and 1 week ago.

        Args:
            target_domain: Domain to analyze

        Returns:
            BacklinkDiff or None if insufficient data
        """
        current = self.create_snapshot(target_domain)
        week_ago = self.get_snapshot_at_date(
            target_domain,
            datetime.now(timezone.utc) - timedelta(days=7)
        )

        if not week_ago:
            logger.warning(f"No snapshot from ~1 week ago for {target_domain}")
            return None

        return self.compute_diff(week_ago, current)

    def get_monthly_diff(self, target_domain: str) -> Optional[BacklinkDiff]:
        """
        Get diff between current state and 1 month ago.

        Args:
            target_domain: Domain to analyze

        Returns:
            BacklinkDiff or None if insufficient data
        """
        current = self.create_snapshot(target_domain)
        month_ago = self.get_snapshot_at_date(
            target_domain,
            datetime.now(timezone.utc) - timedelta(days=30)
        )

        if not month_ago:
            logger.warning(f"No snapshot from ~1 month ago for {target_domain}")
            return None

        return self.compute_diff(month_ago, current)

    def get_velocity_history(
        self,
        target_domain: str,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get link velocity history over a period.

        Args:
            target_domain: Domain to analyze
            days: Number of days to analyze

        Returns:
            List of daily velocity data points
        """
        domain_dir = os.path.join(
            self.storage_dir,
            target_domain.replace('.', '_').replace(':', '_')
        )

        if not os.path.exists(domain_dir):
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Load all snapshots within period
        snapshots = []
        for f in sorted(os.listdir(domain_dir)):
            if not f.startswith('snapshot_') or not f.endswith('.json'):
                continue

            filepath = os.path.join(domain_dir, f)
            snapshot = self.load_snapshot(filepath)
            if snapshot and snapshot.snapshot_time >= cutoff:
                snapshots.append(snapshot)

        if len(snapshots) < 2:
            return []

        # Calculate velocity between consecutive snapshots
        velocity_data = []
        for i in range(1, len(snapshots)):
            diff = self.compute_diff(snapshots[i-1], snapshots[i])
            velocity_data.append({
                'date': diff.to_snapshot_time.isoformat(),
                'links_gained': diff.links_gained,
                'links_lost': diff.links_lost,
                'net_change': diff.net_change,
                'total_links': snapshots[i].total_backlinks,
                'unique_domains': snapshots[i].unique_domains,
                'velocity': diff.links_per_day,
            })

        return velocity_data

    def record_current_state(self, target_domain: str) -> Tuple[BacklinkSnapshot, str]:
        """
        Create and save a snapshot of current state.

        Convenience method for regular scheduled snapshots.

        Args:
            target_domain: Domain to snapshot

        Returns:
            Tuple of (snapshot, filepath)
        """
        snapshot = self.create_snapshot(target_domain)
        filepath = self.save_snapshot(snapshot)
        return snapshot, filepath

    def cleanup_old_snapshots(self, days: int = 90) -> int:
        """
        Remove snapshots older than specified days.

        Args:
            days: Age threshold for deletion

        Returns:
            Number of files deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0

        for domain_dir in os.listdir(self.storage_dir):
            domain_path = os.path.join(self.storage_dir, domain_dir)
            if not os.path.isdir(domain_path):
                continue

            for f in os.listdir(domain_path):
                if not f.startswith('snapshot_') or not f.endswith('.json'):
                    continue

                # Parse timestamp from filename
                timestamp_str = f.replace('snapshot_', '').replace('.json', '')
                try:
                    file_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                    file_time = file_time.replace(tzinfo=timezone.utc)
                    if file_time < cutoff:
                        os.remove(os.path.join(domain_path, f))
                        deleted += 1
                except ValueError:
                    continue

        logger.info(f"Cleaned up {deleted} old snapshot files")
        return deleted


# Singleton instance
_tracker_instance = None


def get_backlink_history_tracker(**kwargs) -> BacklinkHistoryTracker:
    """Get or create singleton BacklinkHistoryTracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = BacklinkHistoryTracker(**kwargs)
    return _tracker_instance

"""
Job Monitor Service
Monitors crawl job status changes and broadcasts updates via WebSocket
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import text

from db.database_manager import get_db_manager
from .websocket_manager import get_websocket_manager

# Get database manager for scraper database
db_manager = get_db_manager()

logger = logging.getLogger(__name__)


class JobMonitor:
    """Monitors job status changes and broadcasts updates"""

    def __init__(self, poll_interval: float = 5.0):
        """
        Initialize job monitor

        Args:
            poll_interval: How often to poll for changes (seconds)
        """
        self.poll_interval = poll_interval
        self.ws_manager = get_websocket_manager()
        self.last_job_states: Dict[int, str] = {}  # job_id -> status
        self.running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start monitoring job status"""
        if self.running:
            logger.warning("Job monitor already running")
            return

        self.running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Job monitor started (poll interval: {self.poll_interval}s)")

    async def stop(self):
        """Stop monitoring"""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Job monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                await self._check_job_status()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job monitor loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _check_job_status(self):
        """Check for job status changes"""
        try:
            with db_manager.get_session('scraper') as session:
                # Get recent active jobs (not completed/failed/cancelled older than 1 hour)
                query = text("""
                    SELECT
                        job_id,
                        url,
                        job_type,
                        status,
                        priority,
                        claimed_by,
                        started_at,
                        completed_at,
                        attempts,
                        max_attempts,
                        last_error,
                        created_at,
                        updated_at
                    FROM crawl_jobs
                    WHERE
                        status IN ('pending', 'claimed', 'running')
                        OR (status IN ('completed', 'failed', 'cancelled')
                            AND updated_at > NOW() - INTERVAL '1 hour')
                    ORDER BY updated_at DESC
                    LIMIT 100
                """)

                result = session.execute(query)
                jobs = result.fetchall()

                for job in jobs:
                    job_id = job[0]
                    url = job[1]
                    job_type = job[2]
                    status = job[3]
                    priority = job[4]
                    claimed_by = job[5]
                    started_at = job[6]
                    completed_at = job[7]
                    attempts = job[8]
                    max_attempts = job[9]
                    last_error = job[10]
                    created_at = job[11]
                    updated_at = job[12]

                    # Check if status changed
                    previous_status = self.last_job_states.get(job_id)

                    if previous_status != status:
                        # Status changed - broadcast event
                        await self._broadcast_job_event(
                            job_id=job_id,
                            url=url,
                            job_type=job_type,
                            status=status,
                            previous_status=previous_status,
                            priority=priority,
                            claimed_by=claimed_by,
                            started_at=started_at,
                            completed_at=completed_at,
                            attempts=attempts,
                            max_attempts=max_attempts,
                            last_error=last_error,
                            created_at=created_at,
                            updated_at=updated_at
                        )

                        # Update tracked state
                        self.last_job_states[job_id] = status

                # Clean up old job states (keep only last 1000)
                if len(self.last_job_states) > 1000:
                    job_ids_to_keep = {job[0] for job in jobs}
                    self.last_job_states = {
                        job_id: status
                        for job_id, status in self.last_job_states.items()
                        if job_id in job_ids_to_keep
                    }

        except Exception as e:
            logger.error(f"Error checking job status: {e}", exc_info=True)

    async def _broadcast_job_event(
        self,
        job_id: int,
        url: str,
        job_type: str,
        status: str,
        previous_status: Optional[str],
        priority: int,
        claimed_by: Optional[str],
        started_at: Optional[datetime],
        completed_at: Optional[datetime],
        attempts: int,
        max_attempts: int,
        last_error: Optional[str],
        created_at: datetime,
        updated_at: datetime
    ):
        """Broadcast job status change event"""

        # Determine event type based on status change
        if previous_status is None:
            event_type = 'job_discovered'
        elif status == 'running' and previous_status in ('pending', 'claimed'):
            event_type = 'job_started'
        elif status == 'completed':
            event_type = 'job_completed'
        elif status == 'failed':
            event_type = 'job_failed'
        elif status == 'cancelled':
            event_type = 'job_cancelled'
        else:
            event_type = 'job_status_change'

        # Prepare event data
        event_data = {
            'job_id': job_id,
            'url': url,
            'job_type': job_type,
            'status': status,
            'previous_status': previous_status,
            'priority': priority,
            'claimed_by': claimed_by,
            'started_at': started_at.isoformat() if started_at else None,
            'completed_at': completed_at.isoformat() if completed_at else None,
            'attempts': attempts,
            'max_attempts': max_attempts,
            'last_error': last_error,
            'created_at': created_at.isoformat() if created_at else None,
            'updated_at': updated_at.isoformat() if updated_at else None,
            'event_type': event_type
        }

        # Broadcast via WebSocket
        await self.ws_manager.broadcast(event_type, event_data)

        logger.info(
            f"Job {job_id} status changed: {previous_status} -> {status} "
            f"(event: {event_type})"
        )

    async def get_job_stats(self) -> Dict[str, Any]:
        """Get current job statistics"""
        try:
            with db_manager.get_session('scraper') as session:
                query = text("""
                    SELECT
                        status,
                        COUNT(*) as count
                    FROM crawl_jobs
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY status
                """)

                result = session.execute(query)
                rows = result.fetchall()

                stats = {
                    'pending': 0,
                    'claimed': 0,
                    'running': 0,
                    'completed': 0,
                    'failed': 0,
                    'cancelled': 0
                }

                for status, count in rows:
                    stats[status] = count

                return stats

        except Exception as e:
            logger.error(f"Error getting job stats: {e}")
            return {}


# Singleton instance
_job_monitor: Optional[JobMonitor] = None


def get_job_monitor(poll_interval: float = 5.0) -> JobMonitor:
    """Get or create job monitor singleton"""
    global _job_monitor
    if _job_monitor is None:
        _job_monitor = JobMonitor(poll_interval=poll_interval)
    return _job_monitor

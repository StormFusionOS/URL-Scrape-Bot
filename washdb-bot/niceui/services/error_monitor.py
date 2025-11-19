"""
Error Monitor Service
Monitors error logs and broadcasts critical errors via WebSocket
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Set
from sqlalchemy import text

from db.database_manager import get_db_manager

# Get database manager for scraper database
db_manager = get_db_manager()
from .websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)


class ErrorMonitor:
    """Monitors error logs and broadcasts critical errors"""

    def __init__(self, poll_interval: float = 10.0):
        """
        Initialize error monitor

        Args:
            poll_interval: How often to poll for new errors (seconds)
        """
        self.poll_interval = poll_interval
        self.ws_manager = get_websocket_manager()
        self.seen_error_ids: Set[int] = set()  # Track which errors we've already broadcast
        self.running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self.last_check_time: Optional[datetime] = None

    async def start(self):
        """Start monitoring errors"""
        if self.running:
            logger.warning("Error monitor already running")
            return

        self.running = True
        self.last_check_time = datetime.now()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Error monitor started (poll interval: {self.poll_interval}s)")

    async def stop(self):
        """Stop monitoring"""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Error monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                await self._check_new_errors()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in error monitor loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _check_new_errors(self):
        """Check for new errors since last check"""
        try:
            with db_manager.get_session('scraper') as session:
                # Get recent errors (last 5 minutes or since last check)
                query = text("""
                    SELECT
                        id,
                        occurred_at,
                        error_category,
                        error_severity,
                        error_message,
                        error_code,
                        stack_trace,
                        url,
                        component,
                        worker_id,
                        error_metadata,
                        is_resolved
                    FROM seo_analytics.seo_error_logs
                    WHERE occurred_at > NOW() - INTERVAL '5 minutes'
                        AND is_resolved = FALSE
                    ORDER BY occurred_at DESC
                    LIMIT 100
                """)

                result = session.execute(query)
                errors = result.fetchall()

                new_errors = []
                for error in errors:
                    error_id = error[0]

                    # Check if this is a new error we haven't seen
                    if error_id not in self.seen_error_ids:
                        new_errors.append(error)
                        self.seen_error_ids.add(error_id)

                # Broadcast new errors
                for error in new_errors:
                    await self._broadcast_error(error)

                # Clean up old seen IDs (keep only last 5000)
                if len(self.seen_error_ids) > 5000:
                    # Keep only the most recent error IDs from current batch
                    current_ids = {err[0] for err in errors}
                    self.seen_error_ids = current_ids

                self.last_check_time = datetime.now()

        except Exception as e:
            logger.error(f"Error checking new errors: {e}", exc_info=True)

    async def _broadcast_error(self, error_row):
        """Broadcast error event"""
        error_id = error_row[0]
        occurred_at = error_row[1]
        error_category = error_row[2]
        error_severity = error_row[3]
        error_message = error_row[4]
        error_code = error_row[5]
        stack_trace = error_row[6]
        url = error_row[7]
        component = error_row[8]
        worker_id = error_row[9]
        error_metadata = error_row[10]
        is_resolved = error_row[11]

        # Prepare event data
        event_data = {
            'error_id': error_id,
            'occurred_at': occurred_at.isoformat() if occurred_at else None,
            'error_category': error_category,
            'error_severity': error_severity,
            'error_message': error_message,
            'error_code': error_code,
            'stack_trace': stack_trace,
            'url': url,
            'component': component,
            'worker_id': worker_id,
            'error_metadata': error_metadata,
            'is_resolved': is_resolved
        }

        # Determine event type based on severity
        if error_severity == 'critical':
            event_type = 'critical_error'
        elif error_severity == 'error':
            event_type = 'new_error'
        elif error_severity == 'warning':
            event_type = 'new_warning'
        else:
            event_type = 'error_info'

        # Broadcast via WebSocket
        await self.ws_manager.broadcast(event_type, event_data)

        logger.info(
            f"New {error_severity} error broadcast: {error_category} - "
            f"{error_message[:50]}... (ID: {error_id})"
        )

    async def get_error_stats(self) -> Dict[str, Any]:
        """Get current error statistics"""
        try:
            with db_manager.get_session('scraper') as session:
                # Get error counts by severity (last 24 hours)
                severity_query = text("""
                    SELECT
                        error_severity,
                        COUNT(*) as count
                    FROM seo_analytics.seo_error_logs
                    WHERE occurred_at > NOW() - INTERVAL '24 hours'
                    GROUP BY error_severity
                """)

                result = session.execute(severity_query)
                severity_rows = result.fetchall()

                severity_stats = {
                    'critical': 0,
                    'error': 0,
                    'warning': 0,
                    'info': 0
                }

                for severity, count in severity_rows:
                    if severity:
                        severity_stats[severity] = count

                # Get error counts by category (last 24 hours)
                category_query = text("""
                    SELECT
                        error_category,
                        COUNT(*) as count
                    FROM seo_analytics.seo_error_logs
                    WHERE occurred_at > NOW() - INTERVAL '24 hours'
                    GROUP BY error_category
                    ORDER BY count DESC
                    LIMIT 10
                """)

                result = session.execute(category_query)
                category_rows = result.fetchall()

                category_stats = {
                    category: count for category, count in category_rows
                }

                # Get unresolved error count
                unresolved_query = text("""
                    SELECT COUNT(*)
                    FROM seo_analytics.seo_error_logs
                    WHERE is_resolved = FALSE
                        AND occurred_at > NOW() - INTERVAL '7 days'
                """)

                result = session.execute(unresolved_query)
                unresolved_count = result.scalar()

                return {
                    'by_severity': severity_stats,
                    'by_category': category_stats,
                    'unresolved_count': unresolved_count or 0,
                    'total_24h': sum(severity_stats.values())
                }

        except Exception as e:
            logger.error(f"Error getting error stats: {e}")
            return {
                'by_severity': {},
                'by_category': {},
                'unresolved_count': 0,
                'total_24h': 0
            }

    async def get_recent_errors(self, limit: int = 50) -> list:
        """Get recent errors"""
        try:
            with db_manager.get_session('scraper') as session:
                query = text("""
                    SELECT
                        id,
                        occurred_at,
                        error_category,
                        error_severity,
                        error_message,
                        error_code,
                        url,
                        component,
                        worker_id,
                        is_resolved
                    FROM seo_analytics.seo_error_logs
                    WHERE occurred_at > NOW() - INTERVAL '24 hours'
                    ORDER BY occurred_at DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {'limit': limit})
                rows = result.fetchall()

                errors = []
                for row in rows:
                    errors.append({
                        'id': row[0],
                        'occurred_at': row[1].isoformat() if row[1] else None,
                        'error_category': row[2],
                        'error_severity': row[3],
                        'error_message': row[4],
                        'error_code': row[5],
                        'url': row[6],
                        'component': row[7],
                        'worker_id': row[8],
                        'is_resolved': row[9]
                    })

                return errors

        except Exception as e:
            logger.error(f"Error getting recent errors: {e}")
            return []


# Singleton instance
_error_monitor: Optional[ErrorMonitor] = None


def get_error_monitor(poll_interval: float = 10.0) -> ErrorMonitor:
    """Get or create error monitor singleton"""
    global _error_monitor
    if _error_monitor is None:
        _error_monitor = ErrorMonitor(poll_interval=poll_interval)
    return _error_monitor

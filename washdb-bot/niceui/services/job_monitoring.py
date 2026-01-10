"""
Job Monitoring Service.

Provides real-time monitoring data for SEO job workers.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


class JobMonitoringService:
    """Service for SEO job monitoring and statistics."""

    STALE_THRESHOLD_MINUTES = 5

    def __init__(self, db_engine):
        self.db_engine = db_engine

    def get_worker_status(self) -> List[Dict[str, Any]]:
        """Get status of all registered workers."""
        if not self.db_engine:
            return []

        stale_threshold = datetime.now() - timedelta(minutes=self.STALE_THRESHOLD_MINUTES)

        try:
            with self.db_engine.connect() as conn:
                # Mark stale workers
                conn.execute(text("""
                    UPDATE job_heartbeats
                    SET status = 'stale'
                    WHERE status = 'running'
                      AND last_heartbeat < :threshold
                """), {'threshold': stale_threshold})
                conn.commit()

                # Get all workers
                result = conn.execute(text("""
                    SELECT worker_name, worker_type, status, last_heartbeat, started_at,
                           pid, hostname, companies_processed, jobs_completed, jobs_failed,
                           current_company_id, current_module, avg_job_duration_seconds,
                           last_error, last_error_at
                    FROM job_heartbeats
                    ORDER BY last_heartbeat DESC
                """))
                rows = result.fetchall()

                workers = []
                for row in rows:
                    last_heartbeat = row[3]
                    started_at = row[4]
                    uptime = None
                    seconds_since_heartbeat = None

                    if started_at:
                        uptime = (datetime.now() - started_at).total_seconds()
                    if last_heartbeat:
                        seconds_since_heartbeat = (datetime.now() - last_heartbeat).total_seconds()

                    workers.append({
                        'worker_name': row[0],
                        'worker_type': row[1],
                        'status': row[2],
                        'last_heartbeat': last_heartbeat,
                        'seconds_since_heartbeat': seconds_since_heartbeat,
                        'started_at': started_at,
                        'uptime_seconds': uptime,
                        'uptime_str': self._format_uptime(uptime) if uptime else None,
                        'pid': row[5],
                        'hostname': row[6],
                        'companies_processed': row[7] or 0,
                        'jobs_completed': row[8] or 0,
                        'jobs_failed': row[9] or 0,
                        'current_company_id': row[10],
                        'current_module': row[11],
                        'avg_job_duration_seconds': row[12],
                        'last_error': row[13],
                        'last_error_at': row[14]
                    })

                return workers
        except Exception as e:
            logger.warning(f"Error getting worker status: {e}")
            return []

    def get_seo_queue_stats(self) -> Dict[str, Any]:
        """Get SEO job queue statistics."""
        if not self.db_engine:
            return {'eligible': 0, 'pending_initial': 0, 'completed_initial': 0, 'due_refresh': 0, 'completion_percent': 0}

        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT
                        COUNT(*) FILTER (WHERE verified = true AND standardized_name IS NOT NULL) as eligible,
                        COUNT(*) FILTER (WHERE verified = true AND standardized_name IS NOT NULL AND seo_initial_complete = false) as pending_initial,
                        COUNT(*) FILTER (WHERE verified = true AND standardized_name IS NOT NULL AND seo_initial_complete = true) as completed_initial,
                        COUNT(*) FILTER (WHERE verified = true AND standardized_name IS NOT NULL AND seo_initial_complete = true AND seo_next_refresh_due <= NOW()) as due_refresh
                    FROM companies
                """))
                row = result.fetchone()

                eligible = row[0] or 0
                completed = row[2] or 0

                return {
                    'eligible': eligible,
                    'pending_initial': row[1] or 0,
                    'completed_initial': completed,
                    'due_refresh': row[3] or 0,
                    'completion_percent': round(completed / max(eligible, 1) * 100, 1)
                }
        except Exception as e:
            logger.warning(f"Error getting queue stats: {e}")
            return {'eligible': 0, 'pending_initial': 0, 'completed_initial': 0, 'due_refresh': 0, 'completion_percent': 0}

    def get_recent_job_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Get recent job history."""
        if not self.db_engine:
            return []

        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT j.tracking_id, j.company_id, c.standardized_name, c.domain,
                           j.module_name, j.run_type, j.status, j.started_at, j.completed_at,
                           j.duration_seconds, j.records_created, j.error_message
                    FROM seo_job_tracking j
                    LEFT JOIN companies c ON j.company_id = c.id
                    ORDER BY j.started_at DESC
                    LIMIT :limit
                """), {'limit': limit})
                rows = result.fetchall()

                return [{
                    'tracking_id': row[0],
                    'company_id': row[1],
                    'company_name': row[2] or 'Unknown',
                    'domain': row[3],
                    'module_name': row[4],
                    'run_type': row[5],
                    'status': row[6],
                    'started_at': row[7],
                    'started_at_str': row[7].strftime('%H:%M:%S') if row[7] else None,
                    'completed_at': row[8],
                    'duration_seconds': row[9],
                    'records_created': row[10] or 0,
                    'error_message': row[11]
                } for row in rows]
        except Exception as e:
            logger.warning(f"Error getting job history: {e}")
            return []

    def get_company_being_processed(self, company_id: int) -> Optional[Dict[str, Any]]:
        """Get details of company currently being processed."""
        if not company_id or not self.db_engine:
            return None

        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, standardized_name, domain, city, state
                    FROM companies
                    WHERE id = :company_id
                """), {'company_id': company_id})
                row = result.fetchone()

                if row:
                    return {
                        'id': row[0],
                        'name': row[1] or 'Unknown',
                        'domain': row[2],
                        'city': row[3],
                        'state': row[4]
                    }
        except Exception as e:
            logger.warning(f"Error getting company: {e}")

        return None

    def get_keyword_stats(self) -> Dict[str, Any]:
        """Get keyword assignment statistics."""
        if not self.db_engine:
            return {'total_keywords': 0, 'companies_with_keywords': 0, 'tier1': 0, 'tier2': 0, 'tier3': 0, 'tier4': 0}

        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_keywords,
                        COUNT(DISTINCT company_id) as companies_with_keywords,
                        COUNT(*) FILTER (WHERE assignment_tier = 1) as tier1,
                        COUNT(*) FILTER (WHERE assignment_tier = 2) as tier2,
                        COUNT(*) FILTER (WHERE assignment_tier = 3) as tier3,
                        COUNT(*) FILTER (WHERE assignment_tier = 4) as tier4,
                        COUNT(*) FILTER (WHERE current_position IS NOT NULL) as with_position,
                        AVG(current_position) FILTER (WHERE current_position IS NOT NULL) as avg_position
                    FROM keyword_company_tracking
                """))
                row = result.fetchone()

                return {
                    'total_keywords': row[0] or 0,
                    'companies_with_keywords': row[1] or 0,
                    'tier1': row[2] or 0,
                    'tier2': row[3] or 0,
                    'tier3': row[4] or 0,
                    'tier4': row[5] or 0,
                    'with_position': row[6] or 0,
                    'avg_position': round(row[7], 1) if row[7] else None
                }
        except Exception as e:
            logger.warning(f"Error getting keyword stats: {e}")
            return {'total_keywords': 0, 'companies_with_keywords': 0, 'tier1': 0, 'tier2': 0, 'tier3': 0, 'tier4': 0}

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            mins = int((seconds % 3600) / 60)
            return f"{hours}h {mins}m"
        else:
            days = int(seconds / 86400)
            hours = int((seconds % 86400) / 3600)
            return f"{days}d {hours}h"

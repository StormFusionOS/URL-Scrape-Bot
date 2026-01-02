"""
Unified Watchdog Service

Enterprise-grade watchdog that monitors all WashDB services and triggers
self-healing actions when issues are detected.

Features:
- Heartbeat monitoring: Detects stale workers (no heartbeat > 5 min)
- Resource monitoring: Chrome count, Xvfb, memory usage
- Proactive healing: Triggers restarts via SystemMonitor with cooldowns
- Event logging: All events logged to watchdog_events table
- Conservative safeguards: 2+ failures before action, cooldowns, hourly limits

Usage:
    python -m services.unified_watchdog

    # Or via systemd:
    systemctl start unified-watchdog
"""

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database_manager import get_db_manager
from services.system_monitor import (
    get_system_monitor,
    ErrorSeverity,
    ServiceName,
    HealingAction,
)
from services.heartbeat_manager import sd_notify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/watchdog.log'),
    ]
)
logger = logging.getLogger("unified_watchdog")


@dataclass
class ServiceConfig:
    """Configuration for a monitored service."""
    worker_type: str
    service_unit: str
    stale_threshold_minutes: int = 5
    failure_threshold: int = 2  # N failures in time_window before healing
    time_window_minutes: int = 10
    cooldown_seconds: int = 300


class UnifiedWatchdog:
    """
    Proactive watchdog that monitors all services and triggers healing.

    Polling intervals:
    - Heartbeat check: every 30 seconds
    - Resource check: every 60 seconds
    - Pattern matching: every 120 seconds
    """

    # Services to monitor
    MONITORED_SERVICES = {
        'seo_orchestrator': ServiceConfig(
            worker_type='seo_orchestrator',
            service_unit='seo-job-worker',
            stale_threshold_minutes=5,
            failure_threshold=2,
            cooldown_seconds=300,
        ),
        'standardization_browser': ServiceConfig(
            worker_type='standardization_browser',
            service_unit='washdb-standardization-browser',
            stale_threshold_minutes=5,
            failure_threshold=2,
            cooldown_seconds=300,
        ),
        'verification_pool': ServiceConfig(
            worker_type='verification',
            service_unit='washdb-verification',
            stale_threshold_minutes=5,
            failure_threshold=2,
            cooldown_seconds=300,
        ),
        'yp_worker': ServiceConfig(
            worker_type='yp_worker',
            service_unit='yp-state-workers',
            stale_threshold_minutes=10,
            failure_threshold=3,
            cooldown_seconds=600,
        ),
        'google_worker': ServiceConfig(
            worker_type='google_worker',
            service_unit='google-state-workers',
            stale_threshold_minutes=10,
            failure_threshold=3,
            cooldown_seconds=600,
        ),
    }

    # Resource thresholds
    CHROME_WARNING_THRESHOLD = 400  # Warning level (was 300)
    CHROME_CRITICAL_THRESHOLD = 500  # Force cleanup (was 720)
    MEMORY_WARNING_PERCENT = 85
    MEMORY_CRITICAL_PERCENT = 95

    # Polling intervals (seconds)
    HEARTBEAT_CHECK_INTERVAL = 30
    RESOURCE_CHECK_INTERVAL = 60
    PATTERN_CHECK_INTERVAL = 120

    # Map worker_type to ServiceName
    SERVICE_NAME_MAP = {
        'seo_orchestrator': ServiceName.SEO_WORKER,
        'standardization_browser': ServiceName.VERIFICATION,
        'verification': ServiceName.VERIFICATION,
        'yp_worker': ServiceName.YP_SCRAPER,
        'google_worker': ServiceName.GOOGLE_SCRAPER,
    }

    def __init__(self):
        self.db_manager = get_db_manager()
        self.system_monitor = get_system_monitor()
        self.running = False
        self._shutdown_event = threading.Event()

        # Tracking
        self._stale_detections: Dict[str, List[datetime]] = {}  # worker_name -> [timestamps]
        self._last_resource_check = datetime.min
        self._last_pattern_check = datetime.min

        # Statistics
        self.events_logged = 0
        self.healings_triggered = 0
        self.started_at = None

    def run(self):
        """Main watchdog loop."""
        self.running = True
        self.started_at = datetime.now()

        # Notify systemd we're ready
        sd_notify("READY=1")
        logger.info("=" * 60)
        logger.info("Unified Watchdog Service Started")
        logger.info(f"Monitoring {len(self.MONITORED_SERVICES)} service types")
        logger.info("=" * 60)

        loop_count = 0
        while self.running and not self._shutdown_event.is_set():
            try:
                loop_count += 1
                now = datetime.now()

                # 1. Heartbeat check (every 30s)
                self._check_heartbeats()

                # 2. Resource check (every 60s)
                if (now - self._last_resource_check).total_seconds() >= self.RESOURCE_CHECK_INTERVAL:
                    self._check_resources()
                    self._last_resource_check = now

                # 3. Pattern check (every 120s)
                if (now - self._last_pattern_check).total_seconds() >= self.PATTERN_CHECK_INTERVAL:
                    self._check_error_patterns()
                    self._check_failure_rates()  # Also check failure rates
                    self._last_pattern_check = now

                # Notify systemd watchdog
                sd_notify("WATCHDOG=1")

                # Log status periodically
                if loop_count % 20 == 0:  # Every 10 minutes
                    self._log_status()

            except Exception as e:
                logger.error(f"Watchdog loop error: {e}", exc_info=True)
                self._log_watchdog_event(
                    event_type='watchdog_error',
                    severity='error',
                    details={'error': str(e)}
                )

            # Sleep in small increments for quick shutdown
            self._shutdown_event.wait(self.HEARTBEAT_CHECK_INTERVAL)

        logger.info("Watchdog shutdown complete")

    def stop(self):
        """Stop the watchdog gracefully."""
        logger.info("Stopping watchdog...")
        self.running = False
        self._shutdown_event.set()

    def _check_heartbeats(self):
        """Check for stale worker heartbeats."""
        try:
            with self.db_manager.get_session() as session:
                # Query for stale workers using the helper function
                result = session.execute(
                    text("SELECT * FROM get_stale_workers(5)")
                )
                stale_workers = result.fetchall()

                for worker in stale_workers:
                    worker_name = worker[0]
                    worker_type = worker[1]
                    service_unit = worker[2]
                    minutes_stale = worker[4]

                    logger.warning(
                        f"Stale worker detected: {worker_name} "
                        f"(type: {worker_type}, stale for {minutes_stale:.1f} min)"
                    )

                    # Track stale detections
                    if worker_name not in self._stale_detections:
                        self._stale_detections[worker_name] = []
                    self._stale_detections[worker_name].append(datetime.now())

                    # Clean old detections (older than 10 min)
                    cutoff = datetime.now() - timedelta(minutes=10)
                    self._stale_detections[worker_name] = [
                        ts for ts in self._stale_detections[worker_name]
                        if ts > cutoff
                    ]

                    # Log event
                    self._log_watchdog_event(
                        event_type='stale_detected',
                        severity='warning',
                        target_service=service_unit,
                        target_worker_type=worker_type,
                        details={
                            'worker_name': worker_name,
                            'minutes_stale': minutes_stale,
                            'current_company_id': worker[5],
                            'current_module': worker[6],
                        }
                    )

                    # Log to SystemMonitor for pattern matching
                    service_name = self.SERVICE_NAME_MAP.get(worker_type, ServiceName.SYSTEM)
                    self.system_monitor.log_error(
                        service=service_name,
                        message=f"Worker {worker_name} stale for {minutes_stale:.1f} minutes",
                        severity=ErrorSeverity.WARNING,
                        error_code="HEARTBEAT_STALE",
                        component=worker_type,
                        context={
                            'worker_name': worker_name,
                            'minutes_stale': minutes_stale,
                            'service_unit': service_unit,
                        }
                    )

                    # Check if we should trigger healing
                    config = self._get_service_config(worker_type)
                    if config:
                        detection_count = len(self._stale_detections.get(worker_name, []))
                        if detection_count >= config.failure_threshold:
                            self._trigger_service_restart(
                                service_unit=config.service_unit,
                                worker_type=worker_type,
                                reason=f"Stale heartbeat ({detection_count} detections in 10 min)"
                            )
                            # Clear detections after healing attempt
                            self._stale_detections[worker_name] = []

        except Exception as e:
            logger.error(f"Heartbeat check failed: {e}")

    def _check_resources(self):
        """Check system resources (Chrome, Xvfb, memory)."""
        try:
            # 1. Chrome process count
            chrome_count = self._get_chrome_count()
            if chrome_count >= self.CHROME_CRITICAL_THRESHOLD:
                logger.error(f"CRITICAL: Chrome process count: {chrome_count}")
                self._log_watchdog_event(
                    event_type='resource_critical',
                    severity='critical',
                    details={'chrome_count': chrome_count, 'threshold': self.CHROME_CRITICAL_THRESHOLD}
                )
                self.system_monitor.log_error(
                    service=ServiceName.BROWSER_POOL,
                    message=f"Chrome process count critical: {chrome_count}",
                    severity=ErrorSeverity.CRITICAL,
                    error_code="CHROME_CRITICAL",
                    context={'count': chrome_count}
                )
            elif chrome_count >= self.CHROME_WARNING_THRESHOLD:
                logger.warning(f"WARNING: Chrome process count: {chrome_count}")
                self._log_watchdog_event(
                    event_type='resource_warning',
                    severity='warning',
                    details={'chrome_count': chrome_count, 'threshold': self.CHROME_WARNING_THRESHOLD}
                )

            # 2. Xvfb status
            xvfb_running = self._check_xvfb()
            if not xvfb_running:
                logger.error("CRITICAL: Xvfb display server not running")
                self._log_watchdog_event(
                    event_type='resource_critical',
                    severity='critical',
                    details={'xvfb_running': False}
                )
                self.system_monitor.log_error(
                    service=ServiceName.XVFB,
                    message="Xvfb display server not running",
                    severity=ErrorSeverity.CRITICAL,
                    error_code="XVFB_DEAD",
                )

            # 3. Memory usage
            memory_percent = self._get_memory_percent()
            if memory_percent >= self.MEMORY_CRITICAL_PERCENT:
                logger.error(f"CRITICAL: Memory usage: {memory_percent}%")
                self._log_watchdog_event(
                    event_type='resource_critical',
                    severity='critical',
                    details={'memory_percent': memory_percent, 'threshold': self.MEMORY_CRITICAL_PERCENT}
                )
                self.system_monitor.log_error(
                    service=ServiceName.SYSTEM,
                    message=f"Memory usage critical: {memory_percent}%",
                    severity=ErrorSeverity.CRITICAL,
                    error_code="MEMORY_CRITICAL",
                    context={'memory_percent': memory_percent}
                )
            elif memory_percent >= self.MEMORY_WARNING_PERCENT:
                logger.warning(f"WARNING: Memory usage: {memory_percent}%")

        except Exception as e:
            logger.error(f"Resource check failed: {e}")

    def _check_error_patterns(self):
        """Proactively check for error patterns that need healing."""
        try:
            # Let SystemMonitor handle pattern detection
            # This is already triggered when we log errors above
            # Here we just ensure patterns are being checked
            logger.debug("Pattern check cycle completed")
        except Exception as e:
            logger.error(f"Pattern check failed: {e}")

    def _check_failure_rates(self):
        """Check for workers with high failure rates and trigger healing."""
        try:
            with self.db_manager.get_session() as session:
                # Find workers with >50% failure rate and minimum 10 jobs processed
                result = session.execute(
                    text("""
                        SELECT worker_name, worker_type, service_unit,
                               jobs_completed, jobs_failed,
                               CASE WHEN (jobs_completed + jobs_failed) > 0
                                    THEN ROUND(jobs_failed::numeric / (jobs_completed + jobs_failed) * 100, 1)
                                    ELSE 0 END as failure_rate_pct
                        FROM job_heartbeats
                        WHERE status = 'running'
                          AND (jobs_completed + jobs_failed) >= 10
                          AND jobs_failed::float / NULLIF(jobs_completed + jobs_failed, 0) > 0.5
                    """)
                )
                high_failure_workers = result.fetchall()

                for worker in high_failure_workers:
                    worker_name = worker[0]
                    worker_type = worker[1]
                    service_unit = worker[2]
                    completed = worker[3]
                    failed = worker[4]
                    failure_rate = worker[5]

                    logger.warning(
                        f"High failure rate detected: {worker_name} "
                        f"({failure_rate}% - {failed}/{completed + failed} jobs failed)"
                    )

                    # Log event
                    self._log_watchdog_event(
                        event_type='high_failure_rate',
                        severity='warning',
                        target_service=service_unit,
                        target_worker_type=worker_type,
                        details={
                            'worker_name': worker_name,
                            'failure_rate': float(failure_rate),
                            'jobs_completed': completed,
                            'jobs_failed': failed
                        }
                    )

                    # Log to SystemMonitor for pattern matching
                    service_name = self.SERVICE_NAME_MAP.get(worker_type, ServiceName.SYSTEM)
                    self.system_monitor.log_error(
                        service=service_name,
                        message=f"Worker {worker_name} has {failure_rate}% failure rate",
                        severity=ErrorSeverity.WARNING,
                        error_code="HIGH_FAILURE_RATE",
                        context={
                            'worker_name': worker_name,
                            'failure_rate': float(failure_rate),
                            'jobs_failed': failed
                        }
                    )

                    # If failure rate > 80% and service_unit is set, trigger restart
                    if failure_rate > 80 and service_unit:
                        reason = f"Extreme failure rate ({failure_rate}%)"
                        self._trigger_service_restart(service_unit, worker_type, reason)

        except Exception as e:
            logger.error(f"Failure rate check failed: {e}")

    def _trigger_service_restart(self, service_unit: str, worker_type: str, reason: str):
        """Trigger a service restart via SystemMonitor."""
        logger.info(f"Triggering restart for {service_unit}: {reason}")

        service_name = self.SERVICE_NAME_MAP.get(worker_type, ServiceName.SYSTEM)
        start_time = time.time()

        try:
            # Use SystemMonitor's healing mechanism (includes cooldowns)
            success = self.system_monitor._trigger_healing_action(
                HealingAction.RESTART_SERVICE,
                reason,
                service_name,
                trigger_type="watchdog"
            )

            duration = time.time() - start_time

            # Log the event
            self._log_watchdog_event(
                event_type='healing_triggered',
                severity='warning' if success else 'error',
                target_service=service_unit,
                target_worker_type=worker_type,
                details={'reason': reason},
                action_taken='RESTART_SERVICE',
                action_success=success,
                action_duration=duration
            )

            if success:
                self.healings_triggered += 1
                logger.info(f"Service restart triggered successfully: {service_unit}")

                # Verify recovery after 60 seconds
                threading.Timer(60, self._verify_recovery, args=[service_unit, worker_type]).start()
            else:
                logger.warning(f"Service restart blocked (likely in cooldown): {service_unit}")

            return success

        except Exception as e:
            logger.error(f"Failed to trigger restart for {service_unit}: {e}")
            self._log_watchdog_event(
                event_type='healing_failed',
                severity='error',
                target_service=service_unit,
                details={'reason': reason, 'error': str(e)},
                action_taken='RESTART_SERVICE',
                action_success=False
            )
            return False

    def _verify_recovery(self, service_unit: str, worker_type: str):
        """Verify that a service recovered after healing."""
        try:
            # Check if heartbeat resumed
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT worker_name, last_heartbeat
                        FROM job_heartbeats
                        WHERE worker_type = :worker_type
                        AND status = 'running'
                        AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                    """),
                    {'worker_type': worker_type}
                )
                active_workers = result.fetchall()

                if active_workers:
                    logger.info(f"Recovery verified for {service_unit}: {len(active_workers)} worker(s) active")
                    self._log_watchdog_event(
                        event_type='recovery_verified',
                        severity='info',
                        target_service=service_unit,
                        target_worker_type=worker_type,
                        details={'active_workers': len(active_workers)}
                    )
                else:
                    logger.warning(f"Recovery NOT verified for {service_unit}: no active workers found")
                    self._log_watchdog_event(
                        event_type='recovery_failed',
                        severity='warning',
                        target_service=service_unit,
                        target_worker_type=worker_type,
                        details={'active_workers': 0}
                    )

        except Exception as e:
            logger.error(f"Recovery verification failed: {e}")

    def _get_service_config(self, worker_type: str) -> Optional[ServiceConfig]:
        """Get configuration for a worker type."""
        for config in self.MONITORED_SERVICES.values():
            if config.worker_type == worker_type:
                return config
        return None

    def _get_chrome_count(self) -> int:
        """Get current Chrome process count."""
        try:
            result = subprocess.run(
                ['pgrep', '-c', '-f', 'chrom'],
                capture_output=True, text=True, timeout=5
            )
            return int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            return 0

    def _check_xvfb(self) -> bool:
        """Check if Xvfb is running."""
        try:
            result = subprocess.run(
                ['pgrep', 'Xvfb'],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_memory_percent(self) -> float:
        """Get memory usage percentage."""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(':')] = int(parts[1])

                total = meminfo.get('MemTotal', 1)
                available = meminfo.get('MemAvailable', total)
                return ((total - available) / total) * 100
        except Exception:
            return 0

    def _log_watchdog_event(
        self,
        event_type: str,
        severity: str = 'info',
        target_service: Optional[str] = None,
        target_worker_type: Optional[str] = None,
        details: Optional[Dict] = None,
        action_taken: Optional[str] = None,
        action_success: Optional[bool] = None,
        action_duration: Optional[float] = None
    ):
        """Log an event to the watchdog_events table."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO watchdog_events
                            (event_type, severity, target_service, target_worker_type,
                             details, action_taken, action_success, action_duration_seconds)
                        VALUES
                            (:event_type, :severity, :target_service, :target_worker_type,
                             CAST(:details AS jsonb), :action_taken, :action_success, :action_duration)
                    """),
                    {
                        'event_type': event_type,
                        'severity': severity,
                        'target_service': target_service,
                        'target_worker_type': target_worker_type,
                        'details': json.dumps(details or {}),
                        'action_taken': action_taken,
                        'action_success': action_success,
                        'action_duration': action_duration,
                    }
                )
                session.commit()
                self.events_logged += 1
        except Exception as e:
            logger.error(f"Failed to log watchdog event: {e}")

    def _log_status(self):
        """Log current watchdog status."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("SELECT * FROM get_watchdog_summary(24)"))
                summary = result.fetchone()

                if summary:
                    logger.info(
                        f"Watchdog status (24h): "
                        f"events={summary[0]}, stale_detections={summary[1]}, "
                        f"healing_actions={summary[2]}, successful={summary[3]}, failed={summary[4]}, "
                        f"active_workers={summary[5]}, stale_workers={summary[6]}"
                    )
        except Exception as e:
            logger.error(f"Failed to log status: {e}")


def main():
    """Main entry point."""
    watchdog = UnifiedWatchdog()

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        watchdog.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        watchdog.run()
    except KeyboardInterrupt:
        watchdog.stop()
    except Exception as e:
        logger.error(f"Watchdog crashed: {e}", exc_info=True)
        sd_notify("STOPPING=1")
        sys.exit(1)


if __name__ == "__main__":
    main()

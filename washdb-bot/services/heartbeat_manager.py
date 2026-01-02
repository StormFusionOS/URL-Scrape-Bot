"""
HeartbeatManager - Reusable heartbeat management for all WashDB services.

Provides:
- Background thread for database heartbeat updates
- systemd watchdog integration via sd_notify
- Worker registration and status tracking
- Job completion/failure recording

Usage:
    from services.heartbeat_manager import HeartbeatManager
    from db.database_manager import get_db_manager

    heartbeat = HeartbeatManager(
        db_manager=get_db_manager(),
        worker_name="standardization_worker_1",
        worker_type="standardization_browser",
        service_unit="washdb-standardization-browser"  # systemd unit name
    )
    heartbeat.start()

    # In main loop:
    heartbeat.set_current_work(company_id=123, module='standardization')
    # On success:
    heartbeat.record_job_complete(duration_seconds=5.2)
    # On failure:
    heartbeat.record_job_failed("Connection timeout")

    # On shutdown:
    heartbeat.stop()
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy import text

# Configure logging
logger = logging.getLogger(__name__)

# Heartbeat settings
HEARTBEAT_INTERVAL = 30  # Update heartbeat every 30 seconds
STALE_THRESHOLD_MINUTES = 5  # Consider worker stale after 5 minutes without heartbeat


def sd_notify(state: str):
    """
    Send notification to systemd.

    Common states:
    - READY=1: Service is ready
    - WATCHDOG=1: Watchdog keepalive ping
    - STOPPING=1: Service is stopping
    - STATUS=<text>: Status text
    """
    notify_socket = os.environ.get('NOTIFY_SOCKET')
    if not notify_socket:
        return  # Not running under systemd

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if notify_socket.startswith('@'):
            # Abstract socket
            notify_socket = '\0' + notify_socket[1:]
        sock.connect(notify_socket)
        sock.sendall(state.encode('utf-8'))
        sock.close()
    except Exception as e:
        logger.debug(f"sd_notify failed: {e}")


# Optional system monitor integration
try:
    from services.system_monitor import get_system_monitor, ErrorSeverity, ServiceName
    SYSTEM_MONITOR_AVAILABLE = True
except ImportError:
    SYSTEM_MONITOR_AVAILABLE = False


class HeartbeatManager:
    """
    Manages heartbeat updates in a background thread.

    Features:
    - Database heartbeat updates every 30 seconds
    - systemd watchdog integration
    - Worker registration with hostname/PID
    - Job completion/failure tracking
    - Average job duration calculation
    - Optional integration with SystemMonitor for error logging
    """

    def __init__(
        self,
        db_manager,
        worker_name: str,
        worker_type: str,
        service_unit: Optional[str] = None,
        enable_sd_notify: bool = True
    ):
        """
        Initialize HeartbeatManager.

        Args:
            db_manager: Database manager with get_session() method
            worker_name: Unique name for this worker (e.g., "standardization_host1")
            worker_type: Type of worker (e.g., "standardization_browser", "verification")
            service_unit: systemd unit name for restart actions (e.g., "washdb-standardization-browser")
            enable_sd_notify: Whether to send systemd watchdog pings
        """
        self.db_manager = db_manager
        self.worker_name = worker_name
        self.worker_type = worker_type
        self.service_unit = service_unit
        self.enable_sd_notify = enable_sd_notify

        self.running = False
        self._thread = None
        self._lock = threading.Lock()

        # Stats
        self.companies_processed = 0
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.current_company_id = None
        self.current_module = None
        self.last_error = None
        self.last_error_at = None
        self.started_at = None
        self._job_durations = []

        # Map worker_type to ServiceName for SystemMonitor
        self._service_name_map = {
            'seo_orchestrator': 'SEO_WORKER',
            'standardization_browser': 'STANDARDIZATION',
            'verification': 'VERIFICATION',
            'yp_worker': 'YP_SCRAPER',
            'google_worker': 'GOOGLE_SCRAPER',
        }

    def start(self, config: Optional[Dict] = None):
        """
        Start the heartbeat thread.

        Args:
            config: Optional configuration dict to store in database
        """
        self.running = True
        self.started_at = datetime.now()

        # Register worker in database
        self._register_worker(config or {})

        # Start background thread
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        logger.info(f"Heartbeat started for worker: {self.worker_name} (type: {self.worker_type})")

    def stop(self, status: str = 'stopped'):
        """
        Stop the heartbeat thread and update final status.

        Args:
            status: Final status to set ('stopped', 'failed', etc.)
        """
        self.running = False
        self._update_status(status)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"Heartbeat stopped for worker: {self.worker_name}")

    def set_current_work(self, company_id: Optional[int] = None, module: Optional[str] = None):
        """
        Update current work being done.

        Args:
            company_id: Current company being processed
            module: Current module/task name
        """
        with self._lock:
            self.current_company_id = company_id
            self.current_module = module

    def record_job_complete(self, duration_seconds: Optional[float] = None):
        """
        Record a completed job.

        Args:
            duration_seconds: How long the job took
        """
        with self._lock:
            self.jobs_completed += 1
            if duration_seconds:
                self._job_durations.append(duration_seconds)
                # Keep only last 100 durations for average
                if len(self._job_durations) > 100:
                    self._job_durations = self._job_durations[-100:]

    def record_job_failed(
        self,
        error: str,
        module_name: Optional[str] = None,
        company_id: Optional[int] = None,
        error_code: Optional[str] = None
    ):
        """
        Record a failed job and optionally log to centralized error tracking.

        Args:
            error: Error message
            module_name: Optional module that failed
            company_id: Optional company ID
            error_code: Optional error code for SystemMonitor
        """
        with self._lock:
            self.jobs_failed += 1
            self.last_error = error[:500] if error else None  # Truncate long errors
            self.last_error_at = datetime.now()

        # Log to centralized system monitor if available
        if SYSTEM_MONITOR_AVAILABLE:
            try:
                monitor = get_system_monitor()
                service_name_str = self._service_name_map.get(self.worker_type, 'SYSTEM')
                service_name = getattr(ServiceName, service_name_str, ServiceName.SYSTEM)

                monitor.log_error(
                    service=service_name,
                    message=error[:500] if error else "Unknown error",
                    severity=ErrorSeverity.ERROR,
                    error_code=error_code or "JOB_FAILED",
                    component=module_name or self.current_module,
                    context={
                        'company_id': company_id or self.current_company_id,
                        'module': module_name or self.current_module,
                        'worker_name': self.worker_name,
                        'worker_type': self.worker_type,
                        'jobs_failed': self.jobs_failed,
                    }
                )
            except Exception as e:
                logger.debug(f"Failed to log error to system monitor: {e}")

    def record_company_complete(self):
        """Record a company fully processed."""
        with self._lock:
            self.companies_processed += 1

    def get_stats(self) -> Dict:
        """Get current worker stats."""
        with self._lock:
            avg_duration = None
            if self._job_durations:
                avg_duration = sum(self._job_durations) / len(self._job_durations)

            return {
                'worker_name': self.worker_name,
                'worker_type': self.worker_type,
                'service_unit': self.service_unit,
                'running': self.running,
                'companies_processed': self.companies_processed,
                'jobs_completed': self.jobs_completed,
                'jobs_failed': self.jobs_failed,
                'current_company_id': self.current_company_id,
                'current_module': self.current_module,
                'avg_job_duration': avg_duration,
                'last_error': self.last_error,
                'last_error_at': self.last_error_at.isoformat() if self.last_error_at else None,
                'started_at': self.started_at.isoformat() if self.started_at else None,
            }

    def _register_worker(self, config: Dict):
        """Register this worker in the database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    INSERT INTO job_heartbeats
                        (worker_name, worker_type, status, pid, hostname, config,
                         service_unit, started_at, last_heartbeat)
                    VALUES
                        (:worker_name, :worker_type, 'running', :pid, :hostname, :config,
                         :service_unit, NOW(), NOW())
                    ON CONFLICT (worker_name)
                    DO UPDATE SET
                        status = 'running',
                        worker_type = :worker_type,
                        pid = :pid,
                        hostname = :hostname,
                        config = :config,
                        service_unit = :service_unit,
                        started_at = NOW(),
                        last_heartbeat = NOW(),
                        companies_processed = 0,
                        jobs_completed = 0,
                        jobs_failed = 0,
                        current_company_id = NULL,
                        current_module = NULL,
                        last_error = NULL,
                        last_error_at = NULL
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'worker_type': self.worker_type,
                    'pid': os.getpid(),
                    'hostname': socket.gethostname(),
                    'config': json.dumps(config),
                    'service_unit': self.service_unit,
                })
                session.commit()
                logger.debug(f"Registered worker: {self.worker_name}")
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")

    def _heartbeat_loop(self):
        """Background loop that updates heartbeat every HEARTBEAT_INTERVAL seconds."""
        while self.running:
            try:
                self._send_heartbeat()
                # Also notify systemd watchdog if enabled
                if self.enable_sd_notify:
                    sd_notify("WATCHDOG=1")
            except Exception as e:
                logger.warning(f"Heartbeat update failed: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(HEARTBEAT_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

    def _send_heartbeat(self):
        """Send a heartbeat update to the database."""
        with self._lock:
            avg_duration = None
            if self._job_durations:
                avg_duration = sum(self._job_durations) / len(self._job_durations)

            try:
                with self.db_manager.get_session() as session:
                    query = text("""
                        UPDATE job_heartbeats
                        SET last_heartbeat = NOW(),
                            status = 'running',
                            companies_processed = :companies_processed,
                            jobs_completed = :jobs_completed,
                            jobs_failed = :jobs_failed,
                            current_company_id = :current_company_id,
                            current_module = :current_module,
                            avg_job_duration_seconds = :avg_duration,
                            last_error = :last_error,
                            last_error_at = :last_error_at
                        WHERE worker_name = :worker_name
                    """)
                    session.execute(query, {
                        'worker_name': self.worker_name,
                        'companies_processed': self.companies_processed,
                        'jobs_completed': self.jobs_completed,
                        'jobs_failed': self.jobs_failed,
                        'current_company_id': self.current_company_id,
                        'current_module': self.current_module,
                        'avg_duration': avg_duration,
                        'last_error': self.last_error,
                        'last_error_at': self.last_error_at,
                    })
                    session.commit()
            except Exception as e:
                logger.warning(f"Failed to update heartbeat: {e}")

    def _update_status(self, status: str):
        """Update worker status in database."""
        try:
            with self.db_manager.get_session() as session:
                query = text("""
                    UPDATE job_heartbeats
                    SET status = :status,
                        last_heartbeat = NOW(),
                        current_company_id = NULL,
                        current_module = NULL
                    WHERE worker_name = :worker_name
                """)
                session.execute(query, {
                    'worker_name': self.worker_name,
                    'status': status
                })
                session.commit()
        except Exception as e:
            logger.error(f"Failed to update status: {e}")

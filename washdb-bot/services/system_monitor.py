"""
SystemMonitor Service

Centralized monitoring and self-healing for all washdb-bot services.

Features:
- Aggregates errors from all services to system_errors table
- Detects error patterns and escalates appropriately
- Triggers self-healing actions with cooldown protection
- Sends email alerts for critical failures
- Provides health status API for dashboards
"""

import hashlib
import json
import os
import subprocess
import threading
import time
import traceback
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from runner.logging_setup import get_logger
from db.database_manager import get_db_manager
from services.email_alerts import EmailAlertService

logger = get_logger("system_monitor")


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ServiceName(str, Enum):
    """Monitored service names."""
    SEO_WORKER = "seo_worker"
    YP_SCRAPER = "yp_scraper"
    GOOGLE_SCRAPER = "google_scraper"
    VERIFICATION = "verification"
    STANDARDIZATION = "standardization"
    BROWSER_POOL = "browser_pool"
    XVFB = "xvfb"
    DATABASE = "database"
    SYSTEM = "system"
    WATCHDOG = "watchdog"


class HealingAction(str, Enum):
    """Self-healing action types."""
    CHROME_CLEANUP = "chrome_cleanup"
    CHROME_KILL_ALL = "chrome_kill_all"
    XVFB_RESTART = "xvfb_restart"
    RESTART_SERVICE = "restart_service"
    BROWSER_POOL_DRAIN = "browser_pool_drain"
    CLEAR_STUCK_JOBS = "clear_stuck_jobs"
    FULL_RESTART = "full_restart"


@dataclass
class HealingActionConfig:
    """Configuration for a self-healing action."""
    action: HealingAction
    cooldown_seconds: int = 300  # 5 minutes default
    max_attempts_per_hour: int = 3
    requires_confirmation: bool = False
    escalates_to: Optional[HealingAction] = None


@dataclass
class ErrorPattern:
    """Pattern for detecting error conditions that trigger healing."""
    pattern_id: str
    service: Optional[ServiceName]
    error_codes: List[str]
    severity_threshold: ErrorSeverity
    occurrence_threshold: int  # N occurrences
    time_window_minutes: int   # within M minutes
    healing_action: HealingAction
    description: str


class SystemMonitor:
    """
    Central monitoring service for washdb-bot infrastructure.

    Responsibilities:
    1. Log errors to system_errors table
    2. Detect patterns in error stream
    3. Execute self-healing actions with safeguards
    4. Send alerts for critical issues
    5. Track resolution effectiveness

    Usage:
        monitor = get_system_monitor()
        monitor.log_error(
            ServiceName.SEO_WORKER,
            "Job timeout after 300s",
            ErrorSeverity.ERROR,
            error_code="JOB_TIMEOUT",
            context={"company_id": 123, "module": "backlink_crawler"}
        )
    """

    _instance = None
    _lock = threading.Lock()

    # Error patterns that trigger healing
    ERROR_PATTERNS = [
        ErrorPattern(
            pattern_id="chrome_overflow",
            service=ServiceName.BROWSER_POOL,
            error_codes=["CHROME_OVERFLOW", "CHROME_CRITICAL", "CHROME_CRASH"],
            severity_threshold=ErrorSeverity.ERROR,
            occurrence_threshold=3,
            time_window_minutes=10,
            healing_action=HealingAction.CHROME_CLEANUP,
            description="Chrome process count exceeds threshold"
        ),
        ErrorPattern(
            pattern_id="xvfb_failure",
            service=ServiceName.XVFB,
            error_codes=["DISPLAY_ERROR", "XVFB_DEAD", "XVFB_UNAVAILABLE"],
            severity_threshold=ErrorSeverity.CRITICAL,
            occurrence_threshold=1,
            time_window_minutes=5,
            healing_action=HealingAction.XVFB_RESTART,
            description="Xvfb display server failure"
        ),
        ErrorPattern(
            pattern_id="service_stale",
            service=None,  # Any service
            error_codes=["HEARTBEAT_STALE", "SERVICE_UNRESPONSIVE", "WATCHDOG_TIMEOUT"],
            severity_threshold=ErrorSeverity.CRITICAL,
            occurrence_threshold=2,
            time_window_minutes=10,
            healing_action=HealingAction.RESTART_SERVICE,
            description="Service heartbeat stale"
        ),
        ErrorPattern(
            pattern_id="stuck_jobs",
            service=ServiceName.SEO_WORKER,
            error_codes=["JOB_STUCK", "JOB_TIMEOUT", "MODULE_TIMEOUT"],
            severity_threshold=ErrorSeverity.ERROR,
            occurrence_threshold=5,
            time_window_minutes=30,
            healing_action=HealingAction.CLEAR_STUCK_JOBS,
            description="Jobs stuck in running state"
        ),
        ErrorPattern(
            pattern_id="browser_captcha_storm",
            service=ServiceName.BROWSER_POOL,
            error_codes=["CAPTCHA_DETECTED", "BOT_BLOCKED", "ACCESS_DENIED"],
            severity_threshold=ErrorSeverity.WARNING,
            occurrence_threshold=10,
            time_window_minutes=15,
            healing_action=HealingAction.BROWSER_POOL_DRAIN,
            description="High CAPTCHA rate detected"
        ),
    ]

    # Healing action configurations
    HEALING_CONFIGS = {
        HealingAction.CHROME_CLEANUP: HealingActionConfig(
            action=HealingAction.CHROME_CLEANUP,
            cooldown_seconds=180,  # 3 minutes
            max_attempts_per_hour=5,
            escalates_to=HealingAction.CHROME_KILL_ALL
        ),
        HealingAction.CHROME_KILL_ALL: HealingActionConfig(
            action=HealingAction.CHROME_KILL_ALL,
            cooldown_seconds=600,  # 10 minutes
            max_attempts_per_hour=2,
            escalates_to=HealingAction.RESTART_SERVICE
        ),
        HealingAction.XVFB_RESTART: HealingActionConfig(
            action=HealingAction.XVFB_RESTART,
            cooldown_seconds=120,  # 2 minutes
            max_attempts_per_hour=3,
        ),
        HealingAction.RESTART_SERVICE: HealingActionConfig(
            action=HealingAction.RESTART_SERVICE,
            cooldown_seconds=300,  # 5 minutes
            max_attempts_per_hour=3,
            escalates_to=HealingAction.FULL_RESTART
        ),
        HealingAction.BROWSER_POOL_DRAIN: HealingActionConfig(
            action=HealingAction.BROWSER_POOL_DRAIN,
            cooldown_seconds=300,
            max_attempts_per_hour=2,
        ),
        HealingAction.CLEAR_STUCK_JOBS: HealingActionConfig(
            action=HealingAction.CLEAR_STUCK_JOBS,
            cooldown_seconds=600,
            max_attempts_per_hour=2,
        ),
        HealingAction.FULL_RESTART: HealingActionConfig(
            action=HealingAction.FULL_RESTART,
            cooldown_seconds=1800,  # 30 minutes
            max_attempts_per_hour=1,
            requires_confirmation=True,
        ),
    }

    # Service name to systemd unit mapping
    SERVICE_UNITS = {
        ServiceName.SEO_WORKER: "seo-job-worker",
        ServiceName.YP_SCRAPER: "yp-state-workers",
        ServiceName.GOOGLE_SCRAPER: "google-state-workers",
        ServiceName.VERIFICATION: "washdb-verification",
        ServiceName.STANDARDIZATION: "washdb-standardization-browser",
        ServiceName.WATCHDOG: "unified-watchdog",
    }

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.db_manager = get_db_manager()
        self.email_service = EmailAlertService()

        # Action tracking
        self._action_history: Dict[HealingAction, List[datetime]] = {
            action: [] for action in HealingAction
        }
        self._action_lock = threading.Lock()

        # Deduplication cache (hash -> last_seen)
        self._dedup_cache: Dict[str, datetime] = {}
        self._dedup_window_seconds = 300  # 5 minutes

        logger.info("SystemMonitor initialized")

    # =========================================================================
    # ERROR LOGGING API
    # =========================================================================

    def log_error(
        self,
        service: ServiceName,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        error_code: Optional[str] = None,
        component: Optional[str] = None,
        error_type: Optional[str] = None,
        stack_trace: Optional[str] = None,
        context: Optional[Dict] = None,
        check_patterns: bool = True,
    ) -> Optional[int]:
        """
        Log an error to the system_errors table.

        This is the primary API for services to report errors.

        Args:
            service: Which service is reporting the error
            message: Human-readable error description
            severity: Error severity level
            error_code: Standardized error code (e.g., 'CHROME_CRASH')
            component: Sub-component within service
            error_type: Python exception class name
            stack_trace: Full traceback string
            context: Additional context dict (company_id, url, etc.)
            check_patterns: Whether to check error patterns for healing

        Returns:
            error_id if logged, None if deduplicated or failed
        """
        try:
            # Capture system state
            system_state = self._capture_system_state()

            # Generate error hash for deduplication
            error_hash = self._generate_error_hash(service, error_code, message)

            # Check for deduplication
            if self._is_duplicate(error_hash):
                self._increment_occurrence_count(error_hash)
                return None

            # Insert new error
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("""
                        INSERT INTO system_errors (
                            service_name, component, error_code, severity,
                            message, stack_trace, error_type, context,
                            system_state, error_hash
                        ) VALUES (
                            :service, :component, :error_code, :severity,
                            :message, :stack_trace, :error_type, CAST(:context AS jsonb),
                            CAST(:system_state AS jsonb), :error_hash
                        ) RETURNING error_id
                    """),
                    {
                        "service": service.value,
                        "component": component,
                        "error_code": error_code,
                        "severity": severity.value,
                        "message": message[:2000],  # Truncate long messages
                        "stack_trace": stack_trace[:10000] if stack_trace else None,
                        "error_type": error_type,
                        "context": json.dumps(context or {}),
                        "system_state": json.dumps(system_state),
                        "error_hash": error_hash,
                    }
                )
                error_id = result.scalar()
                session.commit()

                # Update dedup cache
                self._dedup_cache[error_hash] = datetime.now()

                logger.info(f"Logged error {error_id}: [{severity.value}] {service.value} - {message[:100]}")

                # Check if this triggers a pattern
                if check_patterns and error_code:
                    self._check_error_patterns(service, error_code, severity)

                # Send email for critical errors
                if severity == ErrorSeverity.CRITICAL:
                    self._send_critical_alert(service, message, error_code, context)

                return error_id

        except Exception as e:
            logger.error(f"Failed to log error: {e}")
            return None

    def log_exception(
        self,
        service: ServiceName,
        exception: Exception,
        context: Optional[Dict] = None,
        component: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Optional[int]:
        """
        Convenience method to log a Python exception.

        Automatically extracts exception type and traceback.
        """
        return self.log_error(
            service=service,
            message=str(exception),
            severity=ErrorSeverity.ERROR,
            error_code=error_code or exception.__class__.__name__.upper(),
            component=component,
            error_type=exception.__class__.__name__,
            stack_trace=traceback.format_exc(),
            context=context,
        )

    # =========================================================================
    # SYSTEM STATE CAPTURE
    # =========================================================================

    def _capture_system_state(self) -> Dict:
        """Capture current system state for error context."""
        state = {"timestamp": datetime.now().isoformat()}

        # Chrome process count
        try:
            result = subprocess.run(
                ['pgrep', '-c', '-f', 'chrom'],
                capture_output=True, text=True, timeout=5
            )
            state['chrome_processes'] = int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            state['chrome_processes'] = -1

        # Memory usage
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
                for line in meminfo.split('\n'):
                    if 'MemAvailable' in line:
                        state['memory_available_mb'] = int(line.split()[1]) // 1024
                    elif 'MemTotal' in line:
                        state['memory_total_mb'] = int(line.split()[1]) // 1024
                    elif 'SwapFree' in line:
                        state['swap_free_mb'] = int(line.split()[1]) // 1024
        except Exception:
            pass

        # Xvfb status
        try:
            result = subprocess.run(['pgrep', 'Xvfb'], capture_output=True, text=True, timeout=5)
            state['xvfb_running'] = result.returncode == 0
        except Exception:
            state['xvfb_running'] = None

        return state

    def _generate_error_hash(self, service: ServiceName, error_code: Optional[str], message: str) -> str:
        """Generate hash for error deduplication."""
        key = f"{service.value}|{error_code or 'NONE'}|{message[:100]}"
        return hashlib.sha256(key.encode()).hexdigest()

    def _is_duplicate(self, error_hash: str) -> bool:
        """Check if error was recently logged (within dedup window)."""
        if error_hash not in self._dedup_cache:
            return False
        last_seen = self._dedup_cache[error_hash]
        return (datetime.now() - last_seen).total_seconds() < self._dedup_window_seconds

    def _increment_occurrence_count(self, error_hash: str) -> None:
        """Increment occurrence count for duplicate error."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(
                    text("""
                        UPDATE system_errors
                        SET occurrence_count = occurrence_count + 1,
                            updated_at = NOW()
                        WHERE error_hash = :hash
                        AND timestamp > NOW() - INTERVAL '5 minutes'
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """),
                    {"hash": error_hash}
                )
                session.commit()
        except Exception as e:
            logger.debug(f"Failed to increment occurrence count: {e}")

    # =========================================================================
    # PATTERN DETECTION & SELF-HEALING
    # =========================================================================

    def _check_error_patterns(self, service: ServiceName, error_code: str, severity: ErrorSeverity):
        """Check if recent errors match any healing patterns."""
        for pattern in self.ERROR_PATTERNS:
            # Check service match (None = any service)
            if pattern.service and pattern.service != service:
                continue

            # Check error code match
            if error_code not in pattern.error_codes:
                continue

            # Check severity threshold
            severity_order = [ErrorSeverity.INFO, ErrorSeverity.WARNING, ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]
            if severity_order.index(severity) < severity_order.index(pattern.severity_threshold):
                continue

            # Count recent occurrences
            count = self._count_recent_errors(
                service=service if pattern.service else None,
                error_codes=pattern.error_codes,
                minutes=pattern.time_window_minutes
            )

            if count >= pattern.occurrence_threshold:
                logger.warning(
                    f"Pattern matched: {pattern.pattern_id} ({count} occurrences in {pattern.time_window_minutes}m)"
                )
                self._trigger_healing_action(
                    pattern.healing_action,
                    f"Pattern '{pattern.pattern_id}': {pattern.description}",
                    service
                )

    def _count_recent_errors(
        self,
        service: Optional[ServiceName],
        error_codes: List[str],
        minutes: int
    ) -> int:
        """Count errors matching criteria in time window."""
        try:
            with self.db_manager.get_session() as session:
                query = """
                    SELECT COUNT(*) FROM system_errors
                    WHERE error_code = ANY(:codes)
                    AND timestamp > NOW() - INTERVAL ':minutes minutes'
                    AND resolved = FALSE
                """
                params = {"codes": error_codes, "minutes": minutes}

                if service:
                    query = query.replace(
                        "WHERE error_code",
                        "WHERE service_name = :service AND error_code"
                    )
                    params["service"] = service.value

                result = session.execute(text(query), params)
                return result.scalar() or 0
        except Exception:
            return 0

    def _trigger_healing_action(
        self,
        action: HealingAction,
        reason: str,
        target_service: Optional[ServiceName] = None,
        trigger_type: str = "auto"
    ) -> bool:
        """
        Execute a healing action with cooldown protection.

        Returns True if action was executed, False if blocked.
        """
        config = self.HEALING_CONFIGS.get(action)
        if not config:
            logger.error(f"Unknown healing action: {action}")
            return False

        with self._action_lock:
            now = datetime.now()

            # Clean old history entries
            for act in self._action_history:
                self._action_history[act] = [
                    ts for ts in self._action_history[act]
                    if ts > now - timedelta(hours=1)
                ]

            # Check cooldown
            recent_actions = [
                ts for ts in self._action_history[action]
                if ts > now - timedelta(seconds=config.cooldown_seconds)
            ]
            if recent_actions:
                logger.info(f"Healing action {action.value} in cooldown ({config.cooldown_seconds}s), skipping")
                return False

            # Check hourly limit
            hourly_actions = self._action_history[action]
            if len(hourly_actions) >= config.max_attempts_per_hour:
                logger.warning(f"Healing action {action.value} exceeded hourly limit ({config.max_attempts_per_hour})")
                # Try escalation if configured
                if config.escalates_to:
                    logger.info(f"Escalating to {config.escalates_to.value}")
                    return self._trigger_healing_action(
                        config.escalates_to,
                        f"Escalated from {action.value}: {reason}",
                        target_service,
                        "escalation"
                    )
                return False

            # Record this attempt
            self._action_history[action].append(now)

        # Execute the action
        logger.info(f"Executing healing action: {action.value} - {reason}")
        start_time = time.time()

        try:
            success = self._execute_healing_action(action, target_service)
            duration = time.time() - start_time

            # Log the action to database
            self._log_healing_action(action, reason, success, duration, trigger_type, target_service)

            return success

        except Exception as e:
            logger.error(f"Healing action {action.value} failed: {e}")
            self._log_healing_action(action, reason, False, time.time() - start_time, trigger_type, target_service, str(e))
            return False

    def _execute_healing_action(self, action: HealingAction, target_service: Optional[ServiceName] = None) -> bool:
        """Execute a specific healing action."""
        if action == HealingAction.CHROME_CLEANUP:
            return self._action_chrome_cleanup()
        elif action == HealingAction.CHROME_KILL_ALL:
            return self._action_chrome_kill_all()
        elif action == HealingAction.XVFB_RESTART:
            return self._action_xvfb_restart()
        elif action == HealingAction.RESTART_SERVICE:
            service_name = target_service or ServiceName.SEO_WORKER
            unit = self.SERVICE_UNITS.get(service_name, "seo-job-worker")
            return self._action_restart_service(unit)
        elif action == HealingAction.BROWSER_POOL_DRAIN:
            return self._action_browser_pool_drain()
        elif action == HealingAction.CLEAR_STUCK_JOBS:
            return self._action_clear_stuck_jobs()
        elif action == HealingAction.FULL_RESTART:
            return self._action_full_restart()
        else:
            logger.error(f"Unimplemented healing action: {action}")
            return False

    # =========================================================================
    # HEALING ACTION IMPLEMENTATIONS
    # =========================================================================

    def _action_chrome_cleanup(self) -> bool:
        """Clean up orphaned Chrome processes (older than 1 hour)."""
        try:
            # Find Chrome processes older than 1 hour
            result = subprocess.run(
                ['pgrep', '-f', 'chrom'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.info("No Chrome processes to clean up")
                return True

            pids = result.stdout.strip().split('\n')
            killed = 0

            for pid in pids:
                if not pid.strip():
                    continue
                try:
                    # Check process age
                    stat_path = f"/proc/{pid}/stat"
                    if not os.path.exists(stat_path):
                        continue

                    # Get process start time
                    with open(stat_path, 'r') as f:
                        stat = f.read().split()
                        if len(stat) > 21:
                            # Process start time is in clock ticks
                            start_ticks = int(stat[21])
                            uptime = float(open('/proc/uptime').read().split()[0])
                            hz = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                            age_seconds = uptime - (start_ticks / hz)

                            # Kill if older than 1 hour
                            if age_seconds > 3600:
                                subprocess.run(['kill', '-9', pid], timeout=5)
                                killed += 1
                except Exception:
                    continue

            logger.info(f"Chrome cleanup: killed {killed} orphan processes")
            return True

        except Exception as e:
            logger.error(f"Chrome cleanup failed: {e}")
            return False

    def _action_chrome_kill_all(self) -> bool:
        """Kill all Chrome processes (nuclear option)."""
        try:
            subprocess.run(['pkill', '-9', '-f', 'chromium'], capture_output=True, timeout=10)
            subprocess.run(['pkill', '-9', '-f', 'chromedriver'], capture_output=True, timeout=10)
            subprocess.run(['pkill', '-9', '-f', 'headless_shell'], capture_output=True, timeout=10)
            time.sleep(3)

            # Verify
            result = subprocess.run(['pgrep', '-c', '-f', 'chrom'], capture_output=True, text=True, timeout=5)
            count = int(result.stdout.strip()) if result.returncode == 0 else 0

            logger.info(f"Chrome kill all: {count} processes remaining")
            return count < 10

        except Exception as e:
            logger.error(f"Chrome kill all failed: {e}")
            return False

    def _action_xvfb_restart(self) -> bool:
        """Restart Xvfb display server."""
        try:
            # Kill existing
            subprocess.run(['pkill', '-9', 'Xvfb'], capture_output=True, timeout=5)
            time.sleep(2)

            # Start new
            subprocess.Popen(
                ['/usr/bin/Xvfb', ':99', '-screen', '0', '1920x1080x24'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            time.sleep(3)

            # Verify
            result = subprocess.run(['pgrep', 'Xvfb'], capture_output=True, text=True, timeout=5)
            success = result.returncode == 0

            logger.info(f"Xvfb restart: {'success' if success else 'failed'}")
            return success

        except Exception as e:
            logger.error(f"Xvfb restart failed: {e}")
            return False

    def _action_restart_service(self, service_name: str) -> bool:
        """Restart a systemd service."""
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', service_name],
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0

            if not success:
                logger.error(f"Service restart failed: {result.stderr}")
            else:
                logger.info(f"Service restart {service_name}: success")

            return success

        except Exception as e:
            logger.error(f"Service restart failed: {e}")
            return False

    def _action_browser_pool_drain(self) -> bool:
        """Trigger coordinated browser pool cleanup."""
        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool
            pool = get_browser_pool()
            result = pool.coordinated_cleanup(batch_size=15, batch_delay=5.0)

            logger.info(f"Browser pool drain: {result}")
            return result.get('drain_success', False)

        except ImportError:
            logger.warning("Browser pool not available for drain")
            return False
        except Exception as e:
            logger.error(f"Browser pool drain failed: {e}")
            return False

    def _action_clear_stuck_jobs(self) -> bool:
        """Clear stuck jobs from heartbeat and job tracking tables."""
        try:
            with self.db_manager.get_session() as session:
                # Mark stale heartbeats
                session.execute(text("""
                    UPDATE job_heartbeats
                    SET status = 'stale'
                    WHERE status = 'running'
                    AND last_heartbeat < NOW() - INTERVAL '10 minutes'
                """))

                # Mark stuck SEO jobs as failed (if table exists)
                try:
                    result = session.execute(text("""
                        UPDATE seo_job_tracking
                        SET status = 'failed',
                            error_message = 'Cleared by self-healing: stuck in running state'
                        WHERE status = 'running'
                        AND started_at < NOW() - INTERVAL '2 hours'
                        RETURNING tracking_id
                    """))
                    cleared = result.rowcount
                except Exception:
                    cleared = 0

                session.commit()

            logger.info(f"Cleared {cleared} stuck jobs")
            return True

        except Exception as e:
            logger.error(f"Clear stuck jobs failed: {e}")
            return False

    def _action_full_restart(self) -> bool:
        """Full restart of all scraper services (use with caution)."""
        services = ['seo-job-worker', 'washbot-yp-scraper', 'google-state-workers']
        all_success = True

        # Send email alert first
        self.email_service.send_alert(
            "FULL SYSTEM RESTART INITIATED",
            "The system monitor is restarting all scraper services due to repeated failures.\n\n"
            f"Services: {', '.join(services)}\n\n"
            "This is an automated action. Check logs if issues persist."
        )

        for svc in services:
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', svc],
                    capture_output=True,
                    timeout=60
                )
                if result.returncode != 0:
                    all_success = False
                    logger.error(f"Failed to restart {svc}")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Failed to restart {svc}: {e}")
                all_success = False

        return all_success

    # =========================================================================
    # DATABASE LOGGING
    # =========================================================================

    def _log_healing_action(
        self,
        action: HealingAction,
        reason: str,
        success: bool,
        duration: float,
        trigger_type: str,
        target_service: Optional[ServiceName] = None,
        error_message: Optional[str] = None
    ):
        """Log healing action to database."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO healing_actions (
                            action_type, target_service, trigger_type, trigger_reason,
                            success, result_message, duration_seconds
                        ) VALUES (
                            :action, :target, :trigger, :reason,
                            :success, :result, :duration
                        )
                    """),
                    {
                        "action": action.value,
                        "target": target_service.value if target_service else None,
                        "trigger": trigger_type,
                        "reason": reason,
                        "success": success,
                        "result": error_message if not success else "Action completed successfully",
                        "duration": duration,
                    }
                )
                session.commit()
        except Exception as e:
            logger.error(f"Failed to log healing action: {e}")

    def _send_critical_alert(
        self,
        service: ServiceName,
        message: str,
        error_code: Optional[str],
        context: Optional[Dict]
    ):
        """Send email alert for critical errors."""
        subject = f"CRITICAL: {service.value} - {error_code or 'Error'}"
        body = f"""Critical error detected in {service.value}:

{message}

Error Code: {error_code or 'N/A'}

Context:
{json.dumps(context or {}, indent=2)}

System State:
{json.dumps(self._capture_system_state(), indent=2)}

This may require manual intervention if self-healing does not resolve the issue.
"""
        self.email_service.send_alert(subject, body)

    # =========================================================================
    # QUERY API (for dashboard)
    # =========================================================================

    def get_recent_errors(
        self,
        hours: int = 24,
        service: Optional[ServiceName] = None,
        severity: Optional[ErrorSeverity] = None,
        unresolved_only: bool = False,
        limit: int = 100
    ) -> List[Dict]:
        """Get recent errors for dashboard display."""
        try:
            with self.db_manager.get_session() as session:
                query = """
                    SELECT error_id, timestamp, service_name, component, severity,
                           error_code, message, error_type, context, system_state,
                           resolved, resolution_action, occurrence_count
                    FROM system_errors
                    WHERE timestamp > NOW() - INTERVAL ':hours hours'
                """
                params = {"hours": hours, "limit": limit}

                if service:
                    query += " AND service_name = :service"
                    params["service"] = service.value
                if severity:
                    query += " AND severity = :severity"
                    params["severity"] = severity.value
                if unresolved_only:
                    query += " AND resolved = FALSE"

                query += " ORDER BY timestamp DESC LIMIT :limit"

                result = session.execute(text(query), params)
                rows = result.fetchall()

                return [
                    {
                        "error_id": row[0],
                        "timestamp": row[1].isoformat() if row[1] else None,
                        "service_name": row[2],
                        "component": row[3],
                        "severity": row[4],
                        "error_code": row[5],
                        "message": row[6],
                        "error_type": row[7],
                        "context": row[8],
                        "system_state": row[9],
                        "resolved": row[10],
                        "resolution_action": row[11],
                        "occurrence_count": row[12],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get recent errors: {e}")
            return []

    def get_healing_history(self, hours: int = 24, limit: int = 50) -> List[Dict]:
        """Get recent healing actions for dashboard."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT action_id, timestamp, action_type, target_service,
                               trigger_type, trigger_reason, success, result_message,
                               duration_seconds
                        FROM healing_actions
                        WHERE timestamp > NOW() - INTERVAL ':hours hours'
                        ORDER BY timestamp DESC
                        LIMIT :limit
                    """),
                    {"hours": hours, "limit": limit}
                )
                rows = result.fetchall()

                return [
                    {
                        "action_id": row[0],
                        "timestamp": row[1].isoformat() if row[1] else None,
                        "action_type": row[2],
                        "target_service": row[3],
                        "trigger_type": row[4],
                        "trigger_reason": row[5],
                        "success": row[6],
                        "result_message": row[7],
                        "duration_seconds": row[8],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get healing history: {e}")
            return []

    def get_error_stats(self, hours: int = 24) -> Dict[str, Dict]:
        """Get error statistics by service."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT * FROM get_error_stats_by_service(:hours)
                    """),
                    {"hours": hours}
                )
                rows = result.fetchall()

                return {
                    row[0]: {
                        "total": row[1],
                        "critical": row[2],
                        "error": row[3],
                        "warning": row[4],
                        "unresolved": row[5],
                        "auto_resolved": row[6],
                    }
                    for row in rows
                }
        except Exception as e:
            logger.error(f"Failed to get error stats: {e}")
            return {}

    def resolve_error(self, error_id: int, resolution_action: str = "manual", notes: str = None) -> bool:
        """Mark an error as resolved."""
        try:
            with self.db_manager.get_session() as session:
                session.execute(
                    text("SELECT resolve_error(:id, :action, :notes, FALSE)"),
                    {"id": error_id, "action": resolution_action, "notes": notes}
                )
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to resolve error: {e}")
            return False

    def format_error_for_ai(self, error: Dict) -> str:
        """Format error for AI troubleshooting (markdown)."""
        return f"""## Error #{error.get('error_id', 'N/A')}

**Time:** {error.get('timestamp', 'N/A')}
**Service:** {error.get('service_name', 'N/A')} | **Severity:** {error.get('severity', 'N/A').upper()} | **Code:** {error.get('error_code', 'N/A')}

**Message:** {error.get('message', 'N/A')}

**Error Type:** {error.get('error_type', 'N/A')}

### Context
```json
{json.dumps(error.get('context', {}), indent=2)}
```

### System State at Error Time
```json
{json.dumps(error.get('system_state', {}), indent=2)}
```

---
"""

    # =========================================================================
    # MANUAL HEALING TRIGGERS (for GUI)
    # =========================================================================

    def trigger_manual_healing(self, action: HealingAction, target_service: Optional[ServiceName] = None) -> Tuple[bool, str]:
        """
        Trigger a healing action manually from GUI.

        Returns (success, message)
        """
        success = self._trigger_healing_action(
            action,
            f"Manual trigger from GUI",
            target_service,
            trigger_type="manual"
        )

        if success:
            return True, f"Action '{action.value}' executed successfully"
        else:
            config = self.HEALING_CONFIGS.get(action)
            if config:
                return False, f"Action '{action.value}' is in cooldown or exceeded hourly limit"
            return False, f"Action '{action.value}' failed"


# Singleton getter
_monitor_instance: Optional[SystemMonitor] = None
_monitor_lock = threading.Lock()


def get_system_monitor() -> SystemMonitor:
    """Get the singleton SystemMonitor instance."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = SystemMonitor()
        return _monitor_instance

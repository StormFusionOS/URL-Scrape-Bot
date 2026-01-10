#!/usr/bin/env python3
"""
Browser Watchdog Service - Auto-restart services with stale browser sessions.

Monitors log files and service health to detect stale browser sessions,
then automatically restarts affected services with cooldown protection.

Features:
- Monitors standardization, SEO, and verification services
- Detects stale browser patterns (Connection refused, invalid session id)
- Cooldown periods to prevent restart loops
- Hourly restart limits per service
- Orphan browser cleanup when process count exceeds threshold
- Logging of all watchdog actions
"""

import os
import sys
import time
import logging
import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


@dataclass
class ServiceConfig:
    """Configuration for a monitored service."""
    name: str
    systemd_unit: str
    log_file: str
    stale_patterns: List[str]
    error_threshold: int = 5  # Errors within window to trigger restart
    error_window_seconds: int = 60  # Time window to count errors
    cooldown_seconds: int = 300  # 5 min between restarts
    max_restarts_per_hour: int = 3


@dataclass
class ServiceState:
    """Runtime state for a monitored service."""
    recent_errors: List[datetime] = field(default_factory=list)
    last_restart: Optional[datetime] = None
    restarts_this_hour: int = 0
    hour_start: Optional[datetime] = None


# Browser cleanup configuration
BROWSER_PROCESS_WARNING = 150  # Log warning above this
BROWSER_PROCESS_CRITICAL = 250  # Kill orphans above this
BROWSER_CLEANUP_COOLDOWN = 300  # 5 min between cleanups
BROWSER_PATTERNS = ['headless_shell', 'chromium', 'chrome']

# Service configurations
MONITORED_SERVICES = [
    ServiceConfig(
        name="standardization_pool",
        systemd_unit="standardization-worker-pool",
        log_file="logs/standardization_pool.log",
        stale_patterns=[
            r"Connection refused",
            r"invalid session id",
            r"session not created",
            r"no such session",
            r"Max retries exceeded.*localhost",
        ],
        error_threshold=5,
        error_window_seconds=30,
        cooldown_seconds=180,  # 3 min cooldown
        max_restarts_per_hour=4,
    ),
    ServiceConfig(
        name="seo_job_worker",
        systemd_unit="seo-job-worker",
        log_file="logs/seo_jobs.log",
        stale_patterns=[
            r"CRITICAL:.*Chrome processes",
            r"Still \d+ Chrome processes after cleanup",
            r"Connection refused",
            r"invalid session id",
        ],
        error_threshold=3,
        error_window_seconds=60,
        cooldown_seconds=300,  # 5 min cooldown
        max_restarts_per_hour=2,
    ),
]

# Setup logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'browser_watchdog.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('browser_watchdog')


class BrowserWatchdog:
    """
    Watchdog that monitors services for stale browser sessions
    and automatically restarts them.
    """

    def __init__(self, check_interval: int = 15):
        self.check_interval = check_interval
        self.running = True
        self.service_states: Dict[str, ServiceState] = {}
        self.log_positions: Dict[str, int] = {}
        self.base_path = Path(__file__).parent.parent
        self.check_count = 0
        self.last_heartbeat = datetime.now()
        self.last_browser_cleanup = None
        self.browser_cleanups_this_hour = 0
        self.cleanup_hour_start = None

        # Initialize state for each service
        for svc in MONITORED_SERVICES:
            self.service_states[svc.name] = ServiceState()
            self.log_positions[svc.name] = 0

    def _get_log_path(self, config: ServiceConfig) -> Path:
        """Get full path to service log file."""
        return self.base_path / config.log_file

    def _read_new_log_lines(self, config: ServiceConfig) -> List[str]:
        """Read new lines from log file since last check."""
        log_path = self._get_log_path(config)

        if not log_path.exists():
            return []

        try:
            current_size = log_path.stat().st_size
            last_position = self.log_positions.get(config.name, 0)

            # If file was truncated/rotated, start from beginning
            if current_size < last_position:
                last_position = 0

            if current_size == last_position:
                return []

            with open(log_path, 'r', errors='ignore') as f:
                f.seek(last_position)
                lines = f.readlines()
                self.log_positions[config.name] = f.tell()
                return lines

        except Exception as e:
            logger.warning(f"Error reading log {log_path}: {e}")
            return []

    def _check_for_stale_patterns(self, config: ServiceConfig, lines: List[str]) -> int:
        """Check log lines for stale browser patterns. Returns count of matches."""
        if not lines:
            return 0

        patterns = [re.compile(p, re.IGNORECASE) for p in config.stale_patterns]
        match_count = 0

        for line in lines:
            for pattern in patterns:
                if pattern.search(line):
                    match_count += 1
                    break  # Only count once per line

        return match_count

    def _is_service_running(self, config: ServiceConfig) -> bool:
        """Check if systemd service is running."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', config.systemd_unit],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.strip() == 'active'
        except Exception as e:
            logger.warning(f"Error checking service status {config.systemd_unit}: {e}")
            return False

    def _restart_service(self, config: ServiceConfig) -> bool:
        """Restart the systemd service."""
        logger.info(f"Restarting service: {config.systemd_unit}")

        try:
            # Use sudo only if not running as root
            if os.geteuid() == 0:
                cmd = ['systemctl', 'restart', config.systemd_unit]
            else:
                cmd = ['sudo', 'systemctl', 'restart', config.systemd_unit]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 min timeout for slow restarts
            )

            if result.returncode == 0:
                logger.info(f"Successfully restarted {config.systemd_unit}")
                return True
            else:
                logger.error(f"Failed to restart {config.systemd_unit}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout restarting {config.systemd_unit}")
            return False
        except Exception as e:
            logger.error(f"Error restarting {config.systemd_unit}: {e}")
            return False

    def _should_restart(self, config: ServiceConfig, state: ServiceState, error_count: int) -> bool:
        """Determine if service should be restarted based on errors and cooldowns."""
        now = datetime.now()

        # Add new errors to recent list
        for _ in range(error_count):
            state.recent_errors.append(now)

        # Prune old errors outside window
        cutoff = now - timedelta(seconds=config.error_window_seconds)
        state.recent_errors = [e for e in state.recent_errors if e > cutoff]

        # Check if we've exceeded error threshold
        if len(state.recent_errors) < config.error_threshold:
            return False

        # Check cooldown
        if state.last_restart:
            elapsed = (now - state.last_restart).total_seconds()
            if elapsed < config.cooldown_seconds:
                logger.debug(f"{config.name}: In cooldown ({elapsed:.0f}s < {config.cooldown_seconds}s)")
                return False

        # Check hourly limit
        if state.hour_start is None or (now - state.hour_start).total_seconds() > 3600:
            state.hour_start = now
            state.restarts_this_hour = 0

        if state.restarts_this_hour >= config.max_restarts_per_hour:
            logger.warning(f"{config.name}: Hourly restart limit reached ({config.max_restarts_per_hour})")
            return False

        return True

    def _check_service(self, config: ServiceConfig) -> None:
        """Check a single service for issues and restart if needed."""
        state = self.service_states[config.name]

        # Read new log lines
        new_lines = self._read_new_log_lines(config)

        # Check for stale patterns
        error_count = self._check_for_stale_patterns(config, new_lines)

        if error_count > 0:
            logger.debug(f"{config.name}: Found {error_count} stale browser errors")

        # Determine if restart is needed
        if self._should_restart(config, state, error_count):
            logger.warning(
                f"{config.name}: Detected {len(state.recent_errors)} stale browser errors "
                f"in {config.error_window_seconds}s, triggering restart"
            )

            # Verify service is actually running (might have already crashed)
            if not self._is_service_running(config):
                logger.info(f"{config.name}: Service not running, will restart")

            # Restart the service
            if self._restart_service(config):
                state.last_restart = datetime.now()
                state.restarts_this_hour += 1
                state.recent_errors.clear()

                # Reset log position to avoid re-reading old errors
                log_path = self._get_log_path(config)
                if log_path.exists():
                    self.log_positions[config.name] = log_path.stat().st_size

    def _count_browser_processes(self) -> int:
        """Count total browser processes."""
        total = 0
        for pattern in BROWSER_PATTERNS:
            try:
                result = subprocess.run(
                    ['pgrep', '-c', '-f', pattern],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    total += int(result.stdout.strip())
            except Exception:
                pass
        return total

    def _kill_browser_processes(self, pattern: str) -> int:
        """Kill browser processes matching pattern. Returns count killed."""
        try:
            # First count
            count_result = subprocess.run(
                ['pgrep', '-c', '-f', pattern],
                capture_output=True,
                text=True,
                timeout=10
            )
            count = int(count_result.stdout.strip()) if count_result.returncode == 0 else 0

            if count == 0:
                return 0

            # Kill them
            subprocess.run(
                ['pkill', '-9', '-f', pattern],
                capture_output=True,
                timeout=30
            )

            return count
        except Exception as e:
            logger.warning(f"Error killing {pattern} processes: {e}")
            return 0

    def _cleanup_orphan_browsers(self) -> None:
        """Check browser count and cleanup if above threshold."""
        now = datetime.now()

        # Check cooldown
        if self.last_browser_cleanup:
            elapsed = (now - self.last_browser_cleanup).total_seconds()
            if elapsed < BROWSER_CLEANUP_COOLDOWN:
                return

        # Reset hourly counter
        if self.cleanup_hour_start is None or (now - self.cleanup_hour_start).total_seconds() > 3600:
            self.cleanup_hour_start = now
            self.browser_cleanups_this_hour = 0

        # Max 3 cleanups per hour
        if self.browser_cleanups_this_hour >= 3:
            return

        # Count browsers
        browser_count = self._count_browser_processes()

        if browser_count >= BROWSER_PROCESS_CRITICAL:
            logger.warning(f"CRITICAL: {browser_count} browser processes detected (threshold: {BROWSER_PROCESS_CRITICAL})")
            logger.info("Initiating orphan browser cleanup...")

            total_killed = 0
            for pattern in BROWSER_PATTERNS:
                killed = self._kill_browser_processes(pattern)
                if killed > 0:
                    logger.info(f"Killed {killed} {pattern} processes")
                    total_killed += killed

            # Wait and recount
            time.sleep(3)
            new_count = self._count_browser_processes()

            logger.info(f"Browser cleanup complete: {browser_count} -> {new_count} ({total_killed} killed)")

            self.last_browser_cleanup = now
            self.browser_cleanups_this_hour += 1

        elif browser_count >= BROWSER_PROCESS_WARNING:
            logger.warning(f"High browser count: {browser_count} (warning: {BROWSER_PROCESS_WARNING}, critical: {BROWSER_PROCESS_CRITICAL})")

    def _check_all_services(self) -> None:
        """Check all monitored services."""
        self.check_count += 1

        # Check for orphan browsers every cycle
        try:
            self._cleanup_orphan_browsers()
        except Exception as e:
            logger.error(f"Error in browser cleanup: {e}")

        for config in MONITORED_SERVICES:
            try:
                self._check_service(config)
            except Exception as e:
                logger.error(f"Error checking {config.name}: {e}")

        # Log heartbeat every 5 minutes
        now = datetime.now()
        if (now - self.last_heartbeat).total_seconds() >= 300:
            total_restarts = sum(s.restarts_this_hour for s in self.service_states.values())
            browser_count = self._count_browser_processes()
            logger.info(
                f"Watchdog heartbeat: {self.check_count} checks, "
                f"{total_restarts} restarts this hour, {browser_count} browsers, all services monitored"
            )
            self.last_heartbeat = now

    def run(self) -> None:
        """Main watchdog loop."""
        logger.info("=" * 60)
        logger.info("BROWSER WATCHDOG STARTED")
        logger.info("=" * 60)
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Browser cleanup: warning={BROWSER_PROCESS_WARNING}, critical={BROWSER_PROCESS_CRITICAL}")
        logger.info(f"Monitoring {len(MONITORED_SERVICES)} services:")
        for svc in MONITORED_SERVICES:
            logger.info(f"  - {svc.name} ({svc.systemd_unit})")
        logger.info("=" * 60)

        # Log initial browser count
        browser_count = self._count_browser_processes()
        logger.info(f"Initial browser count: {browser_count}")

        # Initialize log positions to current end (don't process old errors)
        for config in MONITORED_SERVICES:
            log_path = self._get_log_path(config)
            if log_path.exists():
                self.log_positions[config.name] = log_path.stat().st_size
                logger.info(f"Starting log watch for {config.name} at position {self.log_positions[config.name]}")

        while self.running:
            try:
                self._check_all_services()
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                logger.info("Received interrupt, shutting down")
                self.running = False
            except Exception as e:
                logger.error(f"Unexpected error in watchdog loop: {e}")
                time.sleep(self.check_interval)

        logger.info("Browser watchdog stopped")

    def stop(self) -> None:
        """Stop the watchdog."""
        self.running = False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Browser Watchdog Service')
    parser.add_argument('--interval', type=int, default=15,
                        help='Check interval in seconds (default: 15)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Log actions but do not restart services')
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE - will not restart services")
        # Override restart method to just log
        original_restart = BrowserWatchdog._restart_service
        def dry_run_restart(self, config):
            logger.info(f"[DRY RUN] Would restart: {config.systemd_unit}")
            return True
        BrowserWatchdog._restart_service = dry_run_restart

    watchdog = BrowserWatchdog(check_interval=args.interval)

    try:
        watchdog.run()
    except KeyboardInterrupt:
        watchdog.stop()


if __name__ == "__main__":
    main()

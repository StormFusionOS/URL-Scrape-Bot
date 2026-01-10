"""
Xvfb Display Watchdog

Monitors Xvfb health and triggers automatic recovery.
Designed for long-running unattended operation.
"""

import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional, Callable

from runner.logging_setup import get_logger

logger = get_logger("xvfb_watchdog")


class XvfbWatchdog:
    """
    Watchdog for Xvfb virtual display server.

    Monitors the display and triggers recovery actions when it fails.
    Thread-safe singleton implementation.
    """

    _instance = None
    _lock = threading.Lock()

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
        self._display = os.environ.get('DISPLAY', ':99')
        self._check_interval = 10  # seconds
        self._consecutive_failures = 0
        self._max_failures_before_recovery = 3
        self._recovery_callback: Optional[Callable] = None
        self._shutdown = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._last_healthy = datetime.now()
        self._total_recoveries = 0
        self._recovery_lock = threading.Lock()

        logger.info(f"XvfbWatchdog initialized for display {self._display}")

    def start(self, recovery_callback: Optional[Callable] = None):
        """
        Start the watchdog thread.

        Args:
            recovery_callback: Function to call when Xvfb is recovered.
                              Used to notify browser pool to invalidate sessions.
        """
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            logger.warning("XvfbWatchdog already running")
            return

        self._recovery_callback = recovery_callback
        self._shutdown.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="XvfbWatchdog",
            daemon=True
        )
        self._watchdog_thread.start()
        logger.info(f"Xvfb watchdog started for display {self._display}")

    def stop(self):
        """Stop the watchdog thread."""
        self._shutdown.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        logger.info("Xvfb watchdog stopped")

    def is_display_healthy(self) -> bool:
        """
        Check if the X display is responding.

        Returns:
            True if display is healthy and responding
        """
        try:
            result = subprocess.run(
                ['xdpyinfo', '-display', self._display],
                capture_output=True,
                timeout=5,
                env={**os.environ, 'DISPLAY': self._display}
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning(f"xdpyinfo timed out for {self._display}")
            return False
        except FileNotFoundError:
            logger.warning("xdpyinfo not found - using fallback check")
            return self._fallback_display_check()
        except Exception as e:
            logger.error(f"Display health check error: {e}")
            return False

    def _fallback_display_check(self) -> bool:
        """Fallback display check using pgrep for Xvfb process."""
        try:
            result = subprocess.run(
                ['pgrep', '-x', 'Xvfb'],
                capture_output=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def restart_xvfb(self) -> bool:
        """
        Attempt to restart Xvfb via systemd.

        Returns:
            True if restart was successful
        """
        with self._recovery_lock:
            try:
                logger.warning("Attempting to restart Xvfb service...")

                # Try systemctl restart
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', 'xvfb'],
                    capture_output=True,
                    timeout=30
                )

                if result.returncode == 0:
                    time.sleep(2)  # Wait for Xvfb to start
                    if self.is_display_healthy():
                        self._total_recoveries += 1
                        logger.info(f"Xvfb successfully restarted (total recoveries: {self._total_recoveries})")
                        return True
                else:
                    logger.error(f"systemctl restart failed: {result.stderr.decode()}")

                # Fallback: start Xvfb directly
                return self._start_xvfb_directly()

            except subprocess.TimeoutExpired:
                logger.error("Xvfb restart timed out")
                return False
            except Exception as e:
                logger.error(f"Failed to restart Xvfb: {e}")
                return False

    def _start_xvfb_directly(self) -> bool:
        """Start Xvfb directly if systemctl fails."""
        try:
            logger.warning("Attempting direct Xvfb start...")

            # Kill any existing Xvfb on this display
            subprocess.run(
                ['pkill', '-9', '-f', f'Xvfb {self._display}'],
                capture_output=True
            )
            time.sleep(1)

            # Remove lock files
            display_num = self._display.replace(':', '')
            for lock_file in [f'/tmp/.X{display_num}-lock', f'/tmp/.X11-unix/X{display_num}']:
                try:
                    os.unlink(lock_file)
                except (FileNotFoundError, PermissionError):
                    pass

            # Start new Xvfb
            subprocess.Popen(
                ['Xvfb', self._display, '-screen', '0', '1920x1080x24',
                 '-ac', '+extension', 'GLX', '+render', '-noreset'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            time.sleep(2)

            if self.is_display_healthy():
                self._total_recoveries += 1
                logger.info(f"Xvfb started directly (total recoveries: {self._total_recoveries})")
                return True

            logger.error("Direct Xvfb start failed - display still unhealthy")
            return False

        except Exception as e:
            logger.error(f"Failed to start Xvfb directly: {e}")
            return False

    def _watchdog_loop(self):
        """Main watchdog loop - runs in background thread."""
        logger.info("Xvfb watchdog loop started")

        while not self._shutdown.is_set():
            try:
                if self.is_display_healthy():
                    if self._consecutive_failures > 0:
                        logger.info(f"Xvfb recovered after {self._consecutive_failures} failures")
                    self._consecutive_failures = 0
                    self._last_healthy = datetime.now()
                else:
                    self._consecutive_failures += 1
                    logger.warning(
                        f"Xvfb health check failed "
                        f"({self._consecutive_failures}/{self._max_failures_before_recovery})"
                    )

                    if self._consecutive_failures >= self._max_failures_before_recovery:
                        logger.error("Xvfb appears dead - triggering recovery")

                        # Restart Xvfb
                        if self.restart_xvfb():
                            self._consecutive_failures = 0

                            # Notify browser pool to recover sessions
                            if self._recovery_callback:
                                try:
                                    logger.info("Triggering recovery callback...")
                                    self._recovery_callback()
                                except Exception as e:
                                    logger.error(f"Recovery callback error: {e}")
                        else:
                            logger.critical("CRITICAL: Cannot restart Xvfb after multiple attempts!")
                            # Don't reset failures - keep trying

            except Exception as e:
                logger.error(f"Watchdog loop error: {e}")

            self._shutdown.wait(timeout=self._check_interval)

        logger.info("Xvfb watchdog loop exited")

    def get_status(self) -> dict:
        """
        Get watchdog status for monitoring.

        Returns:
            Dict with current health status
        """
        return {
            "display": self._display,
            "healthy": self.is_display_healthy(),
            "consecutive_failures": self._consecutive_failures,
            "last_healthy": self._last_healthy.isoformat(),
            "total_recoveries": self._total_recoveries,
            "check_interval": self._check_interval,
            "running": self._watchdog_thread is not None and self._watchdog_thread.is_alive(),
        }


# Singleton accessor
_xvfb_watchdog: Optional[XvfbWatchdog] = None
_accessor_lock = threading.Lock()


def get_xvfb_watchdog() -> XvfbWatchdog:
    """
    Get the singleton XvfbWatchdog instance.

    Returns:
        The global XvfbWatchdog instance
    """
    global _xvfb_watchdog
    with _accessor_lock:
        if _xvfb_watchdog is None:
            _xvfb_watchdog = XvfbWatchdog()
        return _xvfb_watchdog


def ensure_display_ready(timeout: int = 30) -> bool:
    """
    Ensure the X display is ready before proceeding.
    Useful for startup sequences.

    Args:
        timeout: Maximum seconds to wait for display

    Returns:
        True if display is ready
    """
    watchdog = get_xvfb_watchdog()

    start = time.time()
    while time.time() - start < timeout:
        if watchdog.is_display_healthy():
            return True
        time.sleep(1)

    logger.error(f"Display not ready after {timeout}s")
    return False

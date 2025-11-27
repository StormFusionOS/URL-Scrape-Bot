"""
Health Monitor

Monitors module workers for stuck/unresponsive states
and provides recovery mechanisms.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

from runner.logging_setup import get_logger


logger = get_logger("HealthMonitor")


@dataclass
class ModuleHealth:
    """Health status for a module."""
    module_name: str
    last_heartbeat: Optional[datetime] = None
    consecutive_failures: int = 0
    is_stuck: bool = False
    last_check: Optional[datetime] = None
    status: str = "unknown"  # unknown, healthy, warning, stuck, failed


class HealthMonitor:
    """
    Monitors health of SEO module workers.

    Features:
    - Heartbeat tracking
    - Stuck detection (no heartbeat within timeout)
    - Consecutive failure tracking
    - Recovery callbacks
    """

    def __init__(
        self,
        heartbeat_timeout_seconds: int = 300,
        check_interval_seconds: int = 30,
        max_consecutive_failures: int = 3
    ):
        """
        Initialize health monitor.

        Args:
            heartbeat_timeout_seconds: Time without heartbeat to consider stuck
            check_interval_seconds: How often to check health
            max_consecutive_failures: Failures before marking as failed
        """
        self.heartbeat_timeout = heartbeat_timeout_seconds
        self.check_interval = check_interval_seconds
        self.max_failures = max_consecutive_failures

        # Module health tracking
        self._modules: Dict[str, ModuleHealth] = {}
        self._lock = threading.Lock()

        # Background monitoring
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

        # Callbacks
        self._on_stuck_callback: Optional[Callable[[str], None]] = None
        self._on_failure_callback: Optional[Callable[[str], None]] = None
        self._on_recovery_callback: Optional[Callable[[str], None]] = None

    def register_module(self, module_name: str):
        """Register a module for health monitoring."""
        with self._lock:
            self._modules[module_name] = ModuleHealth(
                module_name=module_name,
                status="unknown"
            )
        logger.debug(f"Registered module for monitoring: {module_name}")

    def unregister_module(self, module_name: str):
        """Unregister a module from monitoring."""
        with self._lock:
            self._modules.pop(module_name, None)
        logger.debug(f"Unregistered module from monitoring: {module_name}")

    def record_heartbeat(self, module_name: str):
        """
        Record a heartbeat from a module.

        Args:
            module_name: Module name
        """
        with self._lock:
            if module_name not in self._modules:
                self._modules[module_name] = ModuleHealth(module_name=module_name)

            module = self._modules[module_name]
            was_stuck = module.is_stuck

            module.last_heartbeat = datetime.now()
            module.is_stuck = False
            module.status = "healthy"

            # Recovery callback if was stuck
            if was_stuck and self._on_recovery_callback:
                try:
                    self._on_recovery_callback(module_name)
                except Exception as e:
                    logger.error(f"Error in recovery callback for {module_name}: {e}")

    def record_success(self, module_name: str):
        """Record a successful operation from module."""
        with self._lock:
            if module_name in self._modules:
                self._modules[module_name].consecutive_failures = 0
                self._modules[module_name].status = "healthy"

    def record_failure(self, module_name: str):
        """Record a failure from module."""
        with self._lock:
            if module_name not in self._modules:
                self._modules[module_name] = ModuleHealth(module_name=module_name)

            module = self._modules[module_name]
            module.consecutive_failures += 1

            if module.consecutive_failures >= self.max_failures:
                module.status = "failed"

                # Failure callback
                if self._on_failure_callback:
                    try:
                        self._on_failure_callback(module_name)
                    except Exception as e:
                        logger.error(f"Error in failure callback for {module_name}: {e}")
            else:
                module.status = "warning"

    def set_on_stuck_callback(self, callback: Callable[[str], None]):
        """Set callback for when a module is detected as stuck."""
        self._on_stuck_callback = callback

    def set_on_failure_callback(self, callback: Callable[[str], None]):
        """Set callback for when a module exceeds failure threshold."""
        self._on_failure_callback = callback

    def set_on_recovery_callback(self, callback: Callable[[str], None]):
        """Set callback for when a stuck module recovers."""
        self._on_recovery_callback = callback

    def start_monitoring(self):
        """Start background health monitoring."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HealthMonitor"
        )
        self._monitor_thread.start()
        logger.info("Health monitoring started")

    def stop_monitoring(self):
        """Stop background health monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        logger.info("Health monitoring stopped")

    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._running:
            try:
                self._check_all_modules()
            except Exception as e:
                logger.error(f"Error in health check: {e}")

            # Wait for next check interval
            for _ in range(int(self.check_interval)):
                if not self._running:
                    break
                time.sleep(1)

    def _check_all_modules(self):
        """Check health of all registered modules."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.heartbeat_timeout)

        with self._lock:
            for name, module in self._modules.items():
                module.last_check = now

                # Skip if no heartbeat recorded yet
                if not module.last_heartbeat:
                    continue

                # Check for stuck (no heartbeat within timeout)
                if module.last_heartbeat < cutoff:
                    if not module.is_stuck:
                        module.is_stuck = True
                        module.status = "stuck"
                        logger.warning(
                            f"Module {name} appears stuck "
                            f"(last heartbeat: {module.last_heartbeat})"
                        )

                        # Stuck callback
                        if self._on_stuck_callback:
                            try:
                                self._on_stuck_callback(name)
                            except Exception as e:
                                logger.error(f"Error in stuck callback for {name}: {e}")

    def get_stuck_modules(self) -> List[str]:
        """Get list of currently stuck modules."""
        with self._lock:
            return [
                name for name, module in self._modules.items()
                if module.is_stuck
            ]

    def get_failed_modules(self) -> List[str]:
        """Get list of failed modules (exceeded failure threshold)."""
        with self._lock:
            return [
                name for name, module in self._modules.items()
                if module.status == "failed"
            ]

    def get_module_health(self, module_name: str) -> Optional[Dict[str, Any]]:
        """Get health status for a specific module."""
        with self._lock:
            module = self._modules.get(module_name)
            if not module:
                return None

            return {
                "module_name": module.module_name,
                "status": module.status,
                "is_stuck": module.is_stuck,
                "consecutive_failures": module.consecutive_failures,
                "last_heartbeat": module.last_heartbeat.isoformat() if module.last_heartbeat else None,
                "last_check": module.last_check.isoformat() if module.last_check else None
            }

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status for all modules."""
        with self._lock:
            return {
                name: {
                    "status": module.status,
                    "is_stuck": module.is_stuck,
                    "consecutive_failures": module.consecutive_failures,
                    "last_heartbeat": module.last_heartbeat.isoformat() if module.last_heartbeat else None
                }
                for name, module in self._modules.items()
            }

    def reset_module(self, module_name: str):
        """Reset health tracking for a module."""
        with self._lock:
            if module_name in self._modules:
                self._modules[module_name] = ModuleHealth(
                    module_name=module_name,
                    status="unknown"
                )

    def reset_all(self):
        """Reset health tracking for all modules."""
        with self._lock:
            for name in self._modules:
                self._modules[name] = ModuleHealth(
                    module_name=name,
                    status="unknown"
                )

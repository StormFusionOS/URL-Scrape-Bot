"""
Self-Healing Infrastructure Coordinator

Monitors all critical components and triggers automatic recovery.
Designed for weeks of unattended operation.

Components monitored:
- Xvfb display server
- Browser pool health
- Chrome process count
- Port allocation
- Memory usage

Recovery actions:
- Restart Xvfb if dead
- Resurrect dead browser sessions
- Clean orphaned Chrome processes
- Release leaked ports
- Trigger garbage collection
"""

import gc
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable

from runner.logging_setup import get_logger

logger = get_logger("self_healing")


class ComponentHealth(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    DEAD = "dead"


@dataclass
class HealthCheck:
    """Health check result."""
    component: str
    status: ComponentHealth
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    metrics: Dict = field(default_factory=dict)


class SelfHealingCoordinator:
    """
    Coordinates self-healing across all infrastructure components.

    Monitors:
    - Xvfb display server
    - Browser pool health
    - Chrome process count
    - Port allocation
    - Memory usage

    Actions:
    - Restart Xvfb if dead
    - Resurrect dead browser sessions
    - Clean orphaned Chrome processes
    - Release leaked ports
    - Trigger garbage collection
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
        self._check_interval = 30  # seconds
        self._shutdown = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

        # Health thresholds
        self._thresholds = {
            'max_chrome_processes': 60,
            'min_healthy_sessions': 3,
            'max_consecutive_failures': 5,
            'max_port_allocations': 200,
            'max_memory_percent': 85,
        }

        # Recovery callbacks
        self._recovery_handlers: Dict[str, Callable] = {}

        # Health history
        self._health_history: List[HealthCheck] = []
        self._max_history = 1000

        # Recovery state
        self._last_recovery: Dict[str, datetime] = {}
        self._recovery_cooldown = 300  # 5 min between recoveries per component

        logger.info("SelfHealingCoordinator initialized")

    def start(self):
        """Start the self-healing coordinator."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("SelfHealingCoordinator already running")
            return

        self._shutdown.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="SelfHealing-Monitor",
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("Self-healing coordinator started")

    def stop(self):
        """Stop the self-healing coordinator."""
        self._shutdown.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
        logger.info("Self-healing coordinator stopped")

    def register_recovery_handler(self, component: str, handler: Callable):
        """Register a custom recovery handler for a component."""
        self._recovery_handlers[component] = handler
        logger.debug(f"Registered recovery handler for {component}")

    def _monitor_loop(self):
        """Main monitoring loop."""
        logger.info("Self-healing monitor loop started")

        while not self._shutdown.is_set():
            try:
                # Run all health checks
                checks = [
                    self._check_xvfb(),
                    self._check_browser_pool(),
                    self._check_chrome_processes(),
                    self._check_port_allocation(),
                    self._check_memory(),
                    self._check_threads(),
                ]

                # Record health history
                for check in checks:
                    self._record_health(check)

                    # Trigger recovery if needed
                    if check.status in (ComponentHealth.CRITICAL, ComponentHealth.DEAD):
                        self._trigger_recovery(check)

                # Log summary periodically
                if len(self._health_history) % 100 == 0:
                    self._log_health_summary()

            except Exception as e:
                logger.error(f"Self-healing monitor error: {e}")

            self._shutdown.wait(timeout=self._check_interval)

        logger.info("Self-healing monitor loop exited")

    def _check_xvfb(self) -> HealthCheck:
        """Check Xvfb health."""
        try:
            from seo_intelligence.drivers.xvfb_watchdog import get_xvfb_watchdog

            watchdog = get_xvfb_watchdog()
            status_dict = watchdog.get_status()

            if status_dict['healthy']:
                return HealthCheck(
                    component='xvfb',
                    status=ComponentHealth.HEALTHY,
                    message='Display server healthy',
                    metrics=status_dict
                )
            else:
                return HealthCheck(
                    component='xvfb',
                    status=ComponentHealth.DEAD,
                    message=f"Display server down ({status_dict['consecutive_failures']} failures)",
                    metrics=status_dict
                )
        except Exception as e:
            return HealthCheck(
                component='xvfb',
                status=ComponentHealth.CRITICAL,
                message=f"Cannot check Xvfb: {e}",
                metrics={}
            )

    def _check_browser_pool(self) -> HealthCheck:
        """Check browser pool health."""
        try:
            from seo_intelligence.drivers.browser_pool import get_browser_pool

            pool = get_browser_pool()
            if not pool.is_enabled():
                return HealthCheck(
                    component='browser_pool',
                    status=ComponentHealth.HEALTHY,
                    message='Pool disabled',
                    metrics={'enabled': False}
                )

            stats = pool.get_stats()

            healthy_sessions = stats.sessions_by_state.get('idle_warm', 0)
            dead_sessions = stats.sessions_by_state.get('dead', 0)
            quarantined = stats.sessions_by_state.get('quarantined', 0)

            metrics = {
                'total_sessions': stats.total_sessions,
                'healthy_sessions': healthy_sessions,
                'dead_sessions': dead_sessions,
                'quarantined': quarantined,
                'active_leases': stats.active_leases,
            }

            if healthy_sessions >= self._thresholds['min_healthy_sessions']:
                status = ComponentHealth.HEALTHY
                message = f"{healthy_sessions} healthy sessions"
            elif healthy_sessions > 0:
                status = ComponentHealth.DEGRADED
                message = f"Low healthy sessions: {healthy_sessions}"
            else:
                status = ComponentHealth.CRITICAL
                message = f"No healthy sessions (dead={dead_sessions}, quarantined={quarantined})"

            return HealthCheck(
                component='browser_pool',
                status=status,
                message=message,
                metrics=metrics
            )

        except Exception as e:
            return HealthCheck(
                component='browser_pool',
                status=ComponentHealth.CRITICAL,
                message=f"Cannot check pool: {e}",
                metrics={}
            )

    def _check_chrome_processes(self) -> HealthCheck:
        """Check Chrome process count."""
        try:
            from seo_intelligence.drivers.chrome_process_manager import get_chrome_process_manager

            pm = get_chrome_process_manager()
            stats = pm.get_stats()

            count = stats['total_chrome_processes']
            tracked = stats['tracked_processes']
            orphans = count - tracked

            metrics = {
                'total': count,
                'tracked': tracked,
                'orphans': orphans,
            }

            if count < self._thresholds['max_chrome_processes']:
                status = ComponentHealth.HEALTHY
                message = f"{count} Chrome processes ({orphans} orphans)"
            elif count < self._thresholds['max_chrome_processes'] * 1.5:
                status = ComponentHealth.DEGRADED
                message = f"High Chrome count: {count}"
            else:
                status = ComponentHealth.CRITICAL
                message = f"Critical Chrome count: {count}"

            return HealthCheck(
                component='chrome_processes',
                status=status,
                message=message,
                metrics=metrics
            )

        except Exception as e:
            return HealthCheck(
                component='chrome_processes',
                status=ComponentHealth.HEALTHY,
                message=f"Cannot check Chrome: {e}",
                metrics={}
            )

    def _check_port_allocation(self) -> HealthCheck:
        """Check port allocation status."""
        try:
            from seo_intelligence.drivers.seleniumbase_drivers import get_port_allocator

            allocator = get_port_allocator()
            stats = allocator.get_stats()
            allocated = stats['allocated_count']

            metrics = {'allocated_ports': allocated}

            if allocated < self._thresholds['max_port_allocations']:
                status = ComponentHealth.HEALTHY
                message = f"{allocated} ports allocated"
            else:
                status = ComponentHealth.CRITICAL
                message = f"Port exhaustion: {allocated} allocated"

            return HealthCheck(
                component='port_allocation',
                status=status,
                message=message,
                metrics=metrics
            )

        except Exception as e:
            return HealthCheck(
                component='port_allocation',
                status=ComponentHealth.HEALTHY,
                message=f"Cannot check ports: {e}",
                metrics={}
            )

    def _check_memory(self) -> HealthCheck:
        """Check memory usage."""
        try:
            import psutil
            memory = psutil.virtual_memory()
            usage_percent = memory.percent

            metrics = {
                'usage_percent': usage_percent,
                'available_gb': memory.available / (1024 ** 3),
            }

            if usage_percent < 70:
                status = ComponentHealth.HEALTHY
                message = f"Memory usage: {usage_percent:.0f}%"
            elif usage_percent < self._thresholds['max_memory_percent']:
                status = ComponentHealth.DEGRADED
                message = f"High memory: {usage_percent:.0f}%"
            else:
                status = ComponentHealth.CRITICAL
                message = f"Critical memory: {usage_percent:.0f}%"

            return HealthCheck(
                component='memory',
                status=status,
                message=message,
                metrics=metrics
            )

        except ImportError:
            return HealthCheck(
                component='memory',
                status=ComponentHealth.HEALTHY,
                message='psutil not available',
                metrics={}
            )
        except Exception as e:
            return HealthCheck(
                component='memory',
                status=ComponentHealth.HEALTHY,
                message=f"Cannot check memory: {e}",
                metrics={}
            )

    def _check_threads(self) -> HealthCheck:
        """Check thread count to detect thread exhaustion."""
        try:
            import threading
            thread_count = threading.active_count()

            metrics = {
                'thread_count': thread_count,
            }

            # Try to get thread breakdown
            try:
                import subprocess
                import os
                result = subprocess.run(
                    ['ps', '-u', str(os.getuid()), '-L', '-o', 'comm'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    from collections import Counter
                    threads = result.stdout.strip().split('\n')[1:]  # Skip header
                    top_threads = dict(Counter(threads).most_common(5))
                    metrics['top_threads'] = top_threads
            except Exception:
                pass

            if thread_count < 1500:
                status = ComponentHealth.HEALTHY
                message = f"Threads: {thread_count}"
            elif thread_count < 2500:
                status = ComponentHealth.DEGRADED
                message = f"High thread count: {thread_count}"
            else:
                status = ComponentHealth.CRITICAL
                message = f"Critical thread count: {thread_count}"

            return HealthCheck(
                component='threads',
                status=status,
                message=message,
                metrics=metrics
            )

        except Exception as e:
            return HealthCheck(
                component='threads',
                status=ComponentHealth.HEALTHY,
                message=f"Cannot check threads: {e}",
                metrics={}
            )

    def _record_health(self, check: HealthCheck):
        """Record a health check result."""
        self._health_history.append(check)
        if len(self._health_history) > self._max_history:
            self._health_history = self._health_history[-self._max_history:]

    def _trigger_recovery(self, check: HealthCheck):
        """Trigger recovery for a component."""
        component = check.component

        # Check cooldown
        last = self._last_recovery.get(component)
        if last and (datetime.now() - last).total_seconds() < self._recovery_cooldown:
            logger.debug(f"Recovery for {component} in cooldown")
            return

        logger.warning(f"Triggering recovery for {component}: {check.message}")
        self._last_recovery[component] = datetime.now()

        # Execute custom handler if registered
        handler = self._recovery_handlers.get(component)
        if handler:
            try:
                handler()
                return
            except Exception as e:
                logger.error(f"Custom recovery handler error for {component}: {e}")

        # Default recovery actions
        self._default_recovery(component)

    def _default_recovery(self, component: str):
        """Default recovery actions for each component."""
        if component == 'xvfb':
            try:
                from seo_intelligence.drivers.xvfb_watchdog import get_xvfb_watchdog
                watchdog = get_xvfb_watchdog()
                if watchdog.restart_xvfb():
                    logger.info("Xvfb recovered via self-healing")
            except Exception as e:
                logger.error(f"Xvfb recovery failed: {e}")

        elif component == 'browser_pool':
            try:
                from seo_intelligence.drivers.browser_pool import get_browser_pool
                pool = get_browser_pool()
                resurrected = pool.resurrect_dead_sessions()
                logger.info(f"Browser pool recovery: resurrected {resurrected} sessions")
            except Exception as e:
                logger.error(f"Browser pool recovery failed: {e}")

        elif component == 'chrome_processes':
            try:
                from seo_intelligence.drivers.chrome_process_manager import get_chrome_process_manager
                pm = get_chrome_process_manager()
                cleaned = pm.cleanup_orphaned_processes()
                logger.info(f"Chrome process recovery: cleaned {cleaned} orphans")
            except Exception as e:
                logger.error(f"Chrome process recovery failed: {e}")

        elif component == 'port_allocation':
            # Force garbage collection to release ports
            gc.collect()
            logger.info("Port allocation recovery: forced garbage collection")

        elif component == 'memory':
            # Force aggressive garbage collection
            gc.collect()
            gc.collect()
            gc.collect()
            logger.info("Memory recovery: forced garbage collection")

        elif component == 'threads':
            # Force garbage collection to clean up thread pools
            import threading
            before = threading.active_count()
            gc.collect()
            gc.collect()
            gc.collect()
            after = threading.active_count()
            logger.info(f"Thread recovery: GC reduced threads from {before} to {after}")

            # If still critical, log detailed thread info
            if after > 2500:
                try:
                    import subprocess
                    import os
                    result = subprocess.run(
                        ['ps', '-u', str(os.getuid()), '-L', '-o', 'comm'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        from collections import Counter
                        threads = result.stdout.strip().split('\n')[1:]
                        top_threads = Counter(threads).most_common(10)
                        logger.warning(f"Top thread types: {top_threads}")
                except Exception:
                    pass

    def _log_health_summary(self):
        """Log health summary."""
        recent = self._health_history[-10:]

        by_component = {}
        for check in recent:
            if check.component not in by_component:
                by_component[check.component] = []
            by_component[check.component].append(check.status.value)

        summary = ", ".join(
            f"{comp}: {statuses[-1]}"
            for comp, statuses in by_component.items()
        )
        logger.info(f"Health summary: {summary}")

    def get_health_report(self) -> Dict:
        """Get comprehensive health report."""
        recent = self._health_history[-100:]

        by_component = {}
        for check in recent:
            if check.component not in by_component:
                by_component[check.component] = {
                    'latest_status': None,
                    'latest_message': None,
                    'healthy_count': 0,
                    'degraded_count': 0,
                    'critical_count': 0,
                }

            comp = by_component[check.component]
            comp['latest_status'] = check.status.value
            comp['latest_message'] = check.message

            if check.status == ComponentHealth.HEALTHY:
                comp['healthy_count'] += 1
            elif check.status == ComponentHealth.DEGRADED:
                comp['degraded_count'] += 1
            else:
                comp['critical_count'] += 1

        return {
            'timestamp': datetime.now().isoformat(),
            'components': by_component,
            'recovery_history': {
                k: v.isoformat() for k, v in self._last_recovery.items()
            }
        }


# Singleton accessor
_self_healing_coordinator: Optional[SelfHealingCoordinator] = None
_accessor_lock = threading.Lock()


def get_self_healing_coordinator() -> SelfHealingCoordinator:
    """
    Get the singleton SelfHealingCoordinator instance.

    Returns:
        The global SelfHealingCoordinator instance
    """
    global _self_healing_coordinator
    with _accessor_lock:
        if _self_healing_coordinator is None:
            _self_healing_coordinator = SelfHealingCoordinator()
        return _self_healing_coordinator

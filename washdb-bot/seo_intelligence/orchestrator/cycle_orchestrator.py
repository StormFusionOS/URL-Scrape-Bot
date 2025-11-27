"""
SEO Cycle Orchestrator

Main orchestrator that manages continuous cycling through all SEO modules.
Provides supervisor pattern with fault isolation and recovery.
"""

import os
import time
import threading
import signal
from datetime import datetime
from typing import Dict, List, Optional, Any, Type
from pathlib import Path

from .state_manager import CycleStateManager
from .resource_manager import ResourceManager, get_resource_manager
from .health_monitor import HealthMonitor
from .module_worker import BaseModuleWorker, WorkerStats

from runner.logging_setup import get_logger


logger = get_logger("SEOCycleOrchestrator")


class SEOCycleOrchestrator:
    """
    Main orchestrator for continuous SEO module cycling.

    Features:
    - Supervisor pattern: isolates module failures
    - Continuous cycling through all 5 modules
    - State persistence for crash recovery
    - Health monitoring and stuck detection
    - Graceful shutdown handling
    """

    MODULE_ORDER = [
        "serp", "citations", "backlinks", "technical", "seo_worker",
        # Phase 2 & 3 modules
        "keyword_intel", "competitive"
    ]

    def __init__(
        self,
        log_dir: str = "logs/seo_modules",
        state_json_path: str = "data/seo_cycle_state.json",
        heartbeat_timeout: int = 300,
        delay_between_modules: float = 5.0,
        delay_between_cycles: float = 60.0
    ):
        """
        Initialize orchestrator.

        Args:
            log_dir: Directory for module logs
            state_json_path: Path for JSON state backup
            heartbeat_timeout: Seconds without heartbeat to consider stuck
            delay_between_modules: Delay in seconds between modules
            delay_between_cycles: Delay in seconds between full cycles
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.delay_between_modules = delay_between_modules
        self.delay_between_cycles = delay_between_cycles

        # Core components
        self.state_manager = CycleStateManager(json_path=state_json_path)
        self.resource_manager = get_resource_manager()
        self.health_monitor = HealthMonitor(
            heartbeat_timeout_seconds=heartbeat_timeout
        )

        # Workers registry
        self._workers: Dict[str, BaseModuleWorker] = {}

        # State
        self._running = False
        self._stop_requested = False
        self._main_thread: Optional[threading.Thread] = None
        self._current_module: Optional[str] = None

        # Statistics
        self._started_at: Optional[datetime] = None
        self._cycles_completed: int = 0

        # Setup health monitor callbacks
        self.health_monitor.set_on_stuck_callback(self._handle_stuck_module)

        # Log file for orchestrator
        self._orchestrator_log = self.log_dir / "orchestrator.log"

    def register_worker(self, module_name: str, worker: BaseModuleWorker):
        """
        Register a worker for a module.

        Args:
            module_name: Module name (must be in MODULE_ORDER)
            worker: Worker instance
        """
        if module_name not in self.MODULE_ORDER:
            raise ValueError(f"Unknown module: {module_name}")

        self._workers[module_name] = worker
        self.health_monitor.register_module(module_name)

        # Set up worker callbacks
        worker.set_heartbeat_callback(
            lambda: self.health_monitor.record_heartbeat(module_name)
        )
        worker.set_progress_callback(
            lambda last_id, processed, errors: self.state_manager.update_module_progress(
                module_name,
                last_company_id=last_id,
                companies_processed=processed,
                errors=errors
            )
        )

        logger.info(f"Registered worker for module: {module_name}")

    def start(self):
        """Start the orchestrator in a background thread."""
        if self._running:
            logger.warning("Orchestrator already running")
            return

        self._running = True
        self._stop_requested = False
        self._started_at = datetime.now()

        # Start health monitoring
        self.health_monitor.start_monitoring()

        # Start main loop in background thread
        self._main_thread = threading.Thread(
            target=self._main_loop,
            daemon=True,
            name="SEOOrchestrator"
        )
        self._main_thread.start()

        logger.info("SEO Cycle Orchestrator started")
        self._log_to_file("=== Orchestrator started ===")

    def stop(self, timeout: float = 30.0):
        """
        Stop the orchestrator gracefully.

        Args:
            timeout: Max seconds to wait for shutdown
        """
        if not self._running:
            return

        logger.info("Stopping orchestrator...")
        self._log_to_file("Stop requested")
        self._stop_requested = True

        # Stop current worker if any
        if self._current_module and self._current_module in self._workers:
            self._workers[self._current_module].stop()

        # Wait for main thread
        if self._main_thread:
            self._main_thread.join(timeout=timeout)
            self._main_thread = None

        # Stop health monitoring
        self.health_monitor.stop_monitoring()

        # Cleanup resources
        self.resource_manager.cleanup_between_cycles()

        self._running = False
        logger.info("Orchestrator stopped")
        self._log_to_file("=== Orchestrator stopped ===")

    def _main_loop(self):
        """Main orchestration loop."""
        try:
            # Get or create cycle state
            state = self.state_manager.get_or_create_cycle()
            self._cycles_completed = state.cycle_count

            while not self._stop_requested:
                try:
                    # Run one full cycle
                    self._run_cycle()

                    if self._stop_requested:
                        break

                    # Delay between cycles
                    self._log_to_file(
                        f"Cycle complete. Waiting {self.delay_between_cycles}s before next cycle..."
                    )
                    self._interruptible_sleep(self.delay_between_cycles)

                except Exception as e:
                    logger.error(f"Error in cycle: {e}", exc_info=True)
                    self._log_to_file(f"[ERROR] Cycle error: {e}")

                    # Wait before retry
                    self._interruptible_sleep(60.0)

        except Exception as e:
            logger.error(f"Orchestrator crashed: {e}", exc_info=True)
            self._log_to_file(f"[CRASH] Orchestrator crashed: {e}")

        finally:
            self._running = False

    def _run_cycle(self):
        """Run one complete cycle through all modules (in parallel)."""
        self._log_to_file(f"=== Starting cycle {self._cycles_completed + 1} ===")
        self._log_to_file("Running all modules in PARALLEL")

        # Start all modules in parallel threads
        module_threads: Dict[str, threading.Thread] = {}
        module_stats: Dict[str, Any] = {}

        for module_name in self.MODULE_ORDER:
            if self._stop_requested:
                break

            # Check if worker is registered
            if module_name not in self._workers:
                logger.warning(f"No worker registered for {module_name}, skipping")
                self._log_to_file(f"[SKIP] No worker for {module_name}")
                continue

            # Create thread for each module
            thread = threading.Thread(
                target=self._run_module_parallel,
                args=(module_name, module_stats),
                daemon=True,
                name=f"Module-{module_name}"
            )
            module_threads[module_name] = thread
            self._log_to_file(f"--- Starting module: {module_name} ---")

        # Start all threads
        for module_name, thread in module_threads.items():
            thread.start()
            logger.info(f"Started module thread: {module_name}")

        # Wait for all threads to complete
        for module_name, thread in module_threads.items():
            while thread.is_alive() and not self._stop_requested:
                thread.join(timeout=1.0)

            if self._stop_requested and thread.is_alive():
                # Stop was requested, try to stop the worker
                if module_name in self._workers:
                    self._workers[module_name].stop()
                thread.join(timeout=5.0)

        # Cleanup between cycles
        if not self._stop_requested:
            self._cycles_completed += 1
            self.resource_manager.cleanup_between_cycles()
            self._log_to_file(f"=== Cycle {self._cycles_completed} complete ===")

    def _run_module_parallel(self, module_name: str, stats_dict: Dict[str, Any]):
        """Run a single module (called from parallel thread)."""
        worker = self._workers[module_name]

        logger.info(f"Running module: {module_name}")

        # Update state
        self.state_manager.update_module_progress(module_name, status="running")

        try:
            # Get resume point
            resume_from = self.state_manager.get_resume_point(module_name)

            # Run worker
            stats = worker.run(resume_from=resume_from)
            stats_dict[module_name] = stats

            # Mark complete or failed
            if stats.companies_failed > stats.companies_processed * 0.5:
                # More than 50% failed - mark as failed
                self.state_manager.update_module_progress(module_name, status="failed")
                self._log_to_file(
                    f"[FAIL] Module {module_name}: "
                    f"{stats.companies_failed}/{stats.companies_processed} failed"
                )
            else:
                self.state_manager.update_module_progress(module_name, status="completed")
                self._log_to_file(
                    f"[OK] Module {module_name}: "
                    f"{stats.companies_succeeded}/{stats.companies_processed} succeeded"
                )

        except Exception as e:
            logger.error(f"Module {module_name} crashed: {e}", exc_info=True)
            self.state_manager.update_module_progress(module_name, status="failed")
            self._log_to_file(f"[CRASH] Module {module_name}: {e}")

    def _run_module(self, module_name: str):
        """Run a single module."""
        worker = self._workers[module_name]

        self._log_to_file(f"--- Starting module: {module_name} ---")
        logger.info(f"Running module: {module_name}")

        # Update state
        self.state_manager.update_module_progress(module_name, status="running")

        try:
            # Get resume point
            resume_from = self.state_manager.get_resume_point(module_name)

            # Run worker
            stats = worker.run(resume_from=resume_from)

            # Mark complete or failed
            if stats.companies_failed > stats.companies_processed * 0.5:
                # More than 50% failed - mark as failed
                self.state_manager.update_module_progress(module_name, status="failed")
                self._log_to_file(
                    f"[FAIL] Module {module_name}: "
                    f"{stats.companies_failed}/{stats.companies_processed} failed"
                )
            else:
                self.state_manager.update_module_progress(module_name, status="completed")
                self._log_to_file(
                    f"[OK] Module {module_name}: "
                    f"{stats.companies_succeeded}/{stats.companies_processed} succeeded"
                )

        except Exception as e:
            logger.error(f"Module {module_name} crashed: {e}", exc_info=True)
            self.state_manager.update_module_progress(module_name, status="failed")
            self._log_to_file(f"[CRASH] Module {module_name}: {e}")

    def _handle_stuck_module(self, module_name: str):
        """Handle a stuck module."""
        logger.warning(f"Module {module_name} is stuck, attempting recovery")
        self._log_to_file(f"[STUCK] Module {module_name} detected as stuck")

        # Try to stop the stuck worker
        if module_name in self._workers:
            self._workers[module_name].stop()

    def _interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by stop request."""
        end_time = time.time() + seconds
        while time.time() < end_time and not self._stop_requested:
            time.sleep(min(1.0, end_time - time.time()))

    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """
        Get full orchestrator status for dashboard.

        Returns:
            Dict with orchestrator and module status
        """
        cycle_status = self.state_manager.get_status()
        health_status = self.health_monitor.get_all_health()

        uptime_seconds = 0
        if self._started_at:
            uptime_seconds = (datetime.now() - self._started_at).total_seconds()

        return {
            "running": self._running,
            "current_module": self._current_module,
            "cycles_completed": self._cycles_completed,
            "uptime_seconds": uptime_seconds,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "cycle": cycle_status,
            "health": health_status,
            "pool_status": self.resource_manager.get_pool_status(),
            "modules": {
                name: {
                    **cycle_status.get("modules", {}).get(name, {}),
                    **health_status.get(name, {}),
                    "log_file": self._workers[name].get_log_file() if name in self._workers else None
                }
                for name in self.MODULE_ORDER
            }
        }

    def get_logs(self, module: str, limit: int = 100) -> List[str]:
        """
        Get recent log lines for a module.

        Args:
            module: Module name ("orchestrator" for main log)
            limit: Max lines to return

        Returns:
            List of log lines
        """
        if module == "orchestrator":
            log_file = self._orchestrator_log
        elif module in self._workers:
            log_file = Path(self._workers[module].get_log_file())
        else:
            return []

        if not log_file.exists():
            return []

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                return [line.rstrip() for line in lines[-limit:]]
        except Exception:
            return []

    def _log_to_file(self, message: str):
        """Log message to orchestrator log file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self._orchestrator_log, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def clear_logs(self):
        """Clear all module log files."""
        # Clear orchestrator log
        try:
            with open(self._orchestrator_log, 'w') as f:
                f.write("")
        except Exception:
            pass

        # Clear worker logs
        for worker in self._workers.values():
            worker.clear_log()

    def reset_state(self):
        """Reset all state for fresh start."""
        if self._running:
            raise RuntimeError("Cannot reset state while running")

        self.state_manager.reset_state()
        self.health_monitor.reset_all()
        self.clear_logs()
        self._cycles_completed = 0

        logger.info("State reset complete")

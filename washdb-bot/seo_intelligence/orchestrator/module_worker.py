"""
Base Module Worker

Abstract base class for all SEO module workers.
Provides common functionality for processing companies and error isolation.
"""

import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

from runner.logging_setup import get_logger


@dataclass
class WorkerResult:
    """Result from processing a single company."""
    company_id: int
    success: bool
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class WorkerStats:
    """Statistics for a worker run."""
    companies_processed: int = 0
    companies_succeeded: int = 0
    companies_failed: int = 0
    total_duration_seconds: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BaseModuleWorker(ABC):
    """
    Abstract base class for SEO module workers.

    Provides:
    - Main processing loop with error isolation
    - Graceful shutdown handling
    - Progress tracking and logging
    - Heartbeat support
    """

    def __init__(
        self,
        name: str,
        log_dir: str = "logs/seo_modules",
        batch_size: int = 10,
        delay_between_companies: float = 1.0
    ):
        """
        Initialize module worker.

        Args:
            name: Worker name (e.g., "serp", "citations")
            log_dir: Directory for log files
            batch_size: Companies to process per batch
            delay_between_companies: Delay in seconds between companies
        """
        self.name = name
        self.log_dir = Path(log_dir)
        self.batch_size = batch_size
        self.delay_between_companies = delay_between_companies

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Log file for this module
        self.log_file = self.log_dir / f"{name}.log"

        # Logger
        self.logger = get_logger(f"Worker.{name}")

        # State
        self._running = False
        self._stop_requested = False
        self._current_company_id: Optional[int] = None
        self._stats = WorkerStats()

        # Heartbeat callback
        self._heartbeat_callback: Optional[Callable[[], None]] = None

        # Progress callback
        self._progress_callback: Optional[Callable[[int, int, int], None]] = None

    def set_heartbeat_callback(self, callback: Callable[[], None]):
        """Set callback to be called periodically for heartbeat."""
        self._heartbeat_callback = callback

    def set_progress_callback(self, callback: Callable[[int, int, int], None]):
        """
        Set callback for progress updates.

        Callback receives: (last_company_id, companies_processed, errors)
        """
        self._progress_callback = callback

    @abstractmethod
    def process_company(self, company_id: int) -> WorkerResult:
        """
        Process a single company.

        This method must be idempotent - safe to retry on failure.

        Args:
            company_id: Company ID to process

        Returns:
            WorkerResult with success/failure and details
        """
        pass

    @abstractmethod
    def get_companies_to_process(
        self,
        limit: int,
        after_id: Optional[int] = None
    ) -> List[int]:
        """
        Get list of company IDs to process.

        Args:
            limit: Maximum companies to return
            after_id: Only return companies with ID > after_id (for resume)

        Returns:
            List of company IDs
        """
        pass

    def get_verification_where_clause(self) -> str:
        """
        Get SQL WHERE clause for filtering companies by verification status.

        Returns companies that have either:
        - Verification status = 'passed'
        - Human label = 'provider'

        Returns:
            SQL WHERE clause string (can be used with AND in queries)
        """
        return (
            "(parse_metadata->'verification'->>'status' = 'passed' OR "
            "parse_metadata->'verification'->>'human_label' = 'provider')"
        )

    def run(self, resume_from: Optional[int] = None) -> WorkerStats:
        """
        Run the worker, processing all companies.

        Args:
            resume_from: Company ID to resume from (exclusive)

        Returns:
            WorkerStats with run statistics
        """
        self._running = True
        self._stop_requested = False
        self._stats = WorkerStats(started_at=datetime.now())

        self.logger.info(f"Starting {self.name} worker (resume_from={resume_from})")
        self._log_to_file(f"=== Starting {self.name} worker ===")

        last_id = resume_from

        try:
            while not self._stop_requested:
                # Get next batch of companies
                companies = self.get_companies_to_process(
                    limit=self.batch_size,
                    after_id=last_id
                )

                if not companies:
                    self.logger.info(f"No more companies to process for {self.name}")
                    self._log_to_file("No more companies to process")
                    break

                # Process each company
                for company_id in companies:
                    if self._stop_requested:
                        self.logger.info(f"Stop requested, halting {self.name}")
                        self._log_to_file("Stop requested, halting")
                        break

                    self._current_company_id = company_id
                    start_time = time.time()

                    try:
                        # Send heartbeat
                        if self._heartbeat_callback:
                            self._heartbeat_callback()

                        # Process company
                        result = self.process_company(company_id)
                        result.duration_seconds = time.time() - start_time

                        # Update stats
                        self._stats.companies_processed += 1
                        if result.success:
                            self._stats.companies_succeeded += 1
                            self._log_to_file(
                                f"[OK] Company {company_id}: {result.message} "
                                f"({result.duration_seconds:.1f}s)"
                            )
                        else:
                            self._stats.companies_failed += 1
                            self._log_to_file(
                                f"[FAIL] Company {company_id}: {result.error or result.message} "
                                f"({result.duration_seconds:.1f}s)"
                            )

                        # Update last processed ID
                        last_id = company_id

                        # Report progress
                        if self._progress_callback:
                            self._progress_callback(
                                last_id,
                                self._stats.companies_processed,
                                self._stats.companies_failed
                            )

                    except Exception as e:
                        # Error isolation - log and continue to next company
                        self._stats.companies_processed += 1
                        self._stats.companies_failed += 1
                        self.logger.error(
                            f"Unhandled error processing company {company_id}: {e}",
                            exc_info=True
                        )
                        self._log_to_file(f"[ERROR] Company {company_id}: {e}")

                        last_id = company_id

                        if self._progress_callback:
                            self._progress_callback(
                                last_id,
                                self._stats.companies_processed,
                                self._stats.companies_failed
                            )

                    # Delay between companies
                    if not self._stop_requested and self.delay_between_companies > 0:
                        time.sleep(self.delay_between_companies)

        except Exception as e:
            self.logger.error(f"Worker {self.name} crashed: {e}", exc_info=True)
            self._log_to_file(f"[CRASH] Worker crashed: {e}")

        finally:
            self._running = False
            self._current_company_id = None
            self._stats.completed_at = datetime.now()

            if self._stats.started_at:
                self._stats.total_duration_seconds = (
                    self._stats.completed_at - self._stats.started_at
                ).total_seconds()

            self.logger.info(
                f"Worker {self.name} finished: "
                f"{self._stats.companies_succeeded}/{self._stats.companies_processed} succeeded, "
                f"{self._stats.companies_failed} failed"
            )
            self._log_to_file(
                f"=== Finished: {self._stats.companies_succeeded}/{self._stats.companies_processed} "
                f"succeeded, {self._stats.companies_failed} failed ==="
            )

        return self._stats

    def stop(self):
        """Request graceful shutdown."""
        self.logger.info(f"Stop requested for {self.name}")
        self._stop_requested = True

    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running

    def get_current_company_id(self) -> Optional[int]:
        """Get the company ID currently being processed."""
        return self._current_company_id

    def get_stats(self) -> Dict[str, Any]:
        """Get current worker statistics."""
        return {
            "name": self.name,
            "running": self._running,
            "current_company_id": self._current_company_id,
            "companies_processed": self._stats.companies_processed,
            "companies_succeeded": self._stats.companies_succeeded,
            "companies_failed": self._stats.companies_failed,
            "started_at": self._stats.started_at.isoformat() if self._stats.started_at else None,
            "completed_at": self._stats.completed_at.isoformat() if self._stats.completed_at else None,
            "total_duration_seconds": self._stats.total_duration_seconds
        }

    def _log_to_file(self, message: str):
        """Log message to module-specific log file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def get_log_file(self) -> str:
        """Get path to this worker's log file."""
        return str(self.log_file)

    def clear_log(self):
        """Clear the log file."""
        try:
            with open(self.log_file, 'w') as f:
                f.write("")
        except Exception:
            pass

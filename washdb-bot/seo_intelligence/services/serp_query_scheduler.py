"""
SERP Query Scheduler

Manages a queue of SERP queries and executes them slowly over time.
This is designed to run 24/7 and process queries at a human-like pace.

Key features:
1. Priority queue - urgent queries processed first
2. Geographic batching - group queries by location for efficiency
3. Smart rate limiting - adapts to session health
4. Retry logic - failed queries get retried with backoff
5. Result callbacks - notify when results are ready

Architecture:
    ┌─────────────────────────────────────────────────┐
    │           Query Queue (Priority)                │
    │  [urgent] [high] [normal] [low] [background]   │
    └─────────────────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────┐
    │           Scheduler Loop (Background)           │
    │  - Picks next query based on priority          │
    │  - Waits for rate limit window                 │
    │  - Gets available session                      │
    │  - Executes search                             │
    │  - Stores result / triggers callback           │
    └─────────────────────────────────────────────────┘

Usage:
    scheduler = SerpQueryScheduler()
    scheduler.start()

    # Queue a query
    job_id = scheduler.queue_query(
        query="pressure washing near me",
        location="Boston, MA",
        priority="normal",
        callback=my_callback_function,
    )

    # Check status
    status = scheduler.get_job_status(job_id)

    # Get result (blocking)
    result = scheduler.wait_for_result(job_id, timeout=3600)
"""

import os
import json
import time
import uuid
import heapq
import random
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger
from seo_intelligence.services.serp_session_pool import get_serp_session_pool

load_dotenv()

logger = get_logger("serp_query_scheduler")


class QueryPriority(Enum):
    """Priority levels for SERP queries."""
    URGENT = 0      # Process ASAP (within rate limits)
    HIGH = 1        # Process soon
    NORMAL = 2      # Standard processing
    LOW = 3         # Process when idle
    BACKGROUND = 4  # Only when nothing else to do


class JobStatus(Enum):
    """Status of a queued job."""
    QUEUED = "queued"
    WAITING = "waiting"       # Waiting for rate limit
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class SerpJob:
    """A single SERP query job."""
    job_id: str
    query: str
    location: Optional[str] = None
    priority: QueryPriority = QueryPriority.NORMAL
    callback: Optional[Callable] = None
    company_id: Optional[int] = None

    # State
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    result: Optional[dict] = None
    error: Optional[str] = None

    # Retry tracking
    attempts: int = 0
    max_attempts: int = 3
    next_retry_at: Optional[datetime] = None

    def __lt__(self, other):
        """For priority queue ordering."""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.created_at < other.created_at

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "query": self.query,
            "location": self.location,
            "priority": self.priority.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "attempts": self.attempts,
            "error": self.error,
        }


@dataclass
class SchedulerConfig:
    """Configuration for the query scheduler."""

    # Rate limiting (queries per hour)
    max_queries_per_hour: int = 20
    min_delay_between_queries_sec: int = 180  # 3 minutes minimum
    max_delay_between_queries_sec: int = 600  # 10 minutes maximum

    # Retry settings
    max_retries: int = 3
    retry_backoff_base_sec: int = 300  # 5 minutes
    retry_backoff_multiplier: float = 2.0

    # Queue settings
    max_queue_size: int = 1000
    persist_queue: bool = True
    queue_file: str = "data/serp_sessions/query_queue.json"

    # Processing settings
    batch_by_location: bool = True
    max_batch_size: int = 5


class SerpQueryScheduler:
    """
    Scheduler for SERP queries.

    Manages a queue and processes queries at a sustainable rate.
    """

    def __init__(self, config: SchedulerConfig = None):
        self.config = config or SchedulerConfig()

        # Job storage
        self._queue: List[SerpJob] = []  # Priority heap
        self._jobs: Dict[str, SerpJob] = {}  # job_id -> job
        self._completed_jobs: Dict[str, SerpJob] = {}  # Recent completed jobs

        # Threading
        self._lock = threading.Lock()
        self._result_events: Dict[str, threading.Event] = {}
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False

        # Rate limiting
        self._queries_this_hour: int = 0
        self._hour_start: datetime = datetime.now()
        self._last_query_at: Optional[datetime] = None

        # Session pool reference
        self._session_pool = None

        # Load persisted queue
        if self.config.persist_queue:
            self._load_queue()

    def _load_queue(self):
        """Load queued jobs from disk."""
        queue_file = Path(self.config.queue_file)
        if queue_file.exists():
            try:
                with open(queue_file) as f:
                    data = json.load(f)

                for job_data in data.get("jobs", []):
                    job = SerpJob(
                        job_id=job_data["job_id"],
                        query=job_data["query"],
                        location=job_data.get("location"),
                        priority=QueryPriority[job_data.get("priority", "NORMAL")],
                        company_id=job_data.get("company_id"),
                    )
                    self._jobs[job.job_id] = job
                    heapq.heappush(self._queue, job)

                logger.info(f"Loaded {len(self._jobs)} queued jobs from disk")
            except Exception as e:
                logger.error(f"Failed to load queue: {e}")

    def _save_queue(self):
        """Save queued jobs to disk."""
        if not self.config.persist_queue:
            return

        queue_file = Path(self.config.queue_file)
        queue_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            jobs_data = [
                {
                    "job_id": job.job_id,
                    "query": job.query,
                    "location": job.location,
                    "priority": job.priority.name,
                    "company_id": job.company_id,
                }
                for job in self._jobs.values()
                if job.status in (JobStatus.QUEUED, JobStatus.WAITING, JobStatus.RETRYING)
            ]

            with open(queue_file, "w") as f:
                json.dump({"jobs": jobs_data, "saved_at": datetime.now().isoformat()}, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save queue: {e}")

    def start(self, proxy_list: List[str] = None):
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting SERP query scheduler")

        # Store proxy list for initialization in scheduler thread
        # NOTE: Session pool must be initialized in the scheduler thread
        # because Playwright requires all browser ops in the same thread
        self._proxy_list = proxy_list

        # Start scheduler thread (session pool initialized there)
        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

        logger.info("SERP query scheduler started")

    def stop(self):
        """Stop the scheduler gracefully."""
        logger.info("Stopping SERP query scheduler")
        self._running = False

        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=30)

        self._save_queue()
        logger.info("SERP query scheduler stopped")

    def queue_query(
        self,
        query: str,
        location: str = None,
        priority: str = "normal",
        callback: Callable = None,
        company_id: int = None,
    ) -> str:
        """
        Queue a SERP query for processing.

        Args:
            query: Search query
            location: Geographic location
            priority: Priority level (urgent, high, normal, low, background)
            callback: Function to call when result is ready
            company_id: Associated company ID

        Returns:
            Job ID for tracking
        """
        job_id = str(uuid.uuid4())[:8]

        # Parse priority
        try:
            priority_enum = QueryPriority[priority.upper()]
        except KeyError:
            priority_enum = QueryPriority.NORMAL

        job = SerpJob(
            job_id=job_id,
            query=query,
            location=location,
            priority=priority_enum,
            callback=callback,
            company_id=company_id,
        )

        with self._lock:
            if len(self._jobs) >= self.config.max_queue_size:
                raise ValueError(f"Queue full (max {self.config.max_queue_size} jobs)")

            self._jobs[job_id] = job
            heapq.heappush(self._queue, job)
            self._result_events[job_id] = threading.Event()

        self._save_queue()
        logger.info(f"Queued job {job_id}: '{query[:30]}...' (priority: {priority})")

        return job_id

    def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get status of a job."""
        job = self._jobs.get(job_id) or self._completed_jobs.get(job_id)
        if job:
            return job.to_dict()
        return None

    def get_job_result(self, job_id: str) -> Optional[dict]:
        """Get result of a completed job."""
        job = self._completed_jobs.get(job_id)
        if job and job.status == JobStatus.COMPLETED:
            return job.result
        return None

    def wait_for_result(self, job_id: str, timeout: float = 3600) -> Optional[dict]:
        """
        Wait for a job to complete and return the result.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum seconds to wait

        Returns:
            SERP results or None if failed/timeout
        """
        event = self._result_events.get(job_id)
        if not event:
            return self.get_job_result(job_id)

        event.wait(timeout=timeout)
        return self.get_job_result(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == JobStatus.QUEUED:
                job.status = JobStatus.FAILED
                job.error = "Cancelled"
                self._complete_job(job)
                return True
        return False

    def get_queue_stats(self) -> dict:
        """Get statistics about the queue."""
        with self._lock:
            queued = sum(1 for j in self._jobs.values() if j.status == JobStatus.QUEUED)
            processing = sum(1 for j in self._jobs.values() if j.status == JobStatus.PROCESSING)
            waiting = sum(1 for j in self._jobs.values() if j.status == JobStatus.WAITING)

            return {
                "queued": queued,
                "processing": processing,
                "waiting": waiting,
                "completed_recently": len(self._completed_jobs),
                "queries_this_hour": self._queries_this_hour,
                "max_queries_per_hour": self.config.max_queries_per_hour,
                "next_query_available_in_sec": self._time_until_next_query(),
            }

    def _time_until_next_query(self) -> int:
        """Calculate seconds until next query is allowed."""
        if not self._last_query_at:
            return 0

        elapsed = (datetime.now() - self._last_query_at).total_seconds()
        remaining = self.config.min_delay_between_queries_sec - elapsed
        return max(0, int(remaining))

    def _can_query_now(self) -> bool:
        """Check if we can execute a query now."""
        # Check hourly limit
        now = datetime.now()
        if (now - self._hour_start).total_seconds() >= 3600:
            self._hour_start = now
            self._queries_this_hour = 0

        if self._queries_this_hour >= self.config.max_queries_per_hour:
            return False

        # Check minimum delay
        if self._last_query_at:
            elapsed = (now - self._last_query_at).total_seconds()
            if elapsed < self.config.min_delay_between_queries_sec:
                return False

        return True

    def _get_next_job(self) -> Optional[SerpJob]:
        """Get the next job to process."""
        with self._lock:
            # First check for retry jobs that are ready
            for job in self._jobs.values():
                if job.status == JobStatus.RETRYING:
                    if job.next_retry_at and datetime.now() >= job.next_retry_at:
                        job.status = JobStatus.QUEUED
                        heapq.heappush(self._queue, job)

            # Get highest priority queued job
            while self._queue:
                job = heapq.heappop(self._queue)
                if job.status == JobStatus.QUEUED:
                    return job

            return None

    def _process_job(self, job: SerpJob):
        """Process a single job."""
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now()
        job.attempts += 1

        logger.info(f"Processing job {job.job_id}: '{job.query[:30]}...' (attempt {job.attempts})")

        try:
            # Execute search through session pool
            result = self._session_pool.search(
                query=job.query,
                location=job.location,
                use_cache=True,
            )

            if result:
                job.status = JobStatus.COMPLETED
                job.result = result
                job.completed_at = datetime.now()

                logger.info(f"Job {job.job_id} completed: {len(result.get('organic_results', []))} organic results")

                # Trigger callback
                if job.callback:
                    try:
                        job.callback(job.job_id, result)
                    except Exception as e:
                        logger.error(f"Callback error for job {job.job_id}: {e}")
            else:
                raise Exception("No results returned")

        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")

            if job.attempts < job.max_attempts:
                # Schedule retry with exponential backoff
                backoff = self.config.retry_backoff_base_sec * (
                    self.config.retry_backoff_multiplier ** (job.attempts - 1)
                )
                job.status = JobStatus.RETRYING
                job.next_retry_at = datetime.now() + timedelta(seconds=backoff)
                job.error = str(e)

                logger.info(f"Job {job.job_id} will retry in {backoff:.0f} seconds")
            else:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = datetime.now()

                logger.error(f"Job {job.job_id} failed permanently after {job.attempts} attempts")

        # Complete the job
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            self._complete_job(job)

        # Update rate limiting
        self._last_query_at = datetime.now()
        self._queries_this_hour += 1

    def _complete_job(self, job: SerpJob):
        """Mark a job as complete and clean up."""
        with self._lock:
            # Move to completed
            if job.job_id in self._jobs:
                del self._jobs[job.job_id]
            self._completed_jobs[job.job_id] = job

            # Signal waiters
            event = self._result_events.get(job.job_id)
            if event:
                event.set()

            # Limit completed jobs memory
            if len(self._completed_jobs) > 1000:
                # Remove oldest completed jobs
                oldest = sorted(
                    self._completed_jobs.values(),
                    key=lambda j: j.completed_at or datetime.min
                )[:500]
                for j in oldest:
                    del self._completed_jobs[j.job_id]
                    if j.job_id in self._result_events:
                        del self._result_events[j.job_id]

        self._save_queue()

    def _scheduler_loop(self):
        """Main scheduler loop.

        NOTE: Session pool is initialized here (not in start()) because
        Playwright requires all browser operations to happen in the same thread.
        """
        # Initialize session pool in this thread
        logger.info("Initializing session pool in scheduler thread...")
        self._session_pool = get_serp_session_pool(
            num_sessions=1,  # Single session to avoid Playwright asyncio conflicts
            proxy_list=getattr(self, '_proxy_list', None),
        )
        logger.info("Session pool initialized")

        logger.info("Scheduler loop started")

        while self._running:
            try:
                # Wait until we can query
                while self._running and not self._can_query_now():
                    time.sleep(10)

                if not self._running:
                    break

                # Get next job
                job = self._get_next_job()

                if job:
                    self._process_job(job)

                    # Random delay for human-like behavior
                    delay = random.uniform(
                        self.config.min_delay_between_queries_sec,
                        self.config.max_delay_between_queries_sec,
                    )
                    logger.debug(f"Waiting {delay:.0f}s before next query")
                    time.sleep(delay)
                else:
                    # No jobs, wait a bit
                    time.sleep(30)

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                time.sleep(60)

        logger.info("Scheduler loop stopped")


# Singleton instance
_scheduler_instance: Optional[SerpQueryScheduler] = None
_scheduler_lock = threading.Lock()


def get_serp_scheduler(config: SchedulerConfig = None) -> SerpQueryScheduler:
    """Get or create the global SERP query scheduler."""
    global _scheduler_instance

    with _scheduler_lock:
        if _scheduler_instance is None:
            _scheduler_instance = SerpQueryScheduler(config)
        return _scheduler_instance


def start_serp_scheduler(proxy_list: List[str] = None):
    """Start the global SERP query scheduler."""
    scheduler = get_serp_scheduler()
    scheduler.start(proxy_list)
    return scheduler


def stop_serp_scheduler():
    """Stop the global SERP query scheduler."""
    global _scheduler_instance

    with _scheduler_lock:
        if _scheduler_instance:
            _scheduler_instance.stop()
            _scheduler_instance = None

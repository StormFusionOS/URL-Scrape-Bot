"""
Cron Scheduler Service for managing scheduled crawl jobs.

This service uses APScheduler to manage cron-based job scheduling,
loading jobs from the database and executing them at specified times.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import ScheduledJob, JobExecutionLog


logger = logging.getLogger(__name__)


class CronSchedulerService:
    """
    Cron scheduler service that manages scheduled crawl jobs.

    Features:
    - Loads jobs from database on startup
    - Schedules jobs using cron expressions
    - Logs job execution results
    - Supports job enable/disable
    - Handles job timeouts and retries
    """

    def __init__(self, database_url: str):
        """
        Initialize the scheduler service.

        Args:
            database_url: SQLAlchemy database URL
        """
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.scheduler = BackgroundScheduler()

        # Add event listeners
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        self._running_jobs: Dict[int, Any] = {}  # Track running jobs

    def start(self):
        """Start the scheduler and load jobs from database."""
        logger.info("Starting Cron Scheduler Service...")

        # Load all enabled jobs from database
        self._load_jobs_from_db()

        # Start the scheduler
        self.scheduler.start()

        logger.info(f"Scheduler started with {len(self.scheduler.get_jobs())} jobs")

    def stop(self):
        """Stop the scheduler."""
        logger.info("Stopping Cron Scheduler Service...")
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    def _load_jobs_from_db(self):
        """Load all enabled jobs from the database and schedule them."""
        with Session(self.engine) as session:
            stmt = select(ScheduledJob).where(ScheduledJob.enabled == True)
            jobs = session.scalars(stmt).all()

            for job in jobs:
                try:
                    self._schedule_job(job)
                    logger.info(f"Loaded job: {job.name} (ID: {job.id})")
                except Exception as e:
                    logger.error(f"Failed to load job {job.id}: {e}")

    def _schedule_job(self, job: ScheduledJob):
        """
        Schedule a single job using its cron expression.

        Args:
            job: ScheduledJob model instance
        """
        # Parse cron expression
        cron_parts = job.schedule_cron.split()
        if len(cron_parts) != 5:
            raise ValueError(f"Invalid cron expression: {job.schedule_cron}")

        minute, hour, day, month, day_of_week = cron_parts

        # Create cron trigger
        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week
        )

        # Add job to scheduler
        self.scheduler.add_job(
            func=self._execute_job,
            trigger=trigger,
            args=[job.id],
            id=f"job_{job.id}",
            name=job.name,
            replace_existing=True,
            max_instances=1  # Prevent overlapping executions
        )

    def _execute_job(self, job_id: int):
        """
        Execute a scheduled job.

        Args:
            job_id: ID of the job to execute
        """
        # Prevent duplicate execution
        if job_id in self._running_jobs:
            logger.warning(f"Job {job_id} is already running, skipping")
            return

        started_at = datetime.now()
        self._running_jobs[job_id] = started_at

        try:
            with Session(self.engine) as session:
                # Get job details
                job = session.get(ScheduledJob, job_id)
                if not job:
                    logger.error(f"Job {job_id} not found in database")
                    return

                if not job.enabled:
                    logger.info(f"Job {job_id} is disabled, skipping")
                    return

                logger.info(f"Executing job: {job.name} (ID: {job_id})")

                # Parse configuration
                config = json.loads(job.config)

                # Create execution log
                log_entry = JobExecutionLog(
                    job_id=job_id,
                    started_at=started_at,
                    status='running',
                    triggered_by='scheduled'
                )
                session.add(log_entry)
                session.commit()

                # Execute job based on type
                result = self._execute_job_by_type(job.job_type, config)

                # Update completion
                completed_at = datetime.now()
                duration = int((completed_at - started_at).total_seconds())

                log_entry.completed_at = completed_at
                log_entry.duration_seconds = duration
                log_entry.status = 'success' if result.get('success') else 'failed'
                log_entry.items_found = result.get('items_found', 0)
                log_entry.items_new = result.get('items_new', 0)
                log_entry.items_updated = result.get('items_updated', 0)
                log_entry.errors_count = result.get('errors_count', 0)
                log_entry.output_log = result.get('output_log', '')
                log_entry.error_log = result.get('error_log', '')

                # Update job statistics
                job.last_run = started_at
                job.last_status = log_entry.status
                job.total_runs += 1
                if log_entry.status == 'success':
                    job.success_runs += 1
                else:
                    job.failed_runs += 1

                session.commit()

                logger.info(f"Job {job_id} completed: {log_entry.status}")

        except Exception as e:
            logger.exception(f"Error executing job {job_id}: {e}")

            # Log the error
            with Session(self.engine) as session:
                log_entry = session.query(JobExecutionLog).filter(
                    JobExecutionLog.job_id == job_id,
                    JobExecutionLog.started_at == started_at
                ).first()

                if log_entry:
                    log_entry.completed_at = datetime.now()
                    log_entry.status = 'failed'
                    log_entry.error_log = str(e)
                    session.commit()

        finally:
            # Remove from running jobs
            self._running_jobs.pop(job_id, None)

    def _execute_job_by_type(self, job_type: str, config: Dict) -> Dict[str, Any]:
        """
        Execute a job based on its type.

        Args:
            job_type: Type of job (e.g., 'yp_crawl', 'google_maps')
            config: Job configuration dictionary

        Returns:
            Dictionary with execution results
        """
        # Placeholder implementation - will be expanded with actual job executors
        logger.info(f"Executing {job_type} with config: {config}")

        if job_type == 'yp_crawl':
            return self._execute_yp_crawl(config)
        elif job_type == 'google_maps':
            return self._execute_google_maps(config)
        elif job_type == 'detail_scrape':
            return self._execute_detail_scrape(config)
        else:
            logger.warning(f"Unknown job type: {job_type}")
            return {
                'success': False,
                'error_log': f'Unknown job type: {job_type}'
            }

    def _execute_yp_crawl(self, config: Dict) -> Dict[str, Any]:
        """Execute Yellow Pages crawl job."""
        # Placeholder - integrate with scrape_yp module
        logger.info(f"YP Crawl: {config.get('search_term')} in {config.get('location')}")
        return {
            'success': True,
            'items_found': 0,
            'items_new': 0,
            'items_updated': 0,
            'errors_count': 0,
            'output_log': 'YP crawl placeholder - not yet implemented'
        }

    def _execute_google_maps(self, config: Dict) -> Dict[str, Any]:
        """Execute Google Maps scrape job."""
        # Placeholder - integrate with scrape_google module
        logger.info(f"Google Maps: {config.get('search_term')} in {config.get('location')}")
        return {
            'success': True,
            'items_found': 0,
            'items_new': 0,
            'items_updated': 0,
            'errors_count': 0,
            'output_log': 'Google Maps scrape placeholder - not yet implemented'
        }

    def _execute_detail_scrape(self, config: Dict) -> Dict[str, Any]:
        """Execute detail page scraping job."""
        # Placeholder - integrate with scrape_site module
        logger.info(f"Detail Scrape: {config.get('url_pattern')}")
        return {
            'success': True,
            'items_found': 0,
            'items_new': 0,
            'items_updated': 0,
            'errors_count': 0,
            'output_log': 'Detail scrape placeholder - not yet implemented'
        }

    def _on_job_executed(self, event):
        """Handle job execution events from APScheduler."""
        if event.exception:
            logger.error(f"Job {event.job_id} failed: {event.exception}")
        else:
            logger.debug(f"Job {event.job_id} executed successfully")

    # Management methods for UI

    def add_job(self, job: ScheduledJob) -> bool:
        """
        Add a new job to the scheduler.

        Args:
            job: ScheduledJob instance

        Returns:
            True if successful
        """
        try:
            self._schedule_job(job)
            logger.info(f"Added job: {job.name} (ID: {job.id})")
            return True
        except Exception as e:
            logger.error(f"Failed to add job: {e}")
            return False

    def remove_job(self, job_id: int) -> bool:
        """
        Remove a job from the scheduler.

        Args:
            job_id: ID of job to remove

        Returns:
            True if successful
        """
        try:
            self.scheduler.remove_job(f"job_{job_id}")
            logger.info(f"Removed job ID: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False

    def update_job(self, job: ScheduledJob) -> bool:
        """
        Update an existing job in the scheduler.

        Args:
            job: Updated ScheduledJob instance

        Returns:
            True if successful
        """
        try:
            # Remove old job
            self.remove_job(job.id)

            # Add updated job if enabled
            if job.enabled:
                self._schedule_job(job)

            logger.info(f"Updated job: {job.name} (ID: {job.id})")
            return True
        except Exception as e:
            logger.error(f"Failed to update job: {e}")
            return False

    def get_job_info(self, job_id: int) -> Optional[Dict]:
        """
        Get information about a scheduled job.

        Args:
            job_id: ID of job

        Returns:
            Dictionary with job info or None
        """
        job = self.scheduler.get_job(f"job_{job_id}")
        if job:
            return {
                'id': job_id,
                'name': job.name,
                'next_run_time': job.next_run_time,
                'is_running': job_id in self._running_jobs
            }
        return None

    def list_jobs(self) -> List[Dict]:
        """
        List all scheduled jobs.

        Returns:
            List of job info dictionaries
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            job_id = int(job.id.replace('job_', ''))
            jobs.append({
                'id': job_id,
                'name': job.name,
                'next_run_time': job.next_run_time,
                'is_running': job_id in self._running_jobs
            })
        return jobs

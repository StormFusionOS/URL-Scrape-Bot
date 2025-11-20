"""
Task logging infrastructure for governance and accountability.

Every scraping/analysis job must write to task_logs table with execution details.
"""
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import TaskLog

# Load environment
load_dotenv()


class TaskLoggerService:
    """
    Service for logging task executions to task_logs table.

    Usage:
        with task_logger.log_task("serp_scraper", "serp") as log_id:
            # Do work
            task_logger.update_progress(log_id, items_processed=10, items_new=5)
        # Task automatically marked as success on context exit

        # Or manually manage:
        log_id = task_logger.start_task("competitor_crawler", "competitor")
        try:
            # Do work
            task_logger.complete_task(log_id, "success", items_processed=100)
        except Exception as e:
            task_logger.complete_task(log_id, "failed", message=str(e))
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize task logger.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def start_task(
        self,
        task_name: str,
        module: str,
        status: str = "running"
    ) -> int:
        """
        Start a new task and return its log ID.

        Args:
            task_name: Name of the task (e.g., 'serp_scraper', 'competitor_crawler')
            module: Module name (e.g., 'serp', 'competitor', 'backlinks')
            status: Initial status (default: 'running')

        Returns:
            Task log ID
        """
        with self.SessionLocal() as session:
            log = TaskLog(
                task_name=task_name,
                module=module,
                started_at=datetime.utcnow(),
                status=status,
                items_processed=0,
                items_new=0,
                items_updated=0,
                items_failed=0
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log.id

    def update_progress(
        self,
        log_id: int,
        items_processed: Optional[int] = None,
        items_new: Optional[int] = None,
        items_updated: Optional[int] = None,
        items_failed: Optional[int] = None,
        message: Optional[str] = None
    ):
        """
        Update task progress.

        Args:
            log_id: Task log ID
            items_processed: Number of items processed (optional)
            items_new: Number of new items (optional)
            items_updated: Number of updated items (optional)
            items_failed: Number of failed items (optional)
            message: Status message (optional)
        """
        with self.SessionLocal() as session:
            log = session.query(TaskLog).filter(TaskLog.id == log_id).first()
            if not log:
                raise ValueError(f"Task log {log_id} not found")

            if items_processed is not None:
                log.items_processed = items_processed
            if items_new is not None:
                log.items_new = items_new
            if items_updated is not None:
                log.items_updated = items_updated
            if items_failed is not None:
                log.items_failed = items_failed
            if message is not None:
                log.message = message

            session.commit()

    def complete_task(
        self,
        log_id: int,
        status: str,
        message: Optional[str] = None,
        items_processed: Optional[int] = None,
        items_new: Optional[int] = None,
        items_updated: Optional[int] = None,
        items_failed: Optional[int] = None
    ):
        """
        Mark task as complete.

        Args:
            log_id: Task log ID
            status: Final status ('success', 'failed', 'partial', 'timeout')
            message: Summary message or error details (optional)
            items_processed: Final count of items processed (optional)
            items_new: Final count of new items (optional)
            items_updated: Final count of updated items (optional)
            items_failed: Final count of failed items (optional)
        """
        with self.SessionLocal() as session:
            log = session.query(TaskLog).filter(TaskLog.id == log_id).first()
            if not log:
                raise ValueError(f"Task log {log_id} not found")

            log.completed_at = datetime.utcnow()
            log.status = status

            if message is not None:
                log.message = message
            if items_processed is not None:
                log.items_processed = items_processed
            if items_new is not None:
                log.items_new = items_new
            if items_updated is not None:
                log.items_updated = items_updated
            if items_failed is not None:
                log.items_failed = items_failed

            session.commit()

    @contextmanager
    def log_task(self, task_name: str, module: str):
        """
        Context manager for automatic task logging.

        Usage:
            with task_logger.log_task("serp_scraper", "serp") as log_id:
                # Do work
                # Automatically marked as success on exit

        Args:
            task_name: Name of the task
            module: Module name

        Yields:
            Task log ID
        """
        log_id = self.start_task(task_name, module)
        try:
            yield log_id
            self.complete_task(log_id, "success")
        except Exception as e:
            self.complete_task(
                log_id,
                "failed",
                message=f"Error: {str(e)}"
            )
            raise


# Global task logger instance
task_logger = TaskLoggerService()


# Convenience functions
def start_task(task_name: str, module: str) -> int:
    """Start a new task and return its log ID."""
    return task_logger.start_task(task_name, module)


def update_progress(
    log_id: int,
    items_processed: Optional[int] = None,
    items_new: Optional[int] = None,
    items_updated: Optional[int] = None,
    items_failed: Optional[int] = None,
    message: Optional[str] = None
):
    """Update task progress."""
    task_logger.update_progress(
        log_id,
        items_processed=items_processed,
        items_new=items_new,
        items_updated=items_updated,
        items_failed=items_failed,
        message=message
    )


def complete_task(
    log_id: int,
    status: str,
    message: Optional[str] = None,
    items_processed: Optional[int] = None,
    items_new: Optional[int] = None,
    items_updated: Optional[int] = None,
    items_failed: Optional[int] = None
):
    """Mark task as complete."""
    task_logger.complete_task(
        log_id,
        status,
        message=message,
        items_processed=items_processed,
        items_new=items_new,
        items_updated=items_updated,
        items_failed=items_failed
    )


def log_task(task_name: str, module: str):
    """
    Context manager for automatic task logging.

    Usage:
        with log_task("serp_scraper", "serp") as log_id:
            # Do work
    """
    return task_logger.log_task(task_name, module)

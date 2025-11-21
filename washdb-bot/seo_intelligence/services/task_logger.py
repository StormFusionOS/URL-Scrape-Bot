"""
Task Logger Service

Provides execution tracking and governance for all SEO intelligence tasks.

Features:
- Automatic task timing and status tracking
- Metrics collection (records processed/created/updated)
- Error logging and stack traces
- Metadata support for task parameters
- Context manager for automatic task lifecycle management

All task executions are logged to the task_logs table for audit trail.
"""

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

# Initialize logger
logger = get_logger("task_logger")


class TaskLogger:
    """
    Service for logging and tracking task execution.

    Usage:
        task_logger = TaskLogger()

        # Manual usage:
        task_id = task_logger.start_task("serp_scraper", metadata={"query": "test"})
        # ... do work ...
        task_logger.complete_task(task_id, status="success", records_processed=100)

        # Context manager usage (recommended):
        with task_logger.log_task("serp_scraper", metadata={"query": "test"}) as task:
            # ... do work ...
            task.increment_processed(10)
            task.increment_created(5)
    """

    def __init__(self):
        """Initialize the task logger with database connection."""
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            raise RuntimeError("DATABASE_URL not set in environment")

        self.engine = create_engine(database_url, echo=False)
        logger.info("TaskLogger initialized")

    def start_task(
        self,
        task_name: str,
        task_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Start a new task and return its ID.

        Args:
            task_name: Name of the task (e.g., "serp_scraper")
            task_type: Type category (e.g., "scraper", "analyzer", "audit")
            metadata: Additional metadata (parameters, configuration, etc.)

        Returns:
            int: Task ID for tracking
        """
        with Session(self.engine) as session:
            try:
                # Insert task log record
                stmt = text("""
                    INSERT INTO task_logs (
                        task_name,
                        task_type,
                        status,
                        started_at,
                        metadata
                    ) VALUES (
                        :task_name,
                        :task_type,
                        'running',
                        NOW(),
                        :metadata::jsonb
                    ) RETURNING task_id
                """)

                import json
                result = session.execute(
                    stmt,
                    {
                        "task_name": task_name,
                        "task_type": task_type,
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )

                task_id = result.scalar_one()
                session.commit()

                logger.info(f"Started task {task_id}: {task_name}")
                return task_id

            except Exception as e:
                session.rollback()
                logger.error(f"Error starting task {task_name}: {e}", exc_info=True)
                raise

    def update_task(
        self,
        task_id: int,
        status: Optional[str] = None,
        records_processed: Optional[int] = None,
        records_created: Optional[int] = None,
        records_updated: Optional[int] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update an existing task's progress.

        Args:
            task_id: Task ID to update
            status: New status ('running', 'success', 'failed', 'cancelled')
            records_processed: Number of records processed (cumulative)
            records_created: Number of records created (cumulative)
            records_updated: Number of records updated (cumulative)
            error_message: Error message if failed
            metadata: Additional metadata to merge

        Returns:
            bool: True if successful, False otherwise
        """
        with Session(self.engine) as session:
            try:
                # Build dynamic UPDATE statement
                updates = []
                params = {"task_id": task_id}

                if status:
                    updates.append("status = :status")
                    params["status"] = status

                if records_processed is not None:
                    updates.append("records_processed = :records_processed")
                    params["records_processed"] = records_processed

                if records_created is not None:
                    updates.append("records_created = :records_created")
                    params["records_created"] = records_created

                if records_updated is not None:
                    updates.append("records_updated = :records_updated")
                    params["records_updated"] = records_updated

                if error_message:
                    updates.append("error_message = :error_message")
                    params["error_message"] = error_message

                if metadata:
                    import json
                    updates.append("metadata = metadata || :metadata::jsonb")
                    params["metadata"] = json.dumps(metadata)

                if not updates:
                    logger.warning(f"No updates provided for task {task_id}")
                    return True

                stmt = text(f"""
                    UPDATE task_logs
                    SET {', '.join(updates)}
                    WHERE task_id = :task_id
                """)

                session.execute(stmt, params)
                session.commit()

                logger.debug(f"Updated task {task_id}: {', '.join(updates)}")
                return True

            except Exception as e:
                session.rollback()
                logger.error(f"Error updating task {task_id}: {e}", exc_info=True)
                return False

    def complete_task(
        self,
        task_id: int,
        status: str = "success",
        records_processed: Optional[int] = None,
        records_created: Optional[int] = None,
        records_updated: Optional[int] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Complete a task and calculate duration.

        Args:
            task_id: Task ID to complete
            status: Final status ('success', 'failed', 'cancelled')
            records_processed: Total records processed
            records_created: Total records created
            records_updated: Total records updated
            error_message: Error message if failed
            metadata: Additional metadata

        Returns:
            bool: True if successful, False otherwise
        """
        with Session(self.engine) as session:
            try:
                # Build UPDATE with completion time
                updates = [
                    "status = :status",
                    "completed_at = NOW()",
                    "duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER"
                ]
                params = {
                    "task_id": task_id,
                    "status": status
                }

                if records_processed is not None:
                    updates.append("records_processed = :records_processed")
                    params["records_processed"] = records_processed

                if records_created is not None:
                    updates.append("records_created = :records_created")
                    params["records_created"] = records_created

                if records_updated is not None:
                    updates.append("records_updated = :records_updated")
                    params["records_updated"] = records_updated

                if error_message:
                    updates.append("error_message = :error_message")
                    params["error_message"] = error_message

                if metadata:
                    import json
                    updates.append("metadata = metadata || :metadata::jsonb")
                    params["metadata"] = json.dumps(metadata)

                stmt = text(f"""
                    UPDATE task_logs
                    SET {', '.join(updates)}
                    WHERE task_id = :task_id
                """)

                session.execute(stmt, params)
                session.commit()

                logger.info(f"Completed task {task_id} with status: {status}")
                return True

            except Exception as e:
                session.rollback()
                logger.error(f"Error completing task {task_id}: {e}", exc_info=True)
                return False

    @contextmanager
    def log_task(
        self,
        task_name: str,
        task_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for automatic task lifecycle management.

        Usage:
            with task_logger.log_task("serp_scraper", metadata={"query": "test"}) as task:
                # ... do work ...
                task.increment_processed(10)
                task.increment_created(5)

        Args:
            task_name: Name of the task
            task_type: Type category
            metadata: Initial metadata

        Yields:
            TaskContext: Context object for tracking progress
        """
        task_id = None
        task_context = None

        try:
            # Start task
            task_id = self.start_task(task_name, task_type, metadata)
            task_context = TaskContext(self, task_id)

            # Yield context to caller
            yield task_context

            # Complete successfully
            self.complete_task(
                task_id,
                status="success",
                records_processed=task_context.records_processed,
                records_created=task_context.records_created,
                records_updated=task_context.records_updated
            )

        except Exception as e:
            # Complete with failure
            if task_id:
                self.complete_task(
                    task_id,
                    status="failed",
                    records_processed=task_context.records_processed if task_context else 0,
                    records_created=task_context.records_created if task_context else 0,
                    records_updated=task_context.records_updated if task_context else 0,
                    error_message=str(e)
                )

            # Re-raise exception
            raise


class TaskContext:
    """
    Context object for tracking task progress within a context manager.

    Attributes:
        task_logger: Parent TaskLogger instance
        task_id: Task ID being tracked
        records_processed: Cumulative records processed
        records_created: Cumulative records created
        records_updated: Cumulative records updated
    """

    def __init__(self, task_logger: TaskLogger, task_id: int):
        """Initialize task context."""
        self.task_logger = task_logger
        self.task_id = task_id
        self.records_processed = 0
        self.records_created = 0
        self.records_updated = 0

    def increment_processed(self, count: int = 1):
        """Increment processed count and update task."""
        self.records_processed += count
        self.task_logger.update_task(
            self.task_id,
            records_processed=self.records_processed
        )

    def increment_created(self, count: int = 1):
        """Increment created count and update task."""
        self.records_created += count
        self.task_logger.update_task(
            self.task_id,
            records_created=self.records_created
        )

    def increment_updated(self, count: int = 1):
        """Increment updated count and update task."""
        self.records_updated += count
        self.task_logger.update_task(
            self.task_id,
            records_updated=self.records_updated
        )

    def add_metadata(self, metadata: Dict[str, Any]):
        """Add metadata to task."""
        self.task_logger.update_task(
            self.task_id,
            metadata=metadata
        )


# Module-level singleton
_task_logger_instance = None


def get_task_logger() -> TaskLogger:
    """Get or create the singleton TaskLogger instance."""
    global _task_logger_instance

    if _task_logger_instance is None:
        _task_logger_instance = TaskLogger()

    return _task_logger_instance


def main():
    """Demo: Test task logging."""
    logger.info("=" * 60)
    logger.info("Task Logger Demo")
    logger.info("=" * 60)
    logger.info("")

    task_logger = get_task_logger()

    # Test 1: Manual usage
    logger.info("Test 1: Manual task logging")
    task_id = task_logger.start_task(
        "test_manual_task",
        task_type="test",
        metadata={"test": "manual"}
    )

    task_logger.update_task(task_id, records_processed=10)
    task_logger.update_task(task_id, records_created=5)
    task_logger.complete_task(
        task_id,
        status="success",
        records_processed=10,
        records_created=5
    )
    logger.info(f"✓ Completed manual task {task_id}")
    logger.info("")

    # Test 2: Context manager usage
    logger.info("Test 2: Context manager task logging")
    try:
        with task_logger.log_task("test_context_task", task_type="test", metadata={"test": "context"}) as task:
            task.increment_processed(5)
            task.increment_created(3)
            task.increment_updated(2)
            task.add_metadata({"result": "success"})

        logger.info("✓ Completed context manager task")
        logger.info("")

    except Exception as e:
        logger.error(f"Context manager test failed: {e}")

    # Test 3: Error handling
    logger.info("Test 3: Error handling")
    try:
        with task_logger.log_task("test_error_task", task_type="test") as task:
            task.increment_processed(1)
            raise ValueError("Simulated error")

    except ValueError:
        logger.info("✓ Error handling test completed (expected error)")
        logger.info("")

    logger.info("=" * 60)
    logger.info("All tests completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

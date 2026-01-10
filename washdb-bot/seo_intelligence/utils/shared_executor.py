"""
Shared ThreadPoolExecutor for SEO Operations.

Provides a singleton bounded thread pool to prevent thread exhaustion.
All timeout-protected operations should use this shared executor instead
of creating new ThreadPoolExecutor instances for each operation.

Thread Exhaustion Problem:
- Creating ThreadPoolExecutor per operation leaks threads when operations timeout
- Python GC doesn't immediately clean up daemon threads
- After hours of operation, thread count can exceed system limits
- Results in "can't start new thread" errors that cascade to all operations

Solution:
- Single shared executor with bounded worker count
- Explicit cancellation on timeout
- Thread count monitoring with safety checks
"""

import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Callable, Any, Optional, TypeVar, Dict

from runner.logging_setup import get_logger

logger = get_logger("shared_executor")

T = TypeVar('T')

# Configuration
MAX_WORKERS = 20  # Bounded pool size
THREAD_WARNING_THRESHOLD = 2000  # Warn when approaching limit
THREAD_CRITICAL_THRESHOLD = 3000  # Force GC and reject new work
EXECUTOR_IDLE_TIMEOUT = 300  # Shutdown idle workers after 5 minutes


class SharedExecutorPool:
    """
    Singleton shared ThreadPoolExecutor for all SEO operations.

    Features:
    - Bounded thread count to prevent exhaustion
    - Thread count monitoring with safety checks
    - Explicit timeout handling without leaking threads
    - Statistics tracking for diagnostics
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
        self._executor: Optional[ThreadPoolExecutor] = None
        self._executor_lock = threading.RLock()

        # Statistics
        self._stats = {
            'submitted': 0,
            'completed': 0,
            'timeouts': 0,
            'errors': 0,
            'thread_warnings': 0,
            'thread_critical': 0,
            'gc_forced': 0,
        }
        self._stats_lock = threading.Lock()

        # Pending futures for cleanup
        self._pending_futures: Dict[int, Future] = {}
        self._future_id = 0
        self._futures_lock = threading.Lock()

        logger.info(f"SharedExecutorPool initialized (max_workers={MAX_WORKERS})")

    def _get_executor(self) -> ThreadPoolExecutor:
        """Get or create the shared executor."""
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS,
                    thread_name_prefix="seo_shared"
                )
                logger.debug("Created shared ThreadPoolExecutor")
            return self._executor

    def _check_thread_safety(self) -> bool:
        """
        Check if it's safe to submit new work.

        Returns:
            True if safe to proceed, False if thread limit is critical
        """
        thread_count = threading.active_count()

        if thread_count >= THREAD_CRITICAL_THRESHOLD:
            with self._stats_lock:
                self._stats['thread_critical'] += 1

            logger.critical(f"Thread count critical: {thread_count} >= {THREAD_CRITICAL_THRESHOLD}")

            # Force garbage collection to try to free threads
            gc.collect()
            gc.collect()
            gc.collect()

            with self._stats_lock:
                self._stats['gc_forced'] += 1

            # Re-check after GC
            thread_count = threading.active_count()
            if thread_count >= THREAD_CRITICAL_THRESHOLD:
                logger.error(f"Thread count still critical after GC: {thread_count}")
                return False

            logger.info(f"Thread count reduced to {thread_count} after GC")

        elif thread_count >= THREAD_WARNING_THRESHOLD:
            with self._stats_lock:
                self._stats['thread_warnings'] += 1
            logger.warning(f"Thread count high: {thread_count}")

        return True

    def submit_with_timeout(
        self,
        func: Callable[..., T],
        timeout: float,
        *args,
        **kwargs
    ) -> T:
        """
        Submit a function for execution with timeout.

        Args:
            func: Function to execute
            timeout: Timeout in seconds
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            FuturesTimeoutError: If execution exceeds timeout
            RuntimeError: If thread limit is critical
            Exception: Any exception raised by func
        """
        # Safety check
        if not self._check_thread_safety():
            with self._stats_lock:
                self._stats['errors'] += 1
            raise RuntimeError(
                f"Thread exhaustion: {threading.active_count()} threads. "
                "Cannot submit new work."
            )

        executor = self._get_executor()

        with self._stats_lock:
            self._stats['submitted'] += 1
            future_id = self._future_id
            self._future_id += 1

        future = executor.submit(func, *args, **kwargs)

        # Track pending future
        with self._futures_lock:
            self._pending_futures[future_id] = future

        try:
            result = future.result(timeout=timeout)

            with self._stats_lock:
                self._stats['completed'] += 1

            return result

        except FuturesTimeoutError:
            with self._stats_lock:
                self._stats['timeouts'] += 1

            # Try to cancel - won't interrupt running task but marks it
            future.cancel()

            logger.warning(
                f"Task timed out after {timeout}s "
                f"(threads: {threading.active_count()})"
            )
            raise

        except Exception as e:
            with self._stats_lock:
                self._stats['errors'] += 1
            raise

        finally:
            # Remove from pending
            with self._futures_lock:
                self._pending_futures.pop(future_id, None)

    def get_stats(self) -> dict:
        """Get executor statistics."""
        with self._stats_lock:
            stats = self._stats.copy()

        stats['active_threads'] = threading.active_count()
        stats['pending_futures'] = len(self._pending_futures)

        return stats

    def shutdown(self, wait: bool = True):
        """Shutdown the executor."""
        with self._executor_lock:
            if self._executor:
                logger.info("Shutting down SharedExecutorPool")
                self._executor.shutdown(wait=wait)
                self._executor = None


# Singleton accessor
_shared_executor: Optional[SharedExecutorPool] = None
_accessor_lock = threading.Lock()


def get_shared_executor() -> SharedExecutorPool:
    """
    Get the singleton SharedExecutorPool instance.

    Returns:
        The global SharedExecutorPool instance
    """
    global _shared_executor
    with _accessor_lock:
        if _shared_executor is None:
            _shared_executor = SharedExecutorPool()
        return _shared_executor


def run_with_timeout(
    func: Callable[..., T],
    timeout: float,
    *args,
    **kwargs
) -> T:
    """
    Convenience function to run a function with timeout using shared executor.

    This is the recommended way to run timeout-protected operations.

    Args:
        func: Function to execute
        timeout: Timeout in seconds
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        FuturesTimeoutError: If execution exceeds timeout
        RuntimeError: If thread limit is critical
        Exception: Any exception raised by func

    Example:
        result = run_with_timeout(slow_function, 30, arg1, arg2, kwarg1=value)
    """
    return get_shared_executor().submit_with_timeout(func, timeout, *args, **kwargs)


def get_thread_stats() -> dict:
    """
    Get thread statistics for monitoring.

    Returns:
        Dict with thread counts and executor stats
    """
    stats = get_shared_executor().get_stats()

    # Add breakdown by thread type if possible
    try:
        import subprocess
        result = subprocess.run(
            ['ps', '-u', str(os.getuid()), '-L', '-o', 'comm'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            from collections import Counter
            threads = result.stdout.strip().split('\n')[1:]  # Skip header
            stats['thread_breakdown'] = dict(Counter(threads).most_common(10))
    except Exception:
        pass

    return stats


import os  # Import at module level for get_thread_stats

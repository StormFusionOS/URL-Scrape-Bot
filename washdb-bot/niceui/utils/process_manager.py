"""
Process manager - tracks active background jobs and enables instant termination.

Cross-platform process management:
- POSIX (Linux/macOS): Uses signals and process groups
- Windows: Uses psutil for process termination
"""

import os
import sys
import signal
from typing import Optional, Dict
from datetime import datetime
from threading import Lock
import logging

# Detect platform
IS_WINDOWS = sys.platform == 'win32'

# Import psutil for cross-platform process management
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False
    if IS_WINDOWS:
        logging.warning("psutil not available - Windows process management will be unavailable")
    else:
        logging.warning("psutil not available - some process management features will be limited")


class ProcessInfo:
    """Information about a tracked process."""

    def __init__(self, job_id: str, job_type: str, pid: Optional[int] = None, log_file: str = None):
        self.job_id = job_id
        self.job_type = job_type
        self.pid = pid
        self.log_file = log_file
        self.start_time = datetime.now()
        self.end_time = None
        self.status = 'running'  # running, stopped, completed, failed
        self.cancel_flag = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'job_id': self.job_id,
            'job_type': self.job_type,
            'pid': self.pid,
            'log_file': self.log_file,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'status': self.status,
            'cancel_requested': self.cancel_flag
        }


class ProcessManager:
    """Manages background processes for jobs."""

    def __init__(self):
        self._processes: Dict[str, ProcessInfo] = {}
        self._lock = Lock()

    def register(self, job_id: str, job_type: str, pid: Optional[int] = None, log_file: str = None) -> ProcessInfo:
        """Register a new process."""
        with self._lock:
            proc_info = ProcessInfo(job_id, job_type, pid, log_file)
            self._processes[job_id] = proc_info
            return proc_info

    def update_pid(self, job_id: str, pid: int):
        """Update the PID for a job."""
        with self._lock:
            if job_id in self._processes:
                self._processes[job_id].pid = pid

    def get(self, job_id: str) -> Optional[ProcessInfo]:
        """Get process info by job ID."""
        return self._processes.get(job_id)

    def get_all(self) -> Dict[str, ProcessInfo]:
        """Get all tracked processes."""
        with self._lock:
            return self._processes.copy()

    def get_running(self) -> Dict[str, ProcessInfo]:
        """Get all running processes."""
        with self._lock:
            return {
                job_id: proc
                for job_id, proc in self._processes.items()
                if proc.status == 'running'
            }

    def set_cancel_flag(self, job_id: str) -> bool:
        """Set the cancel flag for a job (soft cancellation)."""
        with self._lock:
            if job_id in self._processes:
                self._processes[job_id].cancel_flag = True
                return True
            return False

    def is_cancelled(self, job_id: str) -> bool:
        """Check if cancellation has been requested."""
        proc = self.get(job_id)
        return proc.cancel_flag if proc else False

    def kill(self, job_id: str, force: bool = True) -> bool:
        """
        Kill a process immediately (cross-platform).

        Args:
            job_id: Job ID to kill
            force: If True, use forceful termination (SIGKILL/TerminateProcess).
                   If False, use graceful termination (SIGTERM/WM_CLOSE).

        Returns:
            True if process was killed, False otherwise
        """
        with self._lock:
            proc = self._processes.get(job_id)
            if not proc or not proc.pid:
                return False

            try:
                if IS_WINDOWS:
                    # Windows: Use psutil for cross-platform process management
                    return self._kill_windows(proc, force)
                else:
                    # POSIX (Linux/macOS): Use signals and process groups
                    return self._kill_posix(proc, force)

            except ProcessLookupError:
                # Process already dead
                proc.status = 'completed'
                proc.end_time = datetime.now()
                return False

            except Exception as e:
                logging.error(f"Error killing process {job_id} (PID: {proc.pid}): {e}", exc_info=True)
                return False

    def _kill_posix(self, proc: ProcessInfo, force: bool) -> bool:
        """
        Kill a process on POSIX systems (Linux/macOS).

        Args:
            proc: ProcessInfo object
            force: If True, use SIGKILL. If False, use SIGTERM.

        Returns:
            True if process was killed successfully
        """
        sig = signal.SIGKILL if force else signal.SIGTERM

        # Try to kill the process
        os.kill(proc.pid, sig)

        # Also try to kill the process group (catches child processes)
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError) as e:
            logging.debug(f"Could not kill process group for PID {proc.pid}: {e}")

        proc.status = 'stopped'
        proc.end_time = datetime.now()
        proc.cancel_flag = True

        return True

    def _kill_windows(self, proc: ProcessInfo, force: bool) -> bool:
        """
        Kill a process on Windows.

        Args:
            proc: ProcessInfo object
            force: If True, use forceful termination. If False, use graceful termination.

        Returns:
            True if process was killed successfully
        """
        if not psutil:
            logging.error("psutil not available - cannot kill Windows processes")
            return False

        try:
            # Get process and all children
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)

            # Kill children first (bottom-up)
            for child in children:
                try:
                    if force:
                        child.kill()  # Forceful termination
                    else:
                        child.terminate()  # Graceful termination
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logging.debug(f"Could not terminate child process {child.pid}: {e}")

            # Kill parent process
            if force:
                parent.kill()
            else:
                parent.terminate()

            # Wait for process to die (with timeout)
            try:
                parent.wait(timeout=5)
            except psutil.TimeoutExpired:
                logging.warning(f"Process {proc.pid} did not terminate within timeout")

            proc.status = 'stopped'
            proc.end_time = datetime.now()
            proc.cancel_flag = True

            return True

        except psutil.NoSuchProcess:
            # Process already dead
            proc.status = 'completed'
            proc.end_time = datetime.now()
            return False

        except psutil.AccessDenied as e:
            logging.error(f"Access denied killing process {proc.pid}: {e}")
            return False

    def mark_completed(self, job_id: str, success: bool = True):
        """Mark a job as completed."""
        with self._lock:
            if job_id in self._processes:
                self._processes[job_id].status = 'completed' if success else 'failed'
                self._processes[job_id].end_time = datetime.now()

    def unregister(self, job_id: str):
        """Remove a job from tracking."""
        with self._lock:
            if job_id in self._processes:
                del self._processes[job_id]

    def cleanup_completed(self):
        """Remove completed jobs from tracking."""
        with self._lock:
            completed = [
                job_id for job_id, proc in self._processes.items()
                if proc.status in ('completed', 'failed', 'stopped')
            ]
            for job_id in completed:
                del self._processes[job_id]


# Global process manager instance
process_manager = ProcessManager()


# Convenience functions for common operations
def stop_process(job_id: str, force: bool = True) -> bool:
    """
    Stop a process by job ID (cross-platform).

    Args:
        job_id: Job ID to stop
        force: If True, forcefully terminate. If False, gracefully terminate.

    Returns:
        True if process was stopped, False otherwise
    """
    return process_manager.kill(job_id, force=force)


def register_process(job_id: str, job_type: str, pid: Optional[int] = None, log_file: str = None) -> ProcessInfo:
    """
    Register a new process.

    Args:
        job_id: Unique job identifier
        job_type: Type of job (e.g., 'scrape', 'discover')
        pid: Process ID (optional, can be set later)
        log_file: Path to log file (optional)

    Returns:
        ProcessInfo object
    """
    return process_manager.register(job_id, job_type, pid, log_file)


def get_process_info(job_id: str) -> Optional[ProcessInfo]:
    """Get process information by job ID."""
    return process_manager.get(job_id)


def get_running_processes() -> Dict[str, ProcessInfo]:
    """Get all running processes."""
    return process_manager.get_running()


def find_and_kill_processes_by_name(patterns: list[str]) -> int:
    """
    Find and kill processes matching given patterns (cross-platform).

    Args:
        patterns: List of string patterns to match in command line
                 (e.g., ['worker_pool', 'run_state_workers'])

    Returns:
        Number of processes killed
    """
    if not psutil:
        logging.error("psutil not available - cannot find processes by name")
        return 0

    killed_count = 0

    try:
        # Iterate through all running processes
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Get command line
                cmdline = proc.info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline) if cmdline else ''

                # Check if any pattern matches
                if any(pattern in cmdline_str for pattern in patterns):
                    logging.info(f"Killing process {proc.pid}: {cmdline_str[:100]}")
                    try:
                        # Kill process and children
                        children = proc.children(recursive=True)
                        for child in children:
                            try:
                                child.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                        proc.kill()
                        killed_count += 1

                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        logging.debug(f"Could not kill process {proc.pid}: {e}")

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process disappeared or we don't have permission
                continue

    except Exception as e:
        logging.error(f"Error finding processes: {e}", exc_info=True)

    return killed_count

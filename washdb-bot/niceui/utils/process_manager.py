"""
Process manager - tracks active background jobs and enables instant termination.
"""

import os
import signal
from typing import Optional, Dict
from datetime import datetime
from threading import Lock


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
        Kill a process immediately.

        Args:
            job_id: Job ID to kill
            force: If True, use SIGKILL. If False, use SIGTERM.

        Returns:
            True if process was killed, False otherwise
        """
        with self._lock:
            proc = self._processes.get(job_id)
            if not proc or not proc.pid:
                return False

            try:
                sig = signal.SIGKILL if force else signal.SIGTERM

                # Try to kill the process
                os.kill(proc.pid, sig)

                # Also try to kill the process group (catches child processes)
                try:
                    os.killpg(os.getpgid(proc.pid), sig)
                except ProcessLookupError:
                    pass  # Process already dead

                proc.status = 'stopped'
                proc.end_time = datetime.now()
                proc.cancel_flag = True

                return True

            except ProcessLookupError:
                # Process already dead
                proc.status = 'completed'
                proc.end_time = datetime.now()
                return False

            except Exception as e:
                print(f"Error killing process {job_id} (PID: {proc.pid}): {e}")
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

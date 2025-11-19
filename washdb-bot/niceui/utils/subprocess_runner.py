"""
Subprocess runner for crawlers - enables instant kill and real-time log capture.

Cross-platform subprocess management using psutil.
"""

import subprocess
import os
import sys
import signal
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

# Import psutil for cross-platform process management
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


class SubprocessRunner:
    """Runs a crawler as a subprocess with instant kill capability."""

    def __init__(self, job_id: str, log_file: str):
        self.job_id = job_id
        self.log_file = log_file
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.return_code: Optional[int] = None

    def start(self, command: list, cwd: Optional[str] = None) -> int:
        """
        Start the subprocess.

        Args:
            command: Command and arguments as list
            cwd: Working directory

        Returns:
            Process PID
        """
        self.start_time = datetime.now()

        # Ensure log file directory exists
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)

        # Open log file
        log_fd = open(self.log_file, 'a', buffering=1)  # Line buffered

        # Start process with new process group (platform-specific)
        if IS_WINDOWS:
            # Windows: CREATE_NEW_PROCESS_GROUP
            self.process = subprocess.Popen(
                command,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            # POSIX: Use process groups
            self.process = subprocess.Popen(
                command,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                preexec_fn=os.setsid  # Create new process group for clean killing
            )

        self.pid = self.process.pid
        return self.pid

    def kill(self) -> bool:
        """
        Kill the process immediately (cross-platform).

        Uses psutil to kill process and all children on both POSIX and Windows.

        Returns:
            True if killed successfully
        """
        if not self.process or not self.pid:
            return False

        try:
            if HAS_PSUTIL:
                # Use psutil for cross-platform process tree killing
                try:
                    parent = psutil.Process(self.pid)
                    children = parent.children(recursive=True)

                    # Kill children first
                    for child in children:
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    # Kill parent
                    parent.kill()

                except psutil.NoSuchProcess:
                    # Process already dead
                    return False

            else:
                # Fallback to platform-specific kill (POSIX only)
                if IS_WINDOWS:
                    # Windows without psutil - use process.kill()
                    self.process.kill()
                else:
                    # POSIX: Kill process group
                    os.killpg(os.getpgid(self.pid), signal.SIGKILL)

            self.end_time = datetime.now()
            self.return_code = -9
            return True

        except ProcessLookupError:
            # Process already dead
            return False

        except Exception as e:
            print(f"Error killing process {self.pid}: {e}")
            return False

    def is_running(self) -> bool:
        """Check if process is still running."""
        if not self.process:
            return False
        return self.process.poll() is None

    def wait(self, timeout: Optional[float] = None) -> int:
        """
        Wait for process to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Return code
        """
        if not self.process:
            return -1

        try:
            self.return_code = self.process.wait(timeout=timeout)
            self.end_time = datetime.now()
            return self.return_code

        except subprocess.TimeoutExpired:
            return None

    def get_status(self) -> dict:
        """Get process status."""
        elapsed = None
        if self.start_time:
            end = self.end_time or datetime.now()
            elapsed = (end - self.start_time).total_seconds()

        return {
            'job_id': self.job_id,
            'pid': self.pid,
            'running': self.is_running(),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'elapsed': elapsed,
            'return_code': self.return_code,
            'log_file': self.log_file
        }

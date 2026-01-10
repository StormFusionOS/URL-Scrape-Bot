"""
Chrome Process Manager

Provides robust Chrome process tracking and cleanup without nuclear options.
Uses process tree tracking and graceful termination.

Key features:
- Explicit process tracking by session ID
- Graceful termination (SIGTERM then SIGKILL)
- Process tree cleanup
- Orphan detection without killing active sessions
"""

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Set, Optional, List

from runner.logging_setup import get_logger

logger = get_logger("chrome_process_manager")


@dataclass
class TrackedProcess:
    """Tracked Chrome process with metadata."""
    pid: int
    session_id: Optional[str]
    debug_port: Optional[int]
    created_at: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)


class ChromeProcessManager:
    """
    Manages Chrome process lifecycle with explicit tracking.

    Key features:
    - Track all Chrome processes by session
    - Graceful termination before SIGKILL
    - Process tree cleanup (parent + children)
    - No nuclear option - targeted cleanup only
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
        self._tracked: Dict[int, TrackedProcess] = {}
        self._session_pids: Dict[str, Set[int]] = {}
        self._port_to_session: Dict[int, str] = {}
        self._lock = threading.RLock()

        # Cleanup configuration
        self._graceful_timeout = 5  # seconds for SIGTERM
        self._orphan_age_threshold = 300  # 5 minutes

        logger.info("ChromeProcessManager initialized")

    def register_process(self, pid: int, session_id: str,
                         debug_port: Optional[int] = None) -> None:
        """
        Register a Chrome process for tracking.

        Args:
            pid: Process ID
            session_id: Session ID that owns this process
            debug_port: Optional debugging port
        """
        with self._lock:
            self._tracked[pid] = TrackedProcess(
                pid=pid,
                session_id=session_id,
                debug_port=debug_port
            )

            if session_id not in self._session_pids:
                self._session_pids[session_id] = set()
            self._session_pids[session_id].add(pid)

            if debug_port:
                self._port_to_session[debug_port] = session_id

            logger.debug(f"Registered Chrome PID {pid} for session {session_id[:8]}")

    def unregister_process(self, pid: int) -> None:
        """Unregister a Chrome process."""
        with self._lock:
            if pid in self._tracked:
                proc = self._tracked[pid]

                # Clean up session mapping
                if proc.session_id and proc.session_id in self._session_pids:
                    self._session_pids[proc.session_id].discard(pid)
                    if not self._session_pids[proc.session_id]:
                        del self._session_pids[proc.session_id]

                # Clean up port mapping
                if proc.debug_port and proc.debug_port in self._port_to_session:
                    del self._port_to_session[proc.debug_port]

                del self._tracked[pid]
                logger.debug(f"Unregistered Chrome PID {pid}")

    def terminate_session_processes(self, session_id: str,
                                    graceful: bool = True) -> int:
        """
        Terminate all Chrome processes for a session.

        Args:
            session_id: Session ID
            graceful: Whether to try SIGTERM first

        Returns:
            Number of processes terminated
        """
        terminated = 0

        with self._lock:
            pids = self._session_pids.get(session_id, set()).copy()

        for pid in pids:
            if self._terminate_process(pid, graceful):
                terminated += 1
                self.unregister_process(pid)

        # Also terminate child processes
        terminated += self._terminate_children(pids)

        if terminated:
            logger.info(f"Terminated {terminated} processes for session {session_id[:8]}")

        return terminated

    def _terminate_process(self, pid: int, graceful: bool = True) -> bool:
        """
        Terminate a single process.

        Args:
            pid: Process ID
            graceful: Try SIGTERM first if True

        Returns:
            True if process was terminated
        """
        try:
            # Check if process exists
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False

        # Skip zombie processes - they can't be killed
        if self._is_zombie(pid):
            logger.debug(f"Skipping zombie process {pid} (cannot be killed)")
            return False

        try:
            if graceful:
                # Try SIGTERM first
                os.kill(pid, signal.SIGTERM)

                # Wait for graceful termination
                for _ in range(self._graceful_timeout * 10):
                    time.sleep(0.1)
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        logger.debug(f"Process {pid} terminated gracefully")
                        return True

                # Graceful timeout - use SIGKILL
                logger.warning(f"Process {pid} did not terminate gracefully, using SIGKILL")

            os.kill(pid, signal.SIGKILL)
            return True

        except (ProcessLookupError, PermissionError, OSError) as e:
            logger.debug(f"Process {pid} termination error: {e}")
            return False

    def _terminate_children(self, parent_pids: Set[int]) -> int:
        """Terminate child processes of given PIDs."""
        terminated = 0

        for ppid in parent_pids:
            try:
                result = subprocess.run(
                    ['pgrep', '-P', str(ppid)],
                    capture_output=True,
                    text=True
                )

                for child_pid_str in result.stdout.strip().split('\n'):
                    if child_pid_str:
                        try:
                            child_pid = int(child_pid_str)
                            if self._terminate_process(child_pid, graceful=False):
                                terminated += 1
                        except ValueError:
                            pass

            except Exception:
                pass

        return terminated

    def cleanup_orphaned_processes(self) -> int:
        """
        Clean up orphaned Chrome processes.

        Orphaned = parent PID is 1 (init) OR process is old and untracked.
        Does NOT kill processes belonging to tracked sessions.

        Returns:
            Number of processes cleaned up
        """
        cleaned = 0

        try:
            # Get all Chrome processes for current user
            result = subprocess.run(
                ['pgrep', '-u', str(os.getuid()), '-f', 'chrom'],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return 0

            all_chrome_pids = set()
            for pid_str in result.stdout.strip().split('\n'):
                if pid_str:
                    try:
                        all_chrome_pids.add(int(pid_str))
                    except ValueError:
                        pass

            with self._lock:
                tracked_pids = set(self._tracked.keys())

            # Find untracked processes
            untracked = all_chrome_pids - tracked_pids

            for pid in untracked:
                if self._is_orphan_or_stale(pid):
                    if self._terminate_process(pid, graceful=True):
                        cleaned += 1
                        logger.info(f"Cleaned orphaned Chrome PID {pid}")

        except Exception as e:
            logger.error(f"Error cleaning orphaned processes: {e}")

        if cleaned:
            logger.info(f"Cleaned {cleaned} orphaned Chrome processes")

        return cleaned

    def _is_orphan_or_stale(self, pid: int) -> bool:
        """
        Check if process is orphaned (parent=1) or stale (too old).

        Args:
            pid: Process ID to check

        Returns:
            True if process should be cleaned up
        """
        try:
            with open(f'/proc/{pid}/stat', 'r') as f:
                stat = f.read().split()

            ppid = int(stat[3]) if len(stat) > 3 else 0

            # Orphan: parent is init (PID 1)
            if ppid == 1:
                return True

            # Stale: older than threshold
            if len(stat) > 21:
                starttime = int(stat[21])
                with open('/proc/uptime', 'r') as u:
                    uptime = float(u.read().split()[0])
                clk_tck = os.sysconf('SC_CLK_TCK')
                process_age = uptime - (starttime / clk_tck)

                if process_age > self._orphan_age_threshold:
                    return True

            # Zombie state - skip these, they can't be killed
            with open(f'/proc/{pid}/status', 'r') as f:
                status = f.read()
            if 'State:\tZ' in status:
                logger.debug(f"Skipping zombie process {pid}")
                return False  # Don't try to clean zombies - they need parent to reap
            if 'State:\tT' in status:
                return True  # Stopped processes can be cleaned

        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            # Process doesn't exist or can't be read
            pass

        return False

    def _is_zombie(self, pid: int) -> bool:
        """
        Check if a process is a zombie.

        Zombie processes cannot be killed - they must be reaped by their parent.
        Trying to kill them wastes time and log spam.

        Args:
            pid: Process ID to check

        Returns:
            True if process is a zombie
        """
        try:
            with open(f'/proc/{pid}/status', 'r') as f:
                status = f.read()
            return 'State:\tZ' in status
        except (FileNotFoundError, PermissionError):
            return False

    def get_tracked_pids_for_session(self, session_id: str) -> Set[int]:
        """Get all tracked PIDs for a session."""
        with self._lock:
            return self._session_pids.get(session_id, set()).copy()

    def get_active_session_ids(self) -> Set[str]:
        """Get all session IDs with tracked processes."""
        with self._lock:
            return set(self._session_pids.keys())

    def get_stats(self) -> dict:
        """Get process manager statistics."""
        with self._lock:
            return {
                "tracked_processes": len(self._tracked),
                "active_sessions": len(self._session_pids),
                "allocated_ports": len(self._port_to_session),
                "total_chrome_processes": self._count_chrome_processes(),
            }

    def _count_chrome_processes(self) -> int:
        """Count all Chrome processes for current user."""
        try:
            result = subprocess.run(
                ['pgrep', '-c', '-u', str(os.getuid()), '-f', 'chrom'],
                capture_output=True,
                text=True
            )
            return int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            return 0

    def refresh_tracked_processes(self) -> int:
        """
        Remove dead processes from tracking.

        Returns:
            Number of dead processes removed
        """
        removed = 0

        with self._lock:
            dead_pids = []
            for pid in self._tracked:
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    dead_pids.append(pid)

        for pid in dead_pids:
            self.unregister_process(pid)
            removed += 1

        if removed:
            logger.debug(f"Removed {removed} dead processes from tracking")

        return removed


# Singleton accessor
_chrome_process_manager: Optional[ChromeProcessManager] = None
_accessor_lock = threading.Lock()


def get_chrome_process_manager() -> ChromeProcessManager:
    """
    Get the singleton ChromeProcessManager instance.

    Returns:
        The global ChromeProcessManager instance
    """
    global _chrome_process_manager
    with _accessor_lock:
        if _chrome_process_manager is None:
            _chrome_process_manager = ChromeProcessManager()
        return _chrome_process_manager

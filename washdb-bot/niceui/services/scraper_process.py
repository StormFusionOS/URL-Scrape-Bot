"""
Scraper Process Manager
Manages the SEO scraper subprocess with real-time output streaming
"""

import os
import sys
import subprocess
import threading
import time
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ScraperStatus(Enum):
    """Scraper process states"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class ScraperProcessManager:
    """
    Manages the SEO scraper subprocess
    Provides real-time output streaming via WebSocket
    """

    def __init__(self, websocket_manager=None):
        """
        Initialize the scraper process manager

        Args:
            websocket_manager: WebSocket manager instance for broadcasting events
        """
        self.websocket_manager = websocket_manager
        self.process: Optional[subprocess.Popen] = None
        self.status = ScraperStatus.IDLE
        self.pid: Optional[int] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.output_buffer: list = []  # Buffer last 1000 lines
        self.max_buffer_lines = 1000
        self.output_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.event_loop = None  # Store main event loop reference

        # Working directory for scraper
        self.working_dir = "/home/rivercityscrape/ai_seo_scraper/Nathan SEO Bot"

        logger.info("ScraperProcessManager initialized")

    def start_scraper(self, node_type: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Start the SEO scraper process

        Args:
            node_type: Type of nodes to crawl (local, national, or None for all)
            limit: Maximum number of URLs to crawl

        Returns:
            dict: Status response with success/error information
        """
        with self.lock:
            # Check if already running
            if self.status in [ScraperStatus.RUNNING, ScraperStatus.STARTING]:
                return {
                    'success': False,
                    'error': f'Scraper is already {self.status.value}'
                }

            try:
                # Build command
                cmd = [sys.executable, 'main.py', 'crawl']

                if node_type and node_type != 'all':
                    cmd.append(node_type)

                if limit:
                    cmd.append(str(limit))

                logger.info(f"Starting scraper with command: {' '.join(cmd)}")

                # Capture the current event loop
                try:
                    self.event_loop = asyncio.get_running_loop()
                except RuntimeError:
                    # If no loop is running, get the default one
                    self.event_loop = asyncio.get_event_loop()

                # Update status
                self.status = ScraperStatus.STARTING
                self.start_time = datetime.now()
                self.end_time = None
                self.output_buffer.clear()

                # Broadcast status change
                self._broadcast_status()

                # Start process
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    cwd=self.working_dir
                )

                self.pid = self.process.pid
                self.status = ScraperStatus.RUNNING

                logger.info(f"Scraper process started with PID: {self.pid}")

                # Start output streaming thread
                self.output_thread = threading.Thread(
                    target=self._stream_output,
                    daemon=True
                )
                self.output_thread.start()

                # Broadcast status change
                self._broadcast_status()

                return {
                    'success': True,
                    'pid': self.pid,
                    'status': self.status.value
                }

            except Exception as e:
                logger.error(f"Failed to start scraper: {e}")
                self.status = ScraperStatus.FAILED
                self._broadcast_status()
                return {
                    'success': False,
                    'error': str(e)
                }

    def stop_scraper(self, force: bool = False) -> Dict[str, Any]:
        """
        Stop the running scraper process
        Will kill ALL scraper processes, not just the one started by this manager

        Args:
            force: If True, use SIGKILL immediately; otherwise try graceful shutdown first

        Returns:
            dict: Status response
        """
        with self.lock:
            try:
                # First, try to stop the process we started (if any)
                killed_managed = False
                if self.process and self.status != ScraperStatus.IDLE:
                    logger.info(f"Stopping managed scraper process (PID: {self.pid}, force={force})")

                    self.status = ScraperStatus.STOPPING
                    self._broadcast_status()

                    if force:
                        # Immediate kill
                        self.process.kill()
                        logger.info(f"Sent SIGKILL to managed scraper process (PID: {self.pid})")
                    else:
                        # Graceful shutdown with timeout
                        self.process.terminate()
                        logger.info(f"Sent SIGTERM to managed scraper process (PID: {self.pid})")

                        try:
                            self.process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            logger.warning("Graceful shutdown timed out, force killing")
                            self.process.kill()
                            self.process.wait()

                    killed_managed = True

                # Also kill ANY other scraper processes running (started manually or by previous GUI instances)
                try:
                    # Find all python processes running main.py crawl
                    result = subprocess.run(
                        ['pgrep', '-f', 'python.*main.py.*crawl'],
                        capture_output=True,
                        text=True
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().split('\n')
                        for pid in pids:
                            pid = pid.strip()
                            if pid:
                                try:
                                    logger.info(f"Killing external scraper process PID: {pid}")
                                    if force:
                                        subprocess.run(['kill', '-9', pid], check=False)
                                    else:
                                        subprocess.run(['kill', '-15', pid], check=False)
                                        # Wait briefly, then force kill if still running
                                        time.sleep(2)
                                        subprocess.run(['kill', '-9', pid], check=False)
                                except Exception as e:
                                    logger.warning(f"Failed to kill PID {pid}: {e}")

                except Exception as e:
                    logger.warning(f"Failed to search for external scraper processes: {e}")

                self.end_time = datetime.now()
                self.status = ScraperStatus.STOPPED
                self.pid = None
                self.process = None

                logger.info("All scraper processes stopped")

                self._broadcast_status()

                return {
                    'success': True,
                    'status': self.status.value,
                    'killed_managed': killed_managed
                }

            except Exception as e:
                logger.error(f"Failed to stop scraper: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }

    def get_status(self) -> Dict[str, Any]:
        """
        Get current scraper status

        Returns:
            dict: Status information including state, PID, runtime, etc.
        """
        runtime = None
        if self.start_time:
            end = self.end_time or datetime.now()
            runtime = (end - self.start_time).total_seconds()

        return {
            'status': self.status.value,
            'pid': self.pid,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'runtime_seconds': runtime,
            'is_running': self.status == ScraperStatus.RUNNING,
            'output_lines': len(self.output_buffer)
        }

    def get_output(self, last_n_lines: int = 100) -> list:
        """
        Get buffered output lines

        Args:
            last_n_lines: Number of recent lines to return

        Returns:
            list: Output lines
        """
        with self.lock:
            if last_n_lines:
                return self.output_buffer[-last_n_lines:]
            return self.output_buffer.copy()

    def clear_output(self):
        """Clear the output buffer"""
        with self.lock:
            self.output_buffer.clear()
            logger.info("Output buffer cleared")

    def _stream_output(self):
        """
        Thread function to stream process output
        Runs in background and broadcasts each line via WebSocket
        """
        try:
            if not self.process or not self.process.stdout:
                return

            for line in iter(self.process.stdout.readline, ''):
                if not line:
                    break

                line = line.rstrip('\n')

                # Add to buffer
                with self.lock:
                    self.output_buffer.append(line)

                    # Trim buffer if too large
                    if len(self.output_buffer) > self.max_buffer_lines:
                        self.output_buffer = self.output_buffer[-self.max_buffer_lines:]

                # Broadcast via WebSocket
                if self.websocket_manager and self.event_loop:
                    try:
                        # Schedule the coroutine in the event loop
                        asyncio.run_coroutine_threadsafe(
                            self.websocket_manager.broadcast('scraper_output', {
                                'line': line,
                                'timestamp': datetime.now().isoformat()
                            }),
                            self.event_loop
                        )
                    except Exception as e:
                        logger.error(f"Failed to broadcast output: {e}")

            # Process finished
            return_code = self.process.wait()

            logger.info(f"Scraper process exited with code: {return_code}")

            with self.lock:
                self.end_time = datetime.now()

                if return_code == 0:
                    self.status = ScraperStatus.COMPLETED
                else:
                    self.status = ScraperStatus.FAILED

                self.pid = None

            # Broadcast final status
            self._broadcast_status()

        except Exception as e:
            logger.error(f"Error in output streaming thread: {e}")
            with self.lock:
                self.status = ScraperStatus.FAILED
            self._broadcast_status()

    def _broadcast_status(self):
        """Broadcast current status via WebSocket"""
        if self.websocket_manager and self.event_loop:
            try:
                status_data = self.get_status()
                # Schedule the coroutine in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.websocket_manager.broadcast('scraper_status', status_data),
                    self.event_loop
                )
            except Exception as e:
                logger.error(f"Failed to broadcast status: {e}")


# Global instance
_scraper_manager: Optional[ScraperProcessManager] = None


def get_scraper_manager() -> ScraperProcessManager:
    """Get the global scraper manager instance"""
    global _scraper_manager
    if _scraper_manager is None:
        raise RuntimeError("ScraperProcessManager not initialized")
    return _scraper_manager


def initialize_scraper_manager(websocket_manager) -> ScraperProcessManager:
    """
    Initialize the global scraper manager

    Args:
        websocket_manager: WebSocket manager for broadcasting

    Returns:
        ScraperProcessManager instance
    """
    global _scraper_manager
    _scraper_manager = ScraperProcessManager(websocket_manager)
    logger.info("Global scraper manager initialized")
    return _scraper_manager

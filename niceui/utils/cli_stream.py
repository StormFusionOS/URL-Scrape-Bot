"""
CLI stream utilities for capturing and streaming subprocess output.
"""

import asyncio
import time
from typing import Callable, Optional
from datetime import datetime


class CLIStreamer:
    """Streams CLI output from a subprocess with line-by-line processing."""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.running = False
        self.last_output_time = None
        self.start_time = None
        self.lines = []
        self.exit_code = None

    async def run_command(
        self,
        cmd: list,
        on_line: Optional[Callable[[str, str], None]] = None,
        on_complete: Optional[Callable[[int, float], None]] = None,
        cwd: Optional[str] = None
    ):
        """
        Run a command and stream its output.

        Args:
            cmd: Command and arguments as list
            on_line: Callback for each line (line_type: 'stdout'|'stderr', line: str)
            on_complete: Callback when done (exit_code: int, duration: float)
            cwd: Working directory
        """
        self.running = True
        self.start_time = time.time()
        self.last_output_time = self.start_time
        self.lines = []
        self.exit_code = None

        try:
            # Start subprocess
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )

            # Read both stdout and stderr concurrently
            async def read_stream(stream, stream_type):
                while True:
                    line = await stream.readline()
                    if not line:
                        break

                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    self.last_output_time = time.time()
                    self.lines.append((stream_type, decoded_line))

                    if on_line:
                        on_line(stream_type, decoded_line)

            # Wait for both streams
            await asyncio.gather(
                read_stream(self.process.stdout, 'stdout'),
                read_stream(self.process.stderr, 'stderr')
            )

            # Wait for process to complete
            await self.process.wait()
            self.exit_code = self.process.returncode

        except Exception as e:
            if on_line:
                on_line('stderr', f"Error running command: {e}")
            self.exit_code = -1

        finally:
            self.running = False
            duration = time.time() - self.start_time

            if on_complete:
                on_complete(self.exit_code, duration)

    async def terminate(self):
        """Terminate the running process."""
        if self.process and self.running:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    def is_stalled(self, threshold_seconds: int = 30) -> bool:
        """Check if output has stalled."""
        if not self.running or not self.last_output_time:
            return False
        return (time.time() - self.last_output_time) > threshold_seconds

    def get_elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if not self.start_time:
            return 0.0
        return time.time() - self.start_time


class JobState:
    """Global state for tracking the current job."""

    def __init__(self):
        self.active_job = None  # None or dict with job info
        self.streamer = None  # CLIStreamer instance
        self.logs = []  # List of (timestamp, level, message)
        self.metrics = {
            'items_done': 0,
            'items_total': 0,
            'errors': 0,
            'throughput': 0.0
        }

    def reset(self):
        """Reset state for new job."""
        self.active_job = None
        self.streamer = None
        self.logs = []
        self.metrics = {
            'items_done': 0,
            'items_total': 0,
            'errors': 0,
            'throughput': 0.0
        }

    def parse_metrics(self, line: str):
        """Extract metrics from log lines if possible."""
        line_lower = line.lower()

        # Try to extract counts
        if 'processed' in line_lower or 'done' in line_lower:
            import re
            match = re.search(r'(\d+)\s*/\s*(\d+)', line)
            if match:
                self.metrics['items_done'] = int(match.group(1))
                self.metrics['items_total'] = int(match.group(2))

        # Count errors
        if 'error' in line_lower or 'failed' in line_lower:
            self.metrics['errors'] += 1

        # Calculate throughput
        if self.streamer and self.metrics['items_done'] > 0:
            elapsed = self.streamer.get_elapsed()
            if elapsed > 0:
                self.metrics['throughput'] = (self.metrics['items_done'] / elapsed) * 60


# Global job state
job_state = JobState()

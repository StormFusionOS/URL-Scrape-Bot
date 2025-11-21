"""Pytest runner utility for NiceGUI integration.

This module provides a wrapper around SubprocessRunner specifically designed
for running pytest test suites from the GUI.
"""

import sys
import os
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from .subprocess_runner import SubprocessRunner


class PytestRunner:
    """Wrapper for running pytest from the GUI with proper configuration."""

    def __init__(self, suite_name: str):
        """
        Initialize pytest runner for a specific test suite.

        Args:
            suite_name: Name identifier for the test suite (e.g., 'environment', 'safety')
        """
        self.suite_name = suite_name
        self.runner: Optional[SubprocessRunner] = None
        self.log_file: Optional[str] = None
        self.pid: Optional[int] = None

    def start(
        self,
        test_path: str,
        markers: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> int:
        """
        Start pytest run as a subprocess.

        Args:
            test_path: Path to test file or directory (relative to project root)
            markers: Pytest marker expression (e.g., "not slow", "acceptance")
            extra_args: Additional pytest command line arguments
            env_vars: Additional environment variables

        Returns:
            Process PID

        Raises:
            RuntimeError: If tests are already running
        """
        if self.is_running():
            raise RuntimeError(f"Test suite '{self.suite_name}' is already running (PID: {self.pid})")

        # Build pytest command
        cmd = [
            sys.executable,
            '-m', 'pytest',
            test_path,
            '-v',                # Verbose output
            '--tb=short',        # Short traceback format
            '--color=no',        # Disable ANSI color codes for easier parsing
            '-s',                # Show print statements (don't capture stdout)
        ]

        # Add marker filter if specified
        if markers:
            cmd.extend(['-m', markers])

        # Add any extra arguments
        if extra_args:
            cmd.extend(extra_args)

        # Create timestamped log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = f'logs/pytest_{self.suite_name}_{timestamp}.log'

        # Ensure logs directory exists
        Path('logs').mkdir(exist_ok=True)

        # Create subprocess runner
        self.runner = SubprocessRunner(
            job_id=f"pytest_{self.suite_name}_{timestamp}",
            log_file=self.log_file
        )

        # Prepare environment variables
        env = os.environ.copy()

        # Set PYTHONPATH to project root to ensure imports work
        env['PYTHONPATH'] = str(Path.cwd())

        # Ensure DATABASE_URL is set
        if 'DATABASE_URL' not in env:
            env['DATABASE_URL'] = 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db'

        # Add any custom environment variables
        if env_vars:
            env.update(env_vars)

        # Start the subprocess
        self.pid = self.runner.start(
            command=cmd,
            cwd=str(Path.cwd()),
            env=env
        )

        return self.pid

    def stop(self) -> bool:
        """
        Stop the running pytest subprocess.

        Returns:
            True if process was killed, False otherwise
        """
        if self.runner:
            killed = self.runner.kill()
            if killed:
                self.pid = None
            return killed
        return False

    def wait(self, timeout: Optional[int] = None) -> Optional[int]:
        """
        Wait for pytest subprocess to complete.

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            Exit code of the process, or None if timeout occurred
        """
        if self.runner:
            return self.runner.wait(timeout=timeout)
        return None

    def is_running(self) -> bool:
        """
        Check if pytest subprocess is currently running.

        Returns:
            True if running, False otherwise
        """
        if self.runner:
            return self.runner.is_running()
        return False

    def get_log_file(self) -> Optional[str]:
        """
        Get the path to the current log file.

        Returns:
            Path to log file, or None if no test run has been started
        """
        return self.log_file

    def get_pid(self) -> Optional[int]:
        """
        Get the process ID of the running test subprocess.

        Returns:
            PID if running, None otherwise
        """
        return self.pid if self.is_running() else None


def get_test_suite_path(suite: str) -> str:
    """
    Get the test file path for a named test suite.

    Args:
        suite: Suite name ('environment', 'safety', 'acceptance', 'all')

    Returns:
        Path to test file or directory

    Raises:
        ValueError: If suite name is unknown
    """
    suite_map = {
        'environment': 'tests/test_scraper_environment.py',
        'safety': 'tests/test_scraper_safety.py',
        'acceptance': 'tests/test_scraper_acceptance.py',
        'all': 'tests/'
    }

    if suite not in suite_map:
        raise ValueError(
            f"Unknown test suite '{suite}'. "
            f"Valid options: {', '.join(suite_map.keys())}"
        )

    return suite_map[suite]


def get_marker_expression(filter_option: str) -> Optional[str]:
    """
    Get pytest marker expression for a filter option.

    Args:
        filter_option: User-friendly filter name

    Returns:
        Pytest marker expression, or None for 'All Tests'
    """
    filter_map = {
        'All Tests': None,
        'Fast Only (no slow)': 'not slow',
        'Safety Only': 'safety',
        'Acceptance Only': 'acceptance',
        'Integration Only': 'integration',
    }

    return filter_map.get(filter_option)

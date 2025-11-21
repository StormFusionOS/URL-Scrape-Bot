"""Pytest output parser for real-time test result extraction.

This module provides functionality to parse pytest output lines and extract
structured test result data for display in the GUI.
"""

import re
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class TestStatus(Enum):
    """Test result status."""
    PASSED = 'PASSED'
    FAILED = 'FAILED'
    SKIPPED = 'SKIPPED'
    ERROR = 'ERROR'
    XFAIL = 'XFAIL'  # Expected failure
    XPASS = 'XPASS'  # Unexpected pass


class LineType(Enum):
    """Type of pytest output line."""
    TEST_RESULT = 'test_result'
    SUMMARY = 'summary'
    SECTION_HEADER = 'section_header'
    ERROR_LINE = 'error_line'
    LOG = 'log'
    COLLECTING = 'collecting'


@dataclass
class TestResult:
    """Parsed test result information."""
    type: LineType
    file: Optional[str] = None
    test_class: Optional[str] = None
    test_name: Optional[str] = None
    full_name: Optional[str] = None
    status: Optional[TestStatus] = None
    progress: Optional[int] = None  # Percentage (0-100)
    duration: Optional[float] = None  # Seconds


@dataclass
class TestSummary:
    """Parsed test suite summary."""
    type: LineType = LineType.SUMMARY
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0
    xfailed: int = 0
    xpassed: int = 0
    total: int = 0
    duration: float = 0.0


class PytestOutputParser:
    """Parser for pytest verbose output."""

    # Regex patterns for pytest output
    # Example: "tests/test_scraper_safety.py::TestRobots::test_robots PASSED [ 12%]"
    TEST_RESULT_PATTERN = re.compile(
        r'^(.+?)::(.*?)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\s+\[\s*(\d+)%\]'
    )

    # Example: "===== 27 passed, 10 failed, 5 skipped in 5.23s ====="
    SUMMARY_PATTERN = re.compile(
        r'=+\s+'
        r'(?:(\d+)\s+passed)?'
        r'(?:,\s*(\d+)\s+failed)?'
        r'(?:,\s*(\d+)\s+skipped)?'
        r'(?:,\s*(\d+)\s+error)?'
        r'(?:,\s*(\d+)\s+xfailed)?'
        r'(?:,\s*(\d+)\s+xpassed)?'
        r'.*?in\s+([\d.]+)s'
    )

    # Example: "===== test session starts ====="
    SECTION_HEADER_PATTERN = re.compile(r'^=+\s+(.+?)\s+=+$')

    # Example: "collecting ... collected 37 items"
    COLLECTING_PATTERN = re.compile(r'collecting.*collected\s+(\d+)\s+items?')

    # Example: "FAILED tests/test.py::test_name - AssertionError: ..."
    ERROR_LINE_PATTERN = re.compile(r'^(FAILED|ERROR)\s+(.+?)\s+-\s+(.+)$')

    def __init__(self):
        """Initialize parser state."""
        self.total_tests = 0
        self.tests_completed = 0

    def parse_line(self, line: str) -> Optional[Any]:
        """
        Parse a single line of pytest output.

        Args:
            line: Raw output line from pytest

        Returns:
            Parsed result object (TestResult, TestSummary, or dict), or None if not parseable
        """
        line = line.strip()
        if not line:
            return None

        # Try parsing as test result
        result = self._parse_test_result(line)
        if result:
            self.tests_completed += 1
            return result

        # Try parsing as summary
        summary = self._parse_summary(line)
        if summary:
            return summary

        # Try parsing as collection info
        collected = self._parse_collecting(line)
        if collected:
            return collected

        # Try parsing as section header
        header = self._parse_section_header(line)
        if header:
            return header

        # Try parsing as error line
        error = self._parse_error_line(line)
        if error:
            return error

        # Return as generic log line
        return {'type': LineType.LOG, 'message': line}

    def _parse_test_result(self, line: str) -> Optional[TestResult]:
        """Parse a test result line."""
        match = self.TEST_RESULT_PATTERN.match(line)
        if not match:
            return None

        file_path = match.group(1)
        test_path = match.group(2)
        status_str = match.group(3)
        progress = int(match.group(4))

        # Parse test path (may be "TestClass::test_method" or just "test_function")
        test_parts = test_path.split('::')
        if len(test_parts) == 2:
            test_class = test_parts[0]
            test_name = test_parts[1]
        else:
            test_class = None
            test_name = test_parts[0]

        return TestResult(
            type=LineType.TEST_RESULT,
            file=file_path,
            test_class=test_class,
            test_name=test_name,
            full_name=f"{file_path}::{test_path}",
            status=TestStatus[status_str],
            progress=progress
        )

    def _parse_summary(self, line: str) -> Optional[TestSummary]:
        """Parse a test summary line."""
        match = self.SUMMARY_PATTERN.search(line)
        if not match:
            return None

        passed = int(match.group(1) or 0)
        failed = int(match.group(2) or 0)
        skipped = int(match.group(3) or 0)
        error = int(match.group(4) or 0)
        xfailed = int(match.group(5) or 0)
        xpassed = int(match.group(6) or 0)
        duration = float(match.group(7))

        total = passed + failed + skipped + error

        return TestSummary(
            passed=passed,
            failed=failed,
            skipped=skipped,
            error=error,
            xfailed=xfailed,
            xpassed=xpassed,
            total=total,
            duration=duration
        )

    def _parse_collecting(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse test collection line."""
        match = self.COLLECTING_PATTERN.search(line)
        if not match:
            return None

        self.total_tests = int(match.group(1))

        return {
            'type': LineType.COLLECTING,
            'total_tests': self.total_tests,
            'message': line
        }

    def _parse_section_header(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse section header line."""
        match = self.SECTION_HEADER_PATTERN.match(line)
        if not match:
            return None

        return {
            'type': LineType.SECTION_HEADER,
            'section': match.group(1),
            'message': line
        }

    def _parse_error_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse error detail line."""
        match = self.ERROR_LINE_PATTERN.match(line)
        if not match:
            return None

        return {
            'type': LineType.ERROR_LINE,
            'status': match.group(1),
            'test': match.group(2),
            'error': match.group(3),
            'message': line
        }

    def reset(self):
        """Reset parser state for a new test run."""
        self.total_tests = 0
        self.tests_completed = 0


def get_status_color(status: TestStatus) -> str:
    """
    Get UI color for a test status.

    Args:
        status: Test status

    Returns:
        Color name (for NiceGUI color prop)
    """
    color_map = {
        TestStatus.PASSED: 'positive',  # Green
        TestStatus.FAILED: 'negative',  # Red
        TestStatus.SKIPPED: 'warning',  # Yellow/Orange
        TestStatus.ERROR: 'negative',   # Red
        TestStatus.XFAIL: 'info',       # Blue
        TestStatus.XPASS: 'warning',    # Yellow/Orange
    }
    return color_map.get(status, 'grey')


def get_status_icon(status: TestStatus) -> str:
    """
    Get icon for a test status.

    Args:
        status: Test status

    Returns:
        Material icon name
    """
    icon_map = {
        TestStatus.PASSED: 'check_circle',
        TestStatus.FAILED: 'error',
        TestStatus.SKIPPED: 'remove_circle',
        TestStatus.ERROR: 'warning',
        TestStatus.XFAIL: 'info',
        TestStatus.XPASS: 'help',
    }
    return icon_map.get(status, 'circle')


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "5.23s", "1m 30s", "1h 15m")
    """
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

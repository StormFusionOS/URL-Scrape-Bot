"""Testing Page - Automated Pytest Test Suite Runner.

This page provides a GUI interface for running and monitoring the automated
pytest test suite with real-time results, live log streaming, and interactive controls.
"""

from nicegui import ui
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..utils.pytest_runner import PytestRunner, get_test_suite_path, get_marker_expression
from ..utils.test_parser import (
    PytestOutputParser,
    TestResult,
    TestSummary,
    LineType,
    TestStatus,
    get_status_color,
    get_status_icon,
    format_duration
)


class TestingPageState:
    """State management for the Testing page."""

    def __init__(self):
        """Initialize page state."""
        # Runner state
        self.runner: Optional[PytestRunner] = None
        self.running = False
        self.current_suite: Optional[str] = None
        self.current_filter: str = 'All Tests'
        self.active_tab_suite: str = 'environment'  # Track which tab is active

        # Parser
        self.parser = PytestOutputParser()

        # Test results
        self.test_results: List[Dict[str, Any]] = []
        self.summary: Optional[TestSummary] = None

        # Metrics
        self.tests_total = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_skipped = 0
        self.tests_error = 0
        self.duration = 0.0
        self.current_test = ""

        # UI component references
        self.progress_bar: Optional[ui.linear_progress] = None
        self.status_badge: Optional[ui.badge] = None
        self.passed_label: Optional[ui.label] = None
        self.failed_label: Optional[ui.label] = None
        self.skipped_label: Optional[ui.label] = None
        self.duration_label: Optional[ui.label] = None
        self.current_test_label: Optional[ui.label] = None
        self.log_viewer: Optional[ui.log] = None
        self.results_table: Optional[ui.table] = None

        # Control buttons
        self.run_button: Optional[ui.button] = None
        self.stop_button: Optional[ui.button] = None

    def reset_metrics(self):
        """Reset all metrics for a new test run."""
        self.tests_total = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_skipped = 0
        self.tests_error = 0
        self.duration = 0.0
        self.current_test = ""
        self.test_results = []
        self.summary = None
        self.parser.reset()

    def update_ui_metrics(self):
        """Update all UI metric labels."""
        if self.passed_label:
            self.passed_label.set_text(str(self.tests_passed))
        if self.failed_label:
            self.failed_label.set_text(str(self.tests_failed))
        if self.skipped_label:
            self.skipped_label.set_text(str(self.tests_skipped))
        if self.duration_label:
            self.duration_label.set_text(format_duration(self.duration))
        if self.current_test_label:
            self.current_test_label.set_text(self.current_test or 'Waiting...')


# Module-level state instance
state = TestingPageState()


async def run_test_suite(suite_name: str):
    """
    Run a test suite asynchronously with real-time output streaming.

    Args:
        suite_name: Name of the suite ('environment', 'safety', 'acceptance', 'all')
    """
    if state.running:
        # Don't use ui.notify() from async task - no context
        # Just log to console instead
        if state.log_viewer:
            state.log_viewer.push("⚠ Tests already running. Please wait or stop the current run.")
        return

    try:
        # Initialize state for new run
        state.running = True
        state.current_suite = suite_name
        state.reset_metrics()

        # Update UI to running state
        if state.status_badge:
            state.status_badge.props('color=info')
            state.status_badge.set_text('RUNNING')
        if state.progress_bar:
            state.progress_bar.set_value(0)
        if state.log_viewer:
            state.log_viewer.clear()
        if state.results_table:
            state.results_table.rows = []
        if state.run_button:
            state.run_button.props('disable')
        if state.stop_button:
            state.stop_button.props(remove='disable')

        state.update_ui_metrics()

        # Get test path
        test_path = get_test_suite_path(suite_name)

        # Get marker expression
        markers = get_marker_expression(state.current_filter)

        # Log start (don't use ui.notify() from async task - no context)
        if state.log_viewer:
            state.log_viewer.push(f">>> Starting {suite_name} test suite")
            state.log_viewer.push(f">>> Test path: {test_path}")
            if markers:
                state.log_viewer.push(f">>> Markers: {markers}")
            state.log_viewer.push("")

        # Start real-time streaming task
        asyncio.create_task(run_pytest_with_streaming(test_path, markers))

    except Exception as e:
        state.running = False
        # Don't use ui.notify() from async task - no context

        if state.status_badge:
            state.status_badge.props('color=negative')
            state.status_badge.set_text('ERROR')

        if state.log_viewer:
            state.log_viewer.push(f"ERROR: {e}")

        # Re-enable buttons
        if state.run_button:
            state.run_button.props(remove='disable')
        if state.stop_button:
            state.stop_button.props('disable')


async def run_pytest_with_streaming(test_path: str, markers: Optional[str] = None):
    """
    Run pytest with real-time output streaming via asyncio subprocess.

    This provides true WebSocket-like real-time updates as pytest generates output,
    rather than polling a log file.

    Args:
        test_path: Path to test file or directory
        markers: Optional pytest marker expression
    """
    import sys
    import os

    try:
        # Build pytest command
        cmd = [
            sys.executable,
            '-m', 'pytest',
            test_path,
            '-v',
            '--tb=short',
            '--color=no',
            '-s',  # Show print statements
        ]

        if markers:
            cmd.extend(['-m', markers])

        # Set up environment
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path.cwd())
        if 'DATABASE_URL' not in env:
            env['DATABASE_URL'] = 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db'

        # Start subprocess with real-time output capture
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
            env=env,
            cwd=str(Path.cwd())
        )

        # Store process for stop functionality
        state.runner = process

        if state.log_viewer:
            state.log_viewer.push(f">>> Process started (PID: {process.pid})")
            state.log_viewer.push("")

        # Stream output line by line in real-time
        while True:
            line_bytes = await process.stdout.readline()

            if not line_bytes:
                # Process finished
                break

            # Decode line
            line = line_bytes.decode('utf-8', errors='replace').rstrip()

            if line:
                # Parse line for test results
                parsed = state.parser.parse_line(line)

                # Update UI based on parsed data
                if parsed:
                    update_ui_from_parsed_line(parsed)

                # Push to log viewer immediately (real-time WebSocket-like)
                if state.log_viewer:
                    state.log_viewer.push(line)

        # Wait for process to complete
        exit_code = await process.wait()

        # Finalize test run
        finalize_test_run(exit_code)

    except Exception as e:
        state.running = False

        if state.log_viewer:
            state.log_viewer.push("")
            state.log_viewer.push(f"ERROR: {e}")

        if state.status_badge:
            state.status_badge.props('color=negative')
            state.status_badge.set_text('ERROR')

        # Don't use ui.notify() from async task - no context

        # Re-enable buttons
        if state.run_button:
            state.run_button.props(remove='disable')
        if state.stop_button:
            state.stop_button.props('disable')


def update_ui_from_parsed_line(parsed: Any):
    """
    Update UI components based on parsed pytest output.

    Args:
        parsed: Parsed line data (TestResult, TestSummary, or dict)
    """
    if isinstance(parsed, TestResult):
        # Update current test
        state.current_test = parsed.test_name or ""

        # Update metrics
        if parsed.status == TestStatus.PASSED:
            state.tests_passed += 1
        elif parsed.status == TestStatus.FAILED:
            state.tests_failed += 1
        elif parsed.status == TestStatus.SKIPPED:
            state.tests_skipped += 1
        elif parsed.status == TestStatus.ERROR:
            state.tests_error += 1

        # Update progress
        if state.progress_bar and parsed.progress is not None:
            state.progress_bar.set_value(parsed.progress / 100.0)

        # Add to results table
        result_row = {
            'test': parsed.test_name,
            'file': parsed.file,
            'status': parsed.status.value,
            'class': parsed.test_class or '-'
        }
        state.test_results.append(result_row)

        if state.results_table:
            state.results_table.rows.append(result_row)

        # Update metric labels
        state.update_ui_metrics()

    elif isinstance(parsed, TestSummary):
        # Final summary
        state.summary = parsed
        state.tests_total = parsed.total
        state.tests_passed = parsed.passed
        state.tests_failed = parsed.failed
        state.tests_skipped = parsed.skipped
        state.tests_error = parsed.error
        state.duration = parsed.duration

        state.update_ui_metrics()

    elif isinstance(parsed, dict):
        if parsed.get('type') == LineType.COLLECTING:
            state.tests_total = parsed.get('total_tests', 0)


def finalize_test_run(exit_code: Optional[int] = None):
    """
    Finalize the test run and update final UI state.

    Args:
        exit_code: Exit code from pytest process
    """
    state.running = False

    # Update status badge
    if state.status_badge:
        if exit_code == 0:
            state.status_badge.props('color=positive')
            state.status_badge.set_text('PASSED')
            # Don't use ui.notify() from async task - no context
        elif exit_code is not None:
            state.status_badge.props('color=negative')
            state.status_badge.set_text('FAILED')
            # Don't use ui.notify() from async task - no context
        else:
            state.status_badge.props('color=warning')
            state.status_badge.set_text('STOPPED')

    # Update final metrics
    state.update_ui_metrics()

    # Set progress to 100%
    if state.progress_bar:
        state.progress_bar.set_value(1.0)

    # Re-enable run button
    if state.run_button:
        state.run_button.props(remove='disable')
    if state.stop_button:
        state.stop_button.props('disable')

    # Add completion message to log
    if state.log_viewer:
        state.log_viewer.push("")
        if exit_code is not None:
            state.log_viewer.push(f">>> Test run completed (exit code: {exit_code})")
        else:
            state.log_viewer.push(f">>> Test run stopped")


def stop_tests():
    """Stop the currently running test suite."""
    if not state.running or not state.runner:
        ui.notify('No tests currently running', type='warning')
        return

    ui.notify('Stopping tests...', type='info')

    try:
        # Kill the asyncio subprocess
        if hasattr(state.runner, 'terminate'):
            state.runner.terminate()

            state.running = False

            if state.status_badge:
                state.status_badge.props('color=warning')
                state.status_badge.set_text('STOPPED')

            if state.log_viewer:
                state.log_viewer.push("")
                state.log_viewer.push(">>> Test run stopped by user")

            ui.notify('Tests stopped', type='warning')

            # Re-enable run button
            if state.run_button:
                state.run_button.props(remove='disable')
            if state.stop_button:
                state.stop_button.props('disable')
        else:
            ui.notify('Failed to stop tests', type='negative')

    except Exception as e:
        ui.notify(f'Error stopping tests: {e}', type='negative')


def clear_results():
    """Clear all test results and reset the UI."""
    if state.running:
        ui.notify('Cannot clear while tests are running', type='warning')
        return

    state.reset_metrics()

    if state.progress_bar:
        state.progress_bar.set_value(0)
    if state.status_badge:
        state.status_badge.props('color=grey')
        state.status_badge.set_text('READY')
    if state.log_viewer:
        state.log_viewer.clear()
    if state.results_table:
        state.results_table.rows = []

    state.update_ui_metrics()

    ui.notify('Results cleared', type='info')


def render_test_suite_tab(suite_name: str, test_count: int, description: str):
    """
    Render a test suite tab with controls and info.

    Args:
        suite_name: Display name of the suite
        test_count: Number of tests in this suite
        description: Description of what this suite tests
    """
    with ui.card().classes('w-full mb-4'):
        ui.label(suite_name).classes('text-xl font-bold')
        ui.label(description).classes('text-sm text-gray-400 mb-2')

        with ui.row().classes('gap-2'):
            ui.label(f'{test_count} tests').classes('text-sm')
            ui.icon('info').classes('text-sm')


def testing_page():
    """Main Testing page UI."""

    ui.label('Automated Test Suite').classes('text-3xl font-bold mb-4')
    ui.label('Run and monitor pytest test suites with real-time results').classes('text-gray-400 mb-6')

    # Summary Stats Cards
    with ui.row().classes('w-full gap-4 mb-4'):
        with ui.card().classes('flex-1 bg-green-900'):
            ui.label('Passed').classes('text-sm text-gray-300')
            state.passed_label = ui.label('0').classes('text-3xl font-bold')

        with ui.card().classes('flex-1 bg-red-900'):
            ui.label('Failed').classes('text-sm text-gray-300')
            state.failed_label = ui.label('0').classes('text-3xl font-bold')

        with ui.card().classes('flex-1 bg-yellow-900'):
            ui.label('Skipped').classes('text-sm text-gray-300')
            state.skipped_label = ui.label('0').classes('text-3xl font-bold')

        with ui.card().classes('flex-1 bg-blue-900'):
            ui.label('Duration').classes('text-sm text-gray-300')
            state.duration_label = ui.label('0.0s').classes('text-3xl font-bold')

    # Status and Progress Section
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Status:').classes('text-sm')
            state.status_badge = ui.badge('READY', color='grey').classes('text-lg px-4')

            ui.separator().props('vertical')

            ui.label('Current Test:').classes('text-sm')
            state.current_test_label = ui.label('Waiting...').classes('text-sm text-gray-400')

        ui.separator().classes('my-2')

        state.progress_bar = ui.linear_progress(value=0, show_value=True).props('instant-feedback').classes('w-full')

    # Control Panel
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('gap-2 items-center'):
            state.run_button = ui.button(
                'Run Selected Suite',
                icon='play_arrow',
                color='positive',
                on_click=lambda: None  # Will be set per tab
            ).props('outline')

            state.stop_button = ui.button(
                'Stop',
                icon='stop',
                color='negative',
                on_click=stop_tests
            ).props('outline disable')

            ui.button(
                'Clear Results',
                icon='clear_all',
                on_click=clear_results
            ).props('flat')

            ui.separator().props('vertical')

            # Marker filter
            filter_select = ui.select(
                ['All Tests', 'Fast Only (no slow)', 'Safety Only', 'Acceptance Only'],
                value='All Tests',
                label='Filter'
            ).classes('w-56')

            def update_filter(e):
                state.current_filter = e.value

            filter_select.on('update:model-value', update_filter)

    # Tab Selector for Different Test Suites
    with ui.tabs().classes('w-full') as tabs:
        tab_env = ui.tab('Environment (16 tests)', icon='check_circle')
        tab_safety = ui.tab('Safety (37 tests)', icon='security')
        tab_acceptance = ui.tab('Acceptance', icon='integration_instructions')
        tab_all = ui.tab('Run All Tests', icon='play_circle_filled')

    # Tab Panels
    with ui.tab_panels(tabs, value=tab_env).classes('w-full'):
        # Environment Tests Tab
        with ui.tab_panel(tab_env):
            render_test_suite_tab(
                'Environment Validation',
                16,
                'Verify database schema, service imports, connectivity, and configuration'
            )

            # Update active suite when tab is clicked
            tab_env.on('click', lambda: setattr(state, 'active_tab_suite', 'environment'))

        # Safety Tests Tab
        with ui.tab_panel(tab_safety):
            render_test_suite_tab(
                'Safety & Compliance',
                37,
                'Robots.txt compliance, rate limiting, quarantine, CAPTCHA detection, ethical crawling'
            )

            # Update active suite when tab is clicked
            tab_safety.on('click', lambda: setattr(state, 'active_tab_suite', 'safety'))

        # Acceptance Tests Tab
        with ui.tab_panel(tab_acceptance):
            render_test_suite_tab(
                'Acceptance & Integration',
                28,
                'SERP scraper, competitor crawler, citations, backlinks, review mode workflows'
            )

            # Update active suite when tab is clicked
            tab_acceptance.on('click', lambda: setattr(state, 'active_tab_suite', 'acceptance'))

        # Run All Tests Tab
        with ui.tab_panel(tab_all):
            render_test_suite_tab(
                'Complete Test Suite',
                80,
                'Run all test modules (environment, safety, acceptance)'
            )

            # Update active suite when tab is clicked
            tab_all.on('click', lambda: setattr(state, 'active_tab_suite', 'all'))

    # Initialize run button with single handler that uses active_tab_suite
    state.run_button.on('click', lambda: asyncio.create_task(run_test_suite(state.active_tab_suite)))

    # Live Log Viewer
    with ui.card().classes('w-full mb-4'):
        ui.label('Test Output').classes('text-lg font-bold mb-2')
        state.log_viewer = ui.log(max_lines=1000).classes('w-full h-96 bg-gray-900 text-sm font-mono')

    # Results Table
    with ui.card().classes('w-full'):
        ui.label('Test Results').classes('text-lg font-bold mb-2')

        state.results_table = ui.table(
            columns=[
                {'name': 'test', 'label': 'Test Name', 'field': 'test', 'align': 'left', 'sortable': True},
                {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center', 'sortable': True},
                {'name': 'class', 'label': 'Class', 'field': 'class', 'align': 'left', 'sortable': True},
                {'name': 'file', 'label': 'File', 'field': 'file', 'align': 'left', 'sortable': True},
            ],
            rows=[],
            row_key='test',
            pagination={'rowsPerPage': 50, 'sortBy': 'test'}
        ).classes('w-full')

        # Add custom status badges
        state.results_table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge :color="props.value === 'PASSED' ? 'positive' : props.value === 'FAILED' ? 'negative' : 'warning'">
                    {{ props.value }}
                </q-badge>
            </q-td>
        ''')

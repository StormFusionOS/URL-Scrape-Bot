"""
Live log viewer widget - tails log files in real-time and displays with color coding.

Uses NiceGUI's built-in WebSocket for real-time updates via ui.timer and proper binding.
"""

from nicegui import ui, app
from pathlib import Path
from datetime import datetime
import asyncio
import time
from typing import Optional, List
from collections import deque


class LiveLogViewer:
    """A reusable widget for tailing and displaying log files in real-time."""

    def __init__(self, log_file: str, max_lines: int = 500, auto_scroll: bool = True):
        """
        Initialize live log viewer.

        Args:
            log_file: Path to log file to tail
            max_lines: Maximum lines to keep in memory
            auto_scroll: Automatically scroll to bottom on new lines
        """
        # Convert to absolute path for reliability
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        self.log_file = str(log_path)

        self.max_lines = max_lines
        self.auto_scroll = auto_scroll
        self.log_element = None
        self.scroll_area = None
        self.timer = None
        self.file_position = 0
        self.is_tailing = False
        self.line_count = 0
        self.error_message = None

    def create(self) -> 'LiveLogViewer':
        """Create the UI elements for the log viewer."""
        with ui.card().classes('w-full'):
            # Header with controls
            with ui.row().classes('w-full items-center mb-2'):
                ui.label('Live Output').classes('text-xl font-bold')
                ui.space()

                # File status indicator
                log_path = Path(self.log_file)
                if log_path.exists():
                    status_text = f'📄 {log_path.name}'
                    status_class = 'text-green-400'
                else:
                    status_text = f'⚠️ {log_path.name} (not found)'
                    status_class = 'text-yellow-400'
                self.file_status_label = ui.label(status_text).classes(f'text-xs {status_class}')

                # Line count badge
                self.line_count_label = ui.label(f'{self.line_count} lines').classes(
                    'text-sm text-gray-400'
                )

                # Auto-scroll toggle
                self.autoscroll_toggle = ui.checkbox(
                    'Auto-scroll',
                    value=self.auto_scroll,
                    on_change=lambda e: setattr(self, 'auto_scroll', e.value)
                ).classes('text-sm')

                # Refresh button
                ui.button(
                    icon='refresh',
                    on_click=lambda: self.load_last_n_lines(100)
                ).props('flat dense').tooltip('Reload last 100 lines')

                # Clear button
                ui.button(
                    icon='clear_all',
                    on_click=self.clear
                ).props('flat dense').tooltip('Clear output')

            # Log display with scrolling
            self.scroll_area = ui.scroll_area().classes('w-full h-96 bg-gray-900 p-4 rounded font-mono text-sm')
            with self.scroll_area:
                self.log_element = ui.column().classes('w-full gap-0')

        return self

    def start_tailing(self):
        """Start tailing the log file with proper async WebSocket updates."""
        if self.is_tailing:
            return

        self.is_tailing = True

        # Only seek to end if file_position not already set
        # (e.g., by load_last_n_lines)
        if self.file_position == 0:
            log_path = Path(self.log_file)
            if log_path.exists():
                with open(log_path, 'r') as f:
                    f.seek(0, 2)  # Seek to end
                    self.file_position = f.tell()

        # Create timer to poll for new lines - use async callback for proper WebSocket updates
        if not self.timer:
            # Use a slightly slower interval but with proper async handling
            self.timer = ui.timer(0.5, self._async_tail_file)
        else:
            self.timer.active = True

    async def _async_tail_file(self):
        """Async wrapper for tail file that ensures proper UI updates."""
        if not self.is_tailing:
            return

        # Run the file read in background to not block the event loop
        await asyncio.get_event_loop().run_in_executor(None, self._tail_file_sync)

        # Force UI update after adding lines
        if hasattr(self, '_needs_scroll') and self._needs_scroll:
            if self.auto_scroll and self.scroll_area:
                self.scroll_area.scroll_to(percent=1.0)
            self._needs_scroll = False

    def _tail_file_sync(self):
        """Synchronous file reading part of tailing."""
        log_path = Path(self.log_file)

        # Update file status indicator
        if hasattr(self, 'file_status_label'):
            if log_path.exists():
                current_size = log_path.stat().st_size
                if current_size != self.file_position:
                    self.file_status_label.set_text(f'📄 {log_path.name} (active)')
                    self.file_status_label.classes(remove='text-yellow-400', add='text-green-400')
                else:
                    self.file_status_label.set_text(f'📄 {log_path.name} (idle)')
                    self.file_status_label.classes(remove='text-green-400 text-red-400', add='text-gray-400')
            else:
                self.file_status_label.set_text(f'⚠️ {log_path.name} (not found)')
                self.file_status_label.classes(remove='text-green-400', add='text-yellow-400')
                return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.file_position)
                new_lines = f.readlines()
                self.file_position = f.tell()

                if new_lines:
                    self._needs_scroll = True
                    for line in new_lines:
                        line = line.rstrip()
                        if line:
                            self._add_line(line)
        except Exception as e:
            print(f"Error tailing log {log_path.name}: {e}")

    def stop_tailing(self):
        """Stop tailing the log file."""
        self.is_tailing = False
        if self.timer:
            self.timer.active = False

    def _add_line(self, line: str):
        """Add a line to the log display with color coding."""
        if not self.log_element:
            return

        # Increment line count
        self.line_count += 1
        if self.line_count_label:
            self.line_count_label.set_text(f'{self.line_count} lines')

        # Color code based on log level and keywords
        color_class = self._get_line_color(line)

        with self.log_element:
            ui.label(line).classes(f'{color_class} leading-tight text-xs whitespace-pre-wrap')

        # Note: Auto-scroll is handled in _async_tail_file after all lines are added

    def _get_line_color(self, line: str) -> str:
        """Determine color class based on line content."""
        line_lower = line.lower()

        # Error levels (highest priority) - check for multiple patterns
        error_patterns = [
            ' error ', 'error:', '- error -',
            'exception', 'traceback', 'fatal',
            'fail ', 'failed'
        ]
        if any(pattern in line_lower for pattern in error_patterns):
            return 'text-red-400'

        # Warnings
        warning_patterns = [' warning ', 'warning:', '- warning -', 'warn:']
        if any(pattern in line_lower for pattern in warning_patterns):
            return 'text-yellow-400'

        # Success indicators
        if '✓' in line or 'success' in line_lower or 'complete' in line_lower:
            return 'text-green-400'

        # Processing indicators
        if 'processing' in line_lower or 'scraping' in line_lower or 'crawling' in line_lower:
            return 'text-cyan-400'

        # Progress indicators
        if 'found' in line_lower or 'saved' in line_lower or 'added' in line_lower:
            return 'text-purple-300'

        # Debug/trace
        if ' debug ' in line_lower or 'debug:' in line_lower:
            return 'text-gray-500'

        # INFO and general
        if ' info ' in line_lower or 'info:' in line_lower:
            return 'text-blue-300'

        # Default
        return 'text-gray-300'

    def clear(self):
        """Clear the log display."""
        if self.log_element:
            self.log_element.clear()
            self.line_count = 0
            if self.line_count_label:
                self.line_count_label.set_text('0 lines')

    def load_last_n_lines(self, n: int = 100):
        """Load the last N lines from the log file."""
        log_path = Path(self.log_file)

        # Update file status
        if hasattr(self, 'file_status_label'):
            if log_path.exists():
                self.file_status_label.set_text(f'📄 {log_path.name}')
                self.file_status_label.classes(remove='text-yellow-400 text-red-400', add='text-green-400')
            else:
                self.file_status_label.set_text(f'⚠️ {log_path.name} (not found)')
                self.file_status_label.classes(remove='text-green-400', add='text-yellow-400')
                return

        if not log_path.exists():
            if self.log_element:
                self.clear()
                with self.log_element:
                    ui.label(f'⚠️ Log file not found: {log_path}').classes('text-yellow-400')
            return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

                # Take last N lines
                last_lines = lines[-n:] if len(lines) > n else lines

                # Clear and add lines
                self.clear()
                for line in last_lines:
                    line = line.rstrip()
                    if line:
                        self._add_line(line)

                # Update file position
                f.seek(0, 2)
                self.file_position = f.tell()

                # Scroll to bottom after loading
                if self.auto_scroll and self.scroll_area:
                    self.scroll_area.scroll_to(percent=1.0)

        except Exception as e:
            error_msg = f"Error loading log {log_path.name}: {e}"
            print(error_msg)
            if hasattr(self, 'file_status_label'):
                self.file_status_label.set_text(f'❌ {log_path.name} (error)')
                self.file_status_label.classes(remove='text-green-400 text-yellow-400', add='text-red-400')
            if self.log_element:
                self.clear()
                with self.log_element:
                    ui.label(f'❌ Error: {e}').classes('text-red-400')

    def set_log_file(self, log_file: str):
        """Change the log file being tailed."""
        was_tailing = self.is_tailing
        if was_tailing:
            self.stop_tailing()

        self.log_file = log_file
        self.file_position = 0
        self.clear()

        if was_tailing:
            self.start_tailing()

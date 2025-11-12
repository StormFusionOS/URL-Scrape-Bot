"""
Live log viewer widget - tails log files in real-time and displays with color coding.
"""

from nicegui import ui
from pathlib import Path
from datetime import datetime
import asyncio


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
        self.log_file = log_file
        self.max_lines = max_lines
        self.auto_scroll = auto_scroll
        self.log_element = None
        self.timer = None
        self.file_position = 0
        self.is_tailing = False
        self.line_count = 0

    def create(self) -> 'LiveLogViewer':
        """Create the UI elements for the log viewer."""
        with ui.card().classes('w-full'):
            # Header with controls
            with ui.row().classes('w-full items-center mb-2'):
                ui.label('Live Output').classes('text-xl font-bold')
                ui.space()

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

                # Clear button
                ui.button(
                    icon='clear_all',
                    on_click=self.clear
                ).props('flat dense').tooltip('Clear output')

            # Log display with scrolling
            with ui.scroll_area().classes('w-full h-96 bg-gray-900 p-4 rounded font-mono text-sm'):
                self.log_element = ui.column().classes('w-full gap-0')

        return self

    def start_tailing(self):
        """Start tailing the log file."""
        if self.is_tailing:
            return

        self.is_tailing = True

        # Seek to end of file initially (only show new content)
        log_path = Path(self.log_file)
        if log_path.exists():
            with open(log_path, 'r') as f:
                f.seek(0, 2)  # Seek to end
                self.file_position = f.tell()

        # Create timer to poll for new lines
        if not self.timer:
            self.timer = ui.timer(0.5, self._tail_file)
        else:
            self.timer.active = True

    def stop_tailing(self):
        """Stop tailing the log file."""
        self.is_tailing = False
        if self.timer:
            self.timer.active = False

    def _tail_file(self):
        """Read new lines from log file."""
        if not self.is_tailing:
            return

        log_path = Path(self.log_file)
        if not log_path.exists():
            return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to last position
                f.seek(self.file_position)

                # Read new lines
                new_lines = f.readlines()

                # Update position
                self.file_position = f.tell()

                # Add new lines to display
                for line in new_lines:
                    line = line.rstrip()
                    if line:
                        self._add_line(line)

        except Exception as e:
            print(f"Error tailing log {self.log_file}: {e}")

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

    def _get_line_color(self, line: str) -> str:
        """Determine color class based on line content."""
        line_lower = line.lower()

        # Error levels (highest priority)
        if ' error ' in line_lower or 'error:' in line_lower or 'exception' in line_lower:
            return 'text-red-400'
        if ' warning ' in line_lower or 'warning:' in line_lower:
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
        if not log_path.exists():
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

        except Exception as e:
            print(f"Error loading log {self.log_file}: {e}")

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

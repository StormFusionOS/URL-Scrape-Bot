"""
Citation Crawler Real-Time Monitor Widget

Enhanced widget showing:
- Live citation scrape activity stream (WebSocket-like updates)
- Directory status (working/quarantined/skipped)
- Recent citation discoveries
- NAP consistency scores
- Per-directory statistics
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from nicegui import ui, app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


class CitationMonitor:
    """Real-time citation crawler monitoring widget with live WebSocket-like updates."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        # Use the selenium log file for more detailed output
        self.log_file = self.project_root / "logs" / "citation_crawler_selenium.log"
        # Fallback to regular log if selenium log doesn't exist
        if not self.log_file.exists():
            self.log_file = self.project_root / "logs" / "citation_crawler.log"

        # Database
        database_url = os.getenv("DATABASE_URL")
        self.engine = create_engine(database_url, echo=False) if database_url else None

        # Directory definitions (should match citation_crawler_selenium.py)
        self.directories = {
            "yellowpages": {"name": "Yellow Pages", "tier": 1},
            "manta": {"name": "Manta", "tier": 1},
            "bbb": {"name": "BBB", "tier": 2},
            "mapquest": {"name": "MapQuest", "tier": 2},
            "yelp": {"name": "Yelp", "tier": 3},
            "google_business": {"name": "Google Business", "tier": 4},
            "facebook": {"name": "Facebook", "tier": 4, "skip": True},
            "angies_list": {"name": "Angi", "tier": 4},
            "thumbtack": {"name": "Thumbtack", "tier": 4},
            "homeadvisor": {"name": "HomeAdvisor", "tier": 4},
        }

        # UI elements (set in render())
        self.status_badge = None
        self.stats_container = None
        self.live_stream_container = None
        self.scroll_area = None
        self.directory_grid = None
        self.citations_table = None
        self.timer = None
        self.line_count_label = None
        self.file_status_label = None

        # Track log position for live streaming
        self._file_position = 0
        self._line_count = 0
        self._is_tailing = False
        self._needs_scroll = False
        self.auto_scroll = True

    def get_citation_stats(self) -> Dict[str, Any]:
        """Get overall citation statistics."""
        if not self.engine:
            return {"total": 0, "found": 0, "avg_nap": 0}

        try:
            with Session(self.engine) as session:
                # Count total citations and calculate averages
                query = text("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN (metadata->>'is_present')::boolean = true THEN 1 END) as found,
                        AVG(nap_match_score) as avg_nap,
                        COUNT(DISTINCT business_name) as businesses
                    FROM citations
                    WHERE discovered_at > NOW() - INTERVAL '30 days'
                """)

                result = session.execute(query).fetchone()
                return {
                    "total": result[0] or 0,
                    "found": result[1] or 0,
                    "avg_nap": round(result[2] or 0, 2),
                    "businesses": result[3] or 0,
                }
        except Exception as e:
            print(f"Error fetching citation stats: {e}")
            return {"total": 0, "found": 0, "avg_nap": 0, "businesses": 0}

    def get_directory_stats(self) -> List[Dict[str, Any]]:
        """Get per-directory citation statistics."""
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        directory_name,
                        COUNT(*) as total_checks,
                        COUNT(CASE WHEN (metadata->>'is_present')::boolean = true THEN 1 END) as found,
                        AVG(nap_match_score) as avg_nap,
                        MAX(last_verified_at) as last_check
                    FROM citations
                    WHERE discovered_at > NOW() - INTERVAL '30 days'
                    GROUP BY directory_name
                    ORDER BY directory_name
                """)

                results = session.execute(query).fetchall()
                return [
                    {
                        "directory": row[0],
                        "name": self.directories.get(row[0], {}).get("name", row[0]),
                        "tier": self.directories.get(row[0], {}).get("tier", 5),
                        "checks": row[1] or 0,
                        "found": row[2] or 0,
                        "success_rate": round((row[2] or 0) / (row[1] or 1) * 100, 1),
                        "avg_nap": round(row[3] or 0, 2),
                        "last_check": row[4].strftime("%Y-%m-%d %H:%M") if row[4] else "Never",
                        "skip": self.directories.get(row[0], {}).get("skip", False),
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching directory stats: {e}")
            return []

    def get_recent_citations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent citation discoveries."""
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        c.citation_id,
                        c.business_name,
                        c.directory_name,
                        c.nap_match_score,
                        c.listing_url,
                        c.last_verified_at,
                        c.metadata
                    FROM citations c
                    ORDER BY c.last_verified_at DESC
                    LIMIT :limit
                """)

                results = session.execute(query, {"limit": limit}).fetchall()
                return [
                    {
                        "id": row[0],
                        "business": (row[1][:40] + "...") if row[1] and len(row[1]) > 40 else (row[1] or "N/A"),
                        "directory": self.directories.get(row[2], {}).get("name", row[2]),
                        "directory_key": row[2],
                        "nap_score": round(row[3] or 0, 2),
                        "url": row[4],
                        "verified": row[5].strftime("%Y-%m-%d %H:%M") if row[5] else "N/A",
                        "is_found": row[6].get("is_present", False) if row[6] else False,
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error fetching recent citations: {e}")
            return []

    def _get_line_color(self, line: str) -> str:
        """Determine color class based on line content."""
        line_lower = line.lower()

        # Success indicators (highest priority for citation results)
        if 'success' in line_lower or 'found listing' in line_lower or '✓' in line:
            return 'text-green-400'

        # Error levels
        error_patterns = ['error', 'exception', 'traceback', 'fatal', 'fail']
        if any(pattern in line_lower for pattern in error_patterns):
            return 'text-red-400'

        # Warnings and blocks
        warning_patterns = ['warning', 'captcha', 'quarantine', 'skip', 'blocked']
        if any(pattern in line_lower for pattern in warning_patterns):
            return 'text-yellow-400'

        # Processing indicators
        if 'checking' in line_lower or 'starting' in line_lower or 'selenium' in line_lower:
            return 'text-cyan-400'

        # Driver ready
        if 'driver ready' in line_lower:
            return 'text-purple-400'

        # Info
        if 'info' in line_lower:
            return 'text-blue-300'

        # NAP scores
        if 'nap' in line_lower:
            return 'text-orange-300'

        # Default
        return 'text-gray-300'

    def _get_status_badge(self, success_rate: float, skip: bool = False) -> tuple:
        """Get badge color and text based on success rate."""
        if skip:
            return "gray", "SKIP"
        elif success_rate >= 50:
            return "green", "GOOD"
        elif success_rate >= 20:
            return "yellow", "FAIR"
        elif success_rate > 0:
            return "orange", "LOW"
        else:
            return "red", "FAIL"

    def _add_log_line(self, line: str):
        """Add a line to the live stream display."""
        if not self.live_stream_container:
            return

        self._line_count += 1
        if self.line_count_label:
            self.line_count_label.set_text(f'{self._line_count} lines')

        color_class = self._get_line_color(line)

        with self.live_stream_container:
            ui.label(line).classes(f'{color_class} leading-tight text-xs whitespace-pre-wrap font-mono')

    def _tail_file_sync(self):
        """Synchronous file reading for tailing."""
        log_path = Path(self.log_file)

        # Update file status
        if hasattr(self, 'file_status_label') and self.file_status_label:
            if log_path.exists():
                current_size = log_path.stat().st_size
                if current_size != self._file_position:
                    self.file_status_label.set_text(f'📄 {log_path.name} (active)')
                    self.file_status_label.classes(remove='text-yellow-400 text-gray-400', add='text-green-400')
                else:
                    self.file_status_label.set_text(f'📄 {log_path.name} (idle)')
                    self.file_status_label.classes(remove='text-green-400 text-red-400', add='text-gray-400')
            else:
                self.file_status_label.set_text(f'⚠️ {log_path.name} (not found)')
                self.file_status_label.classes(remove='text-green-400', add='text-yellow-400')
                return

        if not log_path.exists():
            return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self._file_position)
                new_lines = f.readlines()
                self._file_position = f.tell()

                if new_lines:
                    self._needs_scroll = True
                    for line in new_lines:
                        line = line.rstrip()
                        if line:
                            self._add_log_line(line)
        except Exception as e:
            print(f"Error tailing log: {e}")

    async def _async_tail_file(self):
        """Async wrapper for tailing that ensures proper UI updates."""
        if not self._is_tailing:
            return

        # Run file read in background thread
        await asyncio.get_event_loop().run_in_executor(None, self._tail_file_sync)

        # Auto-scroll after adding lines
        if self._needs_scroll and self.auto_scroll and self.scroll_area:
            self.scroll_area.scroll_to(percent=1.0)
            self._needs_scroll = False

    def start_tailing(self):
        """Start tailing the log file with WebSocket-like updates."""
        if self._is_tailing:
            return

        self._is_tailing = True

        # Seek to end if not already positioned
        if self._file_position == 0:
            log_path = Path(self.log_file)
            if log_path.exists():
                # Start from end minus a few KB to show recent activity
                file_size = log_path.stat().st_size
                self._file_position = max(0, file_size - 10000)  # Last ~10KB

        # Create async timer for polling
        if not self.timer:
            self.timer = ui.timer(0.3, self._async_tail_file)  # Fast polling for real-time feel
        else:
            self.timer.active = True

    def stop_tailing(self):
        """Stop tailing the log file."""
        self._is_tailing = False
        if self.timer:
            self.timer.active = False

    def load_last_n_lines(self, n: int = 100):
        """Load the last N lines from the log file."""
        log_path = Path(self.log_file)

        if not log_path.exists():
            if self.live_stream_container:
                self.live_stream_container.clear()
                with self.live_stream_container:
                    ui.label(f'⚠️ Log file not found: {log_path}').classes('text-yellow-400')
            return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-n:] if len(lines) > n else lines

                # Clear and reload
                if self.live_stream_container:
                    self.live_stream_container.clear()
                    self._line_count = 0

                for line in last_lines:
                    line = line.rstrip()
                    if line:
                        self._add_log_line(line)

                # Update file position
                f.seek(0, 2)
                self._file_position = f.tell()

                # Scroll to bottom
                if self.auto_scroll and self.scroll_area:
                    self.scroll_area.scroll_to(percent=1.0)

        except Exception as e:
            print(f"Error loading log: {e}")

    def clear_log(self):
        """Clear the log display."""
        if self.live_stream_container:
            self.live_stream_container.clear()
            self._line_count = 0
            if self.line_count_label:
                self.line_count_label.set_text('0 lines')

    async def _refresh_stats(self):
        """Refresh statistics (less frequently than log tailing)."""
        try:
            # Update stats
            stats = self.get_citation_stats()
            if self.stats_container:
                self.stats_container.clear()
                with self.stats_container:
                    with ui.row().classes('gap-4'):
                        with ui.card().classes('p-3'):
                            ui.label('Total Citations').classes('text-xs text-gray-400')
                            ui.label(str(stats['total'])).classes('text-2xl font-bold text-green-400')

                        with ui.card().classes('p-3'):
                            ui.label('Citations Found').classes('text-xs text-gray-400')
                            ui.label(str(stats['found'])).classes('text-2xl font-bold text-blue-400')

                        with ui.card().classes('p-3'):
                            ui.label('Avg NAP Score').classes('text-xs text-gray-400')
                            nap_color = 'text-green-400' if stats['avg_nap'] >= 0.7 else 'text-yellow-400' if stats['avg_nap'] >= 0.5 else 'text-red-400'
                            ui.label(f"{stats['avg_nap']:.2f}").classes(f'text-2xl font-bold {nap_color}')

                        with ui.card().classes('p-3'):
                            ui.label('Businesses').classes('text-xs text-gray-400')
                            ui.label(str(stats['businesses'])).classes('text-2xl font-bold text-purple-400')

            # Update directory grid
            dir_stats = self.get_directory_stats()
            if self.directory_grid:
                self.directory_grid.clear()
                with self.directory_grid:
                    for dir_stat in sorted(dir_stats, key=lambda x: x['tier']):
                        badge_color, badge_text = self._get_status_badge(
                            dir_stat['success_rate'],
                            dir_stat.get('skip', False)
                        )
                        with ui.card().classes('p-2'):
                            with ui.row().classes('items-center gap-2'):
                                ui.badge(f"T{dir_stat['tier']}", color='blue').classes('text-xs')
                                ui.label(dir_stat['name']).classes('font-semibold')
                                ui.badge(badge_text, color=badge_color)

                            with ui.column().classes('gap-1 mt-2'):
                                ui.label(f"Checks: {dir_stat['checks']} | Found: {dir_stat['found']}").classes('text-xs text-gray-400')
                                ui.label(f"Success: {dir_stat['success_rate']}%").classes('text-xs')
                                ui.label(f"NAP: {dir_stat['avg_nap']}").classes('text-xs')
                                ui.label(f"Last: {dir_stat['last_check']}").classes('text-xs text-gray-500')

            # Update citations table
            citations = self.get_recent_citations(15)
            if self.citations_table:
                self.citations_table.clear()
                with self.citations_table:
                    for cit in citations:
                        status_color = 'text-green-400' if cit['is_found'] else 'text-red-400'
                        status_icon = '✓' if cit['is_found'] else '✗'
                        nap_color = 'text-green-400' if cit['nap_score'] >= 0.7 else 'text-yellow-400' if cit['nap_score'] >= 0.5 else 'text-gray-400'

                        with ui.row().classes('w-full py-1 border-b border-gray-700 items-center gap-4'):
                            ui.label(f"{status_icon}").classes(f'{status_color} w-6')
                            ui.label(cit['business']).classes('w-48 truncate')
                            ui.label(cit['directory']).classes('w-24')
                            ui.label(f"{cit['nap_score']}").classes(f'{nap_color} w-16')
                            ui.label(cit['verified']).classes('w-32 text-xs text-gray-400')

        except Exception as e:
            print(f"Stats refresh error: {e}")

    def render(self):
        """Render the citation monitor widget."""
        with ui.card().classes('w-full'):
            # Header
            with ui.row().classes('w-full items-center mb-4'):
                ui.label('Citation Crawler Monitor').classes('text-xl font-bold')
                ui.space()
                ui.button('Refresh Stats', on_click=self._refresh_stats, icon='refresh').props('flat dense')

            # Stats row
            self.stats_container = ui.row().classes('w-full gap-4 mb-4')

            # Tabs
            with ui.tabs().classes('w-full') as tabs:
                live_tab = ui.tab('Live Stream', icon='terminal')
                dirs_tab = ui.tab('Directories', icon='folder')
                results_tab = ui.tab('Results', icon='list')

            with ui.tab_panels(tabs, value=live_tab).classes('w-full'):
                # Live Stream Tab - WebSocket-like real-time updates
                with ui.tab_panel(live_tab):
                    with ui.card().classes('w-full bg-gray-900'):
                        with ui.row().classes('w-full items-center mb-2'):
                            ui.label('Live Output').classes('font-semibold')
                            ui.space()

                            # File status indicator
                            log_path = Path(self.log_file)
                            status_text = f'📄 {log_path.name}' if log_path.exists() else f'⚠️ {log_path.name}'
                            status_class = 'text-green-400' if log_path.exists() else 'text-yellow-400'
                            self.file_status_label = ui.label(status_text).classes(f'text-xs {status_class}')

                            # Line count
                            self.line_count_label = ui.label(f'{self._line_count} lines').classes('text-sm text-gray-400 mx-2')

                            # Auto-scroll toggle
                            ui.checkbox(
                                'Auto-scroll',
                                value=self.auto_scroll,
                                on_change=lambda e: setattr(self, 'auto_scroll', e.value)
                            ).classes('text-sm')

                            # Control buttons
                            ui.button(icon='refresh', on_click=lambda: self.load_last_n_lines(100)).props('flat dense').tooltip('Load last 100 lines')
                            ui.button(icon='clear_all', on_click=self.clear_log).props('flat dense').tooltip('Clear output')

                        # Scrollable log area
                        self.scroll_area = ui.scroll_area().classes('h-96 w-full bg-gray-800 p-2 rounded')
                        with self.scroll_area:
                            self.live_stream_container = ui.column().classes('w-full gap-0')

                        # Load initial lines and start tailing
                        self.load_last_n_lines(50)
                        self.start_tailing()

                # Directories Tab
                with ui.tab_panel(dirs_tab):
                    ui.label('Directory Status').classes('font-semibold mb-2')
                    self.directory_grid = ui.row().classes('w-full flex-wrap gap-4')

                    # Add placeholder directories on first load
                    with self.directory_grid:
                        for key, dir_info in self.directories.items():
                            badge_color = "gray" if dir_info.get("skip") else "blue"
                            with ui.card().classes('p-2'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.badge(f"T{dir_info.get('tier', 5)}", color='blue').classes('text-xs')
                                    ui.label(dir_info['name']).classes('font-semibold')
                                    if dir_info.get("skip"):
                                        ui.badge("SKIP", color="gray")
                                    else:
                                        ui.badge("--", color="blue")

                # Results Tab
                with ui.tab_panel(results_tab):
                    ui.label('Recent Citations').classes('font-semibold mb-2')

                    # Header row
                    with ui.row().classes('w-full py-2 border-b border-gray-600 font-semibold text-sm'):
                        ui.label('').classes('w-6')
                        ui.label('Business').classes('w-48')
                        ui.label('Directory').classes('w-24')
                        ui.label('NAP').classes('w-16')
                        ui.label('Verified').classes('w-32')

                    self.citations_table = ui.column().classes('w-full')

            # Start stats refresh timer (less frequent than log tailing)
            ui.timer(10.0, self._refresh_stats)

            # Initial stats refresh
            ui.timer(0.5, self._refresh_stats, once=True)

        return self


def citation_monitor_widget():
    """Factory function to create and render citation monitor."""
    monitor = CitationMonitor()
    return monitor.render()

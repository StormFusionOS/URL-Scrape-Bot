"""
SERP Scraper Real-Time Monitor Widget

Auto-refreshing widget showing continuous SERP scraper status.
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from nicegui import ui
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


class SerpMonitor:
    """Real-time SERP scraper monitoring widget."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.progress_file = self.project_root / ".serp_scraper_progress.json"
        self.log_file = self.project_root / "logs" / "serp_scraper_service.log"

        # Database
        database_url = os.getenv("DATABASE_URL")
        self.engine = create_engine(database_url, echo=False) if database_url else None

        # UI elements (set in render())
        self.status_badge = None
        self.progress_label = None
        self.stats_container = None
        self.recent_table = None
        self.timer = None

    def get_service_status(self) -> Dict[str, Any]:
        """Get systemd service status."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "washbot-serp-scraper"],
                capture_output=True,
                text=True,
                timeout=2
            )
            is_active = result.stdout.strip() == "active"

            # Get PID and memory if active
            if is_active:
                status_result = subprocess.run(
                    ["systemctl", "show", "washbot-serp-scraper", "--property=MainPID,MemoryCurrent"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                pid = None
                memory_mb = None
                for line in status_result.stdout.splitlines():
                    if line.startswith("MainPID="):
                        pid = line.split("=")[1]
                    elif line.startswith("MemoryCurrent="):
                        memory_bytes = int(line.split("=")[1])
                        memory_mb = memory_bytes / (1024 * 1024)

                return {
                    "active": True,
                    "pid": pid,
                    "memory_mb": round(memory_mb, 1) if memory_mb else None
                }
            else:
                return {"active": False}
        except Exception as e:
            return {"active": False, "error": str(e)}

    def get_progress(self) -> Optional[Dict[str, Any]]:
        """Load progress from JSON file."""
        if not self.progress_file.exists():
            return None

        try:
            with open(self.progress_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def get_recent_scrapes(self, limit: int = 10) -> list:
        """Get recent SERP snapshots from database."""
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        sq.query_text,
                        ss.result_count,
                        ss.created_at,
                        (ss.metadata->>'total_results')::int as total_results
                    FROM serp_snapshots ss
                    JOIN search_queries sq ON ss.query_id = sq.query_id
                    ORDER BY ss.created_at DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {"limit": limit})
                return [
                    {
                        "query": row[0],
                        "results": row[1],
                        "total": row[3] or 0,
                        "time": row[2].strftime("%Y-%m-%d %H:%M")
                    }
                    for row in result.fetchall()
                ]
        except Exception as e:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate SERP statistics."""
        if not self.engine:
            return {}

        try:
            with Session(self.engine) as session:
                # Total snapshots
                total = session.execute(
                    text("SELECT COUNT(*) FROM serp_snapshots")
                ).scalar() or 0

                # Snapshots today
                today = session.execute(
                    text("""
                        SELECT COUNT(*) FROM serp_snapshots
                        WHERE DATE(created_at) = CURRENT_DATE
                    """)
                ).scalar() or 0

                # Our rankings
                our_rankings = session.execute(
                    text("""
                        SELECT COUNT(*) FROM serp_results
                        WHERE is_our_company = TRUE
                    """)
                ).scalar() or 0

                # Average position when we appear
                avg_position = session.execute(
                    text("""
                        SELECT AVG(position) FROM serp_results
                        WHERE is_our_company = TRUE
                    """)
                ).scalar() or 0

                return {
                    "total_snapshots": total,
                    "today_snapshots": today,
                    "our_rankings": our_rankings,
                    "avg_position": round(avg_position, 1) if avg_position else 0
                }
        except Exception:
            return {}

    async def update_display(self):
        """Update all display elements."""
        # Service status
        service = self.get_service_status()
        if service.get("active"):
            self.status_badge.set_text("RUNNING")
            self.status_badge.props("color=positive")
            if service.get("memory_mb"):
                self.status_badge.set_text(f"RUNNING ({service['memory_mb']} MB)")
        else:
            self.status_badge.set_text("STOPPED")
            self.status_badge.props("color=negative")

        # Progress
        progress = self.get_progress()
        if progress:
            cycle = progress.get("cycle_num", 0)
            scraped = progress.get("total_scraped", 0)
            captchas = progress.get("total_captchas", 0)
            last_id = progress.get("last_scraped_id", 0)

            self.progress_label.set_text(
                f"Cycle #{cycle} • {scraped} scraped • {captchas} CAPTCHAs • Last ID: {last_id}"
            )
        else:
            self.progress_label.set_text("No progress data yet")

        # Stats
        stats = self.get_stats()
        if stats:
            self.stats_container.clear()
            with self.stats_container:
                with ui.row().classes("w-full gap-4"):
                    with ui.card().classes("p-4"):
                        ui.label(f"{stats.get('total_snapshots', 0):,}").classes("text-2xl font-bold")
                        ui.label("Total Snapshots").classes("text-sm text-gray-500")

                    with ui.card().classes("p-4"):
                        ui.label(f"{stats.get('today_snapshots', 0)}").classes("text-2xl font-bold")
                        ui.label("Today").classes("text-sm text-gray-500")

                    with ui.card().classes("p-4"):
                        ui.label(f"{stats.get('our_rankings', 0):,}").classes("text-2xl font-bold")
                        ui.label("Our Rankings").classes("text-sm text-gray-500")

                    with ui.card().classes("p-4"):
                        avg_pos = stats.get('avg_position', 0)
                        ui.label(f"#{avg_pos}" if avg_pos else "N/A").classes("text-2xl font-bold")
                        ui.label("Avg Position").classes("text-sm text-gray-500")

        # Recent scrapes table
        recent = self.get_recent_scrapes(10)
        if recent:
            rows = [
                {
                    "query": r["query"][:50],
                    "results": r["results"],
                    "total": f"{r['total']:,}",
                    "time": r["time"]
                }
                for r in recent
            ]
            self.recent_table.update_rows(rows)

    def render(self) -> ui.card:
        """Render the SERP monitor widget."""
        with ui.card().classes("w-full p-6") as card:
            # Header
            with ui.row().classes("w-full items-center justify-between mb-4"):
                ui.label("SERP Scraper Monitor").classes("text-xl font-bold")
                self.status_badge = ui.badge("CHECKING...").props("color=grey")

            # Progress
            self.progress_label = ui.label("Loading progress...").classes("text-sm text-gray-600 mb-4")

            # Stats cards
            self.stats_container = ui.column().classes("w-full mb-6")

            # Recent scrapes table
            ui.label("Recent Scrapes").classes("text-lg font-bold mb-2")
            self.recent_table = ui.table(
                columns=[
                    {"name": "query", "label": "Query", "field": "query", "align": "left"},
                    {"name": "results", "label": "Results", "field": "results", "align": "center"},
                    {"name": "total", "label": "Total", "field": "total", "align": "center"},
                    {"name": "time", "label": "Time", "field": "time", "align": "right"},
                ],
                rows=[],
                row_key="query"
            ).classes("w-full")

            # Control buttons
            with ui.row().classes("w-full gap-2 mt-4"):
                ui.button("View Logs", on_click=lambda: ui.run_javascript(
                    "window.open('/logs?file=serp_scraper_service.log', '_blank')"
                )).props("outline color=primary")

                ui.button("Restart Service", on_click=self.restart_service).props("outline color=warning")

            # Auto-refresh every 5 seconds
            self.timer = ui.timer(5.0, self.update_display)

            # Initial update
            ui.timer(0.1, self.update_display, once=True)

        return card

    async def restart_service(self):
        """Restart the SERP scraper service."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", "washbot-serp-scraper"],
                check=True,
                timeout=5
            )
            ui.notify("SERP scraper service restarted", type="positive")
            await self.update_display()
        except Exception as e:
            ui.notify(f"Failed to restart service: {e}", type="negative")


# Singleton instance
_monitor = None

def get_serp_monitor() -> SerpMonitor:
    """Get or create singleton SERP monitor."""
    global _monitor
    if _monitor is None:
        _monitor = SerpMonitor()
    return _monitor

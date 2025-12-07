"""
SERP Scraper Real-Time Monitor Widget

Enhanced widget showing:
- Live scrape activity stream
- Recent SERP results with rankings
- PAA questions captured
- Priority queue status
- Service statistics
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from nicegui import ui
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


class SerpMonitor:
    """Real-time SERP scraper monitoring widget with live data display."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.progress_file = self.project_root / ".serp_scraper_progress.json"
        self.log_file = self.project_root / "logs" / "continuous_serp_scraper.log"

        # Database
        database_url = os.getenv("DATABASE_URL")
        self.engine = create_engine(database_url, echo=False) if database_url else None

        # UI elements (set in render())
        self.status_badge = None
        self.progress_label = None
        self.stats_container = None
        self.live_stream = None
        self.results_table = None
        self.paa_container = None
        self.queue_container = None
        self.timer = None

        # Track what we've shown to avoid duplicates
        self._last_snapshot_id = 0
        self._last_log_position = 0

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
                        try:
                            memory_bytes = int(line.split("=")[1])
                            memory_mb = memory_bytes / (1024 * 1024)
                        except (ValueError, IndexError):
                            pass

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
        """Get recent SERP snapshots with full result data."""
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        ss.snapshot_id,
                        sq.query_text,
                        ss.result_count,
                        ss.captured_at,
                        (ss.metadata->>'total_results')::bigint as total_results,
                        (ss.metadata->>'paa_count')::int as paa_count,
                        c.name as company_name
                    FROM serp_snapshots ss
                    JOIN search_queries sq ON ss.query_id = sq.query_id
                    LEFT JOIN companies c ON sq.company_id = c.id
                    ORDER BY ss.captured_at DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {"limit": limit})
                return [
                    {
                        "snapshot_id": row[0],
                        "query": row[1][:60] if row[1] else "N/A",
                        "results": row[2] or 0,
                        "total": row[4] or 0,
                        "paa": row[5] or 0,
                        "company": row[6] or "Unknown",
                        "time": row[3].strftime("%H:%M:%S") if row[3] else "N/A",
                        "date": row[3].strftime("%Y-%m-%d") if row[3] else "N/A",
                    }
                    for row in result.fetchall()
                ]
        except Exception as e:
            print(f"Error fetching recent scrapes: {e}")
            return []

    def get_latest_results(self, snapshot_id: int, limit: int = 10) -> list:
        """Get individual SERP results for a snapshot."""
        if not self.engine or not snapshot_id:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        position,
                        title,
                        url,
                        domain,
                        is_our_company,
                        is_competitor
                    FROM serp_results
                    WHERE snapshot_id = :snapshot_id
                    ORDER BY position
                    LIMIT :limit
                """)

                result = session.execute(query, {"snapshot_id": snapshot_id, "limit": limit})
                return [
                    {
                        "position": row[0],
                        "title": (row[1][:50] + "...") if row[1] and len(row[1]) > 50 else (row[1] or "N/A"),
                        "url": row[2],
                        "domain": row[3] or "N/A",
                        "is_ours": row[4],
                        "is_competitor": row[5],
                    }
                    for row in result.fetchall()
                ]
        except Exception as e:
            print(f"Error fetching results: {e}")
            return []

    def get_recent_paa(self, limit: int = 10) -> list:
        """Get recent People Also Ask questions."""
        if not self.engine:
            return []

        try:
            with Session(self.engine) as session:
                query = text("""
                    SELECT
                        question,
                        answer_snippet,
                        source_domain,
                        created_at
                    FROM serp_paa
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {"limit": limit})
                return [
                    {
                        "question": row[0],
                        "answer": (row[1][:100] + "...") if row[1] and len(row[1]) > 100 else (row[1] or ""),
                        "source": row[2] or "N/A",
                        "time": row[3].strftime("%H:%M") if row[3] else "N/A",
                    }
                    for row in result.fetchall()
                ]
        except Exception as e:
            print(f"Error fetching PAA: {e}")
            return []

    def get_priority_queue_status(self) -> Dict[str, Any]:
        """Get priority queue tier counts."""
        try:
            from seo_intelligence.services import get_serp_priority_queue
            queue = get_serp_priority_queue()

            tier_counts = queue.get_tier_counts()
            estimate = queue.get_estimated_completion(scrapes_per_day=30)

            return {
                "tiers": tier_counts,
                "estimate": estimate,
            }
        except Exception as e:
            print(f"Error getting queue status: {e}")
            return {"error": str(e)}

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
                        WHERE DATE(captured_at) = CURRENT_DATE
                    """)
                ).scalar() or 0

                # This week
                week = session.execute(
                    text("""
                        SELECT COUNT(*) FROM serp_snapshots
                        WHERE captured_at > NOW() - INTERVAL '7 days'
                    """)
                ).scalar() or 0

                # Our rankings found
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

                # Total PAA questions
                paa_count = session.execute(
                    text("SELECT COUNT(*) FROM serp_paa")
                ).scalar() or 0

                # Unique PAA questions
                paa_unique = session.execute(
                    text("SELECT COUNT(DISTINCT question) FROM serp_paa")
                ).scalar() or 0

                return {
                    "total_snapshots": total,
                    "today_snapshots": today,
                    "week_snapshots": week,
                    "our_rankings": our_rankings,
                    "avg_position": round(avg_position, 1) if avg_position else 0,
                    "paa_total": paa_count,
                    "paa_unique": paa_unique,
                }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}

    def get_recent_log_lines(self, num_lines: int = 20) -> List[str]:
        """Get recent log lines for live stream."""
        if not self.log_file.exists():
            return []

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to current position or end
                if self._last_log_position > 0:
                    f.seek(self._last_log_position)
                    new_lines = f.readlines()
                    self._last_log_position = f.tell()
                    return [line.strip() for line in new_lines if line.strip()][-num_lines:]
                else:
                    # First read - get last N lines
                    lines = f.readlines()
                    f.seek(0, 2)
                    self._last_log_position = f.tell()
                    return [line.strip() for line in lines if line.strip()][-num_lines:]
        except Exception as e:
            return [f"Error reading log: {e}"]

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
            last_update = progress.get("last_updated", "N/A")

            self.progress_label.set_text(
                f"Cycle #{cycle} | {scraped} scraped | {captchas} CAPTCHAs | Last ID: {last_id}"
            )
        else:
            self.progress_label.set_text("No progress data - scraper may not have run yet")

        # Stats cards
        await self._update_stats()

        # Live stream
        await self._update_live_stream()

        # Recent results table
        await self._update_results_table()

        # PAA questions
        await self._update_paa()

        # Priority queue
        await self._update_queue_status()

    async def _update_stats(self):
        """Update statistics cards."""
        stats = self.get_stats()
        if stats:
            self.stats_container.clear()
            with self.stats_container:
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    # Total Snapshots
                    with ui.card().classes("p-3 min-w-24"):
                        ui.label(f"{stats.get('total_snapshots', 0):,}").classes("text-xl font-bold text-blue-400")
                        ui.label("Total").classes("text-xs text-gray-500")

                    # Today
                    with ui.card().classes("p-3 min-w-24"):
                        today_val = stats.get('today_snapshots', 0)
                        color = "text-green-400" if today_val > 0 else "text-gray-400"
                        ui.label(f"{today_val}").classes(f"text-xl font-bold {color}")
                        ui.label("Today").classes("text-xs text-gray-500")

                    # This Week
                    with ui.card().classes("p-3 min-w-24"):
                        ui.label(f"{stats.get('week_snapshots', 0):,}").classes("text-xl font-bold text-cyan-400")
                        ui.label("This Week").classes("text-xs text-gray-500")

                    # Our Rankings
                    with ui.card().classes("p-3 min-w-24"):
                        ui.label(f"{stats.get('our_rankings', 0):,}").classes("text-xl font-bold text-purple-400")
                        ui.label("Our Rankings").classes("text-xs text-gray-500")

                    # Avg Position
                    with ui.card().classes("p-3 min-w-24"):
                        avg_pos = stats.get('avg_position', 0)
                        pos_color = "text-green-400" if avg_pos and avg_pos <= 10 else "text-yellow-400" if avg_pos and avg_pos <= 20 else "text-red-400"
                        ui.label(f"#{avg_pos}" if avg_pos else "N/A").classes(f"text-xl font-bold {pos_color}")
                        ui.label("Avg Position").classes("text-xs text-gray-500")

                    # PAA Questions
                    with ui.card().classes("p-3 min-w-24"):
                        ui.label(f"{stats.get('paa_unique', 0):,}").classes("text-xl font-bold text-orange-400")
                        ui.label("PAA Questions").classes("text-xs text-gray-500")

    async def _update_live_stream(self):
        """Update live activity stream."""
        lines = self.get_recent_log_lines(15)

        if lines:
            self.live_stream.clear()
            with self.live_stream:
                for line in lines[-15:]:  # Show last 15 lines
                    # Color code based on content
                    if "error" in line.lower() or "captcha" in line.lower():
                        color = "text-red-400"
                    elif "success" in line.lower() or "scraped" in line.lower() or "saved" in line.lower():
                        color = "text-green-400"
                    elif "warning" in line.lower() or "skip" in line.lower():
                        color = "text-yellow-400"
                    elif "processing" in line.lower() or "scraping" in line.lower():
                        color = "text-cyan-400"
                    else:
                        color = "text-gray-400"

                    # Truncate long lines
                    display_line = line[:120] + "..." if len(line) > 120 else line
                    ui.label(display_line).classes(f"text-xs font-mono {color} leading-tight")

    async def _update_results_table(self):
        """Update recent results table."""
        recent = self.get_recent_scrapes(8)

        if recent:
            # Check if we have new data
            newest_id = recent[0]["snapshot_id"] if recent else 0

            rows = [
                {
                    "time": r["time"],
                    "company": r["company"][:25] if r["company"] else "N/A",
                    "query": r["query"][:40],
                    "results": r["results"],
                    "paa": r["paa"],
                }
                for r in recent
            ]
            self.results_table.rows = rows
            self.results_table.update()

            # Update latest results preview if new snapshot
            if newest_id != self._last_snapshot_id and newest_id > 0:
                self._last_snapshot_id = newest_id
                await self._show_result_details(newest_id)

    async def _show_result_details(self, snapshot_id: int):
        """Show details of a specific snapshot's results."""
        results = self.get_latest_results(snapshot_id, limit=10)

        if results and hasattr(self, 'result_details'):
            self.result_details.clear()
            with self.result_details:
                ui.label("Latest SERP Results:").classes("text-sm font-bold text-gray-300 mb-1")
                for r in results:
                    # Highlight our company or competitors
                    if r["is_ours"]:
                        icon = "star"
                        color = "text-green-400"
                    elif r["is_competitor"]:
                        icon = "warning"
                        color = "text-orange-400"
                    else:
                        icon = ""
                        color = "text-gray-400"

                    with ui.row().classes("items-center gap-1"):
                        pos_color = "text-green-400" if r["position"] <= 3 else "text-yellow-400" if r["position"] <= 10 else "text-gray-400"
                        ui.label(f"#{r['position']}").classes(f"text-xs font-bold {pos_color} w-8")
                        if icon:
                            ui.icon(icon, size="xs").classes(color)
                        ui.label(r["title"]).classes(f"text-xs {color} truncate")
                        ui.label(f"({r['domain']})").classes("text-xs text-gray-500")

    async def _update_paa(self):
        """Update PAA questions display."""
        paa_questions = self.get_recent_paa(8)

        self.paa_container.clear()
        with self.paa_container:
            if paa_questions:
                for paa in paa_questions:
                    with ui.card().classes("p-2 mb-1 bg-gray-800"):
                        ui.label(f"Q: {paa['question']}").classes("text-xs font-semibold text-cyan-300")
                        if paa["answer"]:
                            ui.label(f"A: {paa['answer']}").classes("text-xs text-gray-400 mt-1")
                        ui.label(f"Source: {paa['source']} | {paa['time']}").classes("text-xs text-gray-600")
            else:
                ui.label("No PAA questions captured yet").classes("text-xs text-gray-500 italic")

    async def _update_queue_status(self):
        """Update priority queue status."""
        queue_status = self.get_priority_queue_status()

        self.queue_container.clear()
        with self.queue_container:
            if "error" in queue_status:
                ui.label(f"Queue unavailable: {queue_status['error']}").classes("text-xs text-yellow-400")
            elif queue_status.get("tiers"):
                tiers = queue_status["tiers"]
                estimate = queue_status.get("estimate", {})

                with ui.row().classes("gap-2 flex-wrap"):
                    # Tier counts
                    tier_colors = {
                        "never_scraped": "text-red-400",
                        "very_stale": "text-orange-400",
                        "stale": "text-yellow-400",
                        "moderate": "text-blue-400",
                        "fresh": "text-green-400",
                    }

                    for tier, count in tiers.items():
                        color = tier_colors.get(tier, "text-gray-400")
                        with ui.column().classes("items-center"):
                            ui.label(f"{count:,}").classes(f"text-sm font-bold {color}")
                            ui.label(tier.replace("_", " ").title()).classes("text-xs text-gray-500")

                # Estimate
                if estimate:
                    ui.separator().classes("my-2")
                    to_scrape = estimate.get("to_scrape", 0)
                    days = estimate.get("estimated_days", 0)
                    ui.label(f"To scrape: {to_scrape:,} companies").classes("text-xs text-gray-400")
                    ui.label(f"Est. completion: {days:.0f} days at 30/day").classes("text-xs text-gray-500")
            else:
                ui.label("No queue data available").classes("text-xs text-gray-500 italic")

    def render(self) -> ui.card:
        """Render the enhanced SERP monitor widget."""
        with ui.card().classes("w-full p-4") as card:
            # Header
            with ui.row().classes("w-full items-center justify-between mb-3"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("search", size="md").classes("text-blue-400")
                    ui.label("SERP Scraper Monitor").classes("text-xl font-bold")
                self.status_badge = ui.badge("CHECKING...").props("color=grey")

            # Progress
            self.progress_label = ui.label("Loading...").classes("text-sm text-gray-400 mb-3")

            # Stats cards
            self.stats_container = ui.row().classes("w-full mb-4")

            # Main content in tabs
            with ui.tabs().classes("w-full").props("dense") as tabs:
                tab_stream = ui.tab("stream", label="Live Stream", icon="stream")
                tab_results = ui.tab("results", label="Results", icon="list")
                tab_paa = ui.tab("paa", label="PAA Questions", icon="help")
                tab_queue = ui.tab("queue", label="Priority Queue", icon="queue")

            with ui.tab_panels(tabs, value="stream").classes("w-full"):
                # Live Stream Tab
                with ui.tab_panel("stream"):
                    ui.label("Live Activity Stream").classes("text-sm font-bold text-gray-300 mb-2")
                    self.live_stream = ui.column().classes(
                        "w-full h-48 bg-gray-900 p-3 rounded overflow-y-auto font-mono"
                    )
                    with self.live_stream:
                        ui.label("Waiting for activity...").classes("text-xs text-gray-500 italic")

                # Results Tab
                with ui.tab_panel("results"):
                    with ui.row().classes("w-full gap-4"):
                        # Recent scrapes table
                        with ui.column().classes("flex-1"):
                            ui.label("Recent Scrapes").classes("text-sm font-bold mb-2")
                            self.results_table = ui.table(
                                columns=[
                                    {"name": "time", "label": "Time", "field": "time", "align": "left"},
                                    {"name": "company", "label": "Company", "field": "company", "align": "left"},
                                    {"name": "query", "label": "Query", "field": "query", "align": "left"},
                                    {"name": "results", "label": "Results", "field": "results", "align": "center"},
                                    {"name": "paa", "label": "PAA", "field": "paa", "align": "center"},
                                ],
                                rows=[],
                                row_key="time"
                            ).classes("w-full").props("dense")

                        # Result details preview
                        with ui.column().classes("w-64"):
                            self.result_details = ui.column().classes("w-full")
                            with self.result_details:
                                ui.label("Select a scrape to view results").classes("text-xs text-gray-500 italic")

                # PAA Tab
                with ui.tab_panel("paa"):
                    ui.label("Recent People Also Ask Questions").classes("text-sm font-bold mb-2")
                    self.paa_container = ui.column().classes("w-full h-64 overflow-y-auto")
                    with self.paa_container:
                        ui.label("Loading...").classes("text-xs text-gray-500")

                # Queue Tab
                with ui.tab_panel("queue"):
                    ui.label("Priority Queue Status").classes("text-sm font-bold mb-2")
                    self.queue_container = ui.column().classes("w-full")
                    with self.queue_container:
                        ui.label("Loading...").classes("text-xs text-gray-500")

            # Control buttons
            ui.separator().classes("my-3")
            with ui.row().classes("w-full gap-2"):
                ui.button("View Full Logs", icon="article", on_click=lambda: ui.run_javascript(
                    "window.open('/logs?file=continuous_serp_scraper.log', '_blank')"
                )).props("outline color=primary size=sm")

                ui.button("Restart Service", icon="refresh", on_click=self.restart_service).props("outline color=warning size=sm")

                ui.button("Start Scraper", icon="play_arrow", on_click=self.start_service).props("outline color=positive size=sm")

                ui.button("Stop Scraper", icon="stop", on_click=self.stop_service).props("outline color=negative size=sm")

            # Auto-refresh every 3 seconds
            self.timer = ui.timer(3.0, self.update_display)

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

    async def start_service(self):
        """Start the SERP scraper service."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "start", "washbot-serp-scraper"],
                check=True,
                timeout=5
            )
            ui.notify("SERP scraper service started", type="positive")
            await self.update_display()
        except Exception as e:
            ui.notify(f"Failed to start service: {e}", type="negative")

    async def stop_service(self):
        """Stop the SERP scraper service."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "stop", "washbot-serp-scraper"],
                check=True,
                timeout=5
            )
            ui.notify("SERP scraper service stopped", type="info")
            await self.update_display()
        except Exception as e:
            ui.notify(f"Failed to stop service: {e}", type="negative")


# Singleton instance
_monitor = None

def get_serp_monitor() -> SerpMonitor:
    """Get or create singleton SERP monitor."""
    global _monitor
    if _monitor is None:
        _monitor = SerpMonitor()
    return _monitor

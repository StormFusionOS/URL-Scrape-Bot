"""
Unified SEO Dashboard Page

Single dashboard with individual Start/Stop controls for each SEO module:
- SERP (with ranking trends and traffic estimation)
- Citations
- Backlinks
- Technical Audits (with engagement, readability, CWV)
- SEO Worker
- Keyword Intelligence (Phase 2: autocomplete, volume, difficulty, opportunities)
- Competitive Analysis (Phase 3: keyword gaps, content gaps, backlink gaps)

Each module can be started/stopped independently with forceful termination.

Includes SEO Insights section showing:
- Content metrics (word count, content depth, header structure)
- Backlink quality (link placement breakdown)
- SERP features (sitelinks, PAA questions)
- Technical health (JS dependency analysis)
"""

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from nicegui import ui

from niceui.widgets.live_log_viewer import LiveLogViewer
from niceui.widgets.serp_monitor import get_serp_monitor
from niceui.widgets.citation_monitor import citation_monitor_widget
from niceui.services.job_monitoring import JobMonitoringService

# Database imports for SEO insights
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# Job monitoring service singleton
_job_monitor: Optional[JobMonitoringService] = None


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs" / "seo_modules"

# Ensure environment is loaded
load_dotenv(PROJECT_ROOT / '.env')

# Module configuration with worker scripts
MODULES = [
    {"name": "serp", "label": "SERP", "icon": "search", "worker_class": "SERPWorker"},
    {"name": "citations", "label": "Citations", "icon": "business", "worker_class": "CitationWorker"},
    {"name": "backlinks", "label": "Backlinks", "icon": "link", "worker_class": "BacklinkWorker"},
    {"name": "technical", "label": "Technical", "icon": "build", "worker_class": "TechnicalWorker"},
    {"name": "seo_worker", "label": "SEO Worker", "icon": "analytics", "worker_class": "SEOContinuousWorker"},
    {"name": "keyword_intel", "label": "Keywords", "icon": "key", "worker_class": "KeywordIntelligenceWorker"},
    {"name": "competitive", "label": "Competitive", "icon": "trending_up", "worker_class": "CompetitiveAnalysisWorker"},
]

# Database engine for SEO insights
_db_engine = None

# Global module runners - tracks running processes/threads per module
_module_runners: Dict[str, Dict[str, Any]] = {}


def get_db_engine():
    """Get or create database engine for SEO queries."""
    global _db_engine
    if _db_engine is None and DB_AVAILABLE:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            _db_engine = create_engine(database_url, echo=False)
    return _db_engine


def get_job_monitor() -> Optional[JobMonitoringService]:
    """Get or create job monitoring service."""
    global _job_monitor
    if _job_monitor is None:
        engine = get_db_engine()
        if engine:
            _job_monitor = JobMonitoringService(engine)
    return _job_monitor


def query_backlink_stats() -> Dict[str, Any]:
    """Query backlink statistics including placement breakdown."""
    engine = get_db_engine()
    if not engine:
        return {"error": "Database not available"}

    try:
        with Session(engine) as session:
            # Total backlinks
            total = session.execute(
                text("SELECT COUNT(*) FROM backlinks WHERE is_active = TRUE")
            ).scalar() or 0

            # Backlinks by placement (from metadata JSON)
            placement_stats = {
                "content": 0,
                "navigation": 0,
                "footer": 0,
                "sidebar": 0,
                "comments": 0,
                "author_bio": 0,
                "unknown": 0,
            }

            # Query backlinks with metadata
            rows = session.execute(
                text("""
                    SELECT metadata->>'placement' as placement, COUNT(*) as cnt
                    FROM backlinks
                    WHERE is_active = TRUE AND metadata->>'placement' IS NOT NULL
                    GROUP BY metadata->>'placement'
                """)
            ).fetchall()

            for row in rows:
                placement = row[0] or "unknown"
                if placement in placement_stats:
                    placement_stats[placement] = row[1]
                else:
                    placement_stats["unknown"] += row[1]

            # Editorial vs non-editorial
            editorial = session.execute(
                text("""
                    SELECT COUNT(*) FROM backlinks
                    WHERE is_active = TRUE
                    AND (metadata->>'is_editorial')::boolean = TRUE
                """)
            ).scalar() or 0

            # By link type
            link_types = {}
            type_rows = session.execute(
                text("""
                    SELECT link_type, COUNT(*) FROM backlinks
                    WHERE is_active = TRUE
                    GROUP BY link_type
                """)
            ).fetchall()
            for row in type_rows:
                link_types[row[0] or "unknown"] = row[1]

            return {
                "total": total,
                "placement": placement_stats,
                "editorial_count": editorial,
                "non_editorial_count": total - editorial,
                "link_types": link_types,
            }
    except Exception as e:
        return {"error": str(e)}


def query_technical_audit_stats() -> Dict[str, Any]:
    """Query technical audit statistics including JS rendering analysis."""
    engine = get_db_engine()
    if not engine:
        return {"error": "Database not available"}

    try:
        with Session(engine) as session:
            # Total audits
            total = session.execute(
                text("SELECT COUNT(*) FROM page_audits")
            ).scalar() or 0

            # Average scores
            avg_scores = session.execute(
                text("""
                    SELECT
                        AVG(overall_score) as avg_overall,
                        AVG(cwv_score) as avg_cwv
                    FROM page_audits
                    WHERE audited_at > NOW() - INTERVAL '7 days'
                """)
            ).fetchone()

            # JS dependency stats from metadata
            js_stats = session.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE (metadata->>'is_js_dependent')::boolean = TRUE) as js_dependent,
                        AVG((metadata->>'content_change_percent')::float) as avg_content_change,
                        AVG((metadata->>'js_added_links')::int) as avg_js_links
                    FROM page_audits
                    WHERE metadata->>'is_js_dependent' IS NOT NULL
                    AND audited_at > NOW() - INTERVAL '7 days'
                """)
            ).fetchone()

            # CWV rating breakdown
            cwv_ratings = session.execute(
                text("""
                    SELECT lcp_rating, COUNT(*) FROM page_audits
                    WHERE lcp_rating IS NOT NULL
                    AND audited_at > NOW() - INTERVAL '7 days'
                    GROUP BY lcp_rating
                """)
            ).fetchall()

            return {
                "total_audits": total,
                "avg_overall_score": round(avg_scores[0] or 0, 1) if avg_scores else 0,
                "avg_cwv_score": round(avg_scores[1] or 0, 1) if avg_scores else 0,
                "js_dependent_pages": js_stats[0] if js_stats else 0,
                "avg_content_change": round(js_stats[1] or 0, 1) if js_stats else 0,
                "avg_js_links_added": round(js_stats[2] or 0, 1) if js_stats else 0,
                "cwv_ratings": {row[0]: row[1] for row in cwv_ratings} if cwv_ratings else {},
            }
    except Exception as e:
        return {"error": str(e)}


def query_serp_stats() -> Dict[str, Any]:
    """Query SERP statistics including sitelinks and PAA data."""
    engine = get_db_engine()
    if not engine:
        return {"error": "Database not available"}

    try:
        with Session(engine) as session:
            # Total SERP snapshots
            total = session.execute(
                text("SELECT COUNT(*) FROM serp_snapshots")
            ).scalar() or 0

            # Recent snapshots (last 24h)
            recent = session.execute(
                text("""
                    SELECT COUNT(*) FROM serp_snapshots
                    WHERE captured_at > NOW() - INTERVAL '24 hours'
                """)
            ).scalar() or 0

            # PAA questions captured (from serp_paa table)
            paa_total = session.execute(
                text("""
                    SELECT COUNT(*) FROM serp_paa
                """)
            ).scalar() or 0

            # Unique PAA questions
            paa_unique = session.execute(
                text("""
                    SELECT COUNT(DISTINCT question) FROM serp_paa
                """)
            ).scalar() or 0

            # Sitelinks captured (from metadata)
            sitelinks_count = session.execute(
                text("""
                    SELECT COUNT(*) FROM serp_snapshots
                    WHERE metadata->>'sitelinks' IS NOT NULL
                    AND jsonb_array_length(metadata->'sitelinks') > 0
                """)
            ).scalar() or 0

            # Top SERP features detected
            features = session.execute(
                text("""
                    SELECT feature, COUNT(*) as cnt
                    FROM (
                        SELECT jsonb_array_elements_text(metadata->'serp_features') as feature
                        FROM serp_snapshots
                        WHERE metadata->'serp_features' IS NOT NULL
                        AND captured_at > NOW() - INTERVAL '7 days'
                    ) sub
                    GROUP BY feature
                    ORDER BY cnt DESC
                    LIMIT 10
                """)
            ).fetchall()

            return {
                "total_snapshots": total,
                "recent_24h": recent,
                "paa_questions": paa_total,
                "paa_unique": paa_unique,
                "with_sitelinks": sitelinks_count,
                "top_features": {row[0]: row[1] for row in features} if features else {},
            }
    except Exception as e:
        return {"error": str(e)}


def query_content_stats() -> Dict[str, Any]:
    """Query content metrics from content_analysis table."""
    engine = get_db_engine()
    if not engine:
        return {"error": "Database not available"}

    try:
        with Session(engine) as session:
            # Total pages analyzed
            total_analyzed = session.execute(
                text("SELECT COUNT(*) FROM content_analysis")
            ).scalar() or 0

            # Average word count and stats
            word_stats = session.execute(
                text("""
                    SELECT
                        AVG(word_count) as avg_words,
                        MAX(word_count) as max_words,
                        MIN(word_count) as min_words
                    FROM content_analysis
                    WHERE word_count IS NOT NULL
                """)
            ).fetchone()

            # Content depth distribution based on word count
            # thin: <300, moderate: 300-800, comprehensive: 800-1500, in-depth: >1500
            depth_stats = session.execute(
                text("""
                    SELECT
                        CASE
                            WHEN word_count < 300 THEN 'thin'
                            WHEN word_count < 800 THEN 'moderate'
                            WHEN word_count < 1500 THEN 'comprehensive'
                            ELSE 'in-depth'
                        END as depth,
                        COUNT(*) as cnt
                    FROM content_analysis
                    WHERE word_count IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1
                """)
            ).fetchall()

            # Average readability scores
            readability = session.execute(
                text("""
                    SELECT
                        AVG(flesch_reading_ease) as avg_readability,
                        AVG(flesch_kincaid_grade) as avg_grade
                    FROM content_analysis
                    WHERE flesch_reading_ease IS NOT NULL
                """)
            ).fetchone()

            # Heading stats
            heading_stats = session.execute(
                text("""
                    SELECT
                        AVG(heading_count) as avg_headings,
                        SUM(CASE WHEN heading_count = 0 THEN 1 ELSE 0 END) as no_headings
                    FROM content_analysis
                """)
            ).fetchone()

            return {
                "total_analyzed": total_analyzed,
                "depth_distribution": {row[0]: row[1] for row in depth_stats} if depth_stats else {},
                "avg_word_count": round(float(word_stats[0] or 0)) if word_stats else 0,
                "max_word_count": int(word_stats[1] or 0) if word_stats else 0,
                "avg_readability": round(float(readability[0] or 0), 1) if readability else 0,
                "avg_grade_level": round(float(readability[1] or 0), 1) if readability else 0,
                "avg_headings": round(float(heading_stats[0] or 0), 1) if heading_stats else 0,
                "pages_without_headings": int(heading_stats[1] or 0) if heading_stats else 0,
            }
    except Exception as e:
        return {"error": str(e)}


class ModuleRunner:
    """Manages running a single SEO module worker."""

    def __init__(self, module_name: str, worker_class: str, log_dir: Path):
        self.module_name = module_name
        self.worker_class = worker_class
        self.log_dir = log_dir
        self.log_file = log_dir / f"{module_name}.log"

        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._worker = None
        self._running = False
        self._stop_requested = False
        self._started_at: Optional[datetime] = None
        self._stats = {
            'companies_processed': 0,
            'companies_succeeded': 0,
            'companies_failed': 0,
        }

    def start(self):
        """Start the module worker in a background thread."""
        if self._running:
            return

        self._running = True
        self._stop_requested = False
        self._started_at = datetime.now()
        self._stats = {'companies_processed': 0, 'companies_succeeded': 0, 'companies_failed': 0}

        # Run in a separate thread
        self._thread = threading.Thread(
            target=self._run_worker,
            daemon=True,
            name=f"SEO-{self.module_name}"
        )
        self._thread.start()

        self._log(f"=== Started {self.module_name} worker ===")

    def _run_worker(self):
        """Run the worker (called in thread)."""
        try:
            # Import and instantiate the worker
            from seo_intelligence.workers import (
                SERPWorker,
                CitationWorker,
                BacklinkWorker,
                TechnicalWorker,
                SEOContinuousWorker,
                KeywordIntelligenceWorker,
                CompetitiveAnalysisWorker
            )

            worker_classes = {
                "SERPWorker": SERPWorker,
                "CitationWorker": CitationWorker,
                "BacklinkWorker": BacklinkWorker,
                "TechnicalWorker": TechnicalWorker,
                "SEOContinuousWorker": SEOContinuousWorker,
                "KeywordIntelligenceWorker": KeywordIntelligenceWorker,
                "CompetitiveAnalysisWorker": CompetitiveAnalysisWorker,
            }

            worker_cls = worker_classes.get(self.worker_class)
            if not worker_cls:
                self._log(f"[ERROR] Unknown worker class: {self.worker_class}")
                return

            self._worker = worker_cls(log_dir=str(self.log_dir))

            # Set up progress callback
            def progress_callback(last_id, processed, errors):
                self._stats['companies_processed'] = processed
                self._stats['companies_failed'] = errors
                self._stats['companies_succeeded'] = processed - errors

            self._worker.set_progress_callback(progress_callback)

            # Run the worker
            stats = self._worker.run()

            self._stats['companies_processed'] = stats.companies_processed
            self._stats['companies_succeeded'] = stats.companies_succeeded
            self._stats['companies_failed'] = stats.companies_failed

            self._log(f"=== Completed: {stats.companies_succeeded}/{stats.companies_processed} succeeded ===")

        except Exception as e:
            self._log(f"[ERROR] Worker crashed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._running = False
            self._worker = None

    def stop(self, force: bool = True):
        """Stop the module worker.

        Args:
            force: If True, forcefully terminate the worker thread
        """
        self._stop_requested = True
        self._log("Stop requested...")

        # Request graceful stop from worker
        if self._worker:
            self._worker.stop()

        # Wait briefly for graceful shutdown
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # If force and still running, we need to kill any spawned processes
        if force and self._thread and self._thread.is_alive():
            self._log("[FORCE] Forcefully terminating...")
            # Find and kill any child processes (Chrome, etc)
            self._kill_child_processes()

        self._running = False
        self._log("=== Stopped ===")

    def _kill_child_processes(self):
        """Kill any child processes spawned by the worker (Chrome, etc)."""
        try:
            import psutil
            current_pid = os.getpid()

            # Find all chrome/chromium processes that might be ours
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    pinfo = proc.info
                    name = pinfo['name'].lower() if pinfo['name'] else ''

                    # Kill chromium/chrome processes
                    if 'chrom' in name:
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            # psutil not available, try pkill
            try:
                subprocess.run(['pkill', '-f', 'chromium'], timeout=5)
                subprocess.run(['pkill', '-f', 'chrome'], timeout=5)
            except Exception:
                pass
        except Exception as e:
            self._log(f"[WARN] Error killing child processes: {e}")

    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        uptime = 0
        if self._started_at and self._running:
            uptime = (datetime.now() - self._started_at).total_seconds()

        return {
            'running': self._running,
            'started_at': self._started_at.isoformat() if self._started_at else None,
            'uptime_seconds': uptime,
            'companies_processed': self._stats.get('companies_processed', 0),
            'companies_succeeded': self._stats.get('companies_succeeded', 0),
            'companies_failed': self._stats.get('companies_failed', 0),
        }

    def _log(self, message: str):
        """Log message to module log file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass


def get_module_runner(module_name: str, worker_class: str) -> ModuleRunner:
    """Get or create a module runner."""
    global _module_runners

    if module_name not in _module_runners:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _module_runners[module_name] = ModuleRunner(
            module_name=module_name,
            worker_class=worker_class,
            log_dir=LOG_DIR
        )

    return _module_runners[module_name]


class SEODashboard:
    """Unified SEO Dashboard component with individual module controls."""

    def __init__(self):
        self.log_viewers: Dict[str, LiveLogViewer] = {}
        self.status_timer = None
        self.active_tab = "orchestrator"

        # UI elements per module
        self.module_cards: Dict[str, Dict[str, Any]] = {}

    def render(self):
        """Render the dashboard."""
        with ui.column().classes('w-full max-w-7xl mx-auto p-4 gap-4'):
            self._render_header()
            self._render_orchestrator_monitor()
            self._render_module_controls()
            self._render_seo_insights()
            self._render_serp_monitor()
            self._render_citation_monitor()
            self._render_tabbed_logs()

        # Start status update timer
        self.status_timer = ui.timer(2.0, self._update_status)

        # Start insights update timer (every 30 seconds)
        self.insights_timer = ui.timer(30.0, self._update_insights)

        # Start orchestrator monitor timer (every 5 seconds)
        self.orchestrator_timer = ui.timer(5.0, self._update_orchestrator_status)

        # Initial status update
        self._update_status()
        self._update_insights()
        self._update_orchestrator_status()

    def _render_header(self):
        """Render header with global controls."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center'):
                # Title
                ui.icon('dashboard', size='lg').classes('text-blue-400')
                ui.label('SEO Dashboard').classes('text-2xl font-bold ml-2')
                ui.label('(Individual Job Control)').classes('text-sm text-gray-400 ml-2')

                ui.space()

                # Global controls
                ui.button(
                    'Start All',
                    icon='play_arrow',
                    color='positive',
                    on_click=self._on_start_all
                ).props('dense')

                ui.button(
                    'Stop All',
                    icon='stop',
                    color='negative',
                    on_click=self._on_stop_all
                ).props('dense')

                ui.button(
                    'Clear All Logs',
                    icon='delete_sweep',
                    on_click=self._on_clear_logs
                ).props('outline dense')

    def _render_orchestrator_monitor(self):
        """Render the SEO Job Orchestrator monitoring section."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center mb-2'):
                ui.icon('monitor_heart', size='md').classes('text-green-400')
                ui.label('SEO Job Orchestrator').classes('text-xl font-bold ml-2')
                ui.space()
                # Live indicator
                with ui.row().classes('items-center gap-2'):
                    self.orchestrator_live_dot = ui.element('div').classes(
                        'w-3 h-3 rounded-full bg-gray-500'
                    )
                    self.orchestrator_live_label = ui.label('Offline').classes('text-sm text-gray-400')

            # Worker cards container
            self.orchestrator_workers_container = ui.column().classes('w-full gap-2')

            ui.separator().classes('my-3')

            # Queue stats row
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('items-center flex-1'):
                    self.queue_eligible = ui.label('0').classes('text-2xl font-bold text-blue-400')
                    ui.label('Eligible').classes('text-xs text-gray-400')

                with ui.column().classes('items-center flex-1'):
                    self.queue_pending = ui.label('0').classes('text-2xl font-bold text-orange-400')
                    ui.label('Pending').classes('text-xs text-gray-400')

                with ui.column().classes('items-center flex-1'):
                    self.queue_completed = ui.label('0').classes('text-2xl font-bold text-green-400')
                    ui.label('Completed').classes('text-xs text-gray-400')

                with ui.column().classes('items-center flex-1'):
                    self.queue_refresh = ui.label('0').classes('text-2xl font-bold text-purple-400')
                    ui.label('Due Refresh').classes('text-xs text-gray-400')

                with ui.column().classes('items-center flex-1'):
                    self.queue_percent = ui.label('0%').classes('text-2xl font-bold text-cyan-400')
                    ui.label('Complete').classes('text-xs text-gray-400')

            # Progress bar
            self.queue_progress = ui.linear_progress(value=0).classes('w-full mt-2')

            ui.separator().classes('my-3')

            # Keyword stats row
            ui.label('Keyword Tracking').classes('text-sm font-semibold text-gray-300 mb-2')
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('items-center flex-1'):
                    self.kw_total = ui.label('0').classes('text-lg font-bold text-blue-300')
                    ui.label('Total Keywords').classes('text-xs text-gray-500')

                with ui.column().classes('items-center flex-1'):
                    self.kw_companies = ui.label('0').classes('text-lg font-bold text-purple-300')
                    ui.label('Companies').classes('text-xs text-gray-500')

                with ui.column().classes('items-center flex-1'):
                    self.kw_t1 = ui.label('0').classes('text-lg font-bold text-gray-300')
                    ui.label('T1 Seeds').classes('text-xs text-gray-500')

                with ui.column().classes('items-center flex-1'):
                    self.kw_t2 = ui.label('0').classes('text-lg font-bold text-gray-300')
                    ui.label('T2 Location').classes('text-xs text-gray-500')

                with ui.column().classes('items-center flex-1'):
                    self.kw_t3 = ui.label('0').classes('text-lg font-bold text-gray-300')
                    ui.label('T3 Competitor').classes('text-xs text-gray-500')

                with ui.column().classes('items-center flex-1'):
                    self.kw_t4 = ui.label('0').classes('text-lg font-bold text-gray-300')
                    ui.label('T4 Autocomplete').classes('text-xs text-gray-500')

    def _update_orchestrator_status(self):
        """Update the orchestrator monitoring display."""
        monitor = get_job_monitor()
        if not monitor:
            return

        try:
            # Get worker status
            workers = monitor.get_worker_status()

            # Update live indicator
            running_workers = [w for w in workers if w['status'] == 'running']
            if running_workers:
                self.orchestrator_live_dot.classes('w-3 h-3 rounded-full bg-green-500 animate-pulse', remove='bg-gray-500 bg-red-500 bg-orange-500')
                self.orchestrator_live_label.set_text(f'{len(running_workers)} Running')
                self.orchestrator_live_label.classes('text-green-400', remove='text-gray-400 text-red-400 text-orange-400')
            elif any(w['status'] == 'stale' for w in workers):
                self.orchestrator_live_dot.classes('w-3 h-3 rounded-full bg-orange-500', remove='bg-gray-500 bg-green-500 bg-red-500 animate-pulse')
                self.orchestrator_live_label.set_text('Stale')
                self.orchestrator_live_label.classes('text-orange-400', remove='text-gray-400 text-green-400 text-red-400')
            else:
                self.orchestrator_live_dot.classes('w-3 h-3 rounded-full bg-gray-500', remove='bg-green-500 bg-red-500 bg-orange-500 animate-pulse')
                self.orchestrator_live_label.set_text('Offline')
                self.orchestrator_live_label.classes('text-gray-400', remove='text-green-400 text-red-400 text-orange-400')

            # Update worker cards
            self.orchestrator_workers_container.clear()
            with self.orchestrator_workers_container:
                if not workers:
                    ui.label('No workers registered. Start the orchestrator to begin processing.').classes('text-gray-500 text-sm')
                else:
                    for worker in workers:
                        self._render_worker_card(worker, monitor)

            # Get queue stats
            queue_stats = monitor.get_seo_queue_stats()
            self.queue_eligible.set_text(f"{queue_stats['eligible']:,}")
            self.queue_pending.set_text(f"{queue_stats['pending_initial']:,}")
            self.queue_completed.set_text(f"{queue_stats['completed_initial']:,}")
            self.queue_refresh.set_text(f"{queue_stats['due_refresh']:,}")
            self.queue_percent.set_text(f"{queue_stats['completion_percent']}%")
            self.queue_progress.set_value(queue_stats['completion_percent'] / 100)

            # Get keyword stats
            kw_stats = monitor.get_keyword_stats()
            self.kw_total.set_text(f"{kw_stats['total_keywords']:,}")
            self.kw_companies.set_text(f"{kw_stats['companies_with_keywords']:,}")
            self.kw_t1.set_text(f"{kw_stats['tier1']:,}")
            self.kw_t2.set_text(f"{kw_stats['tier2']:,}")
            self.kw_t3.set_text(f"{kw_stats['tier3']:,}")
            self.kw_t4.set_text(f"{kw_stats['tier4']:,}")

        except Exception as e:
            print(f"Error updating orchestrator status: {e}")

    def _render_worker_card(self, worker: Dict[str, Any], monitor: JobMonitoringService):
        """Render a single worker status card."""
        status = worker['status']
        status_colors = {
            'running': ('bg-green-900', 'text-green-400', 'border-green-600'),
            'stopped': ('bg-gray-800', 'text-gray-400', 'border-gray-600'),
            'failed': ('bg-red-900', 'text-red-400', 'border-red-600'),
            'stale': ('bg-orange-900', 'text-orange-400', 'border-orange-600'),
        }
        bg, text_color, border = status_colors.get(status, ('bg-gray-800', 'text-gray-400', 'border-gray-600'))

        with ui.card().classes(f'w-full {bg} border {border}'):
            with ui.row().classes('w-full items-center gap-4'):
                # Status indicator
                if status == 'running':
                    with ui.element('div').classes('relative'):
                        ui.element('div').classes('w-3 h-3 rounded-full bg-green-500 animate-ping absolute')
                        ui.element('div').classes('w-3 h-3 rounded-full bg-green-500 relative')
                else:
                    ui.element('div').classes(f'w-3 h-3 rounded-full {text_color.replace("text-", "bg-")}')

                # Worker info
                with ui.column().classes('flex-1 gap-0'):
                    ui.label(worker['worker_name']).classes(f'font-semibold {text_color}')
                    ui.label(f"{worker['hostname']} (PID: {worker['pid']})").classes('text-xs text-gray-500')

                # Stats
                with ui.row().classes('gap-4'):
                    with ui.column().classes('items-center'):
                        ui.label(str(worker['companies_processed'])).classes('font-bold text-purple-300')
                        ui.label('Companies').classes('text-xs text-gray-500')

                    with ui.column().classes('items-center'):
                        ui.label(str(worker['jobs_completed'])).classes('font-bold text-green-300')
                        ui.label('OK').classes('text-xs text-gray-500')

                    with ui.column().classes('items-center'):
                        ui.label(str(worker['jobs_failed'])).classes('font-bold text-red-300')
                        ui.label('Failed').classes('text-xs text-gray-500')

                    if worker.get('uptime_str'):
                        with ui.column().classes('items-center'):
                            ui.label(worker['uptime_str']).classes('font-bold text-blue-300')
                            ui.label('Uptime').classes('text-xs text-gray-500')

                # Status badge
                ui.badge(status.upper(), color='green' if status == 'running' else 'grey').classes('text-xs')

            # Current work
            if worker.get('current_module') and status == 'running':
                with ui.row().classes('mt-2 items-center gap-2'):
                    ui.spinner('dots', size='xs').classes('text-blue-400')
                    ui.label('Processing:').classes('text-xs text-gray-400')
                    ui.badge(worker['current_module'], color='blue').classes('text-xs')
                    if worker.get('current_company_id'):
                        company = monitor.get_company_being_processed(worker['current_company_id'])
                        if company:
                            ui.label(f"→ {company.get('name', 'Unknown')}").classes('text-xs font-semibold text-white')

    def _render_module_controls(self):
        """Render individual module control cards."""
        ui.label('Module Controls').classes('text-lg font-semibold mt-4')

        with ui.row().classes('w-full gap-3 flex-wrap'):
            for module in MODULES:
                with ui.card().classes('min-w-64 flex-1'):
                    with ui.column().classes('gap-2 p-2'):
                        # Header row with icon and name
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(module['icon'], size='md').classes('text-blue-400')
                            ui.label(module['label']).classes('font-semibold text-lg')
                            ui.space()
                            # Status badge
                            status_badge = ui.badge('stopped', color='grey').classes('text-xs')

                        # Stats row
                        stats_label = ui.label('0/0 processed').classes('text-sm text-gray-400')
                        uptime_label = ui.label('').classes('text-xs text-gray-500')

                        # Control buttons
                        with ui.row().classes('gap-2 mt-2'):
                            start_btn = ui.button(
                                'Start',
                                icon='play_arrow',
                                color='positive',
                                on_click=lambda m=module['name'], w=module['worker_class']: self._on_start_module(m, w)
                            ).props('dense size=sm')

                            stop_btn = ui.button(
                                'Stop',
                                icon='stop',
                                color='negative',
                                on_click=lambda m=module['name']: self._on_stop_module(m)
                            ).props('dense size=sm')

                        # Store references
                        self.module_cards[module['name']] = {
                            'badge': status_badge,
                            'stats': stats_label,
                            'uptime': uptime_label,
                            'start_btn': start_btn,
                            'stop_btn': stop_btn,
                            'worker_class': module['worker_class'],
                        }

    def _render_seo_insights(self):
        """Render SEO Insights section with data from new scrapers."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center mb-2'):
                ui.icon('insights', size='md').classes('text-green-400')
                ui.label('SEO Insights').classes('text-xl font-bold ml-2')
                ui.space()
                self.insights_refresh_btn = ui.button(
                    icon='refresh',
                    on_click=self._update_insights
                ).props('flat dense').classes('text-gray-400')

            # Create containers for each insights section
            with ui.row().classes('w-full gap-4'):
                # Content Metrics Card
                with ui.card().classes('flex-1'):
                    ui.label('Content Metrics').classes('font-semibold text-blue-400')
                    self.content_container = ui.column().classes('gap-1 mt-2')

                # Backlink Quality Card
                with ui.card().classes('flex-1'):
                    ui.label('Backlink Quality').classes('font-semibold text-green-400')
                    self.backlink_container = ui.column().classes('gap-1 mt-2')

                # SERP Features Card
                with ui.card().classes('flex-1'):
                    ui.label('SERP Features').classes('font-semibold text-yellow-400')
                    self.serp_container = ui.column().classes('gap-1 mt-2')

                # Technical Health Card
                with ui.card().classes('flex-1'):
                    ui.label('Technical Health').classes('font-semibold text-purple-400')
                    self.technical_container = ui.column().classes('gap-1 mt-2')

    def _render_serp_monitor(self):
        """Render the SERP scraper monitor widget."""
        monitor = get_serp_monitor()
        monitor.render()

    def _render_citation_monitor(self):
        """Render the Citation crawler monitor widget."""
        citation_monitor_widget()

    def _update_insights(self):
        """Update the SEO insights display with fresh data."""
        try:
            # Update Content Metrics
            self._update_content_insights()

            # Update Backlink Quality
            self._update_backlink_insights()

            # Update SERP Features
            self._update_serp_insights()

            # Update Technical Health
            self._update_technical_insights()

        except Exception as e:
            print(f"Error updating insights: {e}")

    def _update_content_insights(self):
        """Update content metrics display."""
        self.content_container.clear()
        stats = query_content_stats()

        with self.content_container:
            if "error" in stats:
                ui.label(f'Error: {stats["error"]}').classes('text-red-400 text-xs')
                return

            # Total analyzed
            ui.label(f'Pages Analyzed: {stats.get("total_analyzed", 0)}').classes('text-sm')

            # Average word count
            avg_words = stats.get("avg_word_count", 0)
            ui.label(f'Avg Word Count: {avg_words:,}').classes('text-sm')

            # Readability score
            readability = stats.get("avg_readability", 0)
            read_color = 'text-green-400' if readability >= 60 else 'text-yellow-400' if readability >= 30 else 'text-red-400'
            ui.label(f'Avg Readability: {readability}').classes(f'text-sm {read_color}')

            # Content depth distribution
            depth = stats.get("depth_distribution", {})
            if depth:
                ui.label('Content Depth:').classes('text-xs text-gray-400 mt-1')
                for level, count in depth.items():
                    color = {
                        'thin': 'text-red-400',
                        'moderate': 'text-yellow-400',
                        'comprehensive': 'text-green-400',
                        'in-depth': 'text-blue-400',
                    }.get(level, 'text-gray-300')
                    ui.label(f'  {level}: {count}').classes(f'text-xs {color}')

            # Pages without headings
            no_headings = stats.get("pages_without_headings", 0)
            if no_headings > 0:
                ui.label(f'No Headings: {no_headings}').classes('text-xs text-orange-400 mt-1')

    def _update_backlink_insights(self):
        """Update backlink quality display."""
        self.backlink_container.clear()
        stats = query_backlink_stats()

        with self.backlink_container:
            if "error" in stats:
                ui.label(f'Error: {stats["error"]}').classes('text-red-400 text-xs')
                return

            # Total backlinks
            ui.label(f'Total Backlinks: {stats.get("total", 0)}').classes('text-sm')

            # Editorial vs non-editorial
            editorial = stats.get("editorial_count", 0)
            non_editorial = stats.get("non_editorial_count", 0)
            if editorial + non_editorial > 0:
                editorial_pct = round(editorial / (editorial + non_editorial) * 100)
                ui.label(f'Editorial: {editorial_pct}%').classes('text-sm text-green-400')

            # Placement breakdown
            placement = stats.get("placement", {})
            if placement:
                ui.label('Placement:').classes('text-xs text-gray-400 mt-1')
                for loc, count in sorted(placement.items(), key=lambda x: -x[1]):
                    if count > 0:
                        color = 'text-green-400' if loc == 'content' else 'text-gray-300'
                        ui.label(f'  {loc}: {count}').classes(f'text-xs {color}')

            # Link types
            link_types = stats.get("link_types", {})
            if link_types:
                dofollow = link_types.get("dofollow", 0)
                nofollow = link_types.get("nofollow", 0)
                if dofollow + nofollow > 0:
                    dofollow_pct = round(dofollow / (dofollow + nofollow) * 100)
                    ui.label(f'Dofollow: {dofollow_pct}%').classes('text-xs text-gray-400 mt-1')

    def _update_serp_insights(self):
        """Update SERP features display."""
        self.serp_container.clear()
        stats = query_serp_stats()

        with self.serp_container:
            if "error" in stats:
                ui.label(f'Error: {stats["error"]}').classes('text-red-400 text-xs')
                return

            # Total snapshots
            ui.label(f'Total Snapshots: {stats.get("total_snapshots", 0)}').classes('text-sm')

            # Recent activity
            recent = stats.get("recent_24h", 0)
            ui.label(f'Last 24h: {recent}').classes('text-sm text-blue-400')

            # Sitelinks captured
            sitelinks = stats.get("with_sitelinks", 0)
            ui.label(f'With Sitelinks: {sitelinks}').classes('text-sm')

            # PAA questions
            paa_total = stats.get("paa_questions", 0)
            paa_unique = stats.get("paa_unique", 0)
            ui.label(f'PAA: {paa_total} ({paa_unique} unique)').classes('text-sm')

            # Top features
            features = stats.get("top_features", {})
            if features:
                ui.label('Top Features:').classes('text-xs text-gray-400 mt-1')
                for feature, count in list(features.items())[:5]:
                    ui.label(f'  {feature}: {count}').classes('text-xs')

    def _update_technical_insights(self):
        """Update technical health display."""
        self.technical_container.clear()
        stats = query_technical_audit_stats()

        with self.technical_container:
            if "error" in stats:
                ui.label(f'Error: {stats["error"]}').classes('text-red-400 text-xs')
                return

            # Total audits
            ui.label(f'Total Audits: {stats.get("total_audits", 0)}').classes('text-sm')

            # Average scores
            avg_overall = stats.get("avg_overall_score", 0)
            avg_cwv = stats.get("avg_cwv_score", 0)
            score_color = 'text-green-400' if avg_overall >= 70 else 'text-yellow-400' if avg_overall >= 50 else 'text-red-400'
            ui.label(f'Avg Score: {avg_overall}').classes(f'text-sm {score_color}')
            ui.label(f'Avg CWV: {avg_cwv}').classes('text-sm')

            # JS dependency stats
            js_dependent = stats.get("js_dependent_pages", 0)
            avg_change = stats.get("avg_content_change", 0)
            if js_dependent > 0:
                ui.label('JS Rendering:').classes('text-xs text-gray-400 mt-1')
                ui.label(f'  JS-Dependent: {js_dependent}').classes('text-xs text-orange-400')
                ui.label(f'  Avg Content Change: {avg_change}%').classes('text-xs')

            # CWV ratings
            cwv_ratings = stats.get("cwv_ratings", {})
            if cwv_ratings:
                ui.label('LCP Ratings:').classes('text-xs text-gray-400 mt-1')
                for rating, count in cwv_ratings.items():
                    color = {
                        'good': 'text-green-400',
                        'needs_improvement': 'text-yellow-400',
                        'poor': 'text-red-400',
                    }.get(rating, 'text-gray-300')
                    ui.label(f'  {rating}: {count}').classes(f'text-xs {color}')

    def _render_tabbed_logs(self):
        """Render tabbed log viewer."""
        with ui.card().classes('w-full'):
            ui.label('Live Logs').classes('text-xl font-bold mb-2')

            # Create tabs
            tabs = [{"name": m['name'], "label": m['label'], "icon": m['icon']} for m in MODULES]

            with ui.tabs().classes('w-full').props('dense') as tab_container:
                tab_refs = {}
                for tab in tabs:
                    tab_refs[tab['name']] = ui.tab(tab['name'], label=tab['label'], icon=tab['icon'])

            with ui.tab_panels(tab_container, value=MODULES[0]['name']).classes('w-full'):
                for tab in tabs:
                    with ui.tab_panel(tab['name']):
                        log_file = self._get_log_file(tab['name'])
                        viewer = LiveLogViewer(log_file=log_file, max_lines=500)
                        viewer.create()
                        self.log_viewers[tab['name']] = viewer

                        # Load initial content and start tailing
                        viewer.load_last_n_lines(100)
                        viewer.start_tailing()

    def _get_log_file(self, module: str) -> str:
        """Get log file path for a module."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        return str(LOG_DIR / f"{module}.log")

    async def _on_start_module(self, module_name: str, worker_class: str):
        """Start a single module."""
        runner = get_module_runner(module_name, worker_class)

        if runner.is_running():
            ui.notify(f'{module_name} is already running', type='warning')
            return

        runner.start()
        ui.notify(f'Started {module_name}', type='positive')
        self._update_status()

    async def _on_stop_module(self, module_name: str):
        """Stop a single module (forcefully)."""
        global _module_runners

        if module_name not in _module_runners:
            ui.notify(f'{module_name} is not running', type='info')
            return

        runner = _module_runners[module_name]

        if not runner.is_running():
            ui.notify(f'{module_name} is not running', type='info')
            return

        ui.notify(f'Stopping {module_name}...', type='info')

        # Force stop
        runner.stop(force=True)

        ui.notify(f'Stopped {module_name}', type='positive')
        self._update_status()

    async def _on_start_all(self):
        """Start all modules."""
        for module in MODULES:
            runner = get_module_runner(module['name'], module['worker_class'])
            if not runner.is_running():
                runner.start()
                await asyncio.sleep(0.5)  # Stagger starts slightly

        ui.notify('Started all modules', type='positive')
        self._update_status()

    async def _on_stop_all(self):
        """Stop all modules."""
        global _module_runners

        for module_name, runner in _module_runners.items():
            if runner.is_running():
                runner.stop(force=True)

        # Also kill any stray Chrome processes
        try:
            subprocess.run(['pkill', '-f', 'chromium'], timeout=5, capture_output=True)
            subprocess.run(['pkill', '-f', 'chrome'], timeout=5, capture_output=True)
        except Exception:
            pass

        ui.notify('Stopped all modules', type='positive')
        self._update_status()

    async def _on_clear_logs(self):
        """Handle clear logs button click."""
        try:
            # Clear all module log files
            for module in MODULES:
                log_file = LOG_DIR / f"{module['name']}.log"
                try:
                    with open(log_file, 'w') as f:
                        f.write("")
                except Exception:
                    pass

            # Clear viewer displays
            for viewer in self.log_viewers.values():
                viewer.clear()

            ui.notify('Logs cleared', type='info')
        except Exception as e:
            ui.notify(f'Error clearing logs: {e}', type='negative')

    def _update_status(self):
        """Update status display for all modules."""
        global _module_runners

        try:
            for module in MODULES:
                name = module['name']
                card = self.module_cards.get(name)
                if not card:
                    continue

                # Get runner status
                runner = _module_runners.get(name)
                if runner:
                    status = runner.get_status()
                    is_running = status['running']
                    processed = status['companies_processed']
                    succeeded = status['companies_succeeded']
                    failed = status['companies_failed']
                    uptime = status['uptime_seconds']
                else:
                    is_running = False
                    processed = 0
                    succeeded = 0
                    failed = 0
                    uptime = 0

                # Update badge
                badge = card['badge']
                if is_running:
                    badge.set_text('running')
                    badge.props('color=positive')
                else:
                    badge.set_text('stopped')
                    badge.props('color=grey')

                # Update stats
                card['stats'].set_text(f'{succeeded}/{processed} processed, {failed} errors')

                # Update uptime
                if uptime > 0:
                    if uptime > 3600:
                        uptime_str = f'{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m'
                    else:
                        uptime_str = f'{int(uptime // 60)}m {int(uptime % 60)}s'
                    card['uptime'].set_text(f'Uptime: {uptime_str}')
                else:
                    card['uptime'].set_text('')

                # Update button states
                card['start_btn'].set_enabled(not is_running)
                card['stop_btn'].set_enabled(is_running)

        except Exception as e:
            print(f"Error updating status: {e}")


# Need asyncio for async methods
import asyncio


def seo_dashboard_page():
    """Create the SEO dashboard page."""
    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Page setup
    ui.page_title('SEO Dashboard')

    # Dark theme
    ui.query('body').classes('bg-gray-800 text-white')

    # Create dashboard
    dashboard = SEODashboard()
    dashboard.render()

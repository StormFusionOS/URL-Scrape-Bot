"""
Unified SEO Dashboard Page

Single dashboard with Start/Stop button controlling all 7 SEO modules:
- SERP (with ranking trends and traffic estimation)
- Citations
- Backlinks
- Technical Audits (with engagement, readability, CWV)
- SEO Worker
- Keyword Intelligence (Phase 2: autocomplete, volume, difficulty, opportunities)
- Competitive Analysis (Phase 3: keyword gaps, content gaps, backlink gaps)

All modules run in continuous loop mode with tabbed per-module live logs.

Includes SEO Insights section showing:
- Content metrics (word count, content depth, header structure)
- Backlink quality (link placement breakdown)
- SERP features (sitelinks, PAA questions)
- Technical health (JS dependency analysis)
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from nicegui import ui

from niceui.widgets.live_log_viewer import LiveLogViewer
from niceui.widgets.serp_monitor import get_serp_monitor

# Database imports for SEO insights
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs" / "seo_modules"

# Ensure environment is loaded
load_dotenv(PROJECT_ROOT / '.env')

# Module configuration
MODULES = [
    {"name": "serp", "label": "SERP", "icon": "search"},
    {"name": "citations", "label": "Citations", "icon": "business"},
    {"name": "backlinks", "label": "Backlinks", "icon": "link"},
    {"name": "technical", "label": "Technical", "icon": "build"},
    {"name": "seo_worker", "label": "SEO Worker", "icon": "analytics"},
    # Phase 2 & 3 modules
    {"name": "keyword_intel", "label": "Keywords", "icon": "key"},
    {"name": "competitive", "label": "Competitive", "icon": "trending_up"},
]

# Global orchestrator instance (lazy loaded)
_orchestrator = None
_workers_registered = False

# Database engine for SEO insights
_db_engine = None


def get_db_engine():
    """Get or create database engine for SEO queries."""
    global _db_engine
    if _db_engine is None and DB_AVAILABLE:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            _db_engine = create_engine(database_url, echo=False)
    return _db_engine


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


def get_orchestrator(force_new: bool = False):
    """Get or create the SEO orchestrator instance."""
    global _orchestrator, _workers_registered

    if force_new and _orchestrator is not None:
        # Stop existing orchestrator if running
        if _orchestrator.is_running():
            _orchestrator.stop()
        _orchestrator = None
        _workers_registered = False

    if _orchestrator is None:
        from seo_intelligence.orchestrator import SEOCycleOrchestrator
        _orchestrator = SEOCycleOrchestrator(
            log_dir=str(LOG_DIR),
            heartbeat_timeout=300,
            delay_between_modules=5.0,
            delay_between_cycles=60.0
        )
        _workers_registered = False

    # Register workers if not already done
    if not _workers_registered:
        _register_workers(_orchestrator)
        _workers_registered = True

    return _orchestrator


def _register_workers(orchestrator):
    """Register all module workers with the orchestrator."""
    try:
        from seo_intelligence.workers import (
            SERPWorker,
            CitationWorker,
            BacklinkWorker,
            TechnicalWorker,
            SEOContinuousWorker,
            KeywordIntelligenceWorker,
            CompetitiveAnalysisWorker
        )

        workers = [
            ("serp", SERPWorker(log_dir=str(LOG_DIR))),
            ("citations", CitationWorker(log_dir=str(LOG_DIR))),
            ("backlinks", BacklinkWorker(log_dir=str(LOG_DIR))),
            ("technical", TechnicalWorker(log_dir=str(LOG_DIR))),
            ("seo_worker", SEOContinuousWorker(log_dir=str(LOG_DIR))),
            # Phase 2 & 3 workers
            ("keyword_intel", KeywordIntelligenceWorker(log_dir=str(LOG_DIR))),
            ("competitive", CompetitiveAnalysisWorker(log_dir=str(LOG_DIR))),
        ]

        for name, worker in workers:
            orchestrator.register_worker(name, worker)

    except Exception as e:
        print(f"Error registering workers: {e}")
        import traceback
        traceback.print_exc()


class SEODashboard:
    """Unified SEO Dashboard component."""

    def __init__(self):
        self.orchestrator = get_orchestrator()
        self.log_viewers: Dict[str, LiveLogViewer] = {}
        self.status_timer = None
        self.active_tab = "orchestrator"

        # UI elements
        self.status_badge = None
        self.start_btn = None
        self.stop_btn = None
        self.cycle_label = None
        self.uptime_label = None
        self.module_cards = {}

    def render(self):
        """Render the dashboard."""
        with ui.column().classes('w-full max-w-7xl mx-auto p-4 gap-4'):
            self._render_header()
            self._render_module_status()
            self._render_seo_insights()
            self._render_serp_monitor()
            self._render_tabbed_logs()

        # Start status update timer
        self.status_timer = ui.timer(2.0, self._update_status)

        # Start insights update timer (every 30 seconds)
        self.insights_timer = ui.timer(30.0, self._update_insights)

        # Initial status update
        self._update_status()
        self._update_insights()

    def _render_header(self):
        """Render header with controls."""
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center'):
                # Title
                ui.icon('dashboard', size='lg').classes('text-blue-400')
                ui.label('SEO Unified Dashboard').classes('text-2xl font-bold ml-2')

                ui.space()

                # Status badge
                self.status_badge = ui.badge('STOPPED', color='negative').classes('text-lg px-4 py-1')

                # Cycle count
                self.cycle_label = ui.label('Cycle: 0').classes('text-lg ml-4')

                # Uptime
                self.uptime_label = ui.label('Uptime: 0m').classes('text-gray-400 ml-4')

            ui.separator().classes('my-3')

            # Control buttons
            with ui.row().classes('w-full gap-4'):
                self.start_btn = ui.button(
                    'Start All',
                    icon='play_arrow',
                    color='positive',
                    on_click=self._on_start
                ).classes('flex-1')

                self.stop_btn = ui.button(
                    'Stop All',
                    icon='stop',
                    color='negative',
                    on_click=self._on_stop
                ).classes('flex-1')

                ui.button(
                    'Reset State',
                    icon='restart_alt',
                    color='warning',
                    on_click=self._on_reset
                ).props('outline').classes('flex-1')

                ui.button(
                    'Clear Logs',
                    icon='delete_sweep',
                    on_click=self._on_clear_logs
                ).props('outline').classes('flex-1')

    def _render_module_status(self):
        """Render module status cards."""
        with ui.row().classes('w-full gap-2'):
            for module in MODULES:
                with ui.card().classes('flex-1 min-w-32'):
                    with ui.column().classes('items-center p-2'):
                        # Module icon and name
                        ui.icon(module['icon'], size='md').classes('text-gray-400')
                        ui.label(module['label']).classes('font-semibold')

                        # Status indicator
                        status_badge = ui.badge('pending', color='grey').classes('text-xs')
                        self.module_cards[module['name']] = {
                            'badge': status_badge,
                            'icon': None
                        }

                        # Stats
                        stats_label = ui.label('0 processed').classes('text-xs text-gray-500')
                        self.module_cards[module['name']]['stats'] = stats_label

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
            tabs = [{"name": "orchestrator", "label": "Orchestrator", "icon": "hub"}] + \
                   [{"name": m['name'], "label": m['label'], "icon": m['icon']} for m in MODULES]

            with ui.tabs().classes('w-full').props('dense') as tab_container:
                tab_refs = {}
                for tab in tabs:
                    tab_refs[tab['name']] = ui.tab(tab['name'], label=tab['label'], icon=tab['icon'])

            with ui.tab_panels(tab_container, value='orchestrator').classes('w-full'):
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
        if module == "orchestrator":
            return str(LOG_DIR / "orchestrator.log")
        return str(LOG_DIR / f"{module}.log")

    async def _on_start(self):
        """Handle start button click."""
        self.start_btn.disable()
        ui.notify('Starting all SEO modules...', type='info')

        try:
            # Force create new orchestrator to ensure fresh workers
            self.orchestrator = get_orchestrator(force_new=True)
            self.orchestrator.start()
            ui.notify('SEO orchestrator started!', type='positive')
        except Exception as e:
            ui.notify(f'Error starting: {e}', type='negative')
            import traceback
            traceback.print_exc()

        self._update_status()

    async def _on_stop(self):
        """Handle stop button click."""
        self.stop_btn.disable()
        ui.notify('Stopping all SEO modules...', type='info')

        try:
            self.orchestrator.stop(timeout=30.0)
            ui.notify('SEO orchestrator stopped', type='info')
        except Exception as e:
            ui.notify(f'Error stopping: {e}', type='negative')

        self._update_status()

    async def _on_reset(self):
        """Handle reset button click."""
        if self.orchestrator.is_running():
            ui.notify('Stop the orchestrator first', type='warning')
            return

        try:
            self.orchestrator.reset_state()
            ui.notify('State reset complete', type='positive')

            # Reload log viewers
            for viewer in self.log_viewers.values():
                viewer.load_last_n_lines(100)

        except Exception as e:
            ui.notify(f'Error resetting: {e}', type='negative')

        self._update_status()

    async def _on_clear_logs(self):
        """Handle clear logs button click."""
        try:
            self.orchestrator.clear_logs()

            # Clear viewer displays
            for viewer in self.log_viewers.values():
                viewer.clear()

            ui.notify('Logs cleared', type='info')
        except Exception as e:
            ui.notify(f'Error clearing logs: {e}', type='negative')

    def _update_status(self):
        """Update status display."""
        try:
            status = self.orchestrator.get_status()
            running = status.get('running', False)

            # Update main status badge
            if running:
                self.status_badge.set_text('RUNNING')
                self.status_badge.props('color=positive')
                self.start_btn.disable()
                self.stop_btn.enable()
            else:
                self.status_badge.set_text('STOPPED')
                self.status_badge.props('color=negative')
                self.start_btn.enable()
                self.stop_btn.disable()

            # Update cycle count
            cycles = status.get('cycles_completed', 0)
            self.cycle_label.set_text(f'Cycle: {cycles}')

            # Update uptime
            uptime_sec = status.get('uptime_seconds', 0)
            if uptime_sec > 3600:
                uptime_str = f'{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m'
            else:
                uptime_str = f'{uptime_sec // 60}m'
            self.uptime_label.set_text(f'Uptime: {uptime_str}')

            # Update module cards
            modules = status.get('modules', {})
            current_module = status.get('current_module')

            for name, card in self.module_cards.items():
                mod_status = modules.get(name, {})
                mod_state = mod_status.get('status', 'pending')

                # Update badge
                badge = card['badge']
                if name == current_module:
                    badge.set_text('running')
                    badge.props('color=primary')
                elif mod_state == 'completed':
                    badge.set_text('completed')
                    badge.props('color=positive')
                elif mod_state == 'failed':
                    badge.set_text('failed')
                    badge.props('color=negative')
                elif mod_state == 'running':
                    badge.set_text('running')
                    badge.props('color=primary')
                else:
                    badge.set_text('pending')
                    badge.props('color=grey')

                # Update stats
                processed = mod_status.get('companies_processed', 0)
                errors = mod_status.get('errors', 0)
                card['stats'].set_text(f'{processed} processed, {errors} errors')

        except Exception as e:
            print(f"Error updating status: {e}")


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

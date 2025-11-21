"""
SEO Intelligence Dashboard Page

Functional SEO analysis with:
- Live source selection from washdb companies
- Real-time WebSocket log output
- Technical audits and LAS calculations
- Change governance review
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from nicegui import ui, app
from ..theme import COLORS

# Import SEO backend service
try:
    from ..services.seo_backend import get_seo_backend, SEOSource, AnalysisResult
    SEO_BACKEND_AVAILABLE = True
except ImportError as e:
    SEO_BACKEND_AVAILABLE = False
    print(f"SEO Backend import error: {e}")

# Try to import SEO Intelligence modules
try:
    from seo_intelligence.services import get_change_manager
    SEO_AVAILABLE = True
except ImportError:
    SEO_AVAILABLE = False


class SEOIntelligenceController:
    """Controller for SEO Intelligence page with live updates."""

    def __init__(self):
        self.backend = get_seo_backend() if SEO_BACKEND_AVAILABLE else None
        self.selected_sources: List[SEOSource] = []
        self.log_lines: List[str] = []
        self.results: List[AnalysisResult] = []
        self.is_running = False
        self._pending_result_count = 0  # Flag for deferred UI update
        self._results_need_update = False

        # UI elements (set during page creation)
        self.log_container = None
        self.results_container = None
        self.sources_table = None
        self.progress_label = None
        self.stats_container = None

    def add_log(self, message: str):
        """Add a log message and update UI."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_lines.append(line)
        # Keep last 100 lines
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]
        self._update_log_display()

    def _update_log_display(self):
        """Update the log container with current lines."""
        if self.log_container:
            try:
                self.log_container.clear()
                with self.log_container:
                    for line in self.log_lines[-50:]:  # Show last 50
                        color = 'text-gray-300'
                        if '[ERROR]' in line:
                            color = 'text-red-400'
                        elif '[WARN]' in line:
                            color = 'text-yellow-400'
                        elif '[SCORE]' in line:
                            color = 'text-green-400'
                        elif '[COMPLETE]' in line:
                            color = 'text-blue-400'
                        ui.label(line).classes(f'text-xs font-mono {color}')
            except Exception:
                pass  # Ignore UI update errors from async context

    def _update_results_display(self):
        """Update the results container."""
        if self.results_container:
            try:
                self.results_container.clear()
                with self.results_container:
                    if not self.results:
                        ui.label('No results yet. Run an analysis to see results.').classes('text-gray-400 py-4')
                    else:
                        # Create results table
                        columns = [
                            {'name': 'name', 'label': 'Source', 'field': 'name', 'align': 'left'},
                            {'name': 'type', 'label': 'Analysis', 'field': 'type', 'align': 'left'},
                            {'name': 'score', 'label': 'Score', 'field': 'score', 'align': 'center'},
                            {'name': 'grade', 'label': 'Grade', 'field': 'grade', 'align': 'center'},
                            {'name': 'issues', 'label': 'Issues', 'field': 'issues', 'align': 'center'},
                        ]
                        rows = []
                        for r in self.results[-20:]:  # Show last 20
                            rows.append({
                                'name': r.source_name[:30] + '...' if len(r.source_name) > 30 else r.source_name,
                                'type': r.analysis_type.upper(),
                                'score': f"{r.score:.0f}",
                                'grade': r.grade,
                                'issues': str(r.issues_count),
                            })
                        ui.table(columns=columns, rows=rows, row_key='name').classes('w-full')
            except Exception:
                pass  # Ignore UI update errors from async context

    def clear_log(self):
        """Clear the log."""
        self.log_lines = []
        self._update_log_display()
        ui.notify('Log cleared', type='info')

    def clear_results(self):
        """Clear results."""
        self.results = []
        if self.backend:
            self.backend.clear_results()
        self._update_results_display()
        ui.notify('Results cleared', type='info')

    def check_pending_updates(self):
        """Check for pending UI updates (called by timer)."""
        if self._results_need_update and self._pending_result_count > 0:
            self._results_need_update = False
            count = self._pending_result_count
            self._pending_result_count = 0
            self._update_results_display()
            ui.notify(f'Analysis complete: {count} sources analyzed', type='positive')

    async def run_audit(self):
        """Run technical audit on selected sources."""
        if not self.backend:
            ui.notify('SEO Backend not available', type='negative')
            return

        if not self.selected_sources:
            ui.notify('Select at least one source', type='warning')
            return

        if self.is_running:
            ui.notify('Analysis already running', type='warning')
            return

        self.is_running = True
        self.add_log("[START] Starting technical audit batch...")

        try:
            results = await self.backend.run_batch_analysis(
                sources=self.selected_sources,
                analysis_type="audit",
                progress_callback=self.add_log,
            )
            self.results.extend(results)
            # Set flag for timer to pick up
            self._pending_result_count = len(results)
            self._results_need_update = True
        except Exception as e:
            self.add_log(f"[ERROR] Audit failed: {e}")
        finally:
            self.is_running = False

    async def run_las(self):
        """Run LAS calculation on selected sources."""
        if not self.backend:
            ui.notify('SEO Backend not available', type='negative')
            return

        if not self.selected_sources:
            ui.notify('Select at least one source', type='warning')
            return

        if self.is_running:
            ui.notify('Analysis already running', type='warning')
            return

        self.is_running = True
        self.add_log("[START] Starting LAS calculation batch...")

        try:
            results = await self.backend.run_batch_analysis(
                sources=self.selected_sources,
                analysis_type="las",
                progress_callback=self.add_log,
            )
            self.results.extend(results)
            # Set flag for timer to pick up
            self._pending_result_count = len(results)
            self._results_need_update = True
        except Exception as e:
            self.add_log(f"[ERROR] LAS failed: {e}")
        finally:
            self.is_running = False

    def stop_analysis(self):
        """Stop running analysis."""
        if self.backend:
            self.backend.stop_analysis()
            self.add_log("[STOPPED] Analysis stopped by user")
            ui.notify('Stopping analysis...', type='warning')


def create_source_selector(controller: SEOIntelligenceController):
    """Create the source selection panel."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('SEO Sources').classes('text-xl font-bold text-white mb-2')
        ui.label('Select companies from washdb to analyze').classes('text-gray-400 text-sm mb-4')

        if not SEO_BACKEND_AVAILABLE:
            ui.label('SEO Backend not available').classes('text-red-400')
            return

        # Search and filter controls
        with ui.row().classes('w-full gap-4 mb-4 items-end'):
            search_input = ui.input(
                label='Search',
                placeholder='Company name or domain...'
            ).classes('flex-1')

            source_select = ui.select(
                label='Source',
                options=['All', 'Local', 'National'],
                value='All'
            ).classes('w-32')

            limit_select = ui.select(
                label='Limit',
                options=[50, 100, 250, 500],
                value=100
            ).classes('w-24')

        # Stats display
        stats = controller.backend.get_source_stats() if controller.backend else {}
        with ui.row().classes('w-full gap-2 mb-4'):
            ui.badge(f"Total: {stats.get('total_with_website', 0)}", color='blue')
            for src, count in stats.get('by_source', {}).items():
                if count > 0:
                    ui.badge(f"{src}: {count}", color='gray')

        # Source table container
        table_container = ui.element('div').classes('w-full max-h-64 overflow-auto')
        selected_label = ui.label('Selected: 0').classes('text-sm text-gray-400 mt-2')

        def load_sources():
            """Load sources based on filters."""
            if not controller.backend:
                return

            search = search_input.value or ""
            source_filter = "" if source_select.value == "All" else source_select.value
            limit = limit_select.value

            sources = controller.backend.get_seo_sources(
                search=search,
                source_filter=source_filter,
                has_website_only=True,
                limit=limit
            )

            # Create lookup dict for sources by ID
            source_lookup = {s.id: s for s in sources}

            table_container.clear()
            with table_container:
                if not sources:
                    ui.label('No sources found').classes('text-gray-400 py-4')
                    return

                columns = [
                    {'name': 'select', 'label': '', 'field': 'select', 'align': 'center'},
                    {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left'},
                    {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'align': 'left'},
                    {'name': 'source', 'label': 'Source', 'field': 'source', 'align': 'center'},
                ]

                rows = []
                for s in sources:
                    rows.append({
                        'id': s.id,
                        'name': s.name[:40] if s.name else '',
                        'domain': s.domain[:30] if s.domain else '',
                        'source': s.source or '',
                    })

                table = ui.table(
                    columns=columns,
                    rows=rows,
                    row_key='id',
                    selection='multiple',
                ).classes('w-full')

                def on_selection_change(e):
                    # Look up SEOSource objects by ID from selected rows
                    controller.selected_sources = [
                        source_lookup[row['id']] for row in table.selected if row['id'] in source_lookup
                    ]
                    selected_label.set_text(f'Selected: {len(controller.selected_sources)}')

                table.on('selection', on_selection_change)
                controller.sources_table = table

        # Load button and auto-load
        with ui.row().classes('gap-2 mt-2'):
            ui.button('Load Sources', icon='refresh', on_click=load_sources).classes(
                'bg-purple-600 hover:bg-purple-700'
            )
            ui.button('Select All', on_click=lambda: ui.notify('Use table checkboxes')).props('flat')

        # Initial load
        load_sources()


def create_analysis_controls(controller: SEOIntelligenceController):
    """Create analysis control buttons."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('Analysis Controls').classes('text-xl font-bold text-white mb-4')

        with ui.row().classes('gap-4 flex-wrap'):
            ui.button(
                'Run Technical Audit',
                icon='speed',
                on_click=lambda: asyncio.create_task(controller.run_audit())
            ).classes('bg-blue-600 hover:bg-blue-700')

            ui.button(
                'Calculate LAS',
                icon='analytics',
                on_click=lambda: asyncio.create_task(controller.run_las())
            ).classes('bg-green-600 hover:bg-green-700')

            ui.button(
                'Stop',
                icon='stop',
                on_click=controller.stop_analysis
            ).classes('bg-red-600 hover:bg-red-700')

        with ui.row().classes('gap-2 mt-4'):
            ui.button('Clear Log', icon='delete', on_click=controller.clear_log).props('flat')
            ui.button('Clear Results', icon='clear_all', on_click=controller.clear_results).props('flat')


def create_live_log(controller: SEOIntelligenceController):
    """Create live log output panel."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('Live Log').classes('text-xl font-bold text-white')
            ui.badge('WebSocket', color='green').classes('text-xs')

        # Log container with scrolling
        controller.log_container = ui.element('div').classes(
            'w-full h-48 overflow-y-auto bg-gray-900 rounded p-2'
        )
        with controller.log_container:
            ui.label('Ready. Select sources and run analysis.').classes('text-gray-400 text-xs font-mono')


def create_results_panel(controller: SEOIntelligenceController):
    """Create results display panel."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('Analysis Results').classes('text-xl font-bold text-white mb-4')

        controller.results_container = ui.element('div').classes('w-full')
        with controller.results_container:
            ui.label('No results yet. Run an analysis to see results.').classes('text-gray-400 py-4')


def create_change_review_panel():
    """Create pending changes review panel."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        with ui.row().classes('w-full items-center justify-between mb-4'):
            ui.label('Pending Changes').classes('text-xl font-bold text-white')
            ui.button('Refresh', icon='refresh', on_click=lambda: ui.notify('Refreshing...')).props('flat')

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        try:
            manager = get_change_manager()
            changes = manager.get_pending_changes(limit=10)

            if not changes:
                ui.label('No pending changes').classes('text-gray-400 py-2')
                return

            for change in changes[:5]:
                with ui.card().classes('p-3 bg-gray-700 rounded mb-2 w-full'):
                    with ui.row().classes('w-full items-center justify-between'):
                        with ui.column().classes('flex-1'):
                            ui.label(change['change_type']).classes('font-bold text-white')
                            ui.label(change.get('reason', '')[:60] + '...').classes('text-xs text-gray-400')
                        with ui.row().classes('gap-1'):
                            ui.button(icon='check', on_click=lambda c=change: approve_change(c)).props(
                                'flat color=green size=sm'
                            )
                            ui.button(icon='close', on_click=lambda c=change: reject_change(c)).props(
                                'flat color=red size=sm'
                            )
        except Exception as e:
            ui.label(f'Error: {e}').classes('text-red-400')


def approve_change(change: Dict):
    """Approve a pending change."""
    try:
        manager = get_change_manager()
        manager.approve_change(change['change_id'], approved_by='dashboard_user')
        ui.notify(f'Change {change["change_id"]} approved', type='positive')
    except Exception as e:
        ui.notify(f'Error: {e}', type='negative')


def reject_change(change: Dict):
    """Reject a pending change."""
    try:
        manager = get_change_manager()
        manager.reject_change(change['change_id'], rejected_by='dashboard_user', reason='Rejected via dashboard')
        ui.notify(f'Change {change["change_id"]} rejected', type='info')
    except Exception as e:
        ui.notify(f'Error: {e}', type='negative')


def seo_intelligence_page():
    """Main SEO Intelligence dashboard page with live features."""
    controller = SEOIntelligenceController()

    with ui.column().classes('w-full max-w-7xl mx-auto p-4 gap-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('SEO Intelligence').classes('text-3xl font-bold text-white')
            with ui.row().classes('gap-2'):
                if SEO_BACKEND_AVAILABLE:
                    ui.badge('Backend: Ready', color='green')
                else:
                    ui.badge('Backend: Unavailable', color='red')
                if SEO_AVAILABLE:
                    ui.badge('Modules: Active', color='green')
                else:
                    ui.badge('Modules: Missing', color='orange')

        ui.label('Live SEO analysis connected to washdb sources').classes('text-gray-400 mb-2')

        # Main layout: 2 columns
        with ui.row().classes('w-full gap-4'):
            # Left column: Source selection + Controls
            with ui.column().classes('flex-1 min-w-96 gap-4'):
                create_source_selector(controller)
                create_analysis_controls(controller)

            # Right column: Log + Results
            with ui.column().classes('flex-1 min-w-96 gap-4'):
                create_live_log(controller)
                create_results_panel(controller)

        # Bottom: Change review
        create_change_review_panel()

    # Timer to check for pending UI updates from async tasks
    ui.timer(0.5, controller.check_pending_updates)

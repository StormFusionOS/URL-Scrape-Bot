"""
SERP Scraper Runner Dashboard

Interactive GUI for running Google SERP searches with:
- Source selection from washdb (Local/National)
- Manual query input option
- Live progress display
- Results table with position tracking
- PAA questions display
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any
from nicegui import ui
from ..theme import COLORS

# Try to import SERP scraper
try:
    from seo_intelligence.scrapers.serp_scraper import SerpScraper
    SERP_AVAILABLE = True
except ImportError:
    SERP_AVAILABLE = False

# Import SEO backend for source selection
try:
    from ..services.seo_backend import get_seo_backend, SEOSource
    SEO_BACKEND_AVAILABLE = True
except ImportError:
    SEO_BACKEND_AVAILABLE = False


class SerpRunnerController:
    """Controller for SERP scraper dashboard."""

    def __init__(self):
        self.scraper = SerpScraper() if SERP_AVAILABLE else None
        self.backend = get_seo_backend() if SEO_BACKEND_AVAILABLE else None
        self.selected_sources: List[SEOSource] = []
        self.log_lines: List[str] = []
        self.results: List[Dict] = []
        self.paa_questions: List[str] = []
        self.is_running = False

        # UI elements
        self.log_container = None
        self.results_container = None
        self.paa_container = None
        self.run_button = None
        self.stop_button = None
        self.sources_table = None

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
                        if '[ERROR]' in line or 'ERROR' in line:
                            color = 'text-red-400'
                        elif '[WARN]' in line or 'WARNING' in line:
                            color = 'text-yellow-400'
                        elif 'position' in line.lower() or 'rank' in line.lower():
                            color = 'text-green-400'
                        elif '[COMPLETE]' in line or 'Complete' in line:
                            color = 'text-blue-400'
                        ui.label(line).classes(f'text-xs font-mono {color}')
            except Exception:
                pass

    def _update_results_display(self):
        """Update the results container."""
        if self.results_container:
            try:
                self.results_container.clear()
                with self.results_container:
                    if not self.results:
                        ui.label('No results yet. Run a SERP search to see results.').classes('text-gray-400 py-4')
                    else:
                        # Create results table
                        columns = [
                            {'name': 'query', 'label': 'Query', 'field': 'query', 'align': 'left'},
                            {'name': 'position', 'label': 'Rank', 'field': 'position', 'align': 'center'},
                            {'name': 'title', 'label': 'Title', 'field': 'title', 'align': 'left'},
                            {'name': 'url', 'label': 'URL', 'field': 'url', 'align': 'left'},
                            {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'align': 'left'},
                        ]
                        rows = []
                        for r in self.results[-100:]:  # Show last 100
                            rows.append({
                                'query': r.get('query', '')[:30] + ('...' if len(r.get('query', '')) > 30 else ''),
                                'position': r['position'],
                                'title': r['title'][:60] + ('...' if len(r['title']) > 60 else ''),
                                'url': r['url'][:50] + ('...' if len(r['url']) > 50 else ''),
                                'domain': r['domain'][:30],
                            })

                        ui.table(columns=columns, rows=rows).classes('w-full')
                        ui.label(f'Total Results: {len(self.results)}').classes('text-sm text-gray-400 mt-2')
            except Exception as e:
                ui.label(f'Error displaying results: {e}').classes('text-red-400')

    def _update_paa_display(self):
        """Update the PAA questions container."""
        if self.paa_container:
            try:
                self.paa_container.clear()
                with self.paa_container:
                    if not self.paa_questions:
                        ui.label('No "People Also Ask" questions found').classes('text-gray-400 text-sm')
                    else:
                        ui.label(f'Found {len(self.paa_questions)} "People Also Ask" questions:').classes('font-semibold mb-2')
                        for i, question in enumerate(self.paa_questions, 1):
                            ui.label(f'{i}. {question}').classes('text-sm text-gray-300 ml-4')
            except Exception:
                pass

    async def run_serp_for_sources(self, location: str, num_results: int):
        """Run SERP search for selected sources."""
        if not SERP_AVAILABLE or not self.scraper:
            ui.notify('SERP scraper not available', type='negative')
            return

        if not self.selected_sources:
            ui.notify('Please select at least one source', type='warning')
            return

        if self.is_running:
            ui.notify('SERP search already running', type='warning')
            return

        self.is_running = True
        self.results = []
        self.paa_questions = []

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Running SERP search for {len(self.selected_sources)} sources")
        self.add_log(f"Location: {location}, Results per query: {num_results}")

        try:
            # Start scraper
            self.scraper.start()

            # Run search in executor to avoid blocking
            loop = asyncio.get_event_loop()

            for source in self.selected_sources:
                # Construct query from source name
                query = source.name
                self.add_log(f"Searching for: {query}")

                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda q=query: self.scraper.scrape_query(q, location, num_results)
                    )

                    if result:
                        # Add query field to each result
                        for r in result.get('results', []):
                            r['query'] = query
                            # Check if domain matches our source
                            if source.domain and source.domain.lower() in r['domain'].lower():
                                r['is_our_company'] = True

                        self.results.extend(result.get('results', []))

                        # Store PAA questions from first search
                        if not self.paa_questions and result.get('paa_questions'):
                            self.paa_questions = result.get('paa_questions', [])

                        self.add_log(f"✓ Found {len(result.get('results', []))} results for {query}")
                    else:
                        self.add_log(f"[WARN] No results returned for {query}")

                except Exception as e:
                    self.add_log(f"[ERROR] {query}: {e}")

            self.add_log(f"[COMPLETE] SERP search complete: {len(self.results)} total results")

            # Update displays
            self._update_results_display()
            self._update_paa_display()

            ui.notify(f'SERP search complete: {len(self.results)} results', type='positive')

        except Exception as e:
            self.add_log(f"[ERROR] SERP search failed: {e}")
            ui.notify(f'Search failed: {e}', type='negative')
        finally:
            # Stop scraper
            try:
                self.scraper.stop()
            except:
                pass

            self.is_running = False

            # Update button states
            if self.run_button:
                self.run_button.enable()
            if self.stop_button:
                self.stop_button.disable()

    async def run_serp_manual(self, query: str, location: str, num_results: int):
        """Run manual SERP search."""
        if not SERP_AVAILABLE or not self.scraper:
            ui.notify('SERP scraper not available', type='negative')
            return

        if not query.strip():
            ui.notify('Please enter a search query', type='warning')
            return

        if self.is_running:
            ui.notify('SERP search already running', type='warning')
            return

        self.is_running = True

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Running SERP search for: {query}")
        self.add_log(f"Location: {location}, Results: {num_results}")

        try:
            # Start scraper
            self.scraper.start()

            # Run search in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.scraper.scrape_query(query, location, num_results)
            )

            if result:
                # Extract results
                for r in result.get('results', []):
                    r['query'] = query
                self.results.extend(result.get('results', []))
                self.paa_questions = result.get('paa_questions', [])

                self.add_log(f"[COMPLETE] Found {len(result.get('results', []))} organic results")

                # Update displays
                self._update_results_display()
                self._update_paa_display()

                ui.notify(f'SERP search complete: {len(result.get("results", []))} results', type='positive')
            else:
                self.add_log("[ERROR] No results returned from scraper")
                ui.notify('No results returned', type='negative')

        except Exception as e:
            self.add_log(f"[ERROR] SERP search failed: {e}")
            ui.notify(f'Search failed: {e}', type='negative')
        finally:
            # Stop scraper
            try:
                self.scraper.stop()
            except:
                pass

            self.is_running = False

            # Update button states
            if self.run_button:
                self.run_button.enable()
            if self.stop_button:
                self.stop_button.disable()

    def stop_search(self):
        """Stop running search."""
        if self.scraper:
            try:
                self.scraper.stop()
                self.add_log("[STOPPED] Search stopped by user")
                ui.notify('Stopping search...', type='warning')
            except:
                pass


def serp_runner_page():
    """Create the SERP runner page."""
    ui.label('SERP Scraper Runner').classes('text-2xl font-bold mb-4')

    if not SERP_AVAILABLE:
        ui.label('⚠️ SERP scraper not available').classes('text-yellow-400 text-lg')
        ui.label('Install required dependencies or check imports').classes('text-gray-400')
        return

    controller = SerpRunnerController()

    # Source selection panel (if backend available)
    if SEO_BACKEND_AVAILABLE and controller.backend:
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
            ui.label('SEO Sources').classes('text-lg font-semibold mb-2')
            ui.label('Select companies to search for (optional - uses company names as queries)').classes('text-sm text-gray-400 mb-3')

            # Search and filter controls
            with ui.row().classes('w-full gap-4 mb-3 items-end'):
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
                    options=[10, 25, 50, 100],
                    value=25
                ).classes('w-24')

            # Stats display
            stats = controller.backend.get_source_stats()
            with ui.row().classes('w-full gap-2 mb-3'):
                ui.badge(f"Total: {stats.get('total_with_website', 0)}", color='blue')
                for src, count in stats.get('by_source', {}).items():
                    if count > 0:
                        ui.badge(f"{src}: {count}", color='gray')

            # Source table container
            table_container = ui.element('div').classes('w-full max-h-48 overflow-auto')
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
                        ui.label('No sources found').classes('text-gray-400 py-2')
                        return

                    columns = [
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

            # Load button
            with ui.row().classes('gap-2 mt-2'):
                ui.button('Load Sources', icon='refresh', on_click=load_sources).classes('bg-purple-600 hover:bg-purple-700')

            # Initial load
            load_sources()

    # Manual query input (always available as fallback)
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Manual Query (Optional)').classes('text-lg font-semibold mb-3')
        ui.label('Enter a custom search query or leave blank to use selected sources').classes('text-sm text-gray-400 mb-3')

        with ui.row().classes('w-full gap-4'):
            # Query input
            with ui.column().classes('flex-grow'):
                ui.label('Search Query').classes('text-sm text-gray-400 mb-1')
                query_input = ui.input(
                    placeholder='e.g., pressure washing austin',
                    value=''
                ).classes('w-full').props('outlined dense')

            # Location input
            with ui.column().classes('flex-grow'):
                ui.label('Location').classes('text-sm text-gray-400 mb-1')
                location_input = ui.input(
                    placeholder='e.g., Austin, TX',
                    value='Austin, TX'
                ).classes('w-full').props('outlined dense')

            # Number of results
            with ui.column().classes('w-48'):
                ui.label('Results').classes('text-sm text-gray-400 mb-1')
                num_results = ui.select(
                    options=[10, 20, 50, 100],
                    value=20
                ).classes('w-full').props('outlined dense')

        # Action buttons
        with ui.row().classes('mt-4 gap-2'):
            async def run_search():
                if query_input.value.strip():
                    await controller.run_serp_manual(query_input.value, location_input.value, num_results.value)
                elif controller.selected_sources:
                    await controller.run_serp_for_sources(location_input.value, num_results.value)
                else:
                    ui.notify('Please enter a query or select sources', type='warning')

            controller.run_button = ui.button(
                'Run SERP Search',
                icon='search',
                color='primary',
                on_click=run_search
            )

            controller.stop_button = ui.button(
                'Stop',
                icon='stop',
                color='negative',
                on_click=controller.stop_search
            ).props('outline')
            controller.stop_button.disable()

    # Live logs
    with ui.card().classes('p-4 bg-gray-900 rounded-lg w-full mb-4'):
        ui.label('Live Logs').classes('text-lg font-semibold mb-2')
        controller.log_container = ui.column().classes('w-full h-64 overflow-y-auto bg-black p-2 rounded')

    # Results section
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Search Results').classes('text-lg font-semibold mb-2')
        controller.results_container = ui.column().classes('w-full')

    # PAA section
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('People Also Ask (PAA) Questions').classes('text-lg font-semibold mb-2')
        controller.paa_container = ui.column().classes('w-full')

    # Initialize displays
    controller._update_log_display()
    controller._update_results_display()
    controller._update_paa_display()

"""
Citation Crawler Runner Dashboard

Interactive GUI for checking business citations with:
- Source selection from washdb (Local/National)
- Manual NAP information input
- Directory selection (checkboxes)
- Live progress per directory
- NAP score display with color coding
- Mismatch details and change proposals
"""

import asyncio
from datetime import datetime
from typing import List, Dict
from nicegui import ui
from ..theme import COLORS

# Try to import Citation crawler
try:
    from seo_intelligence.scrapers.citation_crawler import CitationCrawler, BusinessInfo, CITATION_DIRECTORIES
    CITATION_AVAILABLE = True
except ImportError:
    CITATION_AVAILABLE = False
    CITATION_DIRECTORIES = {}

# Import SEO backend for source selection
try:
    from ..services.seo_backend import get_seo_backend, SEOSource
    SEO_BACKEND_AVAILABLE = True
except ImportError:
    SEO_BACKEND_AVAILABLE = False


class CitationRunnerController:
    """Controller for Citation crawler dashboard."""

    def __init__(self):
        self.crawler = CitationCrawler() if CITATION_AVAILABLE else None
        self.backend = get_seo_backend() if SEO_BACKEND_AVAILABLE else None
        self.selected_sources: List[SEOSource] = []
        self.log_lines: List[str] = []
        self.results: List[Dict] = []
        self.is_running = False

        # UI elements
        self.log_container = None
        self.results_container = None
        self.run_button = None
        self.stop_button = None
        self.sources_table = None

        # Form elements for auto-fill
        self.business_name_input = None
        self.phone_input = None
        self.address_input = None
        self.city_input = None
        self.state_input = None
        self.zip_code_input = None
        self.website_input = None

    def add_log(self, message: str):
        """Add a log message and update UI."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_lines.append(line)

        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]

        self._update_log_display()

    def _update_log_display(self):
        """Update the log container."""
        if self.log_container:
            try:
                self.log_container.clear()
                with self.log_container:
                    for line in self.log_lines[-50:]:
                        color = 'text-gray-300'
                        if '[ERROR]' in line or 'ERROR' in line:
                            color = 'text-red-400'
                        elif '[WARN]' in line or 'WARNING' in line or 'mismatch' in line.lower():
                            color = 'text-yellow-400'
                        elif 'FOUND' in line or 'match' in line.lower():
                            color = 'text-green-400'
                        elif '[COMPLETE]' in line:
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
                        ui.label('No results yet. Run a citation check to see results.').classes('text-gray-400 py-4')
                    else:
                        # Create results table
                        columns = [
                            {'name': 'business', 'label': 'Business', 'field': 'business', 'align': 'left'},
                            {'name': 'directory', 'label': 'Directory', 'field': 'directory', 'align': 'left'},
                            {'name': 'found', 'label': 'Found', 'field': 'found', 'align': 'center'},
                            {'name': 'nap_score', 'label': 'NAP Score', 'field': 'nap_score', 'align': 'center'},
                            {'name': 'mismatches', 'label': 'Mismatches', 'field': 'mismatches', 'align': 'left'},
                        ]
                        rows = []
                        for r in self.results[-100:]:  # Show last 100
                            # Build mismatches string
                            mismatches = []
                            if not r.get('name_match'):
                                mismatches.append('Name')
                            if not r.get('address_match'):
                                mismatches.append('Address')
                            if not r.get('phone_match'):
                                mismatches.append('Phone')

                            rows.append({
                                'business': r.get('business_name', '')[:30] + ('...' if len(r.get('business_name', '')) > 30 else ''),
                                'directory': r['directory'],
                                'found': '✓' if r.get('is_listed') else '✗',
                                'nap_score': f"{r.get('nap_score', 0):.2f}",
                                'mismatches': ', '.join(mismatches) if mismatches else 'None',
                            })

                        ui.table(columns=columns, rows=rows).classes('w-full')

                        # Summary stats
                        total = len(self.results)
                        found = sum(1 for r in self.results if r.get('is_listed'))
                        avg_score = sum(r.get('nap_score', 0) for r in self.results) / total if total > 0 else 0

                        with ui.row().classes('mt-4 gap-4'):
                            ui.label(f'Directories Checked: {total}').classes('text-sm')
                            ui.label(f'Listings Found: {found}').classes('text-sm')
                            ui.label(f'Avg NAP Score: {avg_score:.2f}').classes('text-sm')
            except Exception as e:
                ui.label(f'Error displaying results: {e}').classes('text-red-400')

    def auto_fill_from_source(self, source: SEOSource):
        """Auto-fill form fields from selected source."""
        if self.business_name_input:
            self.business_name_input.value = source.name or ''
        if self.phone_input:
            self.phone_input.value = source.phone or ''
        if self.address_input:
            self.address_input.value = source.address or ''
        if self.website_input:
            self.website_input.value = source.website or ''

        # Try to parse city/state from address if available
        # This is a simple implementation - could be enhanced
        if source.address:
            parts = source.address.split(',')
            if len(parts) >= 2:
                if self.city_input:
                    self.city_input.value = parts[-2].strip() if len(parts) > 2 else ''
                if self.state_input:
                    state_zip = parts[-1].strip().split()
                    self.state_input.value = state_zip[0] if state_zip else ''
                    if self.zip_code_input and len(state_zip) > 1:
                        self.zip_code_input.value = state_zip[1]

    async def run_citation_check_for_sources(self, directories: List[str]):
        """Run citation check for selected sources."""
        if not CITATION_AVAILABLE or not self.crawler:
            ui.notify('Citation crawler not available', type='negative')
            return

        if not self.selected_sources:
            ui.notify('Please select at least one source', type='warning')
            return

        if not directories:
            ui.notify('Select at least one directory', type='warning')
            return

        if self.is_running:
            ui.notify('Citation check already running', type='warning')
            return

        self.is_running = True
        self.results = []

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Starting citation check for {len(self.selected_sources)} sources")
        self.add_log(f"Directories: {', '.join(directories)}")

        try:
            # Start crawler
            self.crawler.start()

            # Check each source
            loop = asyncio.get_event_loop()

            for source in self.selected_sources:
                self.add_log(f"Checking citations for: {source.name}")

                # Create BusinessInfo object from source
                # Parse city/state from address if needed
                city = ''
                state = ''
                zip_code = ''
                if source.address:
                    parts = source.address.split(',')
                    if len(parts) >= 2:
                        city = parts[-2].strip() if len(parts) > 2 else ''
                        state_zip = parts[-1].strip().split()
                        state = state_zip[0] if state_zip else ''
                        zip_code = state_zip[1] if len(state_zip) > 1 else ''

                biz = BusinessInfo(
                    name=source.name,
                    address=source.address,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    phone=source.phone,
                    website=source.website
                )

                # Check each directory
                for directory in directories:
                    try:
                        result = await loop.run_in_executor(
                            None,
                            lambda d=directory, b=biz: self.crawler.check_directory(b, d)
                        )

                        if result:
                            result_dict = result.to_dict()
                            result_dict['business_name'] = source.name
                            self.results.append(result_dict)

                            score = result.nap_score
                            if result.is_listed:
                                if score >= 0.8:
                                    self.add_log(f"✓ {source.name} on {directory}: NAP score {score:.2f}")
                                elif score >= 0.5:
                                    self.add_log(f"⚠ {source.name} on {directory}: NAP mismatch (score: {score:.2f})")
                                else:
                                    self.add_log(f"[WARN] {source.name} on {directory}: Poor NAP match (score: {score:.2f})")
                            else:
                                self.add_log(f"✗ {source.name} on {directory}: NOT FOUND")
                        else:
                            self.add_log(f"[ERROR] {source.name} on {directory}: Check failed")

                    except Exception as e:
                        self.add_log(f"[ERROR] {source.name} on {directory}: {e}")

            self.add_log(f"[COMPLETE] Citation check complete: {len(self.results)} checks")

            # Update results display
            self._update_results_display()

            ui.notify(f'Citation check complete: {len(self.results)} checks', type='positive')

        except Exception as e:
            self.add_log(f"[ERROR] Citation check failed: {e}")
            ui.notify(f'Check failed: {e}', type='negative')
        finally:
            # Stop crawler
            try:
                self.crawler.stop()
            except:
                pass

            self.is_running = False

            # Update button states
            if self.run_button:
                self.run_button.enable()
            if self.stop_button:
                self.stop_button.disable()

    async def run_citation_check(self, business_info: Dict, directories: List[str]):
        """Run citation check for manual input."""
        if not CITATION_AVAILABLE or not self.crawler:
            ui.notify('Citation crawler not available', type='negative')
            return

        if not business_info.get('name'):
            ui.notify('Business name is required', type='warning')
            return

        if not directories:
            ui.notify('Select at least one directory', type='warning')
            return

        if self.is_running:
            ui.notify('Citation check already running', type='warning')
            return

        self.is_running = True

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Starting citation check for: {business_info['name']}")
        self.add_log(f"Location: {business_info.get('city')}, {business_info.get('state')}")
        self.add_log(f"Directories: {', '.join(directories)}")

        try:
            # Create BusinessInfo object
            biz = BusinessInfo(
                name=business_info['name'],
                address=business_info.get('address', ''),
                city=business_info.get('city', ''),
                state=business_info.get('state', ''),
                zip_code=business_info.get('zip_code', ''),
                phone=business_info.get('phone', ''),
                website=business_info.get('website', '')
            )

            # Start crawler
            self.crawler.start()

            # Check each directory
            loop = asyncio.get_event_loop()

            for directory in directories:
                self.add_log(f"Checking {directory}...")

                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda d=directory: self.crawler.check_directory(biz, d)
                    )

                    if result:
                        result_dict = result.to_dict()
                        result_dict['business_name'] = business_info['name']
                        self.results.append(result_dict)

                        score = result.nap_score
                        if result.is_listed:
                            if score >= 0.8:
                                self.add_log(f"✓ {directory}: FOUND (NAP score: {score:.2f})")
                            elif score >= 0.5:
                                self.add_log(f"⚠ {directory}: FOUND but NAP mismatch (score: {score:.2f})")
                            else:
                                self.add_log(f"[WARN] {directory}: FOUND with poor NAP match (score: {score:.2f})")
                        else:
                            self.add_log(f"✗ {directory}: NOT FOUND")
                    else:
                        self.add_log(f"[ERROR] {directory}: Check failed")

                except Exception as e:
                    self.add_log(f"[ERROR] {directory}: {e}")

            self.add_log(f"[COMPLETE] Citation check complete: {len(self.results)} directories checked")

            # Update results display
            self._update_results_display()

            ui.notify(f'Citation check complete: {len(self.results)} directories', type='positive')

        except Exception as e:
            self.add_log(f"[ERROR] Citation check failed: {e}")
            ui.notify(f'Check failed: {e}', type='negative')
        finally:
            # Stop crawler
            try:
                self.crawler.stop()
            except:
                pass

            self.is_running = False

            # Update button states
            if self.run_button:
                self.run_button.enable()
            if self.stop_button:
                self.stop_button.disable()

    def stop_check(self):
        """Stop running check."""
        if self.crawler:
            try:
                self.crawler.stop()
                self.add_log("[STOPPED] Check stopped by user")
                ui.notify('Stopping check...', type='warning')
            except:
                pass


def citation_runner_page():
    """Create the Citation runner page."""
    ui.label('Citation Crawler Runner').classes('text-2xl font-bold mb-4')

    if not CITATION_AVAILABLE:
        ui.label('⚠️ Citation crawler not available').classes('text-yellow-400 text-lg')
        ui.label('Install required dependencies or check imports').classes('text-gray-400')
        return

    controller = CitationRunnerController()

    # Source selection panel (if backend available)
    if SEO_BACKEND_AVAILABLE and controller.backend:
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
            ui.label('SEO Sources').classes('text-lg font-semibold mb-2')
            ui.label('Select companies to check citations (optional - auto-fills NAP info)').classes('text-sm text-gray-400 mb-3')

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
                    has_website_only=False,  # Allow sources without websites for citation checks
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
                        {'name': 'phone', 'label': 'Phone', 'field': 'phone', 'align': 'left'},
                        {'name': 'source', 'label': 'Source', 'field': 'source', 'align': 'center'},
                    ]

                    rows = []
                    for s in sources:
                        rows.append({
                            'id': s.id,
                            'name': s.name[:40] if s.name else '',
                            'phone': s.phone[:20] if s.phone else '',
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

                        # Auto-fill from first selected source
                        if controller.selected_sources:
                            controller.auto_fill_from_source(controller.selected_sources[0])

                    table.on('selection', on_selection_change)
                    controller.sources_table = table

            # Load button
            with ui.row().classes('gap-2 mt-2'):
                ui.button('Load Sources', icon='refresh', on_click=load_sources).classes('bg-purple-600 hover:bg-purple-700')

            # Initial load
            load_sources()

    # Business information form
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Business Information (NAP)').classes('text-lg font-semibold mb-3')
        ui.label('Auto-filled from selected source or enter manually').classes('text-sm text-gray-400 mb-3')

        with ui.row().classes('w-full gap-4 mb-3'):
            controller.business_name_input = ui.input(
                label='Business Name *',
                placeholder='e.g., ABC Pressure Washing'
            ).classes('flex-grow').props('outlined dense')

            controller.phone_input = ui.input(
                label='Phone',
                placeholder='e.g., (512) 555-0100'
            ).classes('w-64').props('outlined dense')

        with ui.row().classes('w-full gap-4 mb-3'):
            controller.address_input = ui.input(
                label='Street Address',
                placeholder='e.g., 123 Main St'
            ).classes('flex-grow').props('outlined dense')

            controller.website_input = ui.input(
                label='Website',
                placeholder='e.g., https://example.com'
            ).classes('w-64').props('outlined dense')

        with ui.row().classes('w-full gap-4'):
            controller.city_input = ui.input(
                label='City',
                placeholder='e.g., Austin'
            ).classes('flex-grow').props('outlined dense')

            controller.state_input = ui.input(
                label='State',
                placeholder='e.g., TX'
            ).classes('w-32').props('outlined dense')

            controller.zip_code_input = ui.input(
                label='ZIP Code',
                placeholder='e.g., 78701'
            ).classes('w-32').props('outlined dense')

    # Directory selection
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Directories to Check').classes('text-lg font-semibold mb-3')

        directory_checkboxes = {}
        with ui.row().classes('w-full gap-x-8 gap-y-2 flex-wrap'):
            for dir_id, dir_info in CITATION_DIRECTORIES.items():
                checkbox = ui.checkbox(dir_info['name'], value=True)
                directory_checkboxes[dir_id] = checkbox

    # Action buttons
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        with ui.row().classes('gap-2'):
            async def run_check():
                selected_dirs = [dir_id for dir_id, cb in directory_checkboxes.items() if cb.value]

                if controller.selected_sources:
                    await controller.run_citation_check_for_sources(selected_dirs)
                else:
                    await controller.run_citation_check(
                        {
                            'name': controller.business_name_input.value,
                            'address': controller.address_input.value,
                            'city': controller.city_input.value,
                            'state': controller.state_input.value,
                            'zip_code': controller.zip_code_input.value,
                            'phone': controller.phone_input.value,
                            'website': controller.website_input.value,
                        },
                        selected_dirs
                    )

            controller.run_button = ui.button(
                'Run Citation Check',
                icon='fact_check',
                color='primary',
                on_click=run_check
            )

            controller.stop_button = ui.button(
                'Stop',
                icon='stop',
                color='negative',
                on_click=controller.stop_check
            ).props('outline')
            controller.stop_button.disable()

    # Live logs
    with ui.card().classes('p-4 bg-gray-900 rounded-lg w-full mb-4'):
        ui.label('Live Logs').classes('text-lg font-semibold mb-2')
        controller.log_container = ui.column().classes('w-full h-64 overflow-y-auto bg-black p-2 rounded')

    # Results section
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('Citation Check Results').classes('text-lg font-semibold mb-2')
        controller.results_container = ui.column().classes('w-full')

    # Initialize displays
    controller._update_log_display()
    controller._update_results_display()

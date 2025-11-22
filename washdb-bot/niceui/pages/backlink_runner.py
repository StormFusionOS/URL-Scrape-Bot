"""
Backlink Crawler Runner Dashboard

Interactive GUI for discovering backlinks with:
- Source selection from washdb (Local/National)
- Source URLs input (multiple)
- Target domain input or auto-fill from selected sources
- Live backlink discovery
- Link type breakdown (dofollow, nofollow, ugc, sponsored)
- Anchor text display
- Referring domains summary
"""

import asyncio
from datetime import datetime
from typing import List, Dict
from nicegui import ui
from ..theme import COLORS

# Try to import Backlink crawler
try:
    from seo_intelligence.scrapers.backlink_crawler import BacklinkCrawler
    BACKLINK_AVAILABLE = True
except ImportError:
    BACKLINK_AVAILABLE = False

# Import SEO backend for source selection
try:
    from ..services.seo_backend import get_seo_backend, SEOSource
    SEO_BACKEND_AVAILABLE = True
except ImportError:
    SEO_BACKEND_AVAILABLE = False


class BacklinkRunnerController:
    """Controller for Backlink crawler dashboard."""

    def __init__(self):
        self.crawler = BacklinkCrawler() if BACKLINK_AVAILABLE else None
        self.backend = get_seo_backend() if SEO_BACKEND_AVAILABLE else None
        self.selected_sources: List[SEOSource] = []
        self.log_lines: List[str] = []
        self.backlinks: List[Dict] = []
        self.is_running = False

        # UI elements
        self.log_container = None
        self.results_container = None
        self.stats_container = None
        self.run_button = None
        self.stop_button = None
        self.sources_table = None

        # Form elements for auto-fill
        self.target_domain_input = None

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
                        elif '[WARN]' in line or 'WARNING' in line:
                            color = 'text-yellow-400'
                        elif 'FOUND' in line or 'backlink' in line.lower():
                            color = 'text-green-400'
                        elif '[COMPLETE]' in line:
                            color = 'text-blue-400'
                        ui.label(line).classes(f'text-xs font-mono {color}')
            except Exception:
                pass

    def _update_results_display(self):
        """Update the results and stats containers."""
        if self.results_container:
            try:
                self.results_container.clear()
                with self.results_container:
                    if not self.backlinks:
                        ui.label('No backlinks found yet. Run backlink crawler to discover links.').classes('text-gray-400 py-4')
                    else:
                        # Create backlinks table
                        columns = [
                            {'name': 'target', 'label': 'Target Domain', 'field': 'target', 'align': 'left'},
                            {'name': 'source', 'label': 'Source Page', 'field': 'source', 'align': 'left'},
                            {'name': 'anchor', 'label': 'Anchor Text', 'field': 'anchor', 'align': 'left'},
                            {'name': 'link_type', 'label': 'Link Type', 'field': 'link_type', 'align': 'center'},
                        ]
                        rows = []
                        for bl in self.backlinks[-100:]:  # Show last 100
                            rows.append({
                                'target': bl.get('target_domain', '')[:25] + ('...' if len(bl.get('target_domain', '')) > 25 else ''),
                                'source': bl.get('source_url', '')[:40] + ('...' if len(bl.get('source_url', '')) > 40 else ''),
                                'anchor': bl.get('anchor_text', '')[:30] + ('...' if len(bl.get('anchor_text', '')) > 30 else ''),
                                'link_type': bl.get('link_type', 'dofollow'),
                            })

                        ui.table(columns=columns, rows=rows).classes('w-full')
                        ui.label(f'Total Backlinks Found: {len(self.backlinks)}').classes('text-sm text-gray-400 mt-2')
            except Exception as e:
                ui.label(f'Error displaying results: {e}').classes('text-red-400')

        if self.stats_container:
            try:
                self.stats_container.clear()
                with self.stats_container:
                    if not self.backlinks:
                        ui.label('No statistics yet').classes('text-gray-400 text-sm')
                    else:
                        # Calculate stats
                        total = len(self.backlinks)
                        dofollow = sum(1 for bl in self.backlinks if bl.get('link_type') == 'dofollow')
                        nofollow = sum(1 for bl in self.backlinks if bl.get('link_type') == 'nofollow')
                        ugc = sum(1 for bl in self.backlinks if bl.get('link_type') == 'ugc')
                        sponsored = sum(1 for bl in self.backlinks if bl.get('link_type') == 'sponsored')

                        # Get unique referring domains
                        referring_domains = set()
                        for bl in self.backlinks:
                            source = bl.get('source_url', '')
                            if source:
                                try:
                                    from urllib.parse import urlparse
                                    domain = urlparse(source).netloc
                                    if domain:
                                        referring_domains.add(domain)
                                except:
                                    pass

                        with ui.row().classes('gap-6'):
                            with ui.card().classes('p-3 bg-gray-700'):
                                ui.label('Total Backlinks').classes('text-xs text-gray-400')
                                ui.label(str(total)).classes('text-2xl font-bold text-blue-400')

                            with ui.card().classes('p-3 bg-gray-700'):
                                ui.label('Dofollow').classes('text-xs text-gray-400')
                                ui.label(str(dofollow)).classes('text-2xl font-bold text-green-400')

                            with ui.card().classes('p-3 bg-gray-700'):
                                ui.label('Nofollow').classes('text-xs text-gray-400')
                                ui.label(str(nofollow)).classes('text-2xl font-bold text-yellow-400')

                            with ui.card().classes('p-3 bg-gray-700'):
                                ui.label('Referring Domains').classes('text-xs text-gray-400')
                                ui.label(str(len(referring_domains))).classes('text-2xl font-bold text-purple-400')
            except Exception as e:
                ui.label(f'Error displaying stats: {e}').classes('text-red-400')

    def auto_fill_target_domain(self, source: SEOSource):
        """Auto-fill target domain from selected source."""
        if self.target_domain_input and source.domain:
            self.target_domain_input.value = source.domain

    async def run_backlink_for_sources(self, source_urls: str):
        """Run backlink crawler for selected target sources."""
        if not BACKLINK_AVAILABLE or not self.crawler:
            ui.notify('Backlink crawler not available', type='negative')
            return

        if not self.selected_sources:
            ui.notify('Please select at least one target source', type='warning')
            return

        # Parse source URLs (one per line)
        urls = [url.strip() for url in source_urls.split('\n') if url.strip()]

        if not urls:
            ui.notify('Please enter at least one source URL to check', type='warning')
            return

        if self.is_running:
            ui.notify('Backlink crawler already running', type='warning')
            return

        self.is_running = True
        self.backlinks = []

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Starting backlink crawler for {len(self.selected_sources)} targets")
        self.add_log(f"Source URLs to check: {len(urls)}")

        try:
            # Start crawler
            self.crawler.start()

            # Check each target source
            loop = asyncio.get_event_loop()

            for target_source in self.selected_sources:
                target_domain = target_source.domain or target_source.name
                self.add_log(f"Searching for backlinks to: {target_domain}")

                # Check each source URL for backlinks to this target
                for url in urls:
                    try:
                        result = await loop.run_in_executor(
                            None,
                            lambda u=url, t=target_domain: self.crawler.check_page_for_backlinks(u, t)
                        )

                        if result and 'backlinks' in result:
                            backlinks = result['backlinks']
                            if backlinks:
                                # Add target domain to each backlink
                                for bl in backlinks:
                                    bl['target_domain'] = target_domain
                                self.backlinks.extend(backlinks)
                                self.add_log(f"✓ Found {len(backlinks)} backlinks to {target_domain} on {url}")
                            else:
                                self.add_log(f"✗ No backlinks to {target_domain} found on {url}")
                        else:
                            self.add_log(f"[WARN] {url}: No data returned")

                    except Exception as e:
                        self.add_log(f"[ERROR] {url}: {e}")

            self.add_log(f"[COMPLETE] Backlink crawler complete: {len(self.backlinks)} total backlinks")

            # Update displays
            self._update_results_display()

            ui.notify(f'Backlink crawler complete: {len(self.backlinks)} backlinks found', type='positive')

        except Exception as e:
            self.add_log(f"[ERROR] Backlink crawler failed: {e}")
            ui.notify(f'Crawler failed: {e}', type='negative')
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

    async def run_backlink_crawler(self, source_urls: str, target_domain: str):
        """Run backlink crawler asynchronously."""
        if not BACKLINK_AVAILABLE or not self.crawler:
            ui.notify('Backlink crawler not available', type='negative')
            return

        # Parse source URLs (one per line)
        urls = [url.strip() for url in source_urls.split('\n') if url.strip()]

        if not urls:
            ui.notify('Please enter at least one source URL', type='warning')
            return

        if not target_domain.strip():
            ui.notify('Please enter a target domain', type='warning')
            return

        if self.is_running:
            ui.notify('Backlink crawler already running', type='warning')
            return

        self.is_running = True
        self.backlinks = []

        # Update button states
        if self.run_button:
            self.run_button.disable()
        if self.stop_button:
            self.stop_button.enable()

        self.add_log(f"[START] Starting backlink crawler")
        self.add_log(f"Target domain: {target_domain}")
        self.add_log(f"Source URLs: {len(urls)}")

        try:
            # Start crawler
            self.crawler.start()

            # Check each source URL
            loop = asyncio.get_event_loop()

            for url in urls:
                self.add_log(f"Checking {url}...")

                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda u=url: self.crawler.check_page_for_backlinks(u, target_domain)
                    )

                    if result and 'backlinks' in result:
                        backlinks = result['backlinks']
                        if backlinks:
                            # Add target domain to each backlink
                            for bl in backlinks:
                                bl['target_domain'] = target_domain
                            self.backlinks.extend(backlinks)
                            self.add_log(f"✓ Found {len(backlinks)} backlinks on {url}")
                        else:
                            self.add_log(f"✗ No backlinks found on {url}")
                    else:
                        self.add_log(f"[WARN] {url}: No data returned")

                except Exception as e:
                    self.add_log(f"[ERROR] {url}: {e}")

            self.add_log(f"[COMPLETE] Backlink crawler complete: {len(self.backlinks)} total backlinks")

            # Update displays
            self._update_results_display()

            ui.notify(f'Backlink crawler complete: {len(self.backlinks)} backlinks found', type='positive')

        except Exception as e:
            self.add_log(f"[ERROR] Backlink crawler failed: {e}")
            ui.notify(f'Crawler failed: {e}', type='negative')
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

    def stop_crawler(self):
        """Stop running crawler."""
        if self.crawler:
            try:
                self.crawler.stop()
                self.add_log("[STOPPED] Crawler stopped by user")
                ui.notify('Stopping crawler...', type='warning')
            except:
                pass


def backlink_runner_page():
    """Create the Backlink runner page."""
    ui.label('Backlink Crawler Runner').classes('text-2xl font-bold mb-4')

    if not BACKLINK_AVAILABLE:
        ui.label('⚠️ Backlink crawler not available').classes('text-yellow-400 text-lg')
        ui.label('Install required dependencies or check imports').classes('text-gray-400')
        return

    controller = BacklinkRunnerController()

    # Source selection panel for TARGETS (if backend available)
    if SEO_BACKEND_AVAILABLE and controller.backend:
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
            ui.label('Target SEO Sources').classes('text-lg font-semibold mb-2')
            ui.label('Select companies to find backlinks TO (optional - uses their domains as targets)').classes('text-sm text-gray-400 mb-3')

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

                        # Auto-fill target domain from first selected source
                        if controller.selected_sources:
                            controller.auto_fill_target_domain(controller.selected_sources[0])

                    table.on('selection', on_selection_change)
                    controller.sources_table = table

            # Load button
            with ui.row().classes('gap-2 mt-2'):
                ui.button('Load Sources', icon='refresh', on_click=load_sources).classes('bg-purple-600 hover:bg-purple-700')

            # Initial load
            load_sources()

    # Input form
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Crawler Parameters').classes('text-lg font-semibold mb-3')

        with ui.row().classes('w-full gap-4'):
            # Source URLs textarea
            with ui.column().classes('flex-grow'):
                ui.label('Source URLs (one per line) - Pages to check FOR backlinks').classes('text-sm text-gray-400 mb-1')
                source_urls = ui.textarea(
                    placeholder='https://example.com/page1\nhttps://example.com/page2\n...',
                    value=''
                ).classes('w-full').props('outlined dense rows=5')

            # Target domain input
            with ui.column().classes('w-96'):
                ui.label('Target Domain to Find').classes('text-sm text-gray-400 mb-1')
                ui.label('(Auto-filled from selected source or enter manually)').classes('text-xs text-gray-500 mb-1')
                controller.target_domain_input = ui.input(
                    placeholder='e.g., mysite.com',
                    value=''
                ).classes('w-full').props('outlined dense')

                ui.label('Examples:').classes('text-xs text-gray-500 mt-2')
                ui.label('• mysite.com').classes('text-xs text-gray-500 ml-2')
                ui.label('• www.mysite.com').classes('text-xs text-gray-500 ml-2')
                ui.label('(crawler will match variations)').classes('text-xs text-gray-500 ml-2 mt-1')

        # Action buttons
        with ui.row().classes('mt-4 gap-2'):
            async def run_crawler():
                if controller.selected_sources:
                    await controller.run_backlink_for_sources(source_urls.value)
                else:
                    await controller.run_backlink_crawler(source_urls.value, controller.target_domain_input.value)

            controller.run_button = ui.button(
                'Run Backlink Crawler',
                icon='link',
                color='primary',
                on_click=run_crawler
            )

            controller.stop_button = ui.button(
                'Stop',
                icon='stop',
                color='negative',
                on_click=controller.stop_crawler
            ).props('outline')
            controller.stop_button.disable()

    # Statistics cards
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full mb-4'):
        ui.label('Statistics').classes('text-lg font-semibold mb-2')
        controller.stats_container = ui.row().classes('w-full gap-4')

    # Live logs
    with ui.card().classes('p-4 bg-gray-900 rounded-lg w-full mb-4'):
        ui.label('Live Logs').classes('text-lg font-semibold mb-2')
        controller.log_container = ui.column().classes('w-full h-64 overflow-y-auto bg-black p-2 rounded')

    # Results section
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('Discovered Backlinks').classes('text-lg font-semibold mb-2')
        controller.results_container = ui.column().classes('w-full')

    # Initialize displays
    controller._update_log_display()
    controller._update_results_display()

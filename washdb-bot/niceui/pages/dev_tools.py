"""
Developer Tools Page

Testing interface for Phase 2A components:
- URL Canonicalizer: Test URL normalization and deduplication
- Domain Quarantine: View and manage quarantined domains
- Service Health: Monitor singleton service states and cache statistics
"""

from nicegui import ui
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import asyncio

from ..layout import layout
from seo_intelligence.services import (
    get_url_canonicalizer,
    get_domain_quarantine,
    get_source_trust,
    get_section_embedder,
    get_nap_validator,
    get_entity_matcher,
)


class DevToolsPageState:
    """State management for Developer Tools page."""

    def __init__(self):
        # URL Canonicalizer state
        self.test_url: str = ""
        self.canonicalization_results: List[Dict[str, Any]] = []

        # Domain Quarantine state
        self.quarantine_entries: List[Dict[str, Any]] = []
        self.quarantine_stats: Dict[str, Any] = {}

        # Service Health state
        self.service_health: Dict[str, Dict[str, Any]] = {}

        # UI components
        self.url_input: Optional[ui.input] = None
        self.results_container: Optional[ui.element] = None
        self.quarantine_table: Optional[ui.table] = None
        self.stats_container: Optional[ui.element] = None
        self.health_container: Optional[ui.element] = None

        # Update timer
        self.update_timer: Optional[asyncio.Task] = None


state = DevToolsPageState()


async def test_url_canonicalization():
    """Test URL canonicalization and display results."""
    if not state.test_url or not state.test_url.strip():
        ui.notify("Please enter a URL", type="warning")
        return

    try:
        canonicalizer = get_url_canonicalizer()
        result = canonicalizer.canonicalize(state.test_url.strip())

        # Calculate changes made
        changes = []
        if result.original_url != result.canonical_url:
            if result.stripped_params:
                changes.append('params_stripped')
            if result.original_url.lower() != result.original_url:
                changes.append('normalized_case')
            if '://' in result.original_url and result.original_url.split('://')[1].startswith('www.'):
                changes.append('www_removed')
            if result.original_url.rstrip('/') != result.original_url:
                changes.append('trailing_slash_removed')

        # Add to results
        state.canonicalization_results.insert(0, {
            'original_url': state.test_url.strip(),
            'canonical_url': result.canonical_url,
            'url_hash': result.url_hash[:16] + '...',  # Shortened for display
            'domain': result.domain,
            'stripped_params': ', '.join(result.stripped_params) if result.stripped_params else 'None',
            'changes_made': changes,
            'tested_at': datetime.now().strftime('%H:%M:%S'),
        })

        # Keep only last 10 results
        state.canonicalization_results = state.canonicalization_results[:10]

        # Update UI
        update_canonicalizer_results()

        ui.notify("URL canonicalized successfully", type="positive")

    except Exception as e:
        ui.notify(f"Error: {str(e)}", type="negative")


def update_canonicalizer_results():
    """Update the canonicalization results display."""
    if state.results_container:
        state.results_container.clear()
        with state.results_container:
            if not state.canonicalization_results:
                ui.label("No results yet. Enter a URL above to test canonicalization.").classes('text-gray-500 italic')
            else:
                # Show cache stats
                canonicalizer = get_url_canonicalizer()
                cache_size = len(canonicalizer._canonical_cache)

                with ui.card().classes('w-full mb-4'):
                    ui.label(f"Cache: {cache_size} entries").classes('text-sm text-gray-400')

                # Show results
                for result in state.canonicalization_results:
                    with ui.card().classes('w-full mb-2'):
                        ui.label(f"Tested at: {result['tested_at']}").classes('text-xs text-gray-500')

                        with ui.row().classes('w-full items-center gap-4'):
                            ui.label("Original:").classes('text-sm font-bold w-20')
                            ui.label(result['original_url']).classes('text-sm break-all flex-1')

                        with ui.row().classes('w-full items-center gap-4'):
                            ui.label("Canonical:").classes('text-sm font-bold w-20')
                            ui.label(result['canonical_url']).classes('text-sm break-all flex-1 text-green-400')

                        with ui.row().classes('w-full items-center gap-4'):
                            ui.label("Domain:").classes('text-sm font-bold w-20')
                            ui.label(result['domain']).classes('text-sm')

                        with ui.row().classes('w-full items-center gap-4'):
                            ui.label("Hash:").classes('text-sm font-bold w-20')
                            ui.label(result['url_hash']).classes('text-sm font-mono text-gray-400')

                        if result['stripped_params'] != 'None':
                            with ui.row().classes('w-full items-center gap-4'):
                                ui.label("Stripped:").classes('text-sm font-bold w-20')
                                ui.label(result['stripped_params']).classes('text-sm text-yellow-400')

                        if result['changes_made']:
                            ui.label(f"Changes: {', '.join(result['changes_made'])}").classes('text-xs text-blue-400 mt-1')


async def update_quarantine_data():
    """Update quarantine data display."""
    try:
        quarantine = get_domain_quarantine()

        # Get all quarantined domains
        entries = []
        for domain, entry in quarantine._quarantined.items():
            # Check if still quarantined (not expired)
            if quarantine.is_quarantined(domain):
                entries.append({
                    'domain': domain,
                    'reason': entry.reason.value if hasattr(entry.reason, 'value') else str(entry.reason),
                    'quarantined_at': entry.quarantined_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'expires_at': entry.expires_at.strftime('%Y-%m-%d %H:%M:%S') if entry.expires_at else 'Never',
                    'retry_attempts': quarantine.get_retry_attempt(domain),
                    'metadata': str(entry.metadata) if entry.metadata else '',
                })

        state.quarantine_entries = entries

        # Get stats
        state.quarantine_stats = quarantine.get_stats()

        # Update UI
        if state.quarantine_table:
            state.quarantine_table.update()

        if state.stats_container:
            state.stats_container.clear()
            with state.stats_container:
                with ui.row().classes('gap-4'):
                    with ui.card():
                        ui.label("Total Quarantined").classes('text-sm text-gray-400')
                        ui.label(str(state.quarantine_stats.get('total_quarantined', 0))).classes('text-2xl font-bold')

                    with ui.card():
                        ui.label("Active (Not Expired)").classes('text-sm text-gray-400')
                        ui.label(str(len(state.quarantine_entries))).classes('text-2xl font-bold')

                if state.quarantine_stats.get('by_reason'):
                    ui.label("By Reason:").classes('text-sm font-bold mt-4')
                    with ui.column().classes('gap-1'):
                        for reason, count in state.quarantine_stats['by_reason'].items():
                            with ui.row().classes('gap-2'):
                                ui.label(f"{reason}:").classes('text-sm w-48')
                                ui.label(str(count)).classes('text-sm font-bold')

    except Exception as e:
        print(f"Error updating quarantine data: {e}")


def release_domain(domain: str):
    """Release a domain from quarantine."""
    try:
        quarantine = get_domain_quarantine()
        quarantine.release_quarantine(domain)
        ui.notify(f"Released {domain} from quarantine", type="positive")
        asyncio.create_task(update_quarantine_data())
    except Exception as e:
        ui.notify(f"Error: {str(e)}", type="negative")


def clear_all_quarantines():
    """Clear all quarantines."""
    try:
        quarantine = get_domain_quarantine()
        quarantine.clear_all()
        ui.notify("All quarantines cleared", type="positive")
        asyncio.create_task(update_quarantine_data())
    except Exception as e:
        ui.notify(f"Error: {str(e)}", type="negative")


async def update_service_health():
    """Update service health display."""
    try:
        health_data = {}

        # URL Canonicalizer
        canonicalizer = get_url_canonicalizer()
        health_data['URL Canonicalizer'] = {
            'status': 'active',
            'cache_size': len(canonicalizer._canonical_cache),
            'tracking_params': len(canonicalizer.tracking_params),
        }

        # Domain Quarantine
        quarantine = get_domain_quarantine()
        health_data['Domain Quarantine'] = {
            'status': 'active',
            'quarantined_domains': len(quarantine._quarantined),
            'tracked_errors': len(quarantine._error_events),
            'retry_tracking': len(quarantine._retry_attempts),
        }

        # Source Trust
        try:
            trust = get_source_trust()
            health_data['Source Trust'] = {
                'status': 'active',
                'trust_weights': len(trust.trust_weights),
            }
        except:
            health_data['Source Trust'] = {'status': 'error'}

        # Section Embedder
        try:
            embedder = get_section_embedder()
            health_data['Section Embedder'] = {
                'status': 'active',
                'model': embedder.model_name,
            }
        except:
            health_data['Section Embedder'] = {'status': 'not initialized'}

        # NAP Validator
        try:
            nap = get_nap_validator()
            health_data['NAP Validator'] = {
                'status': 'active',
                'conflict_threshold': nap.conflict_threshold,
            }
        except:
            health_data['NAP Validator'] = {'status': 'error'}

        # Entity Matcher
        try:
            matcher = get_entity_matcher()
            health_data['Entity Matcher'] = {
                'status': 'active',
            }
        except:
            health_data['Entity Matcher'] = {'status': 'error'}

        state.service_health = health_data

        # Update UI
        if state.health_container:
            state.health_container.clear()
            with state.health_container:
                for service_name, data in state.service_health.items():
                    with ui.card().classes('w-full mb-2'):
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label(service_name).classes('text-lg font-bold')

                            status = data.get('status', 'unknown')
                            if status == 'active':
                                ui.badge("Active", color="green")
                            elif status == 'not initialized':
                                ui.badge("Not Init", color="orange")
                            else:
                                ui.badge("Error", color="red")

                        # Show metrics
                        metrics = {k: v for k, v in data.items() if k != 'status'}
                        if metrics:
                            with ui.column().classes('gap-1 mt-2'):
                                for key, value in metrics.items():
                                    with ui.row().classes('gap-2'):
                                        ui.label(f"{key}:").classes('text-sm text-gray-400 w-48')
                                        ui.label(str(value)).classes('text-sm')

    except Exception as e:
        print(f"Error updating service health: {e}")


def clear_url_cache():
    """Clear URL canonicalizer cache."""
    try:
        canonicalizer = get_url_canonicalizer()
        canonicalizer._canonical_cache.clear()
        ui.notify("URL cache cleared", type="positive")
        asyncio.create_task(update_service_health())
    except Exception as e:
        ui.notify(f"Error: {str(e)}", type="negative")


async def periodic_updates():
    """Periodically update quarantine and health data."""
    while True:
        await asyncio.sleep(10)  # Update every 10 seconds
        await update_quarantine_data()
        await update_service_health()


def dev_tools_page():
    """Developer Tools page with three tabs for Phase 2A testing."""

    ui.label('Developer Tools').classes('text-2xl font-bold mb-4')
    ui.label('Phase 2A Component Testing Interface').classes('text-gray-400 mb-6')

    with ui.tabs().classes('w-full') as tabs:
        tab1 = ui.tab('URL Canonicalizer', icon='link')
        tab2 = ui.tab('Domain Quarantine', icon='block')
        tab3 = ui.tab('Service Health', icon='monitoring')

    with ui.tab_panels(tabs, value=tab1).classes('w-full'):
        # Tab 1: URL Canonicalizer
        with ui.tab_panel(tab1):
            ui.label('URL Canonicalization Testing').classes('text-xl font-bold mb-4')
            ui.label('Test URL normalization, tracking parameter removal, and deduplication').classes('text-gray-400 mb-4')

            with ui.card().classes('w-full mb-4'):
                ui.label('Test a URL').classes('text-lg font-bold mb-2')

                with ui.row().classes('w-full gap-2'):
                    state.url_input = ui.input(
                        'URL to test',
                        placeholder='https://example.com/page?utm_source=google&fbclid=123',
                        on_change=lambda e: setattr(state, 'test_url', e.value)
                    ).classes('flex-1').on('keydown.enter', test_url_canonicalization)

                    ui.button('Test', on_click=test_url_canonicalization, icon='play_arrow').props('color=primary')

                # Quick test examples
                with ui.row().classes('gap-2 mt-2'):
                    ui.label('Quick tests:').classes('text-sm text-gray-400')
                    ui.button(
                        'Tracking Params',
                        on_click=lambda: (
                            setattr(state, 'test_url', 'https://example.com/?utm_source=google&fbclid=123'),
                            state.url_input.set_value('https://example.com/?utm_source=google&fbclid=123')
                        )
                    ).props('size=sm flat')
                    ui.button(
                        'WWW Strip',
                        on_click=lambda: (
                            setattr(state, 'test_url', 'https://www.example.com/page'),
                            state.url_input.set_value('https://www.example.com/page')
                        )
                    ).props('size=sm flat')
                    ui.button(
                        'Trailing Slash',
                        on_click=lambda: (
                            setattr(state, 'test_url', 'https://example.com/page/'),
                            state.url_input.set_value('https://example.com/page/')
                        )
                    ).props('size=sm flat')

            # Results container
            state.results_container = ui.column().classes('w-full')
            update_canonicalizer_results()

        # Tab 2: Domain Quarantine
        with ui.tab_panel(tab2):
            ui.label('Domain Quarantine Management').classes('text-xl font-bold mb-4')
            ui.label('View and manage quarantined domains with exponential backoff').classes('text-gray-400 mb-4')

            # Stats container
            state.stats_container = ui.row().classes('w-full gap-4 mb-4')

            # Controls
            with ui.card().classes('w-full mb-4'):
                ui.label('Controls').classes('text-lg font-bold mb-2')
                with ui.row().classes('gap-2'):
                    ui.button('Refresh', on_click=lambda: asyncio.create_task(update_quarantine_data()), icon='refresh').props('color=primary')
                    ui.button('Clear All', on_click=clear_all_quarantines, icon='delete_sweep').props('color=negative')

            # Quarantine table
            state.quarantine_table = ui.table(
                columns=[
                    {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'align': 'left'},
                    {'name': 'reason', 'label': 'Reason', 'field': 'reason', 'align': 'left'},
                    {'name': 'quarantined_at', 'label': 'Quarantined At', 'field': 'quarantined_at', 'align': 'left'},
                    {'name': 'expires_at', 'label': 'Expires At', 'field': 'expires_at', 'align': 'left'},
                    {'name': 'retry_attempts', 'label': 'Retries', 'field': 'retry_attempts', 'align': 'center'},
                    {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'align': 'center'},
                ],
                rows=state.quarantine_entries,
                row_key='domain'
            ).classes('w-full')

            # Add action buttons to table
            state.quarantine_table.add_slot('body-cell-actions', '''
                <q-td :props="props">
                    <q-btn size="sm" flat dense icon="cancel" color="primary" @click="$parent.$emit('release', props.row.domain)">
                        <q-tooltip>Release</q-tooltip>
                    </q-btn>
                </q-td>
            ''')
            state.quarantine_table.on('release', lambda e: release_domain(e.args))

            # Initial load
            asyncio.create_task(update_quarantine_data())

        # Tab 3: Service Health
        with ui.tab_panel(tab3):
            ui.label('Service Health Monitor').classes('text-xl font-bold mb-4')
            ui.label('Monitor singleton service states and cache statistics').classes('text-gray-400 mb-4')

            # Controls
            with ui.card().classes('w-full mb-4'):
                ui.label('Controls').classes('text-lg font-bold mb-2')
                with ui.row().classes('gap-2'):
                    ui.button('Refresh', on_click=lambda: asyncio.create_task(update_service_health()), icon='refresh').props('color=primary')
                    ui.button('Clear URL Cache', on_click=clear_url_cache, icon='clear_all').props('color=orange')

            # Health container
            state.health_container = ui.column().classes('w-full')

            # Initial load
            asyncio.create_task(update_service_health())

    # Start periodic updates
    if state.update_timer is None or state.update_timer.done():
        state.update_timer = asyncio.create_task(periodic_updates())

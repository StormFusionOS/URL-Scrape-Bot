"""
Washbot Database Monitor Page
Real-time monitoring of URL source database (washbot_db) integration
"""

from nicegui import ui
from sqlalchemy import text
from datetime import datetime
import sys
import os

from db.database_manager import get_db_manager
from niceui.components.glass_card import glass_card, section_title, divider
from niceui.layout import page_layout

# Get database manager instance
db_manager = get_db_manager()

# URL Source Connector would need to be imported if available
# from url_source_connector import URLSourceConnector


def create_page():
    """Create the washbot_db monitoring page"""

    # Note: URLSourceConnector not needed in integrated system
    # We have direct access to both databases via DatabaseManager
    connector = None
    connector_available = False
    connector_error = None

    # State
    health_data = {
        'washdb': {'status': 'unknown', 'latency_ms': None, 'error': None},
        'scraper': {'status': 'unknown', 'latency_ms': None, 'error': None}
    }

    sync_stats = {
        'total_companies': 0,
        'unique_domains': 0,
        'yp_sources': 0,
        'ha_sources': 0,
        'google_sources': 0,
        'avg_confidence': 0,
        'avg_completeness': 0
    }

    sync_history_stats = {
        'total_syncs': 0,
        'successful_syncs': 0,
        'failed_syncs': 0,
        'skipped_syncs': 0,
        'last_sync_time': None,
        'unique_companies_synced': 0
    }

    recent_syncs = []

    # UI element references
    ui_refs = {
        # Connection health
        'washdb_icon': None,
        'washdb_label': None,
        'washdb_latency': None,
        'washdb_error': None,
        'scraper_icon': None,
        'scraper_label': None,
        'scraper_latency': None,

        # Washdb stats
        'total_companies': None,
        'unique_domains': None,
        'yp_sources': None,
        'ha_sources': None,
        'google_sources': None,
        'avg_confidence': None,
        'avg_completeness': None,

        # Sync history stats
        'total_syncs': None,
        'successful_syncs': None,
        'failed_syncs': None,
        'skipped_syncs': None,
        'last_sync_time': None,
        'unique_companies_synced': None,
        'success_rate': None,

        # Recent syncs table
        'recent_syncs_table': None,

        # Sync controls
        'batch_size_input': None,
        'min_confidence_input': None,
        'priority_input': None,
        'sync_button': None,
        'sync_result_label': None
    }

    def check_connection_health():
        """Check connection health for both databases"""
        try:
            # Check washdb
            washdb_health = db_manager.get_connection_health('washdb')
            health_data['washdb'] = washdb_health

            # Check scraper DB
            scraper_health = db_manager.get_connection_health('scraper')
            health_data['scraper'] = scraper_health

        except Exception as e:
            ui.notify(f'Error checking connection health: {str(e)}', type='negative')

    def fetch_washdb_stats():
        """Fetch statistics from washbot_db using DatabaseManager"""
        try:
            # Query washbot database directly for company statistics
            with db_manager.get_session('washdb') as session:
                result = session.execute(text("""
                    SELECT
                        COUNT(*) as total_companies,
                        COUNT(DISTINCT domain) as unique_domains,
                        SUM(CASE WHEN source = 'YP' THEN 1 ELSE 0 END) as yp_sources,
                        SUM(CASE WHEN source = 'homeadvisor' THEN 1 ELSE 0 END) as ha_sources,
                        SUM(CASE WHEN source = 'Google' THEN 1 ELSE 0 END) as google_sources,
                        AVG(confidence_score) as avg_confidence
                    FROM companies
                    WHERE website IS NOT NULL AND website != ''
                """))
                row = result.fetchone()

                if row:
                    sync_stats['total_companies'] = row[0] or 0
                    sync_stats['unique_domains'] = row[1] or 0
                    sync_stats['yp_sources'] = row[2] or 0
                    sync_stats['ha_sources'] = row[3] or 0
                    sync_stats['google_sources'] = row[4] or 0
                    sync_stats['avg_confidence'] = round(row[5] or 0, 2)

        except Exception as e:
            ui.notify(f'Error fetching washdb stats: {str(e)}', type='negative')

    def fetch_sync_history_stats():
        """Fetch sync history statistics"""
        try:
            with db_manager.get_session('scraper') as session:
                result = session.execute(text("""
                    SELECT * FROM public.url_sync_stats
                """))
                row = result.fetchone()

                if row:
                    sync_history_stats['total_syncs'] = row[0] or 0
                    sync_history_stats['successful_syncs'] = row[1] or 0
                    sync_history_stats['failed_syncs'] = row[2] or 0
                    sync_history_stats['skipped_syncs'] = row[3] or 0
                    sync_history_stats['last_sync_time'] = row[4]
                    sync_history_stats['unique_companies_synced'] = row[5] or 0

        except Exception as e:
            ui.notify(f'Error fetching sync history: {str(e)}', type='negative')

    def fetch_recent_syncs(limit=10):
        """Fetch recent sync operations"""
        try:
            with db_manager.get_session('scraper') as session:
                result = session.execute(text("""
                    SELECT
                        washbot_company_id,
                        company_name,
                        website_url,
                        domain,
                        synced_at,
                        sync_status,
                        source,
                        confidence_score,
                        error_message
                    FROM public.url_sync_history
                    ORDER BY synced_at DESC
                    LIMIT :limit
                """), {'limit': limit})

                recent_syncs.clear()
                for row in result:
                    recent_syncs.append({
                        'company_id': row[0],
                        'company_name': row[1] or 'N/A',
                        'website_url': row[2],
                        'domain': row[3],
                        'synced_at': row[4].strftime('%Y-%m-%d %H:%M:%S') if row[4] else '',
                        'status': row[5],
                        'source': row[6] or 'N/A',
                        'confidence': f"{row[7]:.1f}" if row[7] else 'N/A',
                        'error': row[8] or ''
                    })

        except Exception as e:
            ui.notify(f'Error fetching recent syncs: {str(e)}', type='negative')

    def update_all_displays():
        """Update all displays with current data"""
        update_connection_health_display()
        update_washdb_stats_display()
        update_sync_history_display()
        update_recent_syncs_table()

    def update_connection_health_display():
        """Update connection health indicators"""
        # Washdb connection
        if ui_refs['washdb_icon'] and ui_refs['washdb_label']:
            washdb = health_data['washdb']
            if washdb['connected']:
                ui_refs['washdb_icon'].props('name=check_circle color=positive')
                ui_refs['washdb_label'].set_text('Connected')
                if ui_refs['washdb_latency']:
                    ui_refs['washdb_latency'].set_text(f"{washdb['latency_ms']}ms")
                if ui_refs['washdb_error']:
                    ui_refs['washdb_error'].set_text('')
            else:
                ui_refs['washdb_icon'].props('name=error color=negative')
                ui_refs['washdb_label'].set_text('Disconnected')
                if ui_refs['washdb_latency']:
                    ui_refs['washdb_latency'].set_text('—')
                if ui_refs['washdb_error']:
                    ui_refs['washdb_error'].set_text(washdb['error'] or '')

        # Scraper DB connection
        if ui_refs['scraper_icon'] and ui_refs['scraper_label']:
            scraper = health_data['scraper']
            if scraper['connected']:
                ui_refs['scraper_icon'].props('name=check_circle color=positive')
                ui_refs['scraper_label'].set_text('Connected')
                if ui_refs['scraper_latency']:
                    ui_refs['scraper_latency'].set_text(f"{scraper['latency_ms']}ms")
            else:
                ui_refs['scraper_icon'].props('name=error color=negative')
                ui_refs['scraper_label'].set_text('Disconnected')
                if ui_refs['scraper_latency']:
                    ui_refs['scraper_latency'].set_text('—')

    def update_washdb_stats_display():
        """Update washdb statistics display"""
        if ui_refs['total_companies']:
            ui_refs['total_companies'].set_text(f"{sync_stats['total_companies']:,}")
        if ui_refs['unique_domains']:
            ui_refs['unique_domains'].set_text(f"{sync_stats['unique_domains']:,}")
        if ui_refs['yp_sources']:
            ui_refs['yp_sources'].set_text(f"{sync_stats['yp_sources']:,}")
        if ui_refs['ha_sources']:
            ui_refs['ha_sources'].set_text(f"{sync_stats['ha_sources']:,}")
        if ui_refs['google_sources']:
            ui_refs['google_sources'].set_text(f"{sync_stats['google_sources']:,}")
        if ui_refs['avg_confidence']:
            ui_refs['avg_confidence'].set_text(f"{sync_stats['avg_confidence']:.1f}%")
        if ui_refs['avg_completeness']:
            ui_refs['avg_completeness'].set_text(f"{sync_stats['avg_completeness']:.1f}%")

    def update_sync_history_display():
        """Update sync history statistics display"""
        if ui_refs['total_syncs']:
            ui_refs['total_syncs'].set_text(f"{sync_history_stats['total_syncs']:,}")
        if ui_refs['successful_syncs']:
            ui_refs['successful_syncs'].set_text(f"{sync_history_stats['successful_syncs']:,}")
        if ui_refs['failed_syncs']:
            ui_refs['failed_syncs'].set_text(f"{sync_history_stats['failed_syncs']:,}")
        if ui_refs['skipped_syncs']:
            ui_refs['skipped_syncs'].set_text(f"{sync_history_stats['skipped_syncs']:,}")
        if ui_refs['last_sync_time']:
            last_sync = sync_history_stats['last_sync_time']
            if last_sync:
                time_str = last_sync.strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = 'Never'
            ui_refs['last_sync_time'].set_text(time_str)
        if ui_refs['unique_companies_synced']:
            ui_refs['unique_companies_synced'].set_text(f"{sync_history_stats['unique_companies_synced']:,}")
        if ui_refs['success_rate']:
            total = sync_history_stats['total_syncs']
            if total > 0:
                success_rate = (sync_history_stats['successful_syncs'] / total) * 100
                ui_refs['success_rate'].set_text(f"{success_rate:.1f}%")
            else:
                ui_refs['success_rate'].set_text('N/A')

    def update_recent_syncs_table():
        """Update recent syncs table"""
        if ui_refs['recent_syncs_table']:
            ui_refs['recent_syncs_table'].options['rowData'] = recent_syncs
            ui_refs['recent_syncs_table'].update()

    def refresh_all_data():
        """Refresh all data from databases"""
        ui.notify('Refreshing data...', type='info')
        check_connection_health()
        fetch_washdb_stats()
        fetch_sync_history_stats()
        fetch_recent_syncs()
        update_all_displays()
        ui.notify('Data refreshed', type='positive')

    def trigger_manual_sync():
        """Trigger manual sync operation"""
        # In integrated system, both databases are directly accessible
        # Manual sync via URLSourceConnector is not needed
        ui.notify('Manual sync not needed - databases are directly integrated', type='info')
        return

        try:
            if ui_refs['sync_button']:
                ui_refs['sync_button'].props('disable')

            # Get parameters from inputs
            batch_size = int(ui_refs['batch_size_input'].value) if ui_refs['batch_size_input'] else 100
            min_confidence = float(ui_refs['min_confidence_input'].value) if ui_refs['min_confidence_input'] else 50.0
            priority = int(ui_refs['priority_input'].value) if ui_refs['priority_input'] else 5

            ui.notify(f'Starting sync: batch_size={batch_size}, min_confidence={min_confidence}', type='info')

            # Perform sync
            stats = connector.sync_urls_to_crawler(
                batch_size=batch_size,
                min_confidence=min_confidence,
                priority=priority
            )

            # Display result
            result_msg = (
                f"Sync completed! "
                f"Fetched: {stats['fetched']}, "
                f"Created: {stats['created']}, "
                f"Skipped: {stats['skipped']}, "
                f"Errors: {stats['errors']}"
            )

            if ui_refs['sync_result_label']:
                ui_refs['sync_result_label'].set_text(result_msg)

            if stats['errors'] > 0:
                ui.notify(result_msg, type='warning')
            else:
                ui.notify(result_msg, type='positive')

            # Refresh data to show updated sync history
            refresh_all_data()

        except Exception as e:
            error_msg = f'Sync failed: {str(e)}'
            ui.notify(error_msg, type='negative')
            if ui_refs['sync_result_label']:
                ui_refs['sync_result_label'].set_text(error_msg)

        finally:
            if ui_refs['sync_button']:
                ui_refs['sync_button'].props('enable')

    # Build UI
    with page_layout("Washbot DB Monitor"):
        with ui.column().classes('w-full gap-4'):
            # Connection Health Section
            with glass_card():
                section_title('Connection Health', 'cable')

                with ui.row().classes('w-full gap-8'):
                    # Washdb connection
                    with ui.column().classes('flex-1'):
                        with ui.row().classes('items-center gap-2'):
                            ui_refs['washdb_icon'] = ui.icon('help', size='sm')
                            ui_refs['washdb_label'] = ui.label('Washbot Database').classes('text-lg font-semibold')
                        with ui.column().classes('gap-1 mt-2'):
                            with ui.row().classes('gap-2'):
                                ui.label('Latency:').classes('text-gray-400')
                                ui_refs['washdb_latency'] = ui.label('—').classes('text-white font-mono')
                            ui_refs['washdb_error'] = ui.label('').classes('text-xs text-red-400')

                    # Scraper DB connection
                    with ui.column().classes('flex-1'):
                        with ui.row().classes('items-center gap-2'):
                            ui_refs['scraper_icon'] = ui.icon('help', size='sm')
                            ui_refs['scraper_label'] = ui.label('Scraper Database').classes('text-lg font-semibold')
                        with ui.column().classes('gap-1 mt-2'):
                            with ui.row().classes('gap-2'):
                                ui.label('Latency:').classes('text-gray-400')
                                ui_refs['scraper_latency'] = ui.label('—').classes('text-white font-mono')

                with ui.row().classes('w-full mt-4'):
                    ui.button('Refresh Connection Status', icon='refresh', on_click=lambda: (check_connection_health(), update_connection_health_display())).classes('bg-indigo-600')

            # Washbot DB Statistics Section
            with glass_card():
                section_title('Washbot DB Statistics', 'storage')

                with ui.grid(columns=4).classes('w-full gap-4'):
                    # Total Companies
                    with ui.column().classes('gap-1'):
                        ui.label('Total Companies').classes('text-gray-400 text-sm')
                        ui_refs['total_companies'] = ui.label('0').classes('text-2xl font-bold text-white')

                    # Unique Domains
                    with ui.column().classes('gap-1'):
                        ui.label('Unique Domains').classes('text-gray-400 text-sm')
                        ui_refs['unique_domains'] = ui.label('0').classes('text-2xl font-bold text-white')

                    # YP Sources
                    with ui.column().classes('gap-1'):
                        ui.label('YP Sources').classes('text-gray-400 text-sm')
                        ui_refs['yp_sources'] = ui.label('0').classes('text-2xl font-bold text-yellow-400')

                    # HA Sources
                    with ui.column().classes('gap-1'):
                        ui.label('HA Sources').classes('text-gray-400 text-sm')
                        ui_refs['ha_sources'] = ui.label('0').classes('text-2xl font-bold text-green-400')

                divider()

                with ui.grid(columns=3).classes('w-full gap-4'):
                    # Google Sources
                    with ui.column().classes('gap-1'):
                        ui.label('Google Sources').classes('text-gray-400 text-sm')
                        ui_refs['google_sources'] = ui.label('0').classes('text-2xl font-bold text-blue-400')

                    # Avg Confidence
                    with ui.column().classes('gap-1'):
                        ui.label('Avg Confidence Score').classes('text-gray-400 text-sm')
                        ui_refs['avg_confidence'] = ui.label('0%').classes('text-2xl font-bold text-white')

                    # Avg Completeness
                    with ui.column().classes('gap-1'):
                        ui.label('Avg Data Completeness').classes('text-gray-400 text-sm')
                        ui_refs['avg_completeness'] = ui.label('0%').classes('text-2xl font-bold text-white')

            # Sync History Section
            with glass_card():
                section_title('URL Sync History', 'sync')

                with ui.grid(columns=4).classes('w-full gap-4'):
                    # Total Syncs
                    with ui.column().classes('gap-1'):
                        ui.label('Total Syncs').classes('text-gray-400 text-sm')
                        ui_refs['total_syncs'] = ui.label('0').classes('text-2xl font-bold text-white')

                    # Successful Syncs
                    with ui.column().classes('gap-1'):
                        ui.label('Successful').classes('text-gray-400 text-sm')
                        ui_refs['successful_syncs'] = ui.label('0').classes('text-2xl font-bold text-green-400')

                    # Failed Syncs
                    with ui.column().classes('gap-1'):
                        ui.label('Failed').classes('text-gray-400 text-sm')
                        ui_refs['failed_syncs'] = ui.label('0').classes('text-2xl font-bold text-red-400')

                    # Success Rate
                    with ui.column().classes('gap-1'):
                        ui.label('Success Rate').classes('text-gray-400 text-sm')
                        ui_refs['success_rate'] = ui.label('N/A').classes('text-2xl font-bold text-white')

                divider()

                with ui.grid(columns=2).classes('w-full gap-4'):
                    # Unique Companies Synced
                    with ui.column().classes('gap-1'):
                        ui.label('Unique Companies Synced').classes('text-gray-400 text-sm')
                        ui_refs['unique_companies_synced'] = ui.label('0').classes('text-2xl font-bold text-white')

                    # Last Sync Time
                    with ui.column().classes('gap-1'):
                        ui.label('Last Sync Time').classes('text-gray-400 text-sm')
                        ui_refs['last_sync_time'] = ui.label('Never').classes('text-xl font-mono text-white')

            # Global Actions
            with ui.row().classes('w-full gap-4'):
                ui.button('Refresh All Data', icon='refresh', on_click=refresh_all_data).classes('bg-gradient-to-r from-purple-600 to-indigo-600 text-white px-6 py-3')

        # Initial data load
        refresh_all_data()

        # Auto-refresh timer (every 30 seconds)
        ui.timer(30, refresh_all_data)

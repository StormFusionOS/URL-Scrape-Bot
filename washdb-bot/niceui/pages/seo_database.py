"""
SEO Database Status Page

Shows washdb connection status, latency, and database statistics.
"""

import time
from datetime import datetime
from typing import Dict, Any
from nicegui import ui

from ..theme import COLORS
from ..backend_facade import backend

# Try to import database utilities
try:
    from db.save_discoveries import create_session
    from db.models import Company
    from sqlalchemy import text, func, select
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def measure_db_latency() -> Dict[str, Any]:
    """Measure database connection latency and status."""
    if not DB_AVAILABLE:
        return {
            'connected': False,
            'latency_ms': None,
            'error': 'Database modules not available'
        }

    try:
        session = create_session()
        start = time.perf_counter()
        # Simple query to measure latency
        session.execute(text("SELECT 1"))
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        session.close()

        return {
            'connected': True,
            'latency_ms': round(latency_ms, 2),
            'error': None
        }
    except Exception as e:
        return {
            'connected': False,
            'latency_ms': None,
            'error': str(e)
        }


def get_db_stats() -> Dict[str, Any]:
    """Get database statistics."""
    if not DB_AVAILABLE:
        return {}

    try:
        session = create_session()

        # Total companies
        total = session.execute(
            select(func.count(Company.id))
        ).scalar() or 0

        # Active companies
        active = session.execute(
            select(func.count(Company.id)).where(Company.active == True)
        ).scalar() or 0

        # With websites
        with_website = session.execute(
            select(func.count(Company.id)).where(
                Company.website.isnot(None),
                Company.website != ""
            )
        ).scalar() or 0

        # By source
        by_source = {}
        for source in ['YP', 'Google', 'Bing', 'Manual']:
            count = session.execute(
                select(func.count(Company.id)).where(Company.source == source)
            ).scalar() or 0
            by_source[source] = count

        # Recent activity
        from datetime import timedelta
        recent_24h = session.execute(
            select(func.count(Company.id)).where(
                Company.created_at >= datetime.now() - timedelta(hours=24)
            )
        ).scalar() or 0

        session.close()

        return {
            'total_companies': total,
            'active_companies': active,
            'with_website': with_website,
            'by_source': by_source,
            'new_last_24h': recent_24h,
        }
    except Exception as e:
        return {'error': str(e)}


def seo_database_page():
    """SEO Database status page."""

    # State for refresh
    status_container = None
    stats_container = None
    last_check_label = None

    def refresh_status():
        """Refresh connection status and stats."""
        nonlocal status_container, stats_container, last_check_label

        # Get fresh data
        conn_status = measure_db_latency()
        db_stats = get_db_stats()

        # Update status container
        if status_container:
            status_container.clear()
            with status_container:
                # Connection status card
                with ui.card().classes('p-4 bg-gray-800 rounded-lg'):
                    ui.label('Connection Status').classes('text-lg font-bold text-white mb-3')

                    with ui.row().classes('gap-4 items-center'):
                        if conn_status['connected']:
                            ui.icon('check_circle', color='green').classes('text-3xl')
                            ui.label('Connected').classes('text-xl text-green-400 font-bold')
                        else:
                            ui.icon('error', color='red').classes('text-3xl')
                            ui.label('Disconnected').classes('text-xl text-red-400 font-bold')

                    if conn_status['connected']:
                        with ui.row().classes('mt-3 gap-6'):
                            with ui.column():
                                ui.label('Latency').classes('text-xs text-gray-400')
                                latency = conn_status['latency_ms']
                                color = 'text-green-400' if latency < 50 else 'text-yellow-400' if latency < 200 else 'text-red-400'
                                ui.label(f"{latency} ms").classes(f'text-2xl font-bold {color}')

                            with ui.column():
                                ui.label('Status').classes('text-xs text-gray-400')
                                if latency < 50:
                                    ui.label('Excellent').classes('text-2xl font-bold text-green-400')
                                elif latency < 200:
                                    ui.label('Good').classes('text-2xl font-bold text-yellow-400')
                                else:
                                    ui.label('Slow').classes('text-2xl font-bold text-red-400')
                    else:
                        ui.label(f"Error: {conn_status['error']}").classes('text-red-400 mt-2')

        # Update stats container
        if stats_container:
            stats_container.clear()
            with stats_container:
                if 'error' in db_stats:
                    ui.label(f"Error loading stats: {db_stats['error']}").classes('text-red-400')
                else:
                    # Stats grid
                    with ui.row().classes('gap-4 flex-wrap'):
                        # Total companies
                        with ui.card().classes('p-4 bg-gray-700 rounded-lg min-w-40'):
                            ui.label('Total Records').classes('text-xs text-gray-400')
                            ui.label(f"{db_stats.get('total_companies', 0):,}").classes('text-2xl font-bold text-white')

                        # Active
                        with ui.card().classes('p-4 bg-gray-700 rounded-lg min-w-40'):
                            ui.label('Active').classes('text-xs text-gray-400')
                            ui.label(f"{db_stats.get('active_companies', 0):,}").classes('text-2xl font-bold text-green-400')

                        # With Website
                        with ui.card().classes('p-4 bg-gray-700 rounded-lg min-w-40'):
                            ui.label('With Website').classes('text-xs text-gray-400')
                            ui.label(f"{db_stats.get('with_website', 0):,}").classes('text-2xl font-bold text-blue-400')

                        # New 24h
                        with ui.card().classes('p-4 bg-gray-700 rounded-lg min-w-40'):
                            ui.label('New (24h)').classes('text-xs text-gray-400')
                            ui.label(f"{db_stats.get('new_last_24h', 0):,}").classes('text-2xl font-bold text-purple-400')

                    # By source breakdown
                    ui.label('Records by Source').classes('text-lg font-bold text-white mt-6 mb-2')
                    with ui.row().classes('gap-4 flex-wrap'):
                        for source, count in db_stats.get('by_source', {}).items():
                            with ui.card().classes('p-3 bg-gray-700 rounded-lg min-w-32'):
                                ui.label(source).classes('text-xs text-gray-400')
                                ui.label(f"{count:,}").classes('text-xl font-bold text-white')

        # Update last check time
        if last_check_label:
            last_check_label.set_text(f"Last checked: {datetime.now().strftime('%H:%M:%S')}")

        ui.notify('Status refreshed', type='info', position='bottom-right')

    with ui.column().classes('w-full max-w-6xl mx-auto p-4 gap-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('SEO Database Status').classes('text-3xl font-bold text-white')
            with ui.row().classes('gap-2 items-center'):
                last_check_label = ui.label('Last checked: --').classes('text-sm text-gray-400')
                ui.button('Refresh', icon='refresh', on_click=refresh_status).classes(
                    'bg-purple-600 hover:bg-purple-700'
                )

        ui.label('Washdb connection status and statistics').classes('text-gray-400 mb-4')

        # Connection status section
        ui.label('Connection').classes('text-xl font-bold text-white mb-2')
        status_container = ui.element('div').classes('w-full mb-6')

        # Database statistics section
        ui.label('Database Statistics').classes('text-xl font-bold text-white mb-2')
        stats_container = ui.element('div').classes('w-full')

        # Initial load
        refresh_status()

        # Auto-refresh every 30 seconds
        ui.timer(30.0, refresh_status)

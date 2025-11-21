"""
SEO Intelligence Dashboard Page

Main overview for AI SEO Intelligence system with:
- Pending changes awaiting review
- Local Authority Score summaries
- Recent audit results
- Competitor tracking overview
"""

import os
from datetime import datetime
from nicegui import ui
from ..theme import COLORS

# Try to import SEO Intelligence services
try:
    from seo_intelligence.services import (
        get_change_manager,
        get_las_calculator,
        get_task_logger,
    )
    SEO_AVAILABLE = True
except ImportError:
    SEO_AVAILABLE = False


def create_stat_card(title: str, value: str, subtitle: str = "", color: str = None):
    """Create a statistic card."""
    if color is None:
        color = COLORS.get('accent', '#a78bfa')

    with ui.card().classes('p-4 bg-gray-800 rounded-lg'):
        ui.label(title).classes('text-sm text-gray-400')
        ui.label(value).classes(f'text-3xl font-bold').style(f'color: {color}')
        if subtitle:
            ui.label(subtitle).classes('text-xs text-gray-500 mt-1')


def create_change_review_section():
    """Create the pending changes review section."""
    with ui.card().classes('p-6 bg-gray-800 rounded-lg w-full'):
        with ui.row().classes('w-full items-center justify-between mb-4'):
            ui.label('Pending Changes').classes('text-xl font-bold text-white')
            ui.button('Refresh', on_click=lambda: ui.notify('Refreshing...')).classes(
                'bg-purple-600 hover:bg-purple-700'
            )

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        try:
            manager = get_change_manager()
            changes = manager.get_pending_changes(limit=10)

            if not changes:
                ui.label('No pending changes').classes('text-gray-400 py-4')
                return

            # Create table
            columns = [
                {'name': 'id', 'label': 'ID', 'field': 'change_id', 'align': 'left'},
                {'name': 'type', 'label': 'Type', 'field': 'change_type', 'align': 'left'},
                {'name': 'entity', 'label': 'Entity', 'field': 'entity_type', 'align': 'left'},
                {'name': 'priority', 'label': 'Priority', 'field': 'priority', 'align': 'left'},
                {'name': 'reason', 'label': 'Reason', 'field': 'reason', 'align': 'left'},
            ]

            rows = []
            for change in changes:
                rows.append({
                    'change_id': change['change_id'],
                    'change_type': change['change_type'],
                    'entity_type': change['entity_type'],
                    'priority': change['priority'].upper(),
                    'reason': change['reason'][:50] + '...' if len(change.get('reason', '')) > 50 else change.get('reason', ''),
                })

            with ui.element('div').classes('w-full'):
                table = ui.table(
                    columns=columns,
                    rows=rows,
                    row_key='change_id',
                    selection='single',
                ).classes('w-full')

                with ui.row().classes('mt-4 gap-2'):
                    ui.button('Approve Selected', on_click=lambda: ui.notify('Approve not implemented yet')).classes(
                        'bg-green-600 hover:bg-green-700'
                    )
                    ui.button('Reject Selected', on_click=lambda: ui.notify('Reject not implemented yet')).classes(
                        'bg-red-600 hover:bg-red-700'
                    )

        except Exception as e:
            ui.label(f'Error loading changes: {e}').classes('text-red-400')


def create_las_overview_section():
    """Create the Local Authority Score overview section."""
    with ui.card().classes('p-6 bg-gray-800 rounded-lg w-full'):
        ui.label('Local Authority Scores').classes('text-xl font-bold text-white mb-4')

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        # Placeholder - would be populated from database
        with ui.row().classes('gap-4 flex-wrap'):
            with ui.card().classes('p-4 bg-gray-700 rounded-lg flex-1 min-w-48'):
                ui.label('Average LAS').classes('text-sm text-gray-400')
                ui.label('--').classes('text-3xl font-bold text-purple-400')
                ui.label('No data yet').classes('text-xs text-gray-500')

            with ui.card().classes('p-4 bg-gray-700 rounded-lg flex-1 min-w-48'):
                ui.label('Top Performer').classes('text-sm text-gray-400')
                ui.label('--').classes('text-3xl font-bold text-green-400')
                ui.label('No data yet').classes('text-xs text-gray-500')

            with ui.card().classes('p-4 bg-gray-700 rounded-lg flex-1 min-w-48'):
                ui.label('Needs Attention').classes('text-sm text-gray-400')
                ui.label('0').classes('text-3xl font-bold text-red-400')
                ui.label('Businesses with LAS < 60').classes('text-xs text-gray-500')


def create_audit_summary_section():
    """Create the audit summary section."""
    with ui.card().classes('p-6 bg-gray-800 rounded-lg w-full'):
        ui.label('Recent Audits').classes('text-xl font-bold text-white mb-4')

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        # Stats row
        with ui.row().classes('gap-4 mb-4'):
            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('0').classes('text-2xl font-bold text-white')
                ui.label('Total Audits').classes('text-xs text-gray-400')

            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('0').classes('text-2xl font-bold text-red-400')
                ui.label('Critical Issues').classes('text-xs text-gray-400')

            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('--').classes('text-2xl font-bold text-yellow-400')
                ui.label('Avg Score').classes('text-xs text-gray-400')

        ui.label('No audits performed yet. Run an audit to see results.').classes(
            'text-gray-400 text-center py-4'
        )


def create_competitor_tracking_section():
    """Create the competitor tracking overview."""
    with ui.card().classes('p-6 bg-gray-800 rounded-lg w-full'):
        ui.label('Competitor Tracking').classes('text-xl font-bold text-white mb-4')

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        with ui.row().classes('gap-4 mb-4'):
            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('0').classes('text-2xl font-bold text-white')
                ui.label('Competitors').classes('text-xs text-gray-400')

            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('0').classes('text-2xl font-bold text-blue-400')
                ui.label('Pages Tracked').classes('text-xs text-gray-400')

            with ui.card().classes('p-3 bg-gray-700 rounded flex-1 text-center'):
                ui.label('0').classes('text-2xl font-bold text-green-400')
                ui.label('Keywords').classes('text-xs text-gray-400')

        ui.label('Add competitors to start tracking their SEO strategies.').classes(
            'text-gray-400 text-center py-2'
        )

        with ui.row().classes('justify-center mt-2'):
            ui.button('Add Competitor', on_click=lambda: ui.notify('Not implemented yet')).classes(
                'bg-purple-600 hover:bg-purple-700'
            )


def create_task_log_section():
    """Create the task execution log section."""
    with ui.card().classes('p-6 bg-gray-800 rounded-lg w-full'):
        ui.label('Recent Task Executions').classes('text-xl font-bold text-white mb-4')

        if not SEO_AVAILABLE:
            ui.label('SEO Intelligence module not available').classes('text-gray-400')
            return

        # Placeholder log entries
        logs = []

        if not logs:
            ui.label('No recent task executions').classes('text-gray-400 py-4')
        else:
            for log in logs[:5]:
                with ui.row().classes('w-full py-2 border-b border-gray-700'):
                    ui.label(log.get('task_name', '')).classes('text-white flex-1')
                    ui.label(log.get('status', '')).classes('text-gray-400')


def seo_intelligence_page():
    """Main SEO Intelligence dashboard page."""
    with ui.column().classes('w-full max-w-7xl mx-auto p-6 gap-6'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('SEO Intelligence').classes('text-3xl font-bold text-white')

            if SEO_AVAILABLE:
                ui.badge('Active', color='green').classes('text-sm')
            else:
                ui.badge('Not Configured', color='red').classes('text-sm')

        ui.label('AI-powered SEO analysis and recommendations').classes('text-gray-400 mb-4')

        # Top stats row
        with ui.row().classes('w-full gap-4 flex-wrap'):
            with ui.card().classes('p-4 bg-gray-800 rounded-lg flex-1 min-w-48'):
                ui.label('Pending Reviews').classes('text-sm text-gray-400')
                if SEO_AVAILABLE:
                    try:
                        manager = get_change_manager()
                        stats = manager.get_stats()
                        pending = stats.get('total_pending', 0)
                        ui.label(str(pending)).classes('text-3xl font-bold text-yellow-400')
                    except Exception:
                        ui.label('--').classes('text-3xl font-bold text-gray-400')
                else:
                    ui.label('--').classes('text-3xl font-bold text-gray-400')

            with ui.card().classes('p-4 bg-gray-800 rounded-lg flex-1 min-w-48'):
                ui.label('Today\'s Changes').classes('text-sm text-gray-400')
                if SEO_AVAILABLE:
                    try:
                        stats = manager.get_stats()
                        today = stats.get('changes_last_24h', 0)
                        ui.label(str(today)).classes('text-3xl font-bold text-blue-400')
                    except Exception:
                        ui.label('--').classes('text-3xl font-bold text-gray-400')
                else:
                    ui.label('--').classes('text-3xl font-bold text-gray-400')

            with ui.card().classes('p-4 bg-gray-800 rounded-lg flex-1 min-w-48'):
                ui.label('Applied Changes').classes('text-sm text-gray-400')
                if SEO_AVAILABLE:
                    try:
                        applied = stats.get('total_applied', 0)
                        ui.label(str(applied)).classes('text-3xl font-bold text-green-400')
                    except Exception:
                        ui.label('--').classes('text-3xl font-bold text-gray-400')
                else:
                    ui.label('--').classes('text-3xl font-bold text-gray-400')

            with ui.card().classes('p-4 bg-gray-800 rounded-lg flex-1 min-w-48'):
                ui.label('System Status').classes('text-sm text-gray-400')
                if SEO_AVAILABLE:
                    ui.label('Online').classes('text-3xl font-bold text-green-400')
                else:
                    ui.label('Offline').classes('text-3xl font-bold text-red-400')

        # Main content grid
        with ui.row().classes('w-full gap-6 flex-wrap'):
            # Left column - 60%
            with ui.column().classes('flex-1 min-w-96 gap-6'):
                create_change_review_section()
                create_audit_summary_section()

            # Right column - 40%
            with ui.column().classes('w-96 gap-6'):
                create_las_overview_section()
                create_competitor_tracking_section()

        # Task log at bottom
        create_task_log_section()

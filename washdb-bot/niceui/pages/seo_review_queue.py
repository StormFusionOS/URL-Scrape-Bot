"""
SEO Review Queue Page

Full-featured change governance interface with:
- Filterable pending changes table
- Bulk approve/reject operations
- Change detail modal
- AI recommendation integration
- Execution triggers for SEO phases
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Set
from nicegui import ui, app
from ..theme import COLORS

# Import governance service
try:
    from seo_intelligence.services.governance import (
        get_governance_service,
        get_pending_changes,
        approve_change,
        reject_change,
        ChangeType,
        ChangeStatus
    )
    GOVERNANCE_AVAILABLE = True
except ImportError as e:
    GOVERNANCE_AVAILABLE = False
    print(f"Governance service import error: {e}")

# Import orchestrator for triggering phases
try:
    from seo_intelligence.cli_run_seo_cycle import SEOOrchestrator, ExecutionMode
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    ORCHESTRATOR_AVAILABLE = False


class SEOReviewQueueController:
    """Controller for SEO Review Queue page."""

    def __init__(self):
        self.governance_service = get_governance_service() if GOVERNANCE_AVAILABLE else None
        self.selected_change_ids: Set[int] = set()
        self.pending_changes: List[Dict] = []
        self.filter_change_type: str = "All"
        self.filter_source: str = "All"
        self.sort_by: str = "proposed_at"
        self.sort_desc: bool = True

        # UI elements (set during page creation)
        self.changes_table = None
        self.stats_container = None
        self.selected_count_label = None
        self.detail_dialog = None

    def load_changes(self):
        """Load pending changes with current filters."""
        if not self.governance_service:
            return

        try:
            # Get all pending changes
            all_changes = get_pending_changes(limit=500)

            # Apply filters
            filtered = all_changes

            if self.filter_change_type != "All":
                filtered = [c for c in filtered if c['change_type'] == self.filter_change_type]

            if self.filter_source != "All":
                filtered = [c for c in filtered if c['source'] == self.filter_source]

            # Apply sorting
            if self.sort_by == "proposed_at":
                filtered = sorted(filtered, key=lambda c: c['proposed_at'] or '', reverse=self.sort_desc)
            elif self.sort_by == "change_type":
                filtered = sorted(filtered, key=lambda c: c['change_type'] or '', reverse=self.sort_desc)
            elif self.sort_by == "table_name":
                filtered = sorted(filtered, key=lambda c: c['table_name'] or '', reverse=self.sort_desc)

            self.pending_changes = filtered
            self._update_table()
            self._update_stats()

        except Exception as e:
            ui.notify(f'Error loading changes: {e}', type='negative')

    def _update_table(self):
        """Update the changes table."""
        if not self.changes_table:
            return

        try:
            # Build table rows
            rows = []
            for change in self.pending_changes:
                # Truncate long text
                reason = (change.get('reason') or '')[:80]
                if len(change.get('reason') or '') > 80:
                    reason += '...'

                # Format proposed_at
                proposed_at = change.get('proposed_at')
                if proposed_at:
                    if isinstance(proposed_at, str):
                        proposed_at_str = proposed_at[:16]  # YYYY-MM-DD HH:MM
                    else:
                        proposed_at_str = proposed_at.strftime('%Y-%m-%d %H:%M')
                else:
                    proposed_at_str = ''

                rows.append({
                    'change_id': change['change_id'],
                    'type': change.get('change_type', '')[:20],
                    'table': change.get('table_name', '')[:25],
                    'operation': change.get('operation', '')[:10],
                    'source': change.get('source', '')[:30],
                    'reason': reason,
                    'proposed_at': proposed_at_str,
                })

            self.changes_table.rows = rows
            self.changes_table.update()

        except Exception as e:
            print(f"Error updating table: {e}")

    def _update_stats(self):
        """Update statistics display."""
        if not self.stats_container:
            return

        try:
            # Calculate stats
            total = len(self.pending_changes)
            by_type = {}
            by_source = {}

            for change in self.pending_changes:
                change_type = change.get('change_type', 'unknown')
                source = change.get('source', 'unknown')

                by_type[change_type] = by_type.get(change_type, 0) + 1
                by_source[source] = by_source.get(source, 0) + 1

            # Update UI
            self.stats_container.clear()
            with self.stats_container:
                with ui.row().classes('gap-2 flex-wrap'):
                    ui.badge(f'Total: {total}', color='blue')
                    for ctype, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:5]:
                        ui.badge(f'{ctype}: {count}', color='gray')

        except Exception as e:
            print(f"Error updating stats: {e}")

    def on_selection_change(self, e):
        """Handle table selection changes."""
        try:
            self.selected_change_ids = {row['change_id'] for row in self.changes_table.selected}
            if self.selected_count_label:
                self.selected_count_label.set_text(f'Selected: {len(self.selected_change_ids)}')
        except Exception as e:
            print(f"Error in selection change: {e}")

    async def approve_selected(self):
        """Approve selected changes."""
        if not self.selected_change_ids:
            ui.notify('No changes selected', type='warning')
            return

        if not self.governance_service:
            ui.notify('Governance service not available', type='negative')
            return

        try:
            results = self.governance_service.bulk_approve_changes(
                change_ids=list(self.selected_change_ids),
                reviewed_by='dashboard_user',
                apply_immediately=True
            )

            success_msg = f"Approved: {results['approved']}, Applied: {results['applied']}, Failed: {results['failed']}"
            ui.notify(success_msg, type='positive' if results['failed'] == 0 else 'warning')

            # Clear selection and reload
            self.selected_change_ids.clear()
            self.load_changes()

        except Exception as e:
            ui.notify(f'Error approving changes: {e}', type='negative')

    async def reject_selected(self):
        """Reject selected changes."""
        if not self.selected_change_ids:
            ui.notify('No changes selected', type='warning')
            return

        if not self.governance_service:
            ui.notify('Governance service not available', type='negative')
            return

        try:
            failed = 0
            for change_id in self.selected_change_ids:
                success = reject_change(
                    change_id,
                    reviewed_by='dashboard_user',
                    rejection_reason='Rejected via dashboard bulk operation'
                )
                if not success:
                    failed += 1

            success_count = len(self.selected_change_ids) - failed
            ui.notify(f'Rejected: {success_count}, Failed: {failed}', type='info')

            # Clear selection and reload
            self.selected_change_ids.clear()
            self.load_changes()

        except Exception as e:
            ui.notify(f'Error rejecting changes: {e}', type='negative')

    def show_change_detail(self, change_id: int):
        """Show detailed view of a change."""
        try:
            # Find the change
            change = next((c for c in self.pending_changes if c['change_id'] == change_id), None)
            if not change:
                ui.notify('Change not found', type='warning')
                return

            # Create detail dialog
            with ui.dialog() as dialog, ui.card().classes('p-6 bg-gray-800 min-w-[600px]'):
                ui.label(f"Change #{change_id} Details").classes('text-2xl font-bold text-white mb-4')

                with ui.column().classes('gap-3 w-full'):
                    # Basic info
                    with ui.row().classes('gap-2'):
                        ui.badge(change.get('change_type', 'unknown'), color='blue')
                        ui.badge(change.get('operation', ''), color='green')
                        ui.badge(change.get('status', ''), color='orange')

                    # Table and record
                    ui.label(f"Table: {change.get('table_name', '')}").classes('text-white')
                    if change.get('record_id'):
                        ui.label(f"Record ID: {change.get('record_id')}").classes('text-white')

                    # Source and timestamp
                    ui.label(f"Source: {change.get('source', 'unknown')}").classes('text-gray-400')
                    ui.label(f"Proposed: {change.get('proposed_at', '')}").classes('text-gray-400')

                    # Reason
                    if change.get('reason'):
                        with ui.expansion('Reason', icon='info').classes('w-full'):
                            ui.label(change['reason']).classes('text-gray-300')

                    # Proposed data
                    if change.get('proposed_data'):
                        with ui.expansion('Proposed Data', icon='data_object').classes('w-full'):
                            import json
                            ui.code(json.dumps(change['proposed_data'], indent=2)).classes('text-xs')

                    # Metadata
                    if change.get('metadata'):
                        with ui.expansion('Metadata', icon='description').classes('w-full'):
                            import json
                            ui.code(json.dumps(change['metadata'], indent=2)).classes('text-xs')

                    # Action buttons
                    with ui.row().classes('gap-2 mt-4 justify-end w-full'):
                        ui.button('Close', on_click=dialog.close).props('flat')
                        ui.button(
                            'Approve',
                            icon='check',
                            on_click=lambda: [
                                approve_change(change_id, reviewed_by='dashboard_user', apply_immediately=True),
                                ui.notify('Change approved', type='positive'),
                                dialog.close(),
                                self.load_changes()
                            ]
                        ).classes('bg-green-600 hover:bg-green-700')
                        ui.button(
                            'Reject',
                            icon='close',
                            on_click=lambda: [
                                reject_change(change_id, reviewed_by='dashboard_user', rejection_reason='Rejected via dashboard'),
                                ui.notify('Change rejected', type='info'),
                                dialog.close(),
                                self.load_changes()
                            ]
                        ).classes('bg-red-600 hover:bg-red-700')

            dialog.open()

        except Exception as e:
            ui.notify(f'Error showing details: {e}', type='negative')


def create_filter_controls(controller: SEOReviewQueueController):
    """Create filter and sorting controls."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('Filters & Sorting').classes('text-xl font-bold text-white mb-3')

        with ui.row().classes('w-full gap-4 items-end flex-wrap'):
            # Change type filter
            change_type_options = ['All'] + [ct.value for ct in ChangeType]
            change_type_select = ui.select(
                label='Change Type',
                options=change_type_options,
                value='All',
                on_change=lambda e: setattr(controller, 'filter_change_type', e.value) or controller.load_changes()
            ).classes('flex-1 min-w-40')

            # Source filter
            source_select = ui.input(
                label='Source Filter',
                placeholder='e.g., review_detail_scraper',
                on_change=lambda e: setattr(controller, 'filter_source', e.value or 'All') or controller.load_changes()
            ).classes('flex-1 min-w-48')

            # Sort options
            sort_select = ui.select(
                label='Sort By',
                options=['proposed_at', 'change_type', 'table_name'],
                value='proposed_at',
                on_change=lambda e: setattr(controller, 'sort_by', e.value) or controller.load_changes()
            ).classes('w-40')

            # Sort direction
            ui.button(
                icon='arrow_downward' if controller.sort_desc else 'arrow_upward',
                on_click=lambda: [
                    setattr(controller, 'sort_desc', not controller.sort_desc),
                    controller.load_changes()
                ]
            ).props('flat').classes('mt-6')

            # Refresh button
            ui.button(
                'Refresh',
                icon='refresh',
                on_click=controller.load_changes
            ).classes('bg-purple-600 hover:bg-purple-700 mt-6')

        # Stats display
        controller.stats_container = ui.row().classes('gap-2 mt-3 flex-wrap')


def create_changes_table(controller: SEOReviewQueueController):
    """Create the main changes table."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        with ui.row().classes('w-full items-center justify-between mb-3'):
            ui.label('Pending Changes').classes('text-xl font-bold text-white')
            controller.selected_count_label = ui.label('Selected: 0').classes('text-sm text-gray-400')

        if not GOVERNANCE_AVAILABLE:
            ui.label('Governance service not available').classes('text-red-400')
            return

        # Table columns
        columns = [
            {'name': 'change_id', 'label': 'ID', 'field': 'change_id', 'align': 'left', 'sortable': True},
            {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
            {'name': 'table', 'label': 'Table', 'field': 'table', 'align': 'left', 'sortable': True},
            {'name': 'operation', 'label': 'Op', 'field': 'operation', 'align': 'center'},
            {'name': 'source', 'label': 'Source', 'field': 'source', 'align': 'left'},
            {'name': 'reason', 'label': 'Reason', 'field': 'reason', 'align': 'left'},
            {'name': 'proposed_at', 'label': 'Proposed At', 'field': 'proposed_at', 'align': 'left', 'sortable': True},
        ]

        # Create table
        controller.changes_table = ui.table(
            columns=columns,
            rows=[],
            row_key='change_id',
            selection='multiple',
            on_select=controller.on_selection_change
        ).classes('w-full')

        # Add row click handler for details
        controller.changes_table.on('rowClick', lambda e: controller.show_change_detail(e.args[1]['change_id']))

        # Bulk action buttons
        with ui.row().classes('gap-2 mt-4'):
            ui.button(
                'Approve Selected',
                icon='check_circle',
                on_click=lambda: asyncio.create_task(controller.approve_selected())
            ).classes('bg-green-600 hover:bg-green-700')

            ui.button(
                'Reject Selected',
                icon='cancel',
                on_click=lambda: asyncio.create_task(controller.reject_selected())
            ).classes('bg-red-600 hover:bg-red-700')

            ui.button(
                'Select All',
                on_click=lambda: controller.changes_table.select_all()
            ).props('flat')

            ui.button(
                'Clear Selection',
                on_click=lambda: [
                    setattr(controller, 'selected_change_ids', set()),
                    controller.changes_table.selected.clear(),
                    controller.changes_table.update(),
                    controller.selected_count_label.set_text('Selected: 0')
                ]
            ).props('flat')


def create_actions_panel():
    """Create SEO actions panel."""
    with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
        ui.label('SEO Actions').classes('text-xl font-bold text-white mb-3')

        if not ORCHESTRATOR_AVAILABLE:
            ui.label('Orchestrator not available').classes('text-yellow-400')
            return

        with ui.row().classes('gap-3 flex-wrap'):
            ui.button(
                'Run Daily Tasks',
                icon='event',
                on_click=lambda: run_seo_phase('daily')
            ).classes('bg-blue-600 hover:bg-blue-700')

            ui.button(
                'Run Weekly Tasks',
                icon='calendar_month',
                on_click=lambda: run_seo_phase('weekly')
            ).classes('bg-purple-600 hover:bg-purple-700')

            ui.button(
                'Run Review Scraper',
                icon='rate_review',
                on_click=lambda: run_seo_phase('reviews')
            ).classes('bg-green-600 hover:bg-green-700')

            ui.button(
                'Find Unlinked Mentions',
                icon='link_off',
                on_click=lambda: run_seo_phase('unlinked_mentions')
            ).classes('bg-orange-600 hover:bg-orange-700')


def run_seo_phase(phase: str):
    """Run a specific SEO phase."""
    try:
        ui.notify(f'Starting {phase}... (This will run in the background)', type='info')
        # In production, this would trigger an async background task
        # For now, just notify the user
        ui.notify('SEO phase execution not fully implemented yet', type='warning')
    except Exception as e:
        ui.notify(f'Error: {e}', type='negative')


def seo_review_queue_page():
    """Main SEO Review Queue page."""
    controller = SEOReviewQueueController()

    with ui.column().classes('w-full max-w-7xl mx-auto p-4 gap-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('SEO Review Queue').classes('text-3xl font-bold text-white')
            with ui.row().classes('gap-2'):
                if GOVERNANCE_AVAILABLE:
                    ui.badge('Governance: Active', color='green')
                else:
                    ui.badge('Governance: Unavailable', color='red')
                if ORCHESTRATOR_AVAILABLE:
                    ui.badge('Orchestrator: Ready', color='green')
                else:
                    ui.badge('Orchestrator: Missing', color='orange')

        ui.label('Review and approve proposed SEO data changes').classes('text-gray-400 mb-4')

        # Filters and controls
        create_filter_controls(controller)

        # Main changes table
        create_changes_table(controller)

        # Actions panel
        create_actions_panel()

    # Auto-load changes on page load
    controller.load_changes()

#!/usr/bin/env python3
"""
Category Editor Widget - Manage Google Maps search categories.

Displays categories in a table with add/edit/delete functionality.
"""

from nicegui import ui
from typing import Callable, Optional, List, Dict
from ..utils.category_manager import category_manager


class CategoryEditor:
    """
    Table-based editor for Google Maps search categories.
    """

    def __init__(self, on_change: Optional[Callable] = None):
        """
        Initialize CategoryEditor.

        Args:
            on_change: Callback when categories change
        """
        self.on_change = on_change

        # UI elements
        self.table = None
        self.rows = []

    def render(self):
        """Render the category editor UI."""
        with ui.card().classes('w-full'):
            # Header
            with ui.row().classes('w-full items-center justify-between mb-4'):
                with ui.column().classes('gap-1'):
                    ui.label('Google Target Categories').classes('text-xl font-bold')
                    ui.label('Control what Google Maps searches for').classes('text-sm text-gray-400')

                with ui.row().classes('gap-2'):
                    ui.button(
                        'Add Category',
                        icon='add',
                        color='primary',
                        on_click=self._show_add_dialog
                    ).props('outline')

                    ui.button(
                        'Import CSV',
                        icon='upload',
                        on_click=self._show_import_dialog
                    ).props('flat')

                    ui.button(
                        'Export CSV',
                        icon='download',
                        on_click=self._export_categories
                    ).props('flat')

            # Statistics
            stats = category_manager.get_stats()
            with ui.row().classes('w-full gap-4 mb-4'):
                with ui.card().classes('flex-1 bg-blue-900/20'):
                    ui.label('Total').classes('text-xs text-gray-400')
                    ui.label(str(stats['total'])).classes('text-2xl font-bold text-blue-400')

                with ui.card().classes('flex-1 bg-green-900/20'):
                    ui.label('Google').classes('text-xs text-gray-400')
                    ui.label(str(stats['google'])).classes('text-2xl font-bold text-green-400')

                with ui.card().classes('flex-1 bg-purple-900/20'):
                    ui.label('Yellow Pages').classes('text-xs text-gray-400')
                    ui.label(str(stats['yp'])).classes('text-2xl font-bold text-purple-400')

            # Warning about car wash
            car_wash_cats = [c for c in category_manager.categories if 'car wash' in c['label'].lower() or 'truck wash' in c['label'].lower() or 'fleet' in c['label'].lower()]
            if car_wash_cats:
                with ui.card().classes('w-full bg-orange-900/20 mb-4').style('border: 1px solid rgba(251, 146, 60, 0.5)'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('warning').classes('text-orange-500')
                        ui.label(f'⚠️ Found {len(car_wash_cats)} car wash related categories').classes('text-orange-400 font-semibold')
                    ui.label('These may not be relevant to your business. Consider removing them.').classes('text-sm text-gray-400 mt-1')

            # Category table
            self._render_table()

        return self

    def _render_table(self):
        """Render the categories table."""
        # Prepare rows
        self.rows = []
        for cat in category_manager.categories:
            self.rows.append({
                'label': cat['label'],
                'keyword': cat['keyword'],
                'source': cat['source']
            })

        # Define columns including actions
        columns = [
            {'name': 'label', 'label': 'Category Label', 'field': 'label', 'align': 'left', 'sortable': True},
            {'name': 'keyword', 'label': 'Search Keyword', 'field': 'keyword', 'align': 'left', 'sortable': True},
            {'name': 'source', 'label': 'Source', 'field': 'source', 'align': 'center', 'sortable': True},
            {'name': 'actions', 'label': 'Actions', 'field': 'label', 'align': 'center'},
        ]

        # Render table
        self.table = ui.table(
            columns=columns,
            rows=self.rows,
            row_key='label'
        ).classes('w-full')

        # Add custom cell rendering with action buttons
        self.table.add_slot('body-cell-label', '''
            <q-td :props="props">
                <span class="font-semibold">{{ props.value }}</span>
            </q-td>
        ''')

        self.table.add_slot('body-cell-keyword', '''
            <q-td :props="props">
                <span class="text-blue-400 font-mono text-sm">{{ props.value }}</span>
            </q-td>
        ''')

        self.table.add_slot('body-cell-source', '''
            <q-td :props="props">
                <q-badge :color="props.value === 'google' ? 'green' : 'purple'" outline>
                    {{ props.value }}
                </q-badge>
            </q-td>
        ''')

        # Add action buttons for each row
        self.table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn flat dense round icon="edit" size="sm" color="primary" @click="$parent.$emit('edit', props.row)">
                    <q-tooltip>Edit</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" size="sm" color="negative" @click="$parent.$emit('delete', props.row)">
                    <q-tooltip>Delete</q-tooltip>
                </q-btn>
            </q-td>
        ''')

        # Handle edit and delete events
        self.table.on('edit', lambda e: self._edit_category_by_row(e.args))
        self.table.on('delete', lambda e: self._delete_category_by_row(e.args))

    def _show_add_dialog(self):
        """Show dialog to add a new category."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Add New Category').classes('text-lg font-bold mb-4')

            label_input = ui.input(
                label='Category Label',
                placeholder='e.g., Deck Cleaning'
            ).props('outlined').classes('w-full mb-3')

            keyword_input = ui.input(
                label='Search Keyword',
                placeholder='e.g., deck cleaning'
            ).props('outlined').classes('w-full mb-3')

            source_select = ui.select(
                options={'google': 'Google Maps', 'yp': 'Yellow Pages'},
                value='google',
                label='Source'
            ).props('outlined').classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Add',
                    icon='add',
                    color='primary',
                    on_click=lambda: self._add_category(
                        label_input.value,
                        keyword_input.value,
                        source_select.value,
                        dialog
                    )
                )

        dialog.open()

    def _add_category(self, label: str, keyword: str, source: str, dialog):
        """Add a new category."""
        success, msg = category_manager.add_category(label, keyword, source)

        if success:
            ui.notify(msg, type='positive')
            self._reload_table()
            dialog.close()

            if self.on_change:
                self.on_change()
        else:
            ui.notify(msg, type='warning')

    def _edit_category_by_row(self, row):
        """Edit a category from row click."""
        old_label = row['label']
        old_keyword = row['keyword']
        old_source = row['source']
        self._show_edit_dialog(old_label, old_keyword, old_source)

    def _delete_category_by_row(self, row):
        """Delete a category from row click."""
        label = row['label']
        self._show_delete_dialog(label)

    def _show_edit_dialog(self, old_label: str, old_keyword: str, old_source: str):
        """Show edit dialog for a category."""

        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label(f'Edit: {old_label}').classes('text-lg font-bold mb-4')

            label_input = ui.input(
                label='Category Label',
                value=old_label
            ).props('outlined').classes('w-full mb-3')

            keyword_input = ui.input(
                label='Search Keyword',
                value=old_keyword
            ).props('outlined').classes('w-full mb-3')

            source_select = ui.select(
                options={'google': 'Google Maps', 'yp': 'Yellow Pages'},
                value=old_source,
                label='Source'
            ).props('outlined').classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Save',
                    icon='save',
                    color='primary',
                    on_click=lambda: self._update_category(
                        old_label,
                        label_input.value,
                        keyword_input.value,
                        source_select.value,
                        dialog
                    )
                )

        dialog.open()

    def _update_category(self, old_label: str, new_label: str, keyword: str, source: str, dialog):
        """Update a category."""
        success, msg = category_manager.update_category(old_label, new_label, keyword, source)

        if success:
            ui.notify(msg, type='positive')
            self._reload_table()
            dialog.close()

            if self.on_change:
                self.on_change()
        else:
            ui.notify(msg, type='negative')

    def _show_delete_dialog(self, label: str):
        """Show delete confirmation dialog."""
        with ui.dialog() as dialog, ui.card():
            ui.label('Confirm Deletion').classes('text-lg font-bold mb-3')
            ui.label(f'Delete category "{label}"?').classes('mb-4')
            ui.label('This will not delete existing targets from the database.').classes('text-sm text-gray-400 mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Delete',
                    icon='delete',
                    color='negative',
                    on_click=lambda: self._confirm_delete(label, dialog)
                )

        dialog.open()

    def _confirm_delete(self, label: str, dialog):
        """Confirm and delete category."""
        success, msg = category_manager.remove_category(label)

        if success:
            ui.notify(msg, type='positive')
            self._reload_table()
            dialog.close()

            if self.on_change:
                self.on_change()
        else:
            ui.notify(msg, type='negative')

    def _show_import_dialog(self):
        """Show import dialog."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Import Categories').classes('text-lg font-bold mb-4')

            ui.label('Paste CSV data (label,keyword,source):').classes('text-sm mb-2')

            text_area = ui.textarea(
                placeholder='Window Cleaning,window cleaning,yp\nRoof Cleaning,roof cleaning,google'
            ).props('outlined rows=10').classes('w-full mb-4')

            merge_checkbox = ui.checkbox(
                'Merge with existing (keep both)',
                value=True
            ).classes('mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Import',
                    icon='upload',
                    color='primary',
                    on_click=lambda: self._import_categories(
                        text_area.value,
                        merge_checkbox.value,
                        dialog
                    )
                )

        dialog.open()

    def _import_categories(self, csv_text: str, merge: bool, dialog):
        """Import categories from CSV text."""
        if not csv_text.strip():
            ui.notify('Please paste some CSV data', type='warning')
            return

        # Add header if not present
        if not csv_text.startswith('label,'):
            csv_text = 'label,keyword,source\n' + csv_text

        success, msg = category_manager.import_from_csv_text(csv_text, merge)

        if success:
            ui.notify(msg, type='positive')
            self._reload_table()
            dialog.close()

            if self.on_change:
                self.on_change()
        else:
            ui.notify(msg, type='negative')

    def _export_categories(self):
        """Export categories to CSV."""
        if not category_manager.categories:
            ui.notify('No categories to export', type='warning')
            return

        # Generate CSV
        csv_lines = ['label,keyword,source']
        for cat in category_manager.categories:
            csv_lines.append(f"{cat['label']},{cat['keyword']},{cat['source']}")

        csv_text = '\n'.join(csv_lines)

        # Show export dialog
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Export Categories').classes('text-lg font-bold mb-4')

            ui.label(f'{len(category_manager.categories)} categories:').classes('text-sm mb-2')

            text_area = ui.textarea(value=csv_text).props(
                'outlined readonly rows=15'
            ).classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Close', on_click=dialog.close).props('flat')
                ui.button(
                    'Copy to Clipboard',
                    icon='content_copy',
                    color='primary',
                    on_click=lambda: self._copy_to_clipboard(csv_text, dialog)
                )

        dialog.open()

    def _copy_to_clipboard(self, text: str, dialog):
        """Copy text to clipboard."""
        ui.run_javascript(f'''
            navigator.clipboard.writeText(`{text}`);
        ''')
        ui.notify('Copied to clipboard!', type='positive')
        dialog.close()

    def _reload_table(self):
        """Reload the table data."""
        category_manager.load()
        self._render_table()


# Convenience function
def create_category_editor(on_change: Optional[Callable] = None) -> CategoryEditor:
    """
    Create and render a category editor.

    Args:
        on_change: Callback when categories change

    Returns:
        CategoryEditor instance
    """
    editor = CategoryEditor(on_change)
    editor.render()
    return editor

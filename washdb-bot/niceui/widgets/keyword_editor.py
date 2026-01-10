#!/usr/bin/env python3
"""
Keyword Editor Widget - Reusable component for editing keyword lists.

Features:
- Add/remove keywords with validation
- Search and filter
- Chip-based display
- Import/export
- Real-time updates
"""

from nicegui import ui
from typing import Callable, Optional, List
from ..utils.keyword_manager import keyword_manager


class KeywordEditor:
    """
    Reusable keyword editor component with chip-based display.
    """

    def __init__(
        self,
        file_id: str,
        title: str,
        description: str,
        color: str = 'blue',
        show_search: bool = True,
        show_import_export: bool = True,
        on_change: Optional[Callable] = None
    ):
        """
        Initialize KeywordEditor.

        Args:
            file_id: Keyword file identifier from keyword_manager
            title: Display title
            description: Help text description
            color: Color theme (blue, red, green, purple)
            show_search: Whether to show search box
            show_import_export: Whether to show import/export buttons
            on_change: Callback function when keywords change
        """
        self.file_id = file_id
        self.title = title
        self.description = description
        self.color = color
        self.show_search = show_search
        self.show_import_export = show_import_export
        self.on_change = on_change

        # State
        self.keywords: List[str] = []
        self.filtered_keywords: List[str] = []
        self.search_query: str = ""

        # UI elements (will be set in render)
        self.keyword_container = None
        self.add_input = None
        self.search_input = None
        self.count_badge = None

        # Color mapping
        self.color_map = {
            'blue': {'chip': 'blue-600', 'hover': 'blue-700', 'text': 'blue-100'},
            'red': {'chip': 'red-600', 'hover': 'red-700', 'text': 'red-100'},
            'green': {'chip': 'green-600', 'hover': 'green-700', 'text': 'green-100'},
            'purple': {'chip': 'purple-600', 'hover': 'purple-700', 'text': 'purple-100'},
            'orange': {'chip': 'orange-600', 'hover': 'orange-700', 'text': 'orange-100'},
        }

    def render(self):
        """Render the keyword editor UI."""
        colors = self.color_map.get(self.color, self.color_map['blue'])

        with ui.card().classes('w-full'):
            # Header
            with ui.row().classes('w-full items-center justify-between mb-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(self.title).classes('text-lg font-bold')
                    self.count_badge = ui.badge(
                        '0',
                        color=self.color,
                        outline=True
                    )

                # Import/Export buttons
                if self.show_import_export:
                    with ui.row().classes('gap-1'):
                        ui.button(
                            icon='upload',
                            on_click=self._show_import_dialog
                        ).props('flat dense').tooltip('Import keywords')
                        ui.button(
                            icon='download',
                            on_click=self._export_keywords
                        ).props('flat dense').tooltip('Export keywords')

            # Description
            ui.label(self.description).classes('text-sm text-gray-400 mb-4')

            # Add keyword section
            with ui.row().classes('w-full gap-2 mb-4'):
                self.add_input = ui.input(
                    placeholder='Add new keyword...',
                    on_change=lambda e: self._on_input_change(e.value)
                ).props('outlined dense').classes('flex-grow')
                self.add_input.on('keydown.enter', lambda: self._add_keyword())

                ui.button(
                    'Add',
                    icon='add',
                    color=self.color,
                    on_click=self._add_keyword
                ).props('outline')

            # Search section
            if self.show_search:
                self.search_input = ui.input(
                    placeholder='Search keywords...',
                    on_change=lambda e: self._search_keywords(e.value)
                ).props('outlined dense').classes('w-full mb-4')
                self.search_input.props('prepend-icon=search clearable')

            # Keywords container (chip display)
            ui.label('Keywords:').classes('text-sm font-semibold mb-2')
            self.keyword_container = ui.column().classes('w-full gap-2')

        # Load and display keywords
        self._load_keywords()
        return self

    def _load_keywords(self):
        """Load keywords from manager."""
        self.keywords = keyword_manager.get_keywords(self.file_id)
        self.filtered_keywords = self.keywords.copy()
        self._update_display()

    def _update_display(self):
        """Update the keywords display."""
        if not self.keyword_container:
            return

        # Update count badge
        if self.count_badge:
            self.count_badge.set_text(str(len(self.keywords)))

        # Clear container
        self.keyword_container.clear()

        # Display message if no keywords
        if not self.filtered_keywords:
            with self.keyword_container:
                if self.search_query:
                    ui.label('No keywords match your search.').classes('text-sm text-gray-500 italic')
                else:
                    ui.label('No keywords added yet.').classes('text-sm text-gray-500 italic')
            return

        # Display keywords as chips in rows
        colors = self.color_map.get(self.color, self.color_map['blue'])

        with self.keyword_container:
            # Group into rows of chips
            with ui.row().classes('w-full flex-wrap gap-2'):
                for keyword in self.filtered_keywords:
                    self._create_keyword_chip(keyword, colors)

    def _create_keyword_chip(self, keyword: str, colors: dict):
        """
        Create a keyword chip with remove button.

        Args:
            keyword: Keyword text
            colors: Color configuration
        """
        with ui.element('div').classes(
            f'inline-flex items-center gap-1 px-3 py-1 '
            f'bg-{colors["chip"]} text-{colors["text"]} rounded-full '
            f'hover:bg-{colors["hover"]} transition-colors'
        ):
            ui.label(keyword).classes('text-sm')
            ui.button(
                icon='close',
                on_click=lambda kw=keyword: self._remove_keyword(kw)
            ).props('flat dense size=xs').classes('text-white')

    def _on_input_change(self, value: str):
        """Handle input field changes for validation."""
        # Could add real-time validation here
        pass

    def _add_keyword(self):
        """Add a new keyword."""
        if not self.add_input:
            return

        keyword = self.add_input.value.strip()

        if not keyword:
            ui.notify('Please enter a keyword', type='warning')
            return

        # Add via manager
        success, message = keyword_manager.add_keyword(self.file_id, keyword)

        if success:
            ui.notify(message, type='positive')
            self.add_input.value = ''
            self._load_keywords()

            # Call on_change callback
            if self.on_change:
                self.on_change(self.keywords)
        else:
            ui.notify(message, type='warning')

    def _remove_keyword(self, keyword: str):
        """
        Remove a keyword.

        Args:
            keyword: Keyword to remove
        """
        # Remove via manager
        success, message = keyword_manager.remove_keyword(self.file_id, keyword)

        if success:
            ui.notify(message, type='positive')
            self._load_keywords()

            # Call on_change callback
            if self.on_change:
                self.on_change(self.keywords)
        else:
            ui.notify(message, type='negative')

    def _search_keywords(self, query: str):
        """
        Filter keywords based on search query.

        Args:
            query: Search query
        """
        self.search_query = query.lower().strip()

        if not self.search_query:
            self.filtered_keywords = self.keywords.copy()
        else:
            self.filtered_keywords = [
                kw for kw in self.keywords
                if self.search_query in kw.lower()
            ]

        self._update_display()

    def _show_import_dialog(self):
        """Show import dialog."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Import Keywords').classes('text-lg font-bold mb-4')

            ui.label('Paste keywords below (one per line):').classes('text-sm mb-2')

            text_area = ui.textarea(
                placeholder='keyword1\nkeyword2\nkeyword3...'
            ).props('outlined rows=10').classes('w-full mb-4')

            merge_checkbox = ui.checkbox(
                'Merge with existing keywords (keep both)',
                value=True
            ).classes('mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button(
                    'Import',
                    icon='upload',
                    color=self.color,
                    on_click=lambda: self._import_from_text(
                        text_area.value,
                        merge_checkbox.value,
                        dialog
                    )
                )

        dialog.open()

    def _import_from_text(self, text: str, merge: bool, dialog):
        """
        Import keywords from text.

        Args:
            text: Text containing keywords
            merge: Whether to merge or replace
            dialog: Dialog to close
        """
        if not text.strip():
            ui.notify('Please enter some keywords', type='warning')
            return

        success, message = keyword_manager.import_from_text(
            self.file_id,
            text,
            merge=merge
        )

        if success:
            ui.notify(message, type='positive')
            self._load_keywords()
            dialog.close()

            # Call on_change callback
            if self.on_change:
                self.on_change(self.keywords)
        else:
            ui.notify(message, type='negative')

    def _export_keywords(self):
        """Export keywords to clipboard and show download option."""
        if not self.keywords:
            ui.notify('No keywords to export', type='warning')
            return

        # Create export text
        export_text = '\n'.join(self.keywords)

        # Show export dialog
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Export Keywords').classes('text-lg font-bold mb-4')

            ui.label(f'{len(self.keywords)} keywords:').classes('text-sm mb-2')

            text_area = ui.textarea(value=export_text).props(
                'outlined readonly rows=10'
            ).classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Close', on_click=dialog.close).props('flat')
                ui.button(
                    'Copy to Clipboard',
                    icon='content_copy',
                    color=self.color,
                    on_click=lambda: self._copy_to_clipboard(export_text, dialog)
                )

        dialog.open()

    def _copy_to_clipboard(self, text: str, dialog):
        """
        Copy text to clipboard.

        Args:
            text: Text to copy
            dialog: Dialog to close
        """
        ui.run_javascript(f'''
            navigator.clipboard.writeText(`{text}`).then(() => {{
                console.log('Copied to clipboard');
            }});
        ''')
        ui.notify('Copied to clipboard!', type='positive')
        dialog.close()

    def reload(self):
        """Reload keywords from file."""
        self._load_keywords()


# Convenience function
def create_keyword_editor(
    file_id: str,
    title: str,
    description: str,
    color: str = 'blue',
    **kwargs
) -> KeywordEditor:
    """
    Create and render a keyword editor.

    Args:
        file_id: Keyword file identifier
        title: Display title
        description: Help text
        color: Color theme
        **kwargs: Additional KeywordEditor arguments

    Returns:
        KeywordEditor instance
    """
    editor = KeywordEditor(file_id, title, description, color, **kwargs)
    editor.render()
    return editor

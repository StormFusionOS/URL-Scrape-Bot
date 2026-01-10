#!/usr/bin/env python3
"""
Keyword Statistics Widget - Analytics for keyword management.

Provides insights about:
- Keyword counts and distribution
- File sizes and last modified dates
- Recent changes
- Longest/shortest keywords
"""

from nicegui import ui
from typing import Dict, List
from collections import Counter
from datetime import datetime
import os


class KeywordStats:
    """
    Statistics and analytics for keyword files.
    """

    def __init__(self, keyword_manager):
        """
        Initialize KeywordStats.

        Args:
            keyword_manager: KeywordManager instance
        """
        self.manager = keyword_manager

    def render(self):
        """Render the statistics dashboard."""
        with ui.card().classes('w-full'):
            ui.label('Keyword Statistics & Analytics').classes('text-xl font-bold mb-4')

            # Overall statistics
            self._render_overall_stats()

            # File statistics
            ui.label('File Details').classes('text-lg font-semibold mt-6 mb-3')
            self._render_file_stats()

            # Keyword insights
            ui.label('Keyword Insights').classes('text-lg font-semibold mt-6 mb-3')
            self._render_keyword_insights()

        return self

    def _render_overall_stats(self):
        """Render overall statistics cards."""
        files_by_source = self.manager.get_all_files_by_source()
        total_keywords = sum(f['count'] for source_files in files_by_source.values() for f in source_files)
        total_files = sum(len(files) for files in files_by_source.values())

        # Calculate average keywords per file
        avg_per_file = total_keywords / total_files if total_files > 0 else 0

        # Find largest and smallest files
        all_files = [f for files in files_by_source.values() for f in files]
        largest_file = max(all_files, key=lambda x: x['count']) if all_files else None
        smallest_file = min(all_files, key=lambda x: x['count']) if all_files else None

        with ui.grid(columns=4).classes('w-full gap-4'):
            # Total keywords
            with ui.card().classes('bg-blue-900/20'):
                ui.label('Total Keywords').classes('text-xs text-gray-400')
                ui.label(str(total_keywords)).classes('text-3xl font-bold text-blue-400')
                ui.label('across all sources').classes('text-xs text-gray-500 mt-1')

            # Total files
            with ui.card().classes('bg-green-900/20'):
                ui.label('Active Files').classes('text-xs text-gray-400')
                ui.label(str(total_files)).classes('text-3xl font-bold text-green-400')
                ui.label('being managed').classes('text-xs text-gray-500 mt-1')

            # Average per file
            with ui.card().classes('bg-purple-900/20'):
                ui.label('Avg per File').classes('text-xs text-gray-400')
                ui.label(f'{avg_per_file:.0f}').classes('text-3xl font-bold text-purple-400')
                ui.label('keywords').classes('text-xs text-gray-500 mt-1')

            # Largest file
            with ui.card().classes('bg-orange-900/20'):
                ui.label('Largest File').classes('text-xs text-gray-400')
                if largest_file:
                    ui.label(str(largest_file['count'])).classes('text-3xl font-bold text-orange-400')
                    ui.label(largest_file['name'][:20] + '...').classes('text-xs text-gray-500 mt-1')
                else:
                    ui.label('N/A').classes('text-3xl font-bold text-orange-400')

    def _render_file_stats(self):
        """Render detailed file statistics table."""
        files_by_source = self.manager.get_all_files_by_source()

        # Create table data
        rows = []
        for source, files in files_by_source.items():
            for file_info in files:
                # Get file size
                file_path = file_info['path']
                size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                size_kb = size_bytes / 1024

                # Last modified
                last_mod = file_info.get('last_modified')
                if last_mod:
                    try:
                        mod_dt = datetime.fromisoformat(last_mod)
                        mod_str = mod_dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        mod_str = 'Unknown'
                else:
                    mod_str = 'Never'

                rows.append({
                    'Source': source.upper(),
                    'File': file_info['name'],
                    'Keywords': file_info['count'],
                    'Size': f'{size_kb:.1f} KB',
                    'Last Modified': mod_str
                })

        # Render table
        columns = [
            {'name': 'Source', 'label': 'Source', 'field': 'Source', 'align': 'left'},
            {'name': 'File', 'label': 'File Name', 'field': 'File', 'align': 'left'},
            {'name': 'Keywords', 'label': 'Keywords', 'field': 'Keywords', 'align': 'right'},
            {'name': 'Size', 'label': 'Size', 'field': 'Size', 'align': 'right'},
            {'name': 'Last Modified', 'label': 'Last Modified', 'field': 'Last Modified', 'align': 'left'},
        ]

        ui.table(
            columns=columns,
            rows=rows,
            row_key='File'
        ).classes('w-full').props('dense flat')

    def _render_keyword_insights(self):
        """Render keyword insights and patterns."""
        with ui.grid(columns=2).classes('w-full gap-4'):
            # Left column: Length distribution
            with ui.card().classes('w-full'):
                ui.label('Keyword Length Distribution').classes('text-sm font-semibold mb-3')
                self._render_length_distribution()

            # Right column: Common patterns
            with ui.card().classes('w-full'):
                ui.label('Common Patterns').classes('text-sm font-semibold mb-3')
                self._render_common_patterns()

    def _render_length_distribution(self):
        """Show distribution of keyword lengths."""
        all_keywords = []
        for file_id in self.manager.files.keys():
            all_keywords.extend(self.manager.get_keywords(file_id))

        if not all_keywords:
            ui.label('No keywords to analyze').classes('text-sm text-gray-500 italic')
            return

        # Calculate stats
        lengths = [len(kw) for kw in all_keywords]
        avg_length = sum(lengths) / len(lengths)
        min_length = min(lengths)
        max_length = max(lengths)

        # Find shortest and longest
        shortest = min(all_keywords, key=len)
        longest = max(all_keywords, key=len)

        with ui.column().classes('w-full gap-2'):
            with ui.row().classes('w-full justify-between'):
                ui.label('Average Length:').classes('text-xs text-gray-400')
                ui.label(f'{avg_length:.1f} chars').classes('text-sm font-mono')

            with ui.row().classes('w-full justify-between'):
                ui.label('Shortest:').classes('text-xs text-gray-400')
                ui.label(f'"{shortest}" ({min_length})').classes('text-sm font-mono')

            with ui.row().classes('w-full justify-between'):
                ui.label('Longest:').classes('text-xs text-gray-400')
                ui.label(f'"{longest[:30]}..." ({max_length})').classes('text-sm font-mono')

            # Length categories
            ui.label('Length Categories:').classes('text-xs text-gray-400 mt-3 mb-1')

            short = sum(1 for l in lengths if l <= 10)
            medium = sum(1 for l in lengths if 10 < l <= 20)
            long = sum(1 for l in lengths if 20 < l <= 30)
            very_long = sum(1 for l in lengths if l > 30)

            total = len(lengths)

            categories = [
                ('Short (≤10)', short, 'blue'),
                ('Medium (11-20)', medium, 'green'),
                ('Long (21-30)', long, 'orange'),
                ('Very Long (>30)', very_long, 'red')
            ]

            for label, count, color in categories:
                pct = (count / total * 100) if total > 0 else 0
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label(label).classes('text-xs w-32')
                    ui.linear_progress(value=count/total if total > 0 else 0).classes('flex-1')
                    ui.label(f'{count} ({pct:.0f}%)').classes('text-xs font-mono w-20 text-right')

    def _render_common_patterns(self):
        """Show common patterns in keywords."""
        all_keywords = []
        for file_id in self.manager.files.keys():
            all_keywords.extend(self.manager.get_keywords(file_id))

        if not all_keywords:
            ui.label('No keywords to analyze').classes('text-sm text-gray-500 italic')
            return

        # Common words in keywords
        words = []
        for kw in all_keywords:
            words.extend(kw.split())

        word_counts = Counter(words).most_common(8)

        ui.label('Most Common Words:').classes('text-xs text-gray-400 mb-2')

        for word, count in word_counts:
            pct = (count / len(all_keywords) * 100)
            with ui.row().classes('w-full items-center gap-2 mb-1'):
                ui.label(word).classes('text-sm font-mono flex-1')
                ui.badge(str(count), color='blue').props('outline')

        # Keywords with special characters
        ui.label('Special Patterns:').classes('text-xs text-gray-400 mt-4 mb-2')

        with_dots = sum(1 for kw in all_keywords if '.' in kw)
        with_dashes = sum(1 for kw in all_keywords if '-' in kw)
        with_spaces = sum(1 for kw in all_keywords if ' ' in kw)

        patterns = [
            ('Contains "."', with_dots, 'URLs/domains'),
            ('Contains "-"', with_dashes, 'Hyphenated'),
            ('Contains spaces', with_spaces, 'Multi-word'),
        ]

        for label, count, desc in patterns:
            with ui.row().classes('w-full justify-between items-center'):
                ui.label(label).classes('text-xs')
                with ui.row().classes('items-center gap-2'):
                    ui.label(desc).classes('text-xs text-gray-500 italic')
                    ui.badge(str(count), color='purple').props('outline')


# Convenience function
def create_keyword_stats(keyword_manager) -> KeywordStats:
    """
    Create and render keyword statistics widget.

    Args:
        keyword_manager: KeywordManager instance

    Returns:
        KeywordStats instance
    """
    stats = KeywordStats(keyword_manager)
    stats.render()
    return stats

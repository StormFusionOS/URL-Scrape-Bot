#!/usr/bin/env python3
"""
Filter Preview Widget - Test how keywords affect business filtering.

Allows users to test business names/descriptions against current filters
to see if they would pass or be filtered out.
"""

from nicegui import ui
from typing import Dict, List, Tuple
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scrape_google.google_filter import GoogleFilter
from scrape_yp.yp_filter import YPFilter


class FilterPreview:
    """
    Interactive filter preview widget for testing business filtering.
    """

    def __init__(self):
        """Initialize FilterPreview."""
        # Initialize filters
        self.google_filter = GoogleFilter()
        self.yp_filter = YPFilter()

        # UI elements
        self.business_name_input = None
        self.description_input = None
        self.website_input = None
        self.category_input = None
        self.result_container = None
        self.source_select = None

    def render(self):
        """Render the filter preview UI."""
        with ui.card().classes('w-full'):
            # Header
            ui.label('Filter Preview').classes('text-xl font-bold mb-2')
            ui.label(
                'Test how a business would be filtered by each discovery source'
            ).classes('text-sm text-gray-400 mb-4')

            # Source selector
            with ui.row().classes('w-full gap-4 mb-4'):
                ui.label('Test Against:').classes('text-sm font-semibold my-auto')
                self.source_select = ui.select(
                    options={
                        'all': 'All Sources',
                        'google': 'Google Maps',
                        'yp': 'Yellow Pages'
                    },
                    value='all',
                    label='Discovery Source'
                ).classes('flex-1')

            # Input fields
            with ui.grid(columns=2).classes('w-full gap-4 mb-4'):
                self.business_name_input = ui.input(
                    label='Business Name',
                    placeholder='ABC Pressure Washing'
                ).props('outlined').classes('col-span-2')

                self.description_input = ui.textarea(
                    label='Description (optional)',
                    placeholder='Professional pressure washing services...'
                ).props('outlined rows=3').classes('col-span-2')

                self.website_input = ui.input(
                    label='Website (optional)',
                    placeholder='https://example.com'
                ).props('outlined')

                self.category_input = ui.input(
                    label='Category (optional)',
                    placeholder='Pressure Washing'
                ).props('outlined')

            # Test button
            ui.button(
                'Test Filter',
                icon='science',
                color='primary',
                on_click=self._test_filter
            ).classes('w-full')

            # Results container
            ui.label('Results').classes('text-lg font-semibold mt-6 mb-3')
            self.result_container = ui.column().classes('w-full gap-3')

            with self.result_container:
                ui.label('Enter business details above and click "Test Filter"').classes(
                    'text-sm text-gray-500 italic'
                )

        # Example buttons
        with ui.row().classes('w-full gap-2 mt-4'):
            ui.label('Quick Examples:').classes('text-sm my-auto')
            ui.button(
                'Good Example',
                on_click=lambda: self._load_example('good'),
                icon='check_circle'
            ).props('flat dense').classes('text-green-500')
            ui.button(
                'Bad Example (Equipment)',
                on_click=lambda: self._load_example('equipment'),
                icon='cancel'
            ).props('flat dense').classes('text-red-500')
            ui.button(
                'Bad Example (Training)',
                on_click=lambda: self._load_example('training'),
                icon='cancel'
            ).props('flat dense').classes('text-red-500')

        return self

    def _load_example(self, example_type: str):
        """
        Load example business data.

        Args:
            example_type: Type of example (good, equipment, training)
        """
        examples = {
            'good': {
                'name': 'Crystal Clear Pressure Washing',
                'description': 'Professional exterior cleaning, soft washing, roof cleaning, and deck restoration services',
                'website': 'https://crystalclearpw.com',
                'category': 'Pressure Washing Service'
            },
            'equipment': {
                'name': 'Pro Pressure Equipment & Supplies',
                'description': 'Pressure washer sales, equipment rental, and parts supplier',
                'website': 'https://homedepot.com/pressure-washers',
                'category': 'Equipment Rental'
            },
            'training': {
                'name': 'Pressure Washing Academy',
                'description': 'Learn how to start your own pressure washing business with our online courses',
                'website': 'https://pwacademy.com',
                'category': 'Business Training'
            }
        }

        if example_type in examples:
            ex = examples[example_type]
            self.business_name_input.value = ex['name']
            self.description_input.value = ex['description']
            self.website_input.value = ex['website']
            self.category_input.value = ex['category']

            # Auto-test after loading
            self._test_filter()

    def _test_filter(self):
        """Test the business against filters."""
        # Get input values
        name = self.business_name_input.value.strip()

        if not name:
            ui.notify('Please enter a business name', type='warning')
            return

        description = self.description_input.value.strip()
        website = self.website_input.value.strip()
        category = self.category_input.value.strip()

        # Build business data
        business_data = {
            'name': name,
            'description': description,
            'categories': [category] if category else [],
            'website': website,
            'url': ''  # Google Maps URL (not needed for test)
        }

        # Test against selected sources
        source = self.source_select.value
        results = {}

        if source == 'all' or source == 'google':
            results['Google Maps'] = self._test_google_filter(business_data)

        if source == 'all' or source == 'yp':
            results['Yellow Pages'] = self._test_yp_filter(business_data, category)

        # Display results
        self._display_results(results, business_data)

    def _test_google_filter(self, business_data: Dict) -> Dict:
        """Test against Google filter."""
        return self.google_filter.filter_business(business_data)

    def _test_yp_filter(self, business_data: Dict, category: str) -> Dict:
        """Test against YP filter."""
        # YP filter expects different format
        yp_data = {
            'business_name': business_data['name'],
            'full_description': business_data['description'],
            'categories': [category] if category else [],
            'website': business_data['website']
        }
        return self.yp_filter.filter_listing(yp_data)

    def _display_results(self, results: Dict, business_data: Dict):
        """
        Display filter test results.

        Args:
            results: Dictionary of source -> filter result
            business_data: Original business data
        """
        self.result_container.clear()

        with self.result_container:
            # Business info summary
            with ui.card().classes('w-full bg-gray-800 mb-4'):
                ui.label('Testing:').classes('text-sm font-semibold text-gray-400 mb-2')
                ui.label(business_data['name']).classes('text-lg font-bold')
                if business_data['description']:
                    ui.label(business_data['description']).classes('text-sm text-gray-400 mt-1')

            # Results for each source
            for source_name, result in results.items():
                self._display_source_result(source_name, result)

    def _display_source_result(self, source_name: str, result: Dict):
        """
        Display result for a single source.

        Args:
            source_name: Name of the source
            result: Filter result dictionary
        """
        passed = result.get('passed', False)
        confidence = result.get('confidence', 0.0)
        filter_reason = result.get('filter_reason', '')
        signals = result.get('signals', {})

        # Color based on result
        if passed:
            bg_color = 'bg-green-900/20'
            border_color = 'border-green-500/50'
            icon = 'check_circle'
            icon_color = 'text-green-500'
            status_text = 'PASS'
            status_color = 'text-green-400'
        else:
            bg_color = 'bg-red-900/20'
            border_color = 'border-red-500/50'
            icon = 'cancel'
            icon_color = 'text-red-500'
            status_text = 'FILTERED OUT'
            status_color = 'text-red-400'

        with ui.card().classes(f'w-full {bg_color}').style(f'border: 1px solid; border-color: {border_color[7:]}'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon(icon).classes(f'{icon_color} text-2xl')
                    ui.label(source_name).classes('text-lg font-bold')

                ui.label(status_text).classes(f'text-sm font-bold {status_color}')

            # Confidence score
            confidence_percent = int(confidence * 100)
            with ui.row().classes('w-full items-center gap-2 mb-3'):
                ui.label('Confidence:').classes('text-sm text-gray-400')
                ui.linear_progress(value=confidence).classes('flex-1')
                ui.label(f'{confidence_percent}%').classes('text-sm font-mono')

            # Filter reason (if failed)
            if not passed and filter_reason:
                with ui.card().classes('w-full bg-red-900/20 mt-2'):
                    ui.label('Reason:').classes('text-xs font-semibold text-red-300 mb-1')
                    ui.label(filter_reason).classes('text-sm text-red-200')

            # Signals (detailed breakdown)
            if signals:
                with ui.expansion('View Details', icon='info').classes('w-full mt-2'):
                    with ui.column().classes('w-full gap-2'):
                        # Anti-keywords found
                        if signals.get('anti_keywords'):
                            ui.label('❌ Anti-Keywords Detected:').classes('text-sm font-semibold text-red-400')
                            for kw in signals['anti_keywords'][:5]:  # Show max 5
                                ui.label(f'  • {kw}').classes('text-xs text-red-300 font-mono')

                        # Positive hints found
                        if signals.get('positive_hints'):
                            ui.label('✅ Positive Hints Found:').classes('text-sm font-semibold text-green-400 mt-2')
                            for kw in signals['positive_hints'][:5]:
                                ui.label(f'  • {kw}').classes('text-xs text-green-300 font-mono')

                        # Blocked domain
                        if signals.get('blocked_domain'):
                            ui.label('🚫 Blocked Domain:').classes('text-sm font-semibold text-orange-400 mt-2')
                            ui.label(f'  • {signals.get("domain", "N/A")}').classes('text-xs text-orange-300 font-mono')

                        # Category info (YP)
                        if 'category_status' in signals:
                            ui.label('📁 Category Status:').classes('text-sm font-semibold text-blue-400 mt-2')
                            ui.label(f'  • {signals["category_status"]}').classes('text-xs text-blue-300')

    def reload_filters(self):
        """Reload all filters from disk."""
        self.google_filter = GoogleFilter()
        self.yp_filter = YPFilter()
        ui.notify('Filters reloaded!', type='positive')


# Convenience function
def create_filter_preview() -> FilterPreview:
    """
    Create and render a filter preview widget.

    Returns:
        FilterPreview instance
    """
    preview = FilterPreview()
    preview.render()
    return preview

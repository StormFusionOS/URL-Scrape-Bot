"""
Local Competitors Management Page
Interactive UI for managing manually entered local competitors
"""

from nicegui import ui
from datetime import datetime
import logging
from typing import Optional, Dict, Any
import csv
import io

from niceui.services.local_competitors_api import local_competitors_api

logger = logging.getLogger(__name__)


def create_page():
    """Create the local competitors management page"""

    # State variables
    selected_competitor = None
    competitors_table = None

    # Main container
    with ui.column().classes('w-full max-w-7xl mx-auto p-4 gap-6'):
        # Header
        with ui.card().classes('glass-card'):
            ui.label('Local Competitors Management').classes('text-2xl font-bold text-white mb-2')
            ui.label('Manage and track local business competitors').classes('text-gray-300')

        # Statistics cards
        create_stats_cards()

        # Add/Edit Form and Table
        with ui.row().classes('w-full gap-4'):
            # Left column - Add/Edit Form
            with ui.column().classes('w-1/3'):
                create_competitor_form()

            # Right column - Competitors Table
            with ui.column().classes('w-2/3'):
                competitors_table = create_competitors_table()

        # Sync controls
        create_sync_controls()

        # CSV Upload controls
        create_csv_upload()


def create_stats_cards():
    """Create statistics cards showing competitor metrics"""
    with ui.row().classes('w-full gap-4'):
        # Get statistics
        stats = local_competitors_api.get_competitor_stats('local')

        # Total Local Competitors
        with ui.card().classes('glass-card flex-1'):
            ui.label('Total Local').classes('text-gray-300 text-sm')
            ui.label(str(stats.get('local_count', 0))).classes('text-2xl font-bold text-white')

        # Primary Competitors
        with ui.card().classes('glass-card flex-1'):
            ui.label('Primary').classes('text-gray-300 text-sm')
            ui.label(str(stats.get('primary_count', 0))).classes('text-2xl font-bold text-cyan-400')

        # Tier 1 Competitors
        with ui.card().classes('glass-card flex-1'):
            ui.label('Tier 1').classes('text-gray-300 text-sm')
            ui.label(str(stats.get('tier1_count', 0))).classes('text-2xl font-bold text-purple-400')

        # Never Crawled
        with ui.card().classes('glass-card flex-1'):
            ui.label('Never Crawled').classes('text-gray-300 text-sm')
            ui.label(str(stats.get('never_crawled', 0))).classes('text-2xl font-bold text-yellow-400')

        # Success Rate
        with ui.card().classes('glass-card flex-1'):
            ui.label('Success Rate').classes('text-gray-300 text-sm')
            success_rate = stats.get('success_rate', 0)
            color = 'text-green-400' if success_rate >= 90 else 'text-yellow-400' if success_rate >= 70 else 'text-red-400'
            ui.label(f'{success_rate:.1f}%').classes(f'text-2xl font-bold {color}')


def create_competitor_form():
    """Create the add/edit competitor form"""

    with ui.card().classes('glass-card'):
        ui.label('Add Local Competitor').classes('text-xl font-bold text-white mb-4')

        # Form inputs
        business_name = ui.input('Business Name *',
            placeholder='e.g., Joe\'s Plumbing').classes('w-full')

        url = ui.input('Website URL *',
            placeholder='https://example.com').classes('w-full')

        with ui.row().classes('w-full gap-2'):
            industry = ui.input('Industry',
                placeholder='e.g., Plumbing').classes('flex-1')

            location = ui.input('Location',
                placeholder='e.g., Las Vegas, NV').classes('flex-1')

        address = ui.textarea('Address',
            placeholder='Full address').classes('w-full').props('rows=2')

        phone = ui.input('Phone',
            placeholder='(555) 123-4567').classes('w-full')

        with ui.row().classes('w-full gap-2'):
            priority = ui.number('Priority',
                value=5, min=1, max=10).classes('flex-1')

            tier = ui.select(
                options=['tier1', 'tier2', 'tier3'],
                value='tier2',
                label='Tier').classes('flex-1')

        traffic = ui.number('Est. Monthly Traffic',
            placeholder='10000').classes('w-full')

        tags = ui.input('Tags',
            placeholder='tag1, tag2, tag3 (comma separated)').classes('w-full')

        notes = ui.textarea('Notes',
            placeholder='Additional notes...').classes('w-full').props('rows=2')

        is_primary = ui.checkbox('Primary Competitor')

        # Action buttons
        with ui.row().classes('w-full gap-2 mt-4'):
            async def add_competitor():
                """Add a new competitor"""
                if not business_name.value or not url.value:
                    ui.notify('Business name and URL are required', type='warning')
                    return

                # Prepare data
                data = {
                    'business_name': business_name.value,
                    'url': url.value,
                    'industry': industry.value or None,
                    'location': location.value or None,
                    'address': address.value or None,
                    'phone': phone.value or None,
                    'priority': int(priority.value),
                    'competitor_tier': tier.value,
                    'estimated_monthly_traffic': int(traffic.value) if traffic.value else None,
                    'tags': [tag.strip() for tag in tags.value.split(',')] if tags.value else [],
                    'notes': notes.value or None,
                    'is_primary_competitor': is_primary.value
                }

                # Call API
                result = local_competitors_api.add_local_competitor(data)

                if result['success']:
                    ui.notify('Competitor added successfully', type='positive')
                    # Clear form
                    business_name.value = ''
                    url.value = ''
                    industry.value = ''
                    location.value = ''
                    address.value = ''
                    phone.value = ''
                    priority.value = 5
                    tier.value = 'tier2'
                    traffic.value = None
                    tags.value = ''
                    notes.value = ''
                    is_primary.value = False
                    # Refresh table
                    refresh_table()
                else:
                    ui.notify(f'Error: {result.get("error", "Unknown error")}', type='negative')

            ui.button('Add Competitor', on_click=add_competitor).classes('flex-1').props('color=primary')

            ui.button('Clear', on_click=lambda: clear_form(
                business_name, url, industry, location, address,
                phone, priority, tier, traffic, tags, notes, is_primary
            )).classes('flex-1')


def clear_form(*inputs):
    """Clear all form inputs"""
    for inp in inputs[:-1]:
        inp.value = '' if hasattr(inp, 'value') else None
    inputs[-1].value = False  # Checkbox


def create_competitors_table():
    """Create the competitors table"""

    def refresh_table():
        """Refresh the table data"""
        competitors = local_competitors_api.get_local_competitors()

        # Format data for display
        rows = []
        for comp in competitors:
            rows.append({
                'id': comp['local_competitor_id'],
                'business_name': comp['business_name'],
                'url': comp['url'][:50] + '...' if len(comp['url']) > 50 else comp['url'],
                'priority': comp['priority'],
                'tier': comp.get('competitor_tier', '-'),
                'status': comp['status'],
                'sync_state': comp.get('sync_state', 'unknown'),
                'crawl_status': comp.get('crawl_status', '-'),
                'last_crawled': format_date(comp.get('last_crawled')),
                'crawl_count': comp.get('crawl_count', 0),
                'primary': '✓' if comp.get('is_primary_competitor') else '',
                'actions': comp['local_competitor_id']
            })

        return rows

    with ui.card().classes('glass-card'):
        with ui.row().classes('w-full justify-between items-center mb-4'):
            ui.label('Local Competitors').classes('text-xl font-bold text-white')

            ui.button('Refresh', on_click=lambda: table.update_rows(refresh_table())).props('icon=refresh')

        # Create table
        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'sortable': True},
            {'name': 'business_name', 'label': 'Business Name', 'field': 'business_name', 'sortable': True},
            {'name': 'url', 'label': 'URL', 'field': 'url'},
            {'name': 'priority', 'label': 'Priority', 'field': 'priority', 'sortable': True},
            {'name': 'tier', 'label': 'Tier', 'field': 'tier'},
            {'name': 'primary', 'label': 'Primary', 'field': 'primary'},
            {'name': 'status', 'label': 'Status', 'field': 'status'},
            {'name': 'sync_state', 'label': 'Sync', 'field': 'sync_state'},
            {'name': 'crawl_status', 'label': 'Crawl Status', 'field': 'crawl_status'},
            {'name': 'last_crawled', 'label': 'Last Crawled', 'field': 'last_crawled'},
            {'name': 'crawl_count', 'label': 'Crawls', 'field': 'crawl_count'},
            {'name': 'actions', 'label': 'Actions', 'field': 'actions'}
        ]

        rows = refresh_table()

        table = ui.table(
            columns=columns,
            rows=rows,
            row_key='id',
            selection='single',
            pagination={'rowsPerPage': 10}
        ).classes('w-full')

        # Add action buttons to each row
        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn flat round dense icon="edit" @click="$emit('edit', props.row)" />
                <q-btn flat round dense icon="delete" color="red" @click="$emit('delete', props.row)" />
            </q-td>
        ''')

        # Handle edit and delete events
        async def handle_edit(e):
            comp_id = e.args['id']
            ui.notify(f'Edit functionality for ID {comp_id} not yet implemented', type='info')

        async def handle_delete(e):
            comp_id = e.args['id']
            result = local_competitors_api.delete_local_competitor(comp_id)
            if result['success']:
                ui.notify('Competitor archived', type='positive')
                table.update_rows(refresh_table())
            else:
                ui.notify(f'Error: {result.get("error", "Unknown error")}', type='negative')

        table.on('edit', handle_edit)
        table.on('delete', handle_delete)

        return table


def create_sync_controls():
    """Create sync control buttons"""

    with ui.card().classes('glass-card'):
        ui.label('Sync Controls').classes('text-xl font-bold text-white mb-4')

        with ui.row().classes('w-full gap-4'):
            async def sync_local():
                """Sync all local competitors to competitor_urls"""
                ui.notify('Syncing local competitors...', type='info')
                result = local_competitors_api.bulk_sync_local_competitors()

                if result['success']:
                    msg = f"Synced {result['synced_count']} competitors"
                    if result['skipped_count'] > 0:
                        msg += f", skipped {result['skipped_count']}"
                    ui.notify(msg, type='positive')
                else:
                    ui.notify(f'Error: {result.get("error", "Unknown error")}', type='negative')

            async def sync_national():
                """Sync national competitors from washbot_db"""
                ui.notify('Syncing national competitors from washbot_db...', type='info')
                result = local_competitors_api.sync_national_competitors()

                if result['success']:
                    ui.notify(f"Synced {result['synced_count']} national competitors", type='positive')
                    if result.get('errors'):
                        logger.warning(f"Sync errors: {result['errors']}")
                else:
                    ui.notify(f'Error: {result.get("error", "Unknown error")}', type='negative')

            ui.button('Sync Local to Crawler', on_click=sync_local).props('color=primary icon=sync')
            ui.button('Sync National from WashDB', on_click=sync_national).props('color=secondary icon=cloud_download')

            # Performance metrics
            metrics = local_competitors_api.get_performance_metrics()
            local_metrics = next((m for m in metrics if m['node_type'] == 'local'), {})

            if local_metrics:
                with ui.column().classes('flex-1 text-right'):
                    ui.label(f"Total Crawls: {local_metrics.get('total_crawls', 0)}").classes('text-gray-300')
                    avg_age = local_metrics.get('avg_data_age_days') or 0
                    ui.label(f"Avg Data Age: {avg_age:.1f} days").classes('text-gray-300')


def create_csv_upload():
    """Create CSV upload section"""

    with ui.card().classes('glass-card'):
        ui.label('CSV Upload').classes('text-xl font-bold text-white mb-4')

        with ui.column().classes('w-full gap-4'):
            # Instructions
            ui.label('Upload a CSV file with your local competitor URLs').classes('text-gray-300')

            with ui.expansion('CSV Format Guidelines', icon='info').classes('w-full'):
                ui.markdown('''
                **Required columns:**
                - `url` or `website` - The competitor's website URL (required)
                - `business_name` or `name` - The business name (required)

                **Optional columns:**
                - `industry` - Industry/category
                - `location` - Business location
                - `address` - Full address
                - `phone` - Phone number
                - `priority` - Priority ranking (1-10, default: 5)
                - `tier` - Competitor tier (tier1, tier2, tier3)
                - `is_primary` - Primary competitor (true/false)
                - `traffic` - Estimated monthly traffic
                - `tags` - Comma-separated tags
                - `notes` - Additional notes

                **Example CSV:**
                ```
                url,business_name,industry,location,priority
                https://example1.com,Joe's Plumbing,Plumbing,Las Vegas,8
                https://example2.com,Smith HVAC,HVAC,Henderson,7
                ```
                ''').classes('text-sm text-gray-300')

            # File upload
            async def handle_upload(e):
                """Handle CSV file upload"""
                try:
                    # Get the uploaded file content
                    content = e.content.read()
                    text_content = content.decode('utf-8')

                    # Parse CSV
                    csv_reader = csv.DictReader(io.StringIO(text_content))
                    rows = list(csv_reader)

                    if not rows:
                        ui.notify('CSV file is empty', type='warning')
                        return

                    # Validate and process rows
                    success_count = 0
                    error_count = 0
                    errors = []

                    for i, row in enumerate(rows, 1):
                        # Normalize column names
                        normalized_row = {}
                        for key, value in row.items():
                            if key:
                                normalized_row[key.lower().strip()] = value.strip() if value else None

                        # Check for required fields
                        url = normalized_row.get('url') or normalized_row.get('website')
                        business_name = normalized_row.get('business_name') or normalized_row.get('name') or normalized_row.get('business')

                        if not url or not business_name:
                            error_count += 1
                            errors.append(f"Row {i}: Missing required fields (url and business_name)")
                            continue

                        # Prepare data for API
                        data = {
                            'business_name': business_name,
                            'url': url,
                            'industry': normalized_row.get('industry'),
                            'location': normalized_row.get('location'),
                            'address': normalized_row.get('address'),
                            'phone': normalized_row.get('phone'),
                            'priority': int(normalized_row.get('priority', 5)) if normalized_row.get('priority') else 5,
                            'competitor_tier': normalized_row.get('tier', 'tier2'),
                            'estimated_monthly_traffic': int(normalized_row.get('traffic')) if normalized_row.get('traffic') else None,
                            'tags': [tag.strip() for tag in normalized_row.get('tags', '').split(',')] if normalized_row.get('tags') else [],
                            'notes': normalized_row.get('notes'),
                            'is_primary_competitor': normalized_row.get('is_primary', '').lower() in ['true', 'yes', '1']
                        }

                        # Call API to add competitor
                        result = local_competitors_api.add_local_competitor(data)

                        if result['success']:
                            success_count += 1
                        else:
                            error_count += 1
                            errors.append(f"Row {i} ({business_name}): {result.get('error', 'Unknown error')}")

                    # Show results
                    if success_count > 0:
                        ui.notify(f'Successfully imported {success_count} competitors', type='positive')
                        # Refresh the table if it exists
                        try:
                            refresh_table()
                        except:
                            pass

                    if error_count > 0:
                        error_msg = f'Failed to import {error_count} competitors'
                        if errors and len(errors) <= 3:
                            error_msg += ': ' + '; '.join(errors[:3])
                        elif errors:
                            error_msg += f': {"; ".join(errors[:3])}... and {len(errors) - 3} more'
                        ui.notify(error_msg, type='negative')

                        # Log all errors
                        for error in errors:
                            logger.error(f"CSV import error: {error}")

                except Exception as e:
                    logger.error(f"CSV upload error: {e}")
                    ui.notify(f'Error processing CSV: {str(e)}', type='negative')

            upload = ui.upload(
                label='Upload CSV File',
                on_upload=handle_upload,
                max_file_size=10_000_000  # 10MB limit
            ).classes('w-full').props('accept=".csv"')

            # Sample CSV download
            with ui.row().classes('w-full gap-4'):
                def download_sample_csv():
                    """Generate and download a sample CSV"""
                    sample_data = [
                        ['url', 'business_name', 'industry', 'location', 'priority', 'tier', 'is_primary'],
                        ['https://example-plumber.com', "Joe's Plumbing", 'Plumbing', 'Las Vegas, NV', '8', 'tier1', 'true'],
                        ['https://smithhvac.com', 'Smith HVAC Services', 'HVAC', 'Henderson, NV', '7', 'tier2', 'false'],
                        ['https://quickdrain.com', 'Quick Drain Plumbers', 'Plumbing', 'Las Vegas, NV', '6', 'tier2', 'false']
                    ]

                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerows(sample_data)

                    # NiceGUI download
                    ui.download(
                        output.getvalue().encode('utf-8'),
                        'sample_competitors.csv'
                    )

                ui.button('Download Sample CSV', on_click=download_sample_csv).props('icon=download outline')

                ui.label('Download a sample CSV file to see the expected format').classes('text-sm text-gray-400')


def format_date(date_str):
    """Format date string for display"""
    if not date_str:
        return '-'
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except:
        return date_str
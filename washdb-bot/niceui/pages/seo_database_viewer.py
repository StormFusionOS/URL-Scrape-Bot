"""
Database Viewer Page
Browse the entire SEO scraper database with AI-friendly export capabilities
Dynamic table discovery with support for both public and seo_analytics schemas
"""

from nicegui import ui
from datetime import datetime
from typing import Optional, List, Dict, Any
import json
from db.database_manager import get_db_manager
from db.schema_inspector import get_schema_inspector
from niceui.components.glass_card import glass_card, status_badge, section_title, divider
from niceui.layout import page_layout
import logging

logger = logging.getLogger(__name__)

# Get database manager instance
db_manager = get_db_manager()


def create_page():
    """Create the database viewer page"""

    # Initialize schema inspector
    inspector = get_schema_inspector(db_manager)

    # Discover available schemas
    try:
        available_schemas = inspector.get_schemas()
        logger.info(f"Discovered schemas: {available_schemas}")
    except Exception as e:
        logger.error(f"Error discovering schemas: {e}")
        available_schemas = ['public', 'seo_analytics']

    # State management
    state = {
        'selected_schema': 'public',
        'selected_table': None,
        'table_info': None,
        'available_tables': [],
        'columns': [],
        'rows': [],
        'limit': 100,
        'offset': 0,
        'search_term': '',
        'total_count': 0,
        'max_pages': 5000,
        'node_filter': 'all'  # For competitor_urls filtering
    }

    # UI element references
    ui_refs = {
        'schema_toggle': None,
        'table_selector': None,
        'data_container': None,
        'metadata_container': None,
        'stats_container': None,
        'insights_container': None,
        'node_filter': None,
        'node_filter_container': None
    }

    def load_available_tables(schema: str):
        """Load available tables for a schema"""
        try:
            tables = inspector.get_tables(schema)
            state['available_tables'] = tables
            logger.info(f"Loaded {len(tables)} tables from schema '{schema}'")
            return [table.name for table in tables]
        except Exception as e:
            logger.error(f"Error loading tables from schema '{schema}': {e}")
            ui.notify(f'Error loading tables: {str(e)}', type='negative')
            return []

    def load_table_data():
        """Load data from the selected table using schema inspector"""
        if not state['selected_table']:
            return

        try:
            schema = state['selected_schema']
            table = state['selected_table']

            # Special handling for competitor_urls table with node filtering
            if table == 'competitor_urls' and state['node_filter'] != 'all':
                from sqlalchemy import text
                with db_manager.get_session() as session:
                    # Build query with node filter
                    where_clause = f"WHERE node_type = :node_type" if state['node_filter'] != 'both' else ""

                    # Count query
                    count_query = f"SELECT COUNT(*) FROM {schema}.{table} {where_clause}"
                    params = {'node_type': state['node_filter']} if state['node_filter'] != 'both' else {}

                    result = session.execute(text(count_query), params)
                    state['total_count'] = result.scalar()

                    # Data query
                    data_query = f"""
                        SELECT * FROM {schema}.{table}
                        {where_clause}
                        ORDER BY priority DESC, competitor_url_id
                        LIMIT :limit OFFSET :offset
                    """
                    params['limit'] = state['limit']
                    params['offset'] = state['offset']

                    result = session.execute(text(data_query), params)
                    state['columns'] = list(result.keys())
                    state['rows'] = result.fetchall()
            # Use schema inspector search if there's a search term
            elif state['search_term']:
                state['columns'], state['rows'], state['total_count'] = inspector.search_table_data(
                    schema=schema,
                    table=table,
                    search_term=state['search_term'],
                    limit=state['limit'],
                    offset=state['offset']
                )
            else:
                # Get sample data
                state['columns'], rows = inspector.get_table_sample(
                    schema=schema,
                    table=table,
                    limit=state['limit']
                )
                state['rows'] = rows

                # Get total count
                table_info = next((t for t in state['available_tables'] if t.name == table), None)
                state['total_count'] = table_info.row_count if table_info else 0

        except Exception as e:
            logger.error(f"Error loading table data: {e}")
            ui.notify(f'Error loading table data: {str(e)}', type='negative')
            state['columns'] = []
            state['rows'] = []
            state['total_count'] = 0

    def export_to_json():
        """Export current table data to JSON for AI consumption"""
        if not state['selected_table']:
            ui.notify('Please select a table first', type='warning')
            return

        try:
            # Convert rows to list of dicts
            data_dicts = []
            for row in state['rows']:
                row_dict = {}
                for i, col in enumerate(state['columns']):
                    value = row[i]
                    # Convert datetime objects to strings for JSON serialization
                    if isinstance(value, datetime):
                        row_dict[col] = value.isoformat()
                    else:
                        row_dict[col] = value
                data_dicts.append(row_dict)

            # Create AI-friendly export structure
            export_data = {
                'metadata': {
                    'schema': state['selected_schema'],
                    'table': state['selected_table'],
                    'exported_at': datetime.utcnow().isoformat(),
                    'total_rows_in_table': state['total_count'],
                    'columns': state['columns'],
                    'row_count_in_export': len(data_dicts),
                    'is_partitioned': state['table_info'].is_partitioned if state['table_info'] else False
                },
                'data': data_dicts
            }

            # Convert to JSON
            json_str = json.dumps(export_data, indent=2, default=str)

            # Trigger download
            filename = f"{state['selected_schema']}_{state['selected_table']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            ui.download(json_str.encode('utf-8'), filename)

            ui.notify(f'Exported {len(data_dicts)} rows to {filename}', type='positive')

        except Exception as e:
            logger.error(f"Error exporting to JSON: {e}")
            ui.notify(f'Error exporting data: {str(e)}', type='negative')

    def export_to_csv():
        """Export current table data to CSV"""
        if not state['selected_table']:
            ui.notify('Please select a table first', type='warning')
            return

        try:
            import csv
            import io

            # Create CSV
            output = io.StringIO()
            if state['rows']:
                writer = csv.writer(output)

                # Write header
                writer.writerow(state['columns'])

                # Write rows
                for row in state['rows']:
                    # Convert datetime objects to strings
                    row_values = []
                    for value in row:
                        if isinstance(value, datetime):
                            row_values.append(value.isoformat())
                        else:
                            row_values.append(value)
                    writer.writerow(row_values)

            # Trigger download
            filename = f"{state['selected_schema']}_{state['selected_table']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            ui.download(output.getvalue().encode('utf-8'), filename)

            ui.notify(f'Exported {len(state["rows"])} rows to {filename}', type='positive')

        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            ui.notify(f'Error exporting CSV: {str(e)}', type='negative')

    def on_schema_change(schema: str):
        """Handle schema selection change"""
        state['selected_schema'] = schema
        state['selected_table'] = None
        state['table_info'] = None
        state['rows'] = []
        state['columns'] = []
        state['total_count'] = 0

        # Load tables for new schema
        table_names = load_available_tables(schema)

        # Update table selector options
        if ui_refs['table_selector']:
            ui_refs['table_selector'].options = table_names
            ui_refs['table_selector'].value = None
            ui_refs['table_selector'].update()

        refresh_view()

    def on_table_change(table: str):
        """Handle table selection change"""
        if not table:
            return

        state['selected_table'] = table
        state['offset'] = 0

        # Get table info
        state['table_info'] = next((t for t in state['available_tables'] if t.name == table), None)

        # Show/hide node filter for competitor_urls table
        if ui_refs['node_filter_container']:
            ui_refs['node_filter_container'].clear()
            with ui_refs['node_filter_container']:
                if table == 'competitor_urls':
                    create_node_filter()

        # Load table data
        load_table_data()

        refresh_view()

    def on_node_filter_change(value: str):
        """Handle node filter change"""
        state['node_filter'] = value
        state['offset'] = 0
        load_table_data()
        refresh_view()

    def create_node_filter():
        """Create node type filter for competitor_urls"""
        with ui.column().classes('gap-2 flex-1'):
            ui.label('Node Type Filter').classes('text-sm text-white/60')
            ui.label('Filter competitors by source').classes('text-xs text-white/40')
            ui_refs['node_filter'] = ui.toggle(
                ['all', 'local', 'national', 'both'],
                value=state['node_filter'],
                on_change=lambda e: on_node_filter_change(e.value)
            ).classes('bg-white/10')

    def on_search(e):
        """Handle search input"""
        state['search_term'] = e.value
        state['offset'] = 0

        if state['selected_table']:
            load_table_data()
            refresh_view()

    def prev_page():
        """Load previous page of data"""
        if state['offset'] >= state['limit']:
            state['offset'] -= state['limit']
            load_table_data()
            refresh_view()

    def next_page():
        """Load next page of data"""
        max_offset = state['limit'] * state['max_pages']
        if state['offset'] + state['limit'] < state['total_count'] and state['offset'] + state['limit'] < max_offset:
            state['offset'] += state['limit']
            load_table_data()
            refresh_view()

    def refresh_view():
        """Refresh the data view"""
        if ui_refs['data_container']:
            ui_refs['data_container'].clear()
            with ui_refs['data_container']:
                render_data_view()

        if ui_refs['metadata_container']:
            ui_refs['metadata_container'].clear()
            with ui_refs['metadata_container']:
                render_metadata_view()

        if ui_refs['stats_container']:
            ui_refs['stats_container'].clear()
            with ui_refs['stats_container']:
                render_stats_view()

        if ui_refs['insights_container']:
            ui_refs['insights_container'].clear()
            with ui_refs['insights_container']:
                render_insights_view()

    def render_stats_view():
        """Render statistics view"""
        if state['table_info']:
            with ui.row().classes('gap-4 w-full'):
                # Total Rows
                with glass_card(classes='flex-1'):
                    ui.label('Total Rows').classes('text-sm text-white/60')
                    ui.label(f"{state['table_info'].row_count:,}").classes('text-2xl font-bold text-white')

                # Is Partitioned
                if state['table_info'].is_partitioned:
                    with glass_card(classes='flex-1'):
                        ui.label('Table Type').classes('text-sm text-white/60')
                        ui.label('Partitioned').classes('text-xl font-bold text-purple-300')
                else:
                    with glass_card(classes='flex-1'):
                        ui.label('Table Type').classes('text-sm text-white/60')
                        ui.label('Standard').classes('text-xl font-bold text-white')

                # Current View
                with glass_card(classes='flex-1'):
                    ui.label('Showing Rows').classes('text-sm text-white/60')
                    start = state['offset'] + 1
                    end = min(state['offset'] + len(state['rows']), state['total_count'])
                    if state['rows']:
                        ui.label(f"{start:,} - {end:,}").classes('text-2xl font-bold text-white')
                    else:
                        ui.label("0").classes('text-2xl font-bold text-white/40')

    def render_insights_view():
        """Render quick insights panel"""
        if not state['table_info']:
            return

        section_title('Quick Insights', icon='insights', classes='mb-3')

        with glass_card():
            with ui.column().classes('gap-3 w-full'):
                # Schema info
                with ui.row().classes('items-center gap-2'):
                    ui.icon('schema', size='sm').classes('text-purple-400')
                    ui.label(f"Schema: {state['table_info'].schema}").classes('text-sm text-white')

                # Last updated
                if state['table_info'].last_updated:
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('schedule', size='sm').classes('text-blue-400')
                        ui.label(f"Last Updated: {state['table_info'].last_updated.strftime('%Y-%m-%d %H:%M')}").classes('text-sm text-white/80')

                # Description
                if state['table_info'].description:
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('info', size='sm').classes('text-green-400')
                        ui.label(state['table_info'].description).classes('text-sm text-white/80')

    def render_metadata_view():
        """Render table metadata view"""
        if state['columns']:
            section_title('Table Schema', icon='schema', classes='mb-3')

            # Get column details from inspector
            if state['selected_table']:
                try:
                    column_infos = inspector.get_columns(state['selected_schema'], state['selected_table'])

                    with glass_card():
                        with ui.column().classes('gap-2 w-full'):
                            for col_info in column_infos:
                                with ui.row().classes('items-center gap-4 p-2 rounded bg-white/5'):
                                    ui.label(col_info.name).classes('font-mono text-sm text-white font-semibold flex-1')
                                    ui.label(col_info.data_type).classes('text-xs text-purple-300 bg-purple-500/20 px-2 py-1 rounded')
                                    if not col_info.is_nullable:
                                        ui.label('NOT NULL').classes('text-xs text-orange-300 bg-orange-500/20 px-2 py-1 rounded')
                except Exception as e:
                    logger.error(f"Error loading column metadata: {e}")
                    with glass_card():
                        ui.label('Error loading schema details').classes('text-white/60 text-sm')

    def render_data_view():
        """Render data table view"""
        if not state['rows']:
            with glass_card():
                if state['selected_table']:
                    ui.label('No data found').classes('text-white/60 text-center p-8')
                else:
                    ui.label('Select a table to view data').classes('text-white/60 text-center p-8')
            return

        # Create scrollable table
        with glass_card():
            with ui.scroll_area().classes('w-full h-96'):
                # Table header
                with ui.row().classes('gap-2 mb-2 p-2 bg-purple-500/20 rounded sticky top-0'):
                    for col in state['columns']:
                        ui.label(col).classes('text-xs font-semibold text-white flex-1 min-w-32')

                # Table rows
                for row in state['rows']:
                    with ui.row().classes('gap-2 p-2 hover:bg-white/5 rounded border-b border-white/10'):
                        for value in row:
                            # Truncate long values and handle datetime
                            if isinstance(value, datetime):
                                display_value = value.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                display_value = str(value)[:100] if value is not None else ''
                            ui.label(display_value).classes('text-xs text-white/80 flex-1 min-w-32 font-mono')

    # Build UI
    with page_layout(title="Database Viewer", subtitle="Browse URL Scraper and SEO Analytics data"):
        # Header with export buttons
        with ui.row().classes('items-center justify-between w-full mb-6'):
            with ui.column().classes('gap-1'):
                ui.label('Database Viewer').classes('text-3xl font-bold text-white')
                ui.label('Live view of URL scraper database (public) and SEO analytics data (seo_analytics)').classes('text-white/60')

            # Export buttons
            with ui.row().classes('gap-2'):
                ui.button('Export JSON', icon='download', on_click=export_to_json).classes(
                    'bg-purple-600/30 hover:bg-purple-600/50 text-white border border-purple-400/30'
                )
                ui.button('Export CSV', icon='table_view', on_click=export_to_csv).classes(
                    'bg-blue-600/30 hover:bg-blue-600/50 text-white border border-blue-400/30'
                )

        # Schema and Table Selection
        with glass_card(classes='mb-6'):
            with ui.row().classes('gap-4 w-full items-center'):
                # Schema selector
                with ui.column().classes('gap-2 flex-1'):
                    ui.label('Database Schema').classes('text-sm text-white/80 font-semibold')
                    ui.label('public = URL Scraper • seo_analytics = SEO Data').classes('text-xs text-white/50')
                    ui_refs['schema_toggle'] = ui.toggle(
                        available_schemas,
                        value='public',
                        on_change=lambda e: on_schema_change(e.value)
                    ).classes('bg-white/10')

                # Table selector
                with ui.column().classes('gap-2 flex-1'):
                    ui.label('Table').classes('text-sm text-white/60')
                    ui_refs['table_selector'] = ui.select(
                        options=[],
                        value=None,
                        on_change=lambda e: on_table_change(e.value)
                    ).classes('w-full bg-white/10 text-white')

                # Search
                with ui.column().classes('gap-2 flex-1'):
                    ui.label('Search').classes('text-sm text-white/60')
                    ui.input(
                        placeholder='Search in text columns...',
                        on_change=on_search
                    ).classes('w-full bg-white/10 text-white')

                # Node filter container (shows when competitor_urls is selected)
                ui_refs['node_filter_container'] = ui.column().classes('gap-2 flex-1')

        # Statistics
        ui_refs['stats_container'] = ui.column().classes('w-full mb-6')

        # Quick Insights (only show when table is selected)
        ui_refs['insights_container'] = ui.column().classes('w-full mb-6')

        # Main content area - split into data and metadata
        with ui.row().classes('gap-6 w-full'):
            # Data view (left side, larger)
            with ui.column().classes('gap-4 flex-1'):
                section_title('Table Data', icon='table_chart', classes='mb-3')

                ui_refs['data_container'] = ui.column().classes('w-full')

                # Pagination controls
                with glass_card(classes='mt-4'):
                    with ui.row().classes('gap-4 items-center justify-between w-full'):
                        ui.button('Previous', icon='navigate_before', on_click=prev_page).props(
                            'flat' if state['offset'] == 0 else ''
                        ).classes('text-white')

                        current_page = (state['offset'] // state['limit']) + 1
                        ui.label(f"Page {current_page}").classes('text-white')

                        ui.button('Next', icon='navigate_next', on_click=next_page).classes('text-white')

            # Metadata view (right side, smaller)
            with ui.column().classes('gap-4 w-96'):
                ui_refs['metadata_container'] = ui.column().classes('w-full')

        # Initialize: load tables for default schema
        table_names = load_available_tables('public')
        if ui_refs['table_selector']:
            ui_refs['table_selector'].options = table_names
            ui_refs['table_selector'].update()

        # Auto-refresh timer (every 30 seconds)
        def auto_refresh():
            if state['selected_table']:
                load_table_data()
                refresh_view()

        ui.timer(30.0, auto_refresh)


def show():
    """Show the database viewer page"""
    create_page()

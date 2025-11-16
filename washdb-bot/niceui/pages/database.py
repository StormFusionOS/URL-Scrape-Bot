"""
Database page - view and export scraped data with AG Grid.
"""

import csv
import tempfile
from datetime import datetime
from nicegui import ui, run, app
from ..backend_facade import backend


# Global state for database page
class DatabaseState:
    def __init__(self):
        self.grid = None
        self.search_text = ""
        self.row_count_label = None
        self.companies = []
        self.loading = False


database_state = DatabaseState()


async def load_companies(search_text=""):
    """Load companies from database."""
    if database_state.loading:
        return

    database_state.loading = True
    database_state.search_text = search_text

    try:
        # Fetch companies in I/O bound thread
        companies = await run.io_bound(
            backend.fetch_companies,
            search_text if search_text else None,
            250000
        )

        database_state.companies = companies

        # Update grid
        if database_state.grid:
            database_state.grid.options['rowData'] = companies
            database_state.grid.update()

        # Update row count
        if database_state.row_count_label:
            database_state.row_count_label.text = f'{len(companies)} rows'

        ui.notify(f'Loaded {len(companies)} companies', type='info', timeout=2000)

    except Exception as e:
        ui.notify(f'Error loading data: {str(e)}', type='negative')
        database_state.companies = []

    finally:
        database_state.loading = False


async def reload_data():
    """Reload data from database."""
    ui.notify('Reloading data...', type='info')
    await load_companies(database_state.search_text)


async def export_selected():
    """Export selected rows to CSV."""
    if not database_state.grid:
        ui.notify('Grid not initialized', type='warning')
        return

    # Get selected rows
    selected = await database_state.grid.get_selected_rows()

    if not selected:
        ui.notify('No rows selected. Please select rows to export.', type='warning')
        return

    try:
        # Create temporary CSV file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            delete=False,
            suffix='.csv',
            newline='',
            encoding='utf-8'
        )

        # Write CSV
        fieldnames = ['Name', 'Website', 'Phone', 'Email', 'Services', 'Service Area', 'Address', 'Source', 'Last Updated']
        writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
        writer.writeheader()

        for row in selected:
            writer.writerow({
                'Name': row.get('name', ''),
                'Website': row.get('website', ''),
                'Phone': row.get('phone', ''),
                'Email': row.get('email', ''),
                'Services': row.get('services', ''),
                'Service Area': row.get('service_area', ''),
                'Address': row.get('address', ''),
                'Source': row.get('source', ''),
                'Last Updated': row.get('last_updated', '')
            })

        temp_file.close()

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'companies_export_{timestamp}.csv'

        # Trigger download
        ui.download(temp_file.name, filename)
        ui.notify(f'Exported {len(selected)} rows to {filename}', type='positive', timeout=3000)

    except Exception as e:
        ui.notify(f'Export error: {str(e)}', type='negative')


async def open_website():
    """Open website of selected row."""
    selected = await database_state.grid.get_selected_rows()

    if not selected:
        ui.notify('Please select a row', type='warning')
        return

    if len(selected) > 1:
        ui.notify('Please select only one row', type='warning')
        return

    website = selected[0].get('website')
    if website:
        ui.run_javascript(f'window.open("{website}", "_blank")')
        ui.notify(f'Opening {website}', type='info', timeout=2000)
    else:
        ui.notify('No website URL for this company', type='warning')


async def copy_email():
    """Copy email of selected row to clipboard."""
    selected = await database_state.grid.get_selected_rows()

    if not selected:
        ui.notify('Please select a row', type='warning')
        return

    if len(selected) > 1:
        ui.notify('Please select only one row', type='warning')
        return

    email = selected[0].get('email')
    if email:
        escaped_email = email.replace('"', '\\"').replace("'", "\\'")
        ui.run_javascript(f'navigator.clipboard.writeText("{escaped_email}")')
        ui.notify(f'Copied email: {email}', type='positive', timeout=2000)
    else:
        ui.notify('No email for this company', type='warning')


async def rescrape_selected():
    """Rescrape selected companies."""
    selected = await database_state.grid.get_selected_rows()

    if not selected:
        ui.notify('Please select rows to rescrape', type='warning')
        return

    ui.notify(f'Rescraping {len(selected)} companies...', type='info')

    # TODO: Implement batch rescraping
    # For now, just show a message
    websites = [row.get('website') for row in selected if row.get('website')]
    ui.notify(
        f'Would rescrape {len(websites)} websites (feature coming soon)',
        type='info',
        timeout=3000
    )


def show_clear_database_dialog():
    """Show confirmation dialog for clearing database."""
    with ui.dialog() as dialog, ui.card():
        ui.label('Clear Database?').classes('text-2xl font-bold mb-4')
        ui.label(
            'This will DELETE ALL companies from the database. This action cannot be undone!'
        ).classes('text-red-400 mb-4')

        async def confirm_clear():
            """Confirm and clear database."""
            dialog.close()
            await clear_database()

        with ui.row().classes('gap-2'):
            ui.button(
                'Cancel',
                color='secondary',
                on_click=lambda: dialog.close()
            ).props('outline')

            ui.button(
                'Delete All Companies',
                color='negative',
                on_click=confirm_clear
            )

    dialog.open()


async def clear_database():
    """Clear all companies from the database."""
    ui.notify('Clearing database...', type='info')

    try:
        # Run in I/O bound thread
        result = await run.io_bound(backend.clear_database)

        if result.get('success'):
            ui.notify(
                f'Database cleared: {result.get("deleted_count")} companies deleted',
                type='positive',
                timeout=5000
            )
            # Reload the grid
            await load_companies()
        else:
            ui.notify(
                f'Error clearing database: {result.get("message")}',
                type='negative',
                timeout=5000
            )

    except Exception as e:
        ui.notify(f'Error: {str(e)}', type='negative')


def database_page():
    """Render database page."""
    ui.label('Database Browser').classes('text-3xl font-bold mb-4')

    ui.label(
        'View, search, and export company data from the database.'
    ).classes('text-gray-400 mb-6')

    # Top bar with search and actions
    with ui.card().classes('w-full mb-4'):
        with ui.row().classes('w-full items-center gap-4'):
            # Search box (debounced)
            search_input = ui.input(
                'Search',
                placeholder='Search by name, domain, or website...'
            ).classes('flex-1').props('outlined clearable')

            # Debounced search handler
            search_input.on(
                'update:model-value',
                lambda e: load_companies(e.value),
                throttle=0.5  # 500ms debounce
            )

            # Row count
            database_state.row_count_label = ui.label('0 rows').classes('text-sm text-gray-400 whitespace-nowrap')

            # Reload button
            ui.button(
                'Reload',
                icon='refresh',
                color='primary',
                on_click=lambda: reload_data()
            ).props('outline')

            # Export button
            ui.button(
                'Export Selected',
                icon='download',
                color='positive',
                on_click=lambda: export_selected()
            ).props('outline')

            # Clear database button (for testing)
            ui.button(
                'Clear Database',
                icon='delete_forever',
                color='negative',
                on_click=show_clear_database_dialog
            ).props('outline')

    # Row actions toolbar
    with ui.card().classes('w-full mb-4'):
        ui.label('Row Actions').classes('text-sm font-semibold mb-2 text-gray-400')

        with ui.row().classes('gap-2'):
            ui.button(
                'Open Website',
                icon='open_in_new',
                on_click=lambda: open_website()
            ).props('outline size=sm')

            ui.button(
                'Copy Email',
                icon='content_copy',
                on_click=lambda: copy_email()
            ).props('outline size=sm')

            ui.button(
                'Rescrape Selected',
                icon='refresh',
                on_click=lambda: rescrape_selected()
            ).props('outline size=sm')

        ui.label(
            'Select a row from the table to use these actions'
        ).classes('text-xs text-gray-500 mt-1')

    # AG Grid
    with ui.card().classes('w-full'):
        ui.label('Companies').classes('text-xl font-bold mb-4')

        # AG Grid options
        grid_options = {
            'columnDefs': [
                {
                    'headerName': 'Name',
                    'field': 'name',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'flex': 1,
                    'minWidth': 150,
                },
                {
                    'headerName': 'Website',
                    'field': 'website',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'flex': 1,
                    'minWidth': 200,
                },
                {
                    'headerName': 'Phone',
                    'field': 'phone',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'width': 140,
                },
                {
                    'headerName': 'Email',
                    'field': 'email',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'flex': 1,
                    'minWidth': 180,
                },
                {
                    'headerName': 'Services',
                    'field': 'services',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'flex': 1,
                    'minWidth': 200,
                    'cellStyle': {'whiteSpace': 'normal', 'lineHeight': '1.4'},
                },
                {
                    'headerName': 'Service Area',
                    'field': 'service_area',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'width': 150,
                },
                {
                    'headerName': 'Address',
                    'field': 'address',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'flex': 1,
                    'minWidth': 200,
                },
                {
                    'headerName': 'Source',
                    'field': 'source',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'width': 120,
                },
                {
                    'headerName': 'Last Updated',
                    'field': 'last_updated',
                    'sortable': True,
                    'filter': True,
                    'resizable': True,
                    'width': 180,
                },
            ],
            'rowData': [],
            'rowSelection': 'multiple',
            'animateRows': True,
            'pagination': True,
            'paginationPageSize': 50,
            'defaultColDef': {
                'sortable': True,
                'filter': True,
                'resizable': True,
            },
            'enableRangeSelection': True,
            'enableCellTextSelection': True,
            'ensureDomOrder': True,
        }

        # Create AG Grid
        database_state.grid = ui.aggrid(grid_options).classes('w-full h-[600px]')

    # Instructions
    with ui.expansion('How to Use', icon='help_outline').classes('w-full mt-4'):
        with ui.card().classes('w-full'):
            ui.label('Database Browser Features:').classes('font-semibold mb-3')

            with ui.column().classes('gap-2'):
                ui.label('🔍 Search:')
                with ui.column().classes('ml-6 gap-1'):
                    ui.label('• Type in the search box to filter by name, domain, or website').classes('text-sm')
                    ui.label('• Search is debounced (500ms) for smooth performance').classes('text-sm')

                ui.label('📊 Grid Features:')
                with ui.column().classes('ml-6 gap-1'):
                    ui.label('• Click column headers to sort').classes('text-sm')
                    ui.label('• Use column filters for advanced filtering').classes('text-sm')
                    ui.label('• Drag column borders to resize').classes('text-sm')
                    ui.label('• Select multiple rows by holding Ctrl/Cmd and clicking').classes('text-sm')
                    ui.label('• Copy cell contents with Ctrl+C / Cmd+C').classes('text-sm')

                ui.label('⚡ Actions:')
                with ui.column().classes('ml-6 gap-1'):
                    ui.label('• Reload: Refresh data from database').classes('text-sm')
                    ui.label('• Export Selected: Download selected rows as CSV').classes('text-sm')
                    ui.label('• Open Website: Open company website in new tab (single selection)').classes('text-sm')
                    ui.label('• Copy Email: Copy email to clipboard (single selection)').classes('text-sm')
                    ui.label('• Rescrape Selected: Re-scrape selected companies').classes('text-sm')

            ui.separator().classes('my-3')

            ui.label('💡 Tips:').classes('font-semibold mb-2')
            with ui.column().classes('gap-1'):
                ui.label('• The grid loads up to 250,000 rows by default').classes('text-sm text-gray-400')
                ui.label('• Use search to narrow down results before exporting').classes('text-sm text-gray-400')
                ui.label('• Select all rows with Ctrl+A / Cmd+A in the grid').classes('text-sm text-gray-400')
                ui.label('• Export creates a timestamped CSV file').classes('text-sm text-gray-400')

    # Load initial data on page creation
    async def initial_load():
        await load_companies()
    ui.timer(0.1, initial_load, once=True)

    # Listen for scrape complete events to auto-refresh
    async def check_refresh():
        """Check if scrape completed and refresh if needed."""
        if app.storage.general.get('scrape_complete'):
            # Clear the flag
            del app.storage.general['scrape_complete']
            # Reload data
            await load_companies(database_state.search_text)

    ui.timer(2.0, check_refresh)  # Check every 2 seconds

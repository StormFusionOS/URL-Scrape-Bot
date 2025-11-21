"""
Local Competitors Page

Manage local competitor URLs for SEO tracking.
- Manual URL entry
- CSV bulk upload
- View and manage existing competitors
"""

import csv
import io
from datetime import datetime
from typing import List, Dict, Any
from urllib.parse import urlparse
from nicegui import ui, events

from ..theme import COLORS

# Try to import database and competitor modules
try:
    from db.save_discoveries import create_session
    from sqlalchemy import text
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    from seo_intelligence.scrapers.competitor_crawler import get_competitor_crawler
    CRAWLER_AVAILABLE = True
except ImportError:
    CRAWLER_AVAILABLE = False


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    parsed = urlparse(url)
    return parsed.netloc.lower().replace('www.', '')


def get_competitors() -> List[Dict[str, Any]]:
    """Get existing competitors from database."""
    if not DB_AVAILABLE:
        return []

    try:
        session = create_session()
        result = session.execute(text("""
            SELECT competitor_id, domain, name, website_url, business_type,
                   location, is_active, discovered_at, last_crawled_at
            FROM competitors
            ORDER BY competitor_id DESC
            LIMIT 100
        """))
        rows = result.fetchall()
        session.close()

        competitors = []
        for row in rows:
            competitors.append({
                'id': row[0],
                'domain': row[1],
                'name': row[2],
                'website_url': row[3],
                'business_type': row[4],
                'location': row[5],
                'is_active': row[6],
                'discovered_at': row[7].strftime('%Y-%m-%d %H:%M') if row[7] else '',
                'last_crawled': row[8].strftime('%Y-%m-%d %H:%M') if row[8] else 'Never',
            })
        return competitors
    except Exception as e:
        print(f"Error fetching competitors: {e}")
        return []


def add_competitor(
    domain: str,
    name: str = None,
    website_url: str = None,
    business_type: str = 'local',
    location: str = None,
) -> bool:
    """Add a competitor to the database."""
    if not DB_AVAILABLE:
        return False

    try:
        session = create_session()

        # Check if exists
        result = session.execute(
            text("SELECT competitor_id FROM competitors WHERE domain = :domain"),
            {"domain": domain}
        )
        if result.fetchone():
            session.close()
            return False  # Already exists

        # Insert new competitor
        session.execute(
            text("""
                INSERT INTO competitors (domain, name, website_url, business_type, location, is_active)
                VALUES (:domain, :name, :website_url, :business_type, :location, TRUE)
            """),
            {
                "domain": domain,
                "name": name or domain,
                "website_url": website_url or f"https://{domain}",
                "business_type": business_type,
                "location": location,
            }
        )
        session.commit()
        session.close()
        return True
    except Exception as e:
        print(f"Error adding competitor: {e}")
        return False


def delete_competitor(competitor_id: int) -> bool:
    """Delete a competitor from the database."""
    if not DB_AVAILABLE:
        return False

    try:
        session = create_session()
        session.execute(
            text("DELETE FROM competitors WHERE competitor_id = :id"),
            {"id": competitor_id}
        )
        session.commit()
        session.close()
        return True
    except Exception as e:
        print(f"Error deleting competitor: {e}")
        return False


def local_competitors_page():
    """Local Competitors management page."""

    # State
    competitors_container = None
    upload_log = []

    def refresh_competitors():
        """Refresh the competitors list."""
        if competitors_container:
            competitors_container.clear()
            with competitors_container:
                create_competitors_table()
        ui.notify('Refreshed', type='info', position='bottom-right')

    def create_competitors_table():
        """Create the competitors table."""
        competitors = get_competitors()

        if not competitors:
            ui.label('No competitors added yet').classes('text-gray-400 py-4')
            return

        columns = [
            {'name': 'domain', 'label': 'Domain', 'field': 'domain', 'align': 'left'},
            {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left'},
            {'name': 'type', 'label': 'Type', 'field': 'business_type', 'align': 'center'},
            {'name': 'location', 'label': 'Location', 'field': 'location', 'align': 'left'},
            {'name': 'crawled', 'label': 'Last Crawled', 'field': 'last_crawled', 'align': 'center'},
            {'name': 'active', 'label': 'Active', 'field': 'is_active', 'align': 'center'},
        ]

        rows = []
        for c in competitors:
            rows.append({
                'id': c['id'],
                'domain': c['domain'],
                'name': c['name'] or c['domain'],
                'business_type': c['business_type'] or 'local',
                'location': c['location'] or '-',
                'last_crawled': c['last_crawled'],
                'is_active': 'Yes' if c['is_active'] else 'No',
            })

        table = ui.table(
            columns=columns,
            rows=rows,
            row_key='id',
            selection='multiple',
        ).classes('w-full')

        def delete_selected():
            if not table.selected:
                ui.notify('Select competitors to delete', type='warning')
                return
            count = 0
            for row in table.selected:
                if delete_competitor(row['id']):
                    count += 1
            ui.notify(f'Deleted {count} competitors', type='positive')
            refresh_competitors()

        with ui.row().classes('mt-2 gap-2'):
            ui.button('Delete Selected', icon='delete', on_click=delete_selected).classes(
                'bg-red-600 hover:bg-red-700'
            )

    def add_single_competitor():
        """Add a single competitor from input fields."""
        url = url_input.value.strip()
        name = name_input.value.strip()
        location = location_input.value.strip()

        if not url:
            ui.notify('URL is required', type='warning')
            return

        domain = extract_domain(url)
        if not domain:
            ui.notify('Invalid URL', type='warning')
            return

        website_url = url if url.startswith('http') else f'https://{url}'

        if add_competitor(domain, name or None, website_url, 'local', location or None):
            ui.notify(f'Added: {domain}', type='positive')
            url_input.value = ''
            name_input.value = ''
            location_input.value = ''
            refresh_competitors()
        else:
            ui.notify(f'{domain} already exists', type='warning')

    async def handle_csv_upload(e):
        """Handle CSV file upload."""
        try:
            # Debug: print event attributes
            print(f"Upload event type: {type(e)}")
            print(f"Upload event attrs: {dir(e)}")

            # NiceGUI upload - try multiple ways to get content
            content = None

            # Method 1: Direct content attribute (SpooledTemporaryFile)
            if hasattr(e, 'content') and e.content is not None:
                e.content.seek(0)  # Reset file pointer
                raw = e.content.read()
                content = raw.decode('utf-8') if isinstance(raw, bytes) else raw
                print(f"Method 1: Got {len(content)} chars")

            # Method 2: Check for 'name' attribute indicating UploadEventArguments
            elif hasattr(e, 'name'):
                print(f"File name: {e.name}")
                # The content should be in e.content
                if hasattr(e, 'content'):
                    e.content.seek(0)
                    raw = e.content.read()
                    content = raw.decode('utf-8') if isinstance(raw, bytes) else raw

            if not content:
                ui.notify('Could not read file content', type='negative')
                print(f"Failed to read content. Event: {e}")
                return

            reader = csv.DictReader(io.StringIO(content))
            rows_list = list(reader)
            print(f"Parsed {len(rows_list)} rows from CSV")

            added = 0
            skipped = 0
            errors = 0

            for row in rows_list:
                # Support various column names
                url = row.get('url') or row.get('URL') or row.get('website') or row.get('Website') or ''
                name = row.get('name') or row.get('Name') or row.get('business_name') or row.get('Business_Name') or ''
                location = row.get('location') or row.get('Location') or row.get('city') or row.get('City') or ''
                industry = row.get('industry') or row.get('Industry') or row.get('business_type') or 'local'

                if not url:
                    errors += 1
                    continue

                domain = extract_domain(url)
                if not domain:
                    errors += 1
                    continue

                website_url = url if url.startswith('http') else f'https://{url}'

                if add_competitor(domain, name or None, website_url, industry, location or None):
                    added += 1
                else:
                    skipped += 1

            ui.notify(
                f'CSV Import: {added} added, {skipped} duplicates, {errors} errors',
                type='positive' if added > 0 else 'warning'
            )
            refresh_competitors()

        except Exception as ex:
            ui.notify(f'CSV Error: {str(ex)}', type='negative')

    with ui.column().classes('w-full max-w-6xl mx-auto p-4 gap-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-2'):
            ui.label('Local Competitors').classes('text-3xl font-bold text-white')
            ui.button('Refresh', icon='refresh', on_click=refresh_competitors).classes(
                'bg-purple-600 hover:bg-purple-700'
            )

        ui.label('Manage local competitor URLs for SEO tracking').classes('text-gray-400 mb-4')

        # Add competitor section
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
            ui.label('Add Competitor').classes('text-xl font-bold text-white mb-4')

            with ui.row().classes('w-full gap-4 items-end flex-wrap'):
                url_input = ui.input(
                    label='Competitor URL *',
                    placeholder='https://competitor.com'
                ).classes('flex-1 min-w-64')

                name_input = ui.input(
                    label='Business Name',
                    placeholder='Optional'
                ).classes('w-48')

                location_input = ui.input(
                    label='Location',
                    placeholder='City, State'
                ).classes('w-48')

                ui.button('Add', icon='add', on_click=add_single_competitor).classes(
                    'bg-green-600 hover:bg-green-700'
                )

        # CSV Upload section
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
            ui.label('Bulk Import (CSV)').classes('text-xl font-bold text-white mb-2')
            ui.label('Upload a CSV file with columns: url, name, location').classes('text-gray-400 text-sm mb-4')

            with ui.row().classes('gap-4 items-center'):
                ui.upload(
                    label='Choose CSV File',
                    on_upload=handle_csv_upload,
                    auto_upload=True,
                ).props('accept=".csv"').classes('max-w-xs')

                with ui.column().classes('text-sm text-gray-400'):
                    ui.label('Expected columns:')
                    ui.label('- url (required): Competitor website URL').classes('text-xs')
                    ui.label('- name (optional): Business name').classes('text-xs')
                    ui.label('- location (optional): City, State').classes('text-xs')

        # Existing competitors section
        with ui.card().classes('p-4 bg-gray-800 rounded-lg w-full'):
            with ui.row().classes('w-full items-center justify-between mb-4'):
                ui.label('Existing Competitors').classes('text-xl font-bold text-white')
                competitors = get_competitors()
                ui.badge(f'{len(competitors)} total', color='blue')

            competitors_container = ui.element('div').classes('w-full')
            with competitors_container:
                create_competitors_table()

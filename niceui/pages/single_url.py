"""
Single URL scraping page - scrape one URL at a time with detailed results.
"""

from nicegui import ui, run
from ..backend_facade import backend


# Global state for single URL scraping
class SingleUrlState:
    def __init__(self):
        self.scraping = False
        self.current_result = None


single_url_state = SingleUrlState()


async def scrape_url(url_input, result_card, scrape_button, upsert_button):
    """Scrape a single URL and display results."""
    url = url_input.value.strip()

    if not url:
        ui.notify('Please enter a URL', type='warning')
        return

    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        url_input.value = url

    single_url_state.scraping = True
    scrape_button.disable()
    upsert_button.disable()

    ui.notify(f'Scraping {url}...', type='info')

    try:
        # Run scrape in I/O bound thread (preview only, no DB save)
        result = await run.io_bound(backend.scrape_one_preview, url)

        # Store result
        single_url_state.current_result = result
        single_url_state.scraping = False

        # Update result card
        display_result(result, result_card, upsert_button)

        if result.get('status') == 'success':
            ui.notify(f'Successfully scraped {result.get("domain")}', type='positive', timeout=3000)
        else:
            ui.notify(f'Scraping failed: {result.get("error")}', type='negative')

    except Exception as e:
        ui.notify(f'Error: {str(e)}', type='negative')
        single_url_state.current_result = None
        single_url_state.scraping = False

        # Show error in result card
        result_card.clear()
        with result_card:
            ui.label('Scraping Error').classes('text-xl font-bold text-red-500 mb-2')
            ui.label(f'Error: {str(e)}').classes('text-sm text-red-400')

    finally:
        scrape_button.enable()


def display_result(result, result_card, upsert_button):
    """Display scrape results in the result card."""
    result_card.clear()

    with result_card:
        if result.get('status') == 'error':
            # Error state
            ui.label('Scraping Failed').classes('text-xl font-bold text-red-500 mb-4')
            ui.label(f"Error: {result.get('error')}").classes('text-sm text-red-400')
            upsert_button.disable()
            return

        # Success - enable upsert button
        upsert_button.enable()

        # Header with domain and name
        domain = result.get('domain', 'Unknown')
        name = result.get('name')

        ui.label('Scrape Results').classes('text-xl font-bold mb-4 text-green-500')

        with ui.row().classes('w-full items-center justify-between mb-4'):
            ui.label(name or domain).classes('text-2xl font-bold')

            # Open website link
            canonical_url = result.get('canonical_url') or result.get('url')
            if canonical_url:
                ui.link(
                    'Open Website',
                    canonical_url,
                    new_tab=True
                ).props('icon=open_in_new').classes('text-blue-400')

        ui.separator().classes('mb-4')

        # Grid layout for fields
        with ui.grid(columns=1).classes('w-full gap-3'):

            # Domain
            with ui.row().classes('w-full items-center gap-2'):
                ui.label('Domain:').classes('font-semibold text-gray-400 min-w-32')
                ui.label(domain).classes('text-base')

            # Name
            if name:
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label('Business Name:').classes('font-semibold text-gray-400 min-w-32')
                    ui.label(name).classes('text-base')

            # Email(s) with copy button
            emails = result.get('emails', [])
            with ui.row().classes('w-full items-center gap-2'):
                ui.label('Email(s):').classes('font-semibold text-gray-400 min-w-32')
                if emails:
                    with ui.row().classes('gap-2 items-center flex-1'):
                        email_text = ', '.join(emails)
                        ui.label(email_text).classes('text-base')
                        ui.button(
                            icon='content_copy',
                            on_click=lambda et=email_text: copy_to_clipboard(et, 'Email(s) copied to clipboard')
                        ).props('flat dense size=sm').classes('text-blue-400').tooltip('Copy emails')
                else:
                    ui.label('Not found').classes('text-base text-gray-500 italic')

            # Phone(s) with copy button
            phones = result.get('phones', [])
            with ui.row().classes('w-full items-center gap-2'):
                ui.label('Phone(s):').classes('font-semibold text-gray-400 min-w-32')
                if phones:
                    with ui.row().classes('gap-2 items-center flex-1'):
                        phone_text = ', '.join(phones)
                        ui.label(phone_text).classes('text-base')
                        ui.button(
                            icon='content_copy',
                            on_click=lambda pt=phone_text: copy_to_clipboard(pt, 'Phone(s) copied to clipboard')
                        ).props('flat dense size=sm').classes('text-blue-400').tooltip('Copy phones')
                else:
                    ui.label('Not found').classes('text-base text-gray-500 italic')

            # Services
            services = result.get('services')
            if services:
                with ui.column().classes('w-full gap-1'):
                    ui.label('Services:').classes('font-semibold text-gray-400')
                    ui.label(services).classes('text-base')

            # Service Area
            service_area = result.get('service_area')
            if service_area:
                with ui.column().classes('w-full gap-1'):
                    ui.label('Service Area:').classes('font-semibold text-gray-400')
                    ui.label(service_area).classes('text-base')

            # Address
            address = result.get('address')
            if address:
                with ui.column().classes('w-full gap-1'):
                    ui.label('Address:').classes('font-semibold text-gray-400')
                    ui.label(address).classes('text-base')


def copy_to_clipboard(text, message):
    """Copy text to clipboard and show notification."""
    # Escape quotes in text for JavaScript
    escaped_text = text.replace('"', '\\"').replace("'", "\\'")
    ui.run_javascript(f'navigator.clipboard.writeText("{escaped_text}")')
    ui.notify(message, type='positive', timeout=2000)


async def upsert_to_db():
    """Upsert the current result to the database."""
    if not single_url_state.current_result:
        ui.notify('No scrape result to save', type='warning')
        return

    if single_url_state.current_result.get('status') == 'error':
        ui.notify('Cannot save failed scrape result', type='warning')
        return

    ui.notify('Saving to database...', type='info')

    try:
        # Run upsert in I/O bound thread
        result = await run.io_bound(
            backend.upsert_from_scrape,
            single_url_state.current_result
        )

        if result.get('success'):
            ui.notify(result.get('message'), type='positive', timeout=4000)
        else:
            ui.notify(result.get('message'), type='negative', timeout=5000)

    except Exception as e:
        ui.notify(f'Upsert error: {str(e)}', type='negative')


def single_url_page():
    """Render single URL scraping page."""
    ui.label('Single URL Scraper').classes('text-3xl font-bold mb-4')

    ui.label(
        'Scrape a single business website to preview extracted data before saving to the database.'
    ).classes('text-gray-400 mb-6')

    # Input card
    with ui.card().classes('w-full mb-4'):
        ui.label('URL Input').classes('text-xl font-bold mb-4')

        # URL input
        url_input = ui.input(
            'URL',
            placeholder='https://example.com'
        ).classes('w-full mb-2').props('outlined')

        ui.label(
            'Enter a business website URL (protocol optional - defaults to https://)'
        ).classes('text-sm text-gray-400 mb-4')

        # Buttons
        with ui.row().classes('gap-2'):
            scrape_button = ui.button(
                'Scrape Now',
                icon='search',
                color='primary',
                on_click=lambda: scrape_url(
                    url_input,
                    result_card,
                    scrape_button,
                    upsert_button
                )
            ).props('size=lg')

            upsert_button = ui.button(
                'Upsert to DB',
                icon='save',
                color='positive',
                on_click=lambda: upsert_to_db()
            ).props('size=lg')
            upsert_button.disable()

    # Result card
    result_card = ui.card().classes('w-full mb-4 p-6')
    with result_card:
        with ui.column().classes('items-center justify-center p-8'):
            ui.icon('search', size='xl').classes('text-gray-600 mb-2')
            ui.label('Ready to scrape').classes('text-lg text-gray-400 italic')
            ui.label('Enter a URL above and click "Scrape Now"').classes('text-sm text-gray-500')

    # Instructions
    with ui.expansion('How to Use', icon='help_outline').classes('w-full mt-4'):
        with ui.card().classes('w-full'):
            ui.label('Step-by-step guide:').classes('font-semibold mb-3')

            with ui.column().classes('gap-2'):
                ui.label('1. Enter a business website URL (e.g., https://example.com)')
                ui.label('2. Click "Scrape Now" to extract business information from the website')
                ui.label('3. Review the extracted details:')

                with ui.column().classes('ml-6 gap-1'):
                    ui.label('• Business name').classes('text-sm')
                    ui.label('• Domain').classes('text-sm')
                    ui.label('• Contact information (emails and phones)').classes('text-sm')
                    ui.label('• Services offered').classes('text-sm')
                    ui.label('• Service area / location').classes('text-sm')
                    ui.label('• Physical address').classes('text-sm')

                ui.label('4. Use the copy buttons to quickly copy email addresses or phone numbers')
                ui.label('5. Click "Upsert to DB" to save the information to your database')

            ui.separator().classes('my-3')

            ui.label('💡 Tips:').classes('font-semibold mb-2')
            with ui.column().classes('gap-1'):
                ui.label('• The scraper automatically visits common subpages (About, Contact, Services) to find more information').classes('text-sm text-gray-400')
                ui.label('• Email addresses from the business domain are prioritized').classes('text-sm text-gray-400')
                ui.label('• Multiple emails/phones are shown if found on the website').classes('text-sm text-gray-400')
                ui.label('• Upserting will update existing records or create new ones based on the domain').classes('text-sm text-gray-400')

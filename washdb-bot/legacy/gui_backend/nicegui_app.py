#!/usr/bin/env python3
"""
⚠️ DEPRECATED: Washdb-Bot NiceGUI Dashboard (Legacy)

This is an old prototype of the NiceGUI interface.
It has been replaced by the production NiceGUI interface in niceui/.

Use instead:
    python -m niceui.main

This file is kept for reference only.
"""

# Exit immediately if run directly
if __name__ == '__main__':
    print("=" * 70)
    print("⚠️  DEPRECATED: gui_backend/nicegui_app.py")
    print("=" * 70)
    print()
    print("This is an old prototype. Use the production interface instead:")
    print()
    print("  cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
    print("  source venv/bin/activate")
    print("  python -m niceui.main")
    print()
    print("Or use: ./restart_dashboard.sh")
    print()
    print("=" * 70)
    import sys
    sys.exit(1)

# Original code (disabled for reference)
"""
ORIGINAL DOCSTRING:
Washdb-Bot NiceGUI Dashboard
Modern web interface for controlling and monitoring the washdb-bot scraper.

Port: 8080 (configurable)
Database: washdb PostgreSQL database
"""

from nicegui import ui, app
from datetime import datetime
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('../logs/nicegui_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Custom color theme (Purple theme)
COLORS = {
    'primary': '#7c3aed',      # Purple
    'secondary': '#6d28d9',    # Darker purple
    'accent': '#a78bfa',       # Lighter purple
    'dark': '#1e1b4b',         # Dark purple background
    'positive': '#10b981',     # Green for success
    'negative': '#ef4444',     # Red for errors
    'info': '#3b82f6',         # Blue for info
    'warning': '#f59e0b',      # Orange for warnings
}


def apply_custom_styles():
    """Apply custom CSS styles for the purple theme."""
    ui.add_head_html(f'''
        <style>
            :root {{
                --q-primary: {COLORS['primary']};
                --q-secondary: {COLORS['secondary']};
                --q-accent: {COLORS['accent']};
                --q-positive: {COLORS['positive']};
                --q-negative: {COLORS['negative']};
                --q-info: {COLORS['info']};
                --q-warning: {COLORS['warning']};
            }}

            .q-page {{
                background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
            }}

            .stat-card {{
                background: rgba(124, 58, 237, 0.1);
                border: 1px solid {COLORS['accent']};
                border-radius: 8px;
                padding: 16px;
            }}
        </style>
    ''')


@ui.page('/')
async def index():
    """Main dashboard page."""
    apply_custom_styles()

    with ui.header().classes('items-center justify-between').style(
        f'background-color: {COLORS["primary"]}; padding: 1rem;'
    ):
        ui.label('Washdb-Bot Dashboard').classes('text-2xl font-bold')
        ui.label(f'🟢 Online').classes('text-lg')

    with ui.column().classes('w-full p-4 gap-4'):
        # Welcome section
        with ui.card().classes('w-full'):
            ui.label('Welcome to Washdb-Bot').classes('text-3xl font-bold')
            ui.label(f'Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}').classes('text-gray-400')

        # Stats cards
        with ui.row().classes('w-full gap-4'):
            with ui.card().classes('flex-1 stat-card'):
                ui.label('Total URLs').classes('text-gray-400')
                ui.label('0').classes('text-4xl font-bold').style(f'color: {COLORS["accent"]}')

            with ui.card().classes('flex-1 stat-card'):
                ui.label('Scraped Today').classes('text-gray-400')
                ui.label('0').classes('text-4xl font-bold').style(f'color: {COLORS["accent"]}')

            with ui.card().classes('flex-1 stat-card'):
                ui.label('Active Jobs').classes('text-gray-400')
                ui.label('0').classes('text-4xl font-bold').style(f'color: {COLORS["accent"]}')

            with ui.card().classes('flex-1 stat-card'):
                ui.label('Success Rate').classes('text-gray-400')
                ui.label('100%').classes('text-4xl font-bold').style(f'color: {COLORS["positive"]}')

        # Control panel
        with ui.card().classes('w-full'):
            ui.label('Scraper Control').classes('text-2xl font-bold mb-4')

            with ui.row().classes('gap-2'):
                ui.button('Start Scraper', icon='play_arrow', color=COLORS['positive'])
                ui.button('Stop Scraper', icon='stop', color=COLORS['negative'])
                ui.button('Refresh Stats', icon='refresh', color=COLORS['info'])

        # Recent activity
        with ui.card().classes('w-full'):
            ui.label('Recent Activity').classes('text-2xl font-bold mb-4')

            with ui.column().classes('w-full gap-2'):
                ui.label('No recent activity').classes('text-gray-400 italic')

    # Footer
    with ui.footer().style(f'background-color: {COLORS["dark"]}; padding: 1rem;'):
        ui.label('Washdb-Bot v1.0.0 | Powered by NiceGUI').classes('text-gray-400')


@ui.page('/scraper')
async def scraper_page():
    """Scraper management page."""
    apply_custom_styles()

    with ui.header().classes('items-center justify-between').style(
        f'background-color: {COLORS["primary"]}; padding: 1rem;'
    ):
        ui.link('← Dashboard', '/').classes('text-white')
        ui.label('Scraper Management').classes('text-2xl font-bold')

    with ui.column().classes('w-full p-4 gap-4'):
        with ui.card().classes('w-full'):
            ui.label('Configure Scraper').classes('text-2xl font-bold mb-4')

            ui.input('Target URL', placeholder='https://example.com').classes('w-full')
            ui.number('Concurrent Workers', value=5, min=1, max=20).classes('w-full')
            ui.number('Request Delay (seconds)', value=1.0, step=0.1, min=0.1).classes('w-full')

            with ui.row().classes('gap-2 mt-4'):
                ui.button('Save Configuration', icon='save', color=COLORS['primary'])
                ui.button('Run Test', icon='bug_report', color=COLORS['info'])


@ui.page('/data')
async def data_page():
    """Data viewer page."""
    apply_custom_styles()

    with ui.header().classes('items-center justify-between').style(
        f'background-color: {COLORS["primary"]}; padding: 1rem;'
    ):
        ui.link('← Dashboard', '/').classes('text-white')
        ui.label('Scraped Data').classes('text-2xl font-bold')

    with ui.column().classes('w-full p-4 gap-4'):
        with ui.card().classes('w-full'):
            ui.label('Data Browser').classes('text-2xl font-bold mb-4')
            ui.label('Data table will be displayed here').classes('text-gray-400 italic')


def main():
    """Run the NiceGUI application."""
    logger.info("=" * 70)
    logger.info("Starting Washdb-Bot NiceGUI Dashboard")
    logger.info("=" * 70)

    # Enable dark mode
    ui.dark_mode().enable()

    # Run the app
    ui.run(
        title='Washdb-Bot Dashboard',
        port=8080,
        host='0.0.0.0',
        reload=True,
        show=False,
        dark=True
    )


if __name__ in {'__main__', '__mp_main__'}:
    main()

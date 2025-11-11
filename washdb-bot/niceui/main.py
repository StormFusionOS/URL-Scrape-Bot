#!/usr/bin/env python3
"""
Main entry point for NiceGUI dashboard.
Run with: python -m niceui.main
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from nicegui import ui, app
from niceui.theme import apply_theme
from niceui.layout import layout
from niceui.router import router
from niceui import pages


def register_pages():
    """Register all pages with the router."""
    router.register('dashboard', pages.dashboard_page)
    router.register('discover', pages.discover_page)
    router.register('database', pages.database_page)
    router.register('scheduler', pages.scheduler_page)
    router.register('logs', pages.logs_page)
    router.register('status', pages.status_page)
    router.register('settings', pages.settings_page)


def create_app():
    """Create and configure the NiceGUI application."""
    # Add static files directory
    static_dir = Path(__file__).parent / 'static'
    app.add_static_files('/static', str(static_dir))

    # Apply theme
    apply_theme()

    # Register all pages
    register_pages()

    # Setup layout
    content_area = layout.setup()

    # Load default page
    with content_area:
        pages.dashboard_page()


def run():
    """Run the application."""
    # Create the app
    create_app()

    # Print startup info
    print("=" * 70)
    print("Starting Washdb-Bot NiceGUI Dashboard")
    print("=" * 70)
    print("URL: http://127.0.0.1:8080")
    print("=" * 70)

    # Run with uvicorn-like settings
    ui.run(
        title='Washdb-Bot Dashboard',
        port=8080,
        host='127.0.0.1',
        reload=False,
        show=False,
        dark=True,
        binding_refresh_interval=0.1,
        favicon='niceui/static/favicon.svg'
    )


if __name__ == '__main__':
    run()

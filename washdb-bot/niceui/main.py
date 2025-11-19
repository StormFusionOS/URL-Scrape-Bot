#!/usr/bin/env python3
"""
Main entry point for NiceGUI dashboard.
Run with: python -m niceui.main
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from nicegui import ui, app
from niceui.theme import apply_theme
from niceui.layout import layout
from niceui.router import router
from niceui import pages

# Import SEO Intelligence services
from niceui.services.websocket_manager import get_websocket_manager
from niceui.services.job_monitor import get_job_monitor
from niceui.services.error_monitor import get_error_monitor
from niceui.services.scraper_process import initialize_scraper_manager

import logging

# Initialize logger for services
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def register_pages():
    """
    Register all dashboard pages with the router.

    Washbot Pages:
        - dashboard: Main overview with KPIs and stats
        - discover: YP crawler controls and telemetry
        - database: Company data browser with CSV export
        - scheduler: Scheduled job configuration
        - status: System status, health checks, and application logs (combined)
        - settings: Configuration management

    SEO Intelligence Pages:
        - seo_database: SEO scraper database viewer
        - seo_scraper: Run SEO scraper controls
        - seo_data: View scraped SEO data
        - washdb_sync: Washbot DB synchronization monitor
        - competitors: Local competitors management
    """
    # Washbot original pages
    router.register('dashboard', pages.dashboard_page)
    router.register('discover', pages.discover_page)
    router.register('database', pages.database_page)
    router.register('scheduler', pages.scheduler_page)
    router.register('logs', pages.logs_page)
    router.register('status', pages.status_page)
    router.register('settings', pages.settings_page)

    # SEO Intelligence pages
    router.register('seo_database', pages.seo_database_page)
    router.register('seo_scraper', pages.seo_scraper_page)
    router.register('seo_data', pages.seo_data_page)
    router.register('washdb_sync', pages.washdb_sync_page)
    router.register('competitors', pages.competitors_page)


def create_app():
    """
    Create and configure the NiceGUI application.

    Setup steps:
        1. Register static files directory
        2. Apply dark theme
        3. Register all page routes
        4. Setup main layout (navbar + content area)
        5. Load default dashboard page
    """
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


async def startup():
    """Initialize SEO Intelligence services on startup"""
    try:
        logger.info("Starting SEO Intelligence background services...")

        # Initialize scraper process manager
        ws_manager = get_websocket_manager()
        initialize_scraper_manager(ws_manager)
        logger.info("Scraper manager initialized")

        # Start job monitor (polls scraper database for job status)
        job_monitor = get_job_monitor(poll_interval=5.0)
        await job_monitor.start()
        logger.info("Job monitor started")

        # Start error monitor (polls scraper database for errors)
        error_monitor = get_error_monitor(poll_interval=10.0)
        await error_monitor.start()
        logger.info("Error monitor started")

        logger.info("SEO Intelligence services started successfully")
    except Exception as e:
        logger.error(f"Failed to start SEO Intelligence services: {e}", exc_info=True)
        logger.warning("Dashboard will continue without SEO Intelligence features")


def delayed_startup():
    """Run startup logic after app is fully initialized"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(startup())
    except Exception as e:
        logger.error(f"Failed to start background services: {e}", exc_info=True)


def run():
    """
    Run the NiceGUI dashboard application.

    Reads port and host from environment variables (NICEGUI_PORT, GUI_HOST).
    Default: http://127.0.0.1:8080
    """
    # Create the app
    create_app()

    # Mount Socket.IO for real-time updates
    try:
        ws_manager = get_websocket_manager()
        socketio_asgi_app = ws_manager.get_asgi_app()
        app.mount('/socket.io', socketio_asgi_app)
        logger.info("Socket.IO mounted at /socket.io")
    except Exception as e:
        logger.error(f"Failed to mount Socket.IO: {e}", exc_info=True)
        logger.warning("Real-time features will be unavailable")

    # Start background services after a short delay using timer
    ui.timer(2.0, delayed_startup, once=True)
    logger.info("Scheduled background services to start in 2 seconds")

    # Get configuration from environment
    port = int(os.getenv('NICEGUI_PORT', '8080'))
    host = os.getenv('GUI_HOST', '127.0.0.1')

    # Print startup info
    print("=" * 70)
    print("Starting Washdb-Bot NiceGUI Dashboard")
    print("=" * 70)
    print(f"URL: http://{host}:{port}")
    print(f"Log Directory: {Path(__file__).parent.parent / 'logs'}")
    print("=" * 70)

    # Run with uvicorn-like settings
    ui.run(
        title='Washdb-Bot Dashboard',
        port=port,
        host=host,
        reload=False,
        show=False,
        dark=True,
        binding_refresh_interval=0.1,
        favicon='niceui/static/favicon.svg'
    )


if __name__ == '__main__':
    run()

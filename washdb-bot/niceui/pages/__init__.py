"""
Pages for NiceGUI dashboard.
"""

# Washbot original pages
from .dashboard import dashboard_page
from .discover import discover_page
from .database import database_page
from .logs import logs_page
from .status import status_page
from .settings import settings_page
from .scheduler import scheduler_page

# SEO Intelligence pages (imported with aliases)
from .seo_database_viewer import create_page as seo_database_page
from .seo_run_scraper import create_page as seo_scraper_page
from .seo_scraped_data import create_page as seo_data_page
from .seo_washdb_monitor import create_page as washdb_sync_page
from .seo_local_competitors import create_page as competitors_page

__all__ = [
    # Original Washbot pages
    'dashboard_page',
    'discover_page',
    'database_page',
    'logs_page',
    'status_page',
    'settings_page',
    'scheduler_page',
    # SEO Intelligence pages
    'seo_database_page',
    'seo_scraper_page',
    'seo_data_page',
    'washdb_sync_page',
    'competitors_page',
]

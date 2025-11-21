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
from .seo_intelligence import seo_intelligence_page

__all__ = [
    'dashboard_page',
    'discover_page',
    'database_page',
    'logs_page',
    'status_page',
    'settings_page',
    'scheduler_page',
    'seo_intelligence_page',
]

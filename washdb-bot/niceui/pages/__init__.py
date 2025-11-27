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
from .diagnostics import diagnostics_page
from .run_history import run_history_page
from .seo_intelligence import seo_intelligence_page
from .seo_database import seo_database_page
from .seo_review_queue import seo_review_queue_page
from .local_competitors import local_competitors_page
from .dev_tools import dev_tools_page
from .testing import testing_page
from .scraper_review import scraper_review_page
from .yp_discover import yp_discover_page
from .verification import verification_page
from .seo_dashboard import seo_dashboard_page

__all__ = [
    'dashboard_page',
    'discover_page',
    'database_page',
    'logs_page',
    'status_page',
    'settings_page',
    'scheduler_page',
    'diagnostics_page',
    'run_history_page',
    'seo_intelligence_page',
    'seo_database_page',
    'seo_review_queue_page',
    'local_competitors_page',
    'dev_tools_page',
    'testing_page',
    'scraper_review_page',
    'yp_discover_page',
    'verification_page',
    'seo_dashboard_page',
]

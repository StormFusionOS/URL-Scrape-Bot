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
from .seo_database import seo_database_page
from .local_competitors import local_competitors_page
from .dev_tools import dev_tools_page
from .testing import testing_page
from .scraper_review import scraper_review_page
from .serp_runner import serp_runner_page
from .citation_runner import citation_runner_page
from .backlink_runner import backlink_runner_page

__all__ = [
    'dashboard_page',
    'discover_page',
    'database_page',
    'logs_page',
    'status_page',
    'settings_page',
    'scheduler_page',
    'seo_intelligence_page',
    'seo_database_page',
    'local_competitors_page',
    'dev_tools_page',
    'testing_page',
    'scraper_review_page',
    'serp_runner_page',
    'citation_runner_page',
    'backlink_runner_page',
]

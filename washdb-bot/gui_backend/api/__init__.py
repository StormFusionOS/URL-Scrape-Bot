"""
API routes package for Washdb-Bot GUI Backend.
"""

from .scraper_routes import scraper_bp
from .data_routes import data_bp
from .stats_routes import stats_bp

__all__ = ['scraper_bp', 'data_bp', 'stats_bp']

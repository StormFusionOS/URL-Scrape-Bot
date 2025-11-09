"""
Database module for washdb-bot.

This module handles:
- Database connection management
- SQLAlchemy models
- Database operations
"""

from db.models import Base, Company, canonicalize_url, domain_from_url

__version__ = "0.1.0"

__all__ = [
    "Base",
    "Company",
    "canonicalize_url",
    "domain_from_url",
]

"""
Database module for washdb-bot.

This module handles:
- Database connection management
- SQLAlchemy models
- Database operations
- Dual database support (washdb + scraper)
"""

from db.models import Base, Company, canonicalize_url, domain_from_url
from db.save_discoveries import (
    upsert_discovered,
    normalize_phone,
    normalize_email,
    create_session,
)
from db.update_details import (
    update_company_details,
    update_batch,
)
from db.database_manager import DatabaseManager, get_db_manager
from db.schema_inspector import get_schema_inspector

__version__ = "0.1.0"

__all__ = [
    "Base",
    "Company",
    "canonicalize_url",
    "domain_from_url",
    "upsert_discovered",
    "normalize_phone",
    "normalize_email",
    "create_session",
    "update_company_details",
    "update_batch",
    "DatabaseManager",
    "get_db_manager",
    "get_schema_inspector",
]

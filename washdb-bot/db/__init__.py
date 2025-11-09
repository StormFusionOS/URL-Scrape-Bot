"""
Database module for washdb-bot.

This module handles:
- Database connection management
- SQLAlchemy models
- Database operations
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
]

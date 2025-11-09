"""
Individual website scraper module for washdb-bot.

This module handles:
- Scraping individual business websites
- Extracting contact information
- Handling various website structures
"""

from scrape_site.site_parse import (
    parse_site_content,
    extract_company_name,
    extract_phones,
    extract_emails,
    extract_services,
    extract_service_area,
    extract_address,
    extract_reviews,
    extract_json_ld,
)

__version__ = "0.1.0"

__all__ = [
    "parse_site_content",
    "extract_company_name",
    "extract_phones",
    "extract_emails",
    "extract_services",
    "extract_service_area",
    "extract_address",
    "extract_reviews",
    "extract_json_ld",
]

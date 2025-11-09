"""
Database models for washdb-bot using SQLAlchemy 2.0 style.

Models:
- Company: Stores business/company information scraped from various sources
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse

import tldextract
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class Company(Base):
    """
    Company/Business model for storing scraped business information.

    Attributes:
        id: Primary key
        name: Business name
        website: Canonical URL (normalized, unique)
        domain: Domain extracted from website (e.g., 'example.com')
        phone: Contact phone number
        email: Contact email address
        services: Description of services offered
        service_area: Geographic service area
        address: Physical address
        source: Data source (e.g., 'YP', 'Manual')
        rating_yp: Yellow Pages rating
        rating_google: Google rating
        reviews_google: Number of Google reviews
        reviews_yp: Number of Yellow Pages reviews
        active: Whether the company is active
        created_at: Record creation timestamp
        last_updated: Last update timestamp
    """

    __tablename__ = "companies"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Core Information
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[str] = mapped_column(
        Text, unique=True, index=True, nullable=False, comment="Canonical URL (normalized)"
    )
    domain: Mapped[str] = mapped_column(
        Text, index=True, nullable=False, comment="Domain extracted via tldextract"
    )

    # Contact Information
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Business Details
    services: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    service_area: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Source and Ratings
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="e.g., 'YP' or 'Manual'"
    )
    rating_yp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating_google: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviews_google: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviews_yp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status and Timestamps
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of Company."""
        return f"<Company(id={self.id}, name='{self.name}', domain='{self.domain}')>"


# Helper Functions


def canonicalize_url(raw_url: str) -> str:
    """
    Canonicalize a URL by:
    - Ensuring it has a scheme (defaults to https://)
    - Removing fragments (#...)
    - Removing trailing slashes
    - Standardizing www. subdomain (removes www.)
    - Converting to lowercase

    Args:
        raw_url: Raw URL string to canonicalize

    Returns:
        Canonicalized URL string

    Examples:
        >>> canonicalize_url("example.com")
        'https://example.com'
        >>> canonicalize_url("http://www.example.com/")
        'http://example.com'
        >>> canonicalize_url("https://example.com/page#section")
        'https://example.com/page'
    """
    # Strip whitespace
    url = raw_url.strip()

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # Parse the URL
    parsed = urlparse(url)

    # Normalize the netloc (remove www.)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Normalize the path (remove trailing slash unless it's the root)
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")

    # Reconstruct URL without fragment and with normalized components
    canonical = urlunparse(
        (
            parsed.scheme,  # scheme
            netloc,  # netloc (domain)
            path,  # path
            parsed.params,  # params
            parsed.query,  # query
            "",  # fragment (removed)
        )
    )

    return canonical


def domain_from_url(url: str) -> str:
    """
    Extract the registered domain from a URL using tldextract.

    This extracts the domain + suffix (e.g., 'example.com' from 'https://www.example.com/path')
    without the subdomain.

    Args:
        url: URL string to extract domain from

    Returns:
        Domain string (e.g., 'example.com')

    Examples:
        >>> domain_from_url("https://www.example.com/path")
        'example.com'
        >>> domain_from_url("http://subdomain.example.co.uk")
        'example.co.uk'
    """
    # Extract domain components
    extracted = tldextract.extract(url)

    # Combine domain and suffix
    domain = f"{extracted.domain}.{extracted.suffix}"

    return domain.lower()

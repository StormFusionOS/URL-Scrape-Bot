"""
Database models for washdb-bot using SQLAlchemy 2.0 style.

Models:
- Company: Stores business/company information scraped from various sources
- ScheduledJob: Stores scheduled crawl/scrape jobs with cron schedules
- JobExecutionLog: Logs execution history of scheduled jobs
- CityRegistry: US cities dataset for city-first scraping
- YPTarget: Target list for Yellow Pages city-first crawling
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse

import tldextract
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
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
        source: Data source (e.g., 'YP', 'HA', 'Manual')
        rating_yp: Yellow Pages rating
        rating_google: Google rating
        reviews_google: Number of Google reviews
        reviews_yp: Number of Yellow Pages reviews
        rating_ha: HomeAdvisor rating
        reviews_ha: Number of HomeAdvisor reviews
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

    # HomeAdvisor ratings (added for HA integration)
    rating_ha: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviews_ha: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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


class HAStaging(Base):
    """
    HomeAdvisor staging table for pipeline workflow.

    Stores businesses discovered from HomeAdvisor (Phase 1) before URL finding (Phase 2).
    This table acts as a queue for the url_finder_worker to process.

    Attributes:
        id: Primary key
        name: Business name
        address: Full address (city, state, zip extracted from this)
        phone: Contact phone number
        profile_url: HomeAdvisor profile URL (unique identifier)
        rating_ha: HomeAdvisor rating
        reviews_ha: Number of HomeAdvisor reviews
        created_at: When business was discovered
        processed: Whether URL finding has been completed
        retry_count: Number of URL finding attempts
        next_retry_at: When to retry URL finding (exponential backoff)
        last_error: Error message from last URL finding attempt
    """

    __tablename__ = "ha_staging"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Business Information
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profile_url: Mapped[str] = mapped_column(
        Text, unique=True, index=True, nullable=False,
        comment="HomeAdvisor profile URL (unique identifier)"
    )

    # Ratings
    rating_ha: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviews_ha: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Pipeline Status
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
        comment="When business was discovered"
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Whether URL finding has been completed"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of URL finding attempts"
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When to retry URL finding (exponential backoff)"
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Error message from last URL finding attempt"
    )

    def __repr__(self) -> str:
        """String representation of HAStaging."""
        return f"<HAStaging(id={self.id}, name='{self.name}', processed={self.processed}, retry_count={self.retry_count})>"


class ScheduledJob(Base):
    """
    Scheduled crawl/scrape job model.

    Attributes:
        id: Primary key
        name: Human-readable job name
        description: Optional job description
        job_type: Type of job (e.g., 'yp_crawl', 'google_maps', 'detail_scrape')
        schedule_cron: Cron expression for scheduling
        config: JSON configuration for the job (search terms, locations, etc.)
        enabled: Whether the job is active
        priority: Job priority (high=1, medium=2, low=3)
        timeout_minutes: Maximum execution time before job is killed
        max_retries: Number of times to retry on failure
        last_run: Timestamp of last execution
        last_status: Status of last execution (success, failed, timeout, etc.)
        next_run: Scheduled next execution time
        total_runs: Total number of executions
        success_runs: Number of successful executions
        failed_runs: Number of failed executions
        created_at: Record creation timestamp
        created_by: User who created the job
        updated_at: Last update timestamp
    """

    __tablename__ = "scheduled_jobs"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Core Information
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="e.g., 'yp_crawl', 'google_maps', 'detail_scrape', 'db_maintenance'"
    )

    # Schedule Configuration
    schedule_cron: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Cron expression (e.g., '0 2 * * *' for daily at 2am)"
    )
    config: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="JSON configuration (search terms, locations, limits, etc.)"
    )

    # Job Control
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False,
        comment="1=high, 2=medium, 3=low"
    )
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # Execution Status
    last_run: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="success, failed, timeout, cancelled"
    )
    next_run: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Statistics
    total_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of ScheduledJob."""
        return f"<ScheduledJob(id={self.id}, name='{self.name}', type='{self.job_type}', enabled={self.enabled})>"


class JobExecutionLog(Base):
    """
    Job execution history log model.

    Attributes:
        id: Primary key
        job_id: Foreign key to scheduled_jobs
        started_at: Execution start timestamp
        completed_at: Execution completion timestamp
        status: Execution status (success, failed, timeout, cancelled)
        duration_seconds: Execution duration in seconds
        items_found: Number of items found during execution
        items_new: Number of new items added
        items_updated: Number of items updated
        items_skipped: Number of items skipped
        errors_count: Number of errors encountered
        output_log: Captured stdout/output from execution
        error_log: Captured stderr/errors from execution
        triggered_by: How the job was triggered (scheduled, manual, retry)
    """

    __tablename__ = "job_execution_logs"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign Key
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('scheduled_jobs.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Execution Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Execution Results
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="success, failed, timeout, cancelled"
    )

    # Statistics
    items_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    items_new: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    items_updated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    items_skipped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    errors_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # Logs
    output_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    triggered_by: Mapped[str] = mapped_column(
        String(50), default='scheduled', nullable=False,
        comment="scheduled, manual, retry"
    )

    def __repr__(self) -> str:
        """String representation of JobExecutionLog."""
        return f"<JobExecutionLog(id={self.id}, job_id={self.job_id}, status='{self.status}', started='{self.started_at}')>"


class CityRegistry(Base):
    """
    US Cities Registry for city-first scraping.

    Populated from uscities.csv dataset with ~31,255 cities across all US states.
    Used to generate city-level scraping targets for Yellow Pages and other providers.

    Attributes:
        id: Primary key
        city: Full city name (may include special characters)
        city_ascii: ASCII-normalized city name
        state_id: 2-letter state code (e.g., 'CA', 'TX')
        state_name: Full state name (e.g., 'California', 'Texas')
        county_fips: 5-digit FIPS code for county
        county_name: County name
        lat: Latitude (decimal degrees)
        lng: Longitude (decimal degrees)
        population: Population estimate
        density: Population density per square mile
        timezone: IANA timezone (e.g., 'America/New_York')
        zips: Space-separated list of ZIP codes
        ranking: City size ranking (1=largest, 5=smallest)
        source: Data source (typically 'shape')
        military: Military base flag
        incorporated: Incorporation status
        active: Whether this city is active for scraping
        city_slug: YP-style city-state slug (e.g., 'los-angeles-ca')
        yp_geo: Fallback search format (e.g., 'Los Angeles, CA')
        priority: Computed priority based on population tier (1-3)
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "city_registry"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Core City Information (from uscities.csv)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    city_ascii: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    state_id: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True,
        comment="2-letter state code (e.g., CA, TX)"
    )
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Geographic Details
    county_fips: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    county_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    # Demographics
    population: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True,
        comment="Population estimate (used for prioritization)"
    )
    density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Time & Location
    timezone: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="IANA timezone (e.g., America/New_York)"
    )
    zips: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Space-separated list of ZIP codes"
    )

    # Metadata from Dataset
    ranking: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="City size ranking (1=largest, 5=smallest)"
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default='shape'
    )
    military: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    incorporated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Scraping Configuration
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
        comment="Whether this city is active for scraping"
    )
    city_slug: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
        comment="YP-style city-state slug (e.g., 'los-angeles-ca')"
    )
    yp_geo: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Fallback search format (e.g., 'Los Angeles, CA')"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, index=True,
        comment="Scraping priority based on population tier (1=high, 2=medium, 3=low)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of CityRegistry."""
        return f"<CityRegistry(id={self.id}, city='{self.city}', state='{self.state_id}', slug='{self.city_slug}')>"


class YPTarget(Base):
    """
    Yellow Pages scraping target (city × category).

    Each row represents a city-category combination to be scraped.
    Generated from CityRegistry × allowed categories.

    Attributes:
        id: Primary key
        provider: Source provider (always 'YP')
        state_id: 2-letter state code
        city: City name
        city_slug: YP city-state slug
        yp_geo: Fallback search format
        category_label: Human-readable category name
        category_slug: YP URL slug for category
        primary_url: City-category URL (e.g., /los-angeles-ca/window-cleaning)
        fallback_url: Search URL with geo_location_terms
        max_pages: Maximum pages to crawl (based on population tier)
        priority: Scraping priority (from city registry)
        status: Current status (planned, in_progress, done, failed, parked)
        last_attempt_ts: Last attempt timestamp
        attempts: Number of scraping attempts
        note: Optional note (e.g., reason for failure)
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "yp_targets"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provider & Location
    provider: Mapped[str] = mapped_column(
        String(10), nullable=False, default='YP', index=True
    )
    state_id: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True,
        comment="2-letter state code"
    )
    city: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    city_slug: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="YP city-state slug (e.g., 'los-angeles-ca')"
    )
    yp_geo: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Fallback search format (e.g., 'Los Angeles, CA')"
    )

    # Category
    category_label: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Human-readable category name (e.g., 'Window Cleaning')"
    )
    category_slug: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="YP URL slug (e.g., 'window-cleaning')"
    )

    # URLs
    primary_url: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="City-category URL (e.g., /los-angeles-ca/window-cleaning)"
    )
    fallback_url: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Search URL with geo_location_terms"
    )

    # Crawl Configuration
    max_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Max pages to crawl (1-3 based on population tier)"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, index=True,
        comment="Priority (1=high, 2=medium, 3=low)"
    )

    # Status Tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='planned', index=True,
        comment="planned, in_progress, done, failed, parked"
    )
    last_attempt_ts: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of scraping attempts"
    )
    note: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Optional note (e.g., 'no results page 1', 'blocked')"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of YPTarget."""
        return f"<YPTarget(id={self.id}, city='{self.city}', state='{self.state_id}', category='{self.category_label}', status='{self.status}')>"


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

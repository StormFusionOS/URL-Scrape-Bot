"""
Database models for washdb-bot using SQLAlchemy 2.0 style.

Models:
- Company: Stores business/company information scraped from various sources
- ScheduledJob: Stores scheduled crawl/scrape jobs with cron schedules
- JobExecutionLog: Logs execution history of scheduled jobs
- CityRegistry: US cities dataset for city-first scraping
- YPTarget: Target list for Yellow Pages city-first crawling
- GoogleTarget: Target list for Google Maps city-first crawling
- BingTarget: Target list for Bing Local Search city-first crawling
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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator


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
        source: Data source (e.g., 'YP', 'Google', 'Bing', 'Manual')
        rating_yp: Yellow Pages rating
        rating_google: Google rating
        rating_bing: Bing Local Search rating
        reviews_google: Number of Google reviews
        reviews_yp: Number of Yellow Pages reviews
        reviews_bing: Number of Bing reviews
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
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True, comment="Indexed for deduplication")
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)

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
    rating_bing: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviews_google: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviews_yp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviews_bing: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


    # Parse Metadata (for traceability and explainability)
    # Use JSON with PostgreSQL variant for cross-database compatibility (SQLite tests + PostgreSQL production)
    parse_metadata: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="JSON with parsing/filtering signals: profile_url, category_tags, is_sponsored, filter_score, filter_reason, source_page_url"
    )

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
        status: Current status (PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED)
        last_attempt_ts: Last attempt timestamp
        attempts: Number of scraping attempts
        note: Optional note (e.g., reason for failure)
        claimed_by: Worker ID that claimed this target
        claimed_at: When target was claimed by worker
        heartbeat_at: Last worker heartbeat timestamp
        page_current: Current page being crawled (0-based, 0=not started)
        page_target: Target page count (same as max_pages)
        last_listing_id: Last processed listing ID (for resume cursor)
        next_page_url: URL of next page to crawl (for resume)
        last_error: Last error message encountered
        finished_at: When target was completed
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

    # Status Tracking (Enhanced for crash recovery)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='PLANNED', index=True,
        comment="PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED"
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

    # Worker Claim & Heartbeat (for crash recovery)
    claimed_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Worker ID that claimed this target (e.g., 'worker_0_pid_12345')"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was claimed by worker"
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="Last worker heartbeat timestamp (for orphan detection)"
    )

    # Page-level Progress (for resume from exact page)
    page_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Current page being crawled (0=not started, 1=first page, etc.)"
    )
    page_target: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Target page count (same as max_pages)"
    )
    last_listing_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Last processed listing ID (stable cursor for resume)"
    )
    next_page_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="URL of next page to crawl (for resume)"
    )

    # Error Tracking
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last error message encountered"
    )

    # Completion Tracking
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was completed (status=DONE)"
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
        return f"<YPTarget(id={self.id}, city='{self.city}', state='{self.state_id}', category='{self.category_label}', status='{self.status}', page={self.page_current}/{self.page_target})>"


class GoogleTarget(Base):
    """
    Google Maps scraping target (city × category).

    Each row represents a city-category combination to be scraped from Google Maps.
    Generated from CityRegistry × allowed categories.

    Attributes:
        id: Primary key
        provider: Source provider (always 'Google')
        state_id: 2-letter state code
        city: City name
        city_slug: City-state slug (e.g., 'providence-ri')
        lat: City latitude
        lng: City longitude
        category_label: Human-readable category name
        category_keyword: Google search keyword
        search_query: Full Google Maps search query
        max_results: Maximum results to fetch (1-100)
        priority: Scraping priority (1=high, 2=medium, 3=low)
        status: Current status (PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED)
        last_attempt_ts: Last attempt timestamp
        attempts: Number of scraping attempts
        note: Optional note (e.g., reason for failure)
        claimed_by: Worker ID that claimed this target
        claimed_at: When target was claimed by worker
        heartbeat_at: Last worker heartbeat timestamp
        results_found: Number of businesses found
        results_saved: Number of businesses saved to DB
        duplicates_skipped: Number of duplicates skipped
        last_error: Last error message encountered
        captcha_detected: Whether CAPTCHA was encountered
        finished_at: When target was completed
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "google_targets"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provider & Location
    provider: Mapped[str] = mapped_column(
        String(10), nullable=False, default='Google', index=True
    )
    state_id: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True,
        comment="2-letter state code"
    )
    city: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    city_slug: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="City-state slug (e.g., 'providence-ri')"
    )
    lat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City latitude"
    )
    lng: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City longitude"
    )

    # Category
    category_label: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Human-readable category name (e.g., 'Window Cleaning')"
    )
    category_keyword: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Google search keyword (e.g., 'window cleaning')"
    )

    # Search Configuration
    search_query: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Full search query (e.g., 'car wash near Providence, RI')"
    )
    max_results: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20,
        comment="Maximum results to fetch (1-100)"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, index=True,
        comment="Priority (1=high, 2=medium, 3=low)"
    )

    # Status Tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='PLANNED', index=True,
        comment="PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED"
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
        comment="Optional note (e.g., 'no results', 'blocked')"
    )

    # Worker Claim & Heartbeat (for crash recovery)
    claimed_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Worker ID that claimed this target"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was claimed by worker"
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="Last worker heartbeat (for orphan detection)"
    )

    # Results Tracking
    results_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses found"
    )
    results_saved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses saved to DB"
    )
    duplicates_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of duplicates skipped"
    )

    # Error Tracking
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last error message encountered"
    )
    captcha_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether CAPTCHA was encountered"
    )

    # Completion Tracking
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was completed (status=DONE)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of GoogleTarget."""
        return f"<GoogleTarget(id={self.id}, city='{self.city}', state='{self.state_id}', category='{self.category_label}', status='{self.status}', results={self.results_saved})>"


class BingTarget(Base):
    """
    Bing Local Search scraping target (city × category).

    Each row represents a city-category combination to be scraped from Bing Local Search.
    Generated from CityRegistry × allowed categories.

    Attributes:
        id: Primary key
        provider: Source provider (always 'Bing')
        state_id: 2-letter state code
        city: City name
        city_slug: City-state slug (e.g., 'providence-ri')
        lat: City latitude
        lng: City longitude
        category_label: Human-readable category name
        category_keyword: Bing search keyword
        search_query: Full Bing Local Search query
        max_results: Maximum results to fetch (1-100)
        priority: Scraping priority (1=high, 2=medium, 3=low)
        status: Current status (PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED)
        last_attempt_ts: Last attempt timestamp
        attempts: Number of scraping attempts
        note: Optional note (e.g., reason for failure)
        claimed_by: Worker ID that claimed this target
        claimed_at: When target was claimed by worker
        heartbeat_at: Last worker heartbeat timestamp
        results_found: Number of businesses found
        results_saved: Number of businesses saved to DB
        duplicates_skipped: Number of duplicates skipped
        last_error: Last error message encountered
        captcha_detected: Whether CAPTCHA was encountered
        finished_at: When target was completed
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "bing_targets"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provider & Location
    provider: Mapped[str] = mapped_column(
        String(10), nullable=False, default='Bing', index=True
    )
    state_id: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True,
        comment="2-letter state code"
    )
    city: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    city_slug: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="City-state slug (e.g., 'providence-ri')"
    )
    lat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City latitude"
    )
    lng: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City longitude"
    )

    # Category
    category_label: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Human-readable category name (e.g., 'Window Cleaning')"
    )
    category_keyword: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Bing search keyword (e.g., 'window cleaning')"
    )

    # Search Configuration
    search_query: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Full search query (e.g., 'car wash near Providence, RI')"
    )
    max_results: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20,
        comment="Maximum results to fetch (1-100)"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, index=True,
        comment="Priority (1=high, 2=medium, 3=low)"
    )

    # Status Tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='PLANNED', index=True,
        comment="PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED"
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
        comment="Optional note (e.g., 'no results', 'blocked')"
    )

    # Worker Claim & Heartbeat (for crash recovery)
    claimed_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Worker ID that claimed this target"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was claimed by worker"
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="Last worker heartbeat (for orphan detection)"
    )

    # Results Tracking
    results_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses found"
    )
    results_saved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses saved to DB"
    )
    duplicates_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of duplicates skipped"
    )

    # Error Tracking
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last error message encountered"
    )
    captcha_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether CAPTCHA was encountered"
    )

    # Completion Tracking
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was completed (status=DONE)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of BingTarget."""
        return f"<BingTarget(id={self.id}, city='{self.city}', state='{self.state_id}', category='{self.category_label}', status='{self.status}', results={self.results_saved})>"


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


class YelpTarget(Base):
    """
    Yelp scraping target (city × category).

    Each row represents a city-category combination to be scraped from Yelp.
    Generated from CityRegistry × allowed categories.

    Attributes:
        id: Primary key
        provider: Source provider (always 'Yelp')
        state_id: 2-letter state code
        city: City name
        city_slug: City-state slug (e.g., 'providence-ri')
        lat: City latitude
        lng: City longitude
        category_label: Human-readable category name
        category_keyword: Yelp search keyword
        max_results: Maximum results to fetch (1-100)
        priority: Scraping priority (1=high, 2=medium, 3=low)
        status: Current status (PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED)
        last_attempt_ts: Last attempt timestamp
        attempts: Number of scraping attempts
        note: Optional note (e.g., reason for failure)
        claimed_by: Worker ID that claimed this target
        claimed_at: When target was claimed by worker
        heartbeat_at: Last worker heartbeat timestamp
        results_found: Number of businesses found
        results_saved: Number of businesses saved to DB
        duplicates_skipped: Number of duplicates skipped
        last_error: Last error message encountered
        captcha_detected: Whether CAPTCHA was encountered
        finished_at: When target was completed
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "yelp_targets"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provider & Location
    provider: Mapped[str] = mapped_column(
        String(10), nullable=False, default='Yelp', index=True
    )
    state_id: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True,
        comment="2-letter state code"
    )
    city: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    city_slug: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="City-state slug (e.g., 'providence-ri')"
    )
    lat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City latitude"
    )
    lng: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="City longitude"
    )

    # Category
    category_label: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Human-readable category name (e.g., 'Window Cleaning')"
    )
    category_keyword: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Yelp search keyword (e.g., 'window cleaning')"
    )

    # Search Configuration
    max_results: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20,
        comment="Maximum results to fetch (1-100)"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, index=True,
        comment="Priority (1=high, 2=medium, 3=low)"
    )

    # Status Tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='PLANNED', index=True,
        comment="PLANNED, IN_PROGRESS, DONE, FAILED, STUCK, PARKED"
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
        comment="Optional note (e.g., 'no results', 'blocked')"
    )

    # Worker Claim & Heartbeat (for crash recovery)
    claimed_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Worker ID that claimed this target"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was claimed by worker"
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="Last worker heartbeat (for orphan detection)"
    )

    # Results Tracking
    results_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses found"
    )
    results_saved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of businesses saved to DB"
    )
    duplicates_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of duplicates skipped"
    )

    # Error Tracking
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last error message encountered"
    )
    captcha_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether CAPTCHA was encountered"
    )

    # Completion Tracking
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="When target was completed (status=DONE)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of YelpTarget."""
        return f"<YelpTarget(id={self.id}, city='{self.city}', state='{self.state_id}', category='{self.category_label}', status='{self.status}', results={self.results_saved})>"


class SiteCrawlState(Base):
    """
    Site crawler state for resumable crawling.

    Tracks the crawl progress for individual domains, allowing the site scraper
    to resume from where it left off if interrupted.

    Phases:
        - 'parsing_home': Currently parsing homepage
        - 'crawling_internal': Crawling internal pages (contact, about, services)
        - 'done': All target pages discovered and parsed
        - 'failed': Crawl failed (too many errors, site unreachable, etc.)

    State Management:
        - After each page parse, save cursor (last_completed_url + pending_queue)
        - Queue is bounded to MAX_QUEUE_SIZE (default: 50 URLs)
        - On restart, rebuild queue from saved state and continue
    """

    __tablename__ = "site_crawl_state"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Domain being crawled
    domain: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False,
        comment="Domain being crawled (e.g., 'example.com')"
    )

    # Crawl Phase
    phase: Mapped[str] = mapped_column(
        String(50), nullable=False, default='parsing_home',
        comment="Current phase: parsing_home, crawling_internal, done, failed"
    )

    # Cursor State
    last_completed_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last URL successfully parsed (for resume)"
    )

    # Pending URL Queue (bounded, max 50 URLs)
    pending_queue: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSON array of pending URLs to crawl (max 50)"
    )

    # Discovered Target URLs
    discovered_targets: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSON with discovered URLs: {contact: [...], about: [...], services: [...]}"
    )

    # Statistics
    pages_crawled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Total pages crawled so far"
    )
    targets_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Total target pages found (contact/about/services)"
    )
    errors_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Number of errors encountered"
    )

    # Error Tracking
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Last error message (for debugging)"
    )

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
        comment="When crawl started"
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="Last cursor save timestamp"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="When crawl completed (done or failed)"
    )

    def __repr__(self) -> str:
        """String representation of SiteCrawlState."""
        return f"<SiteCrawlState(domain='{self.domain}', phase='{self.phase}', pages={self.pages_crawled})>"


class BusinessSource(Base):
    """
    Business data source tracking for NAP consistency validation.

    Tracks business information from multiple sources (YP, Google, Yelp, citations, etc.)
    to enable multi-source NAP consistency validation and conflict detection.
    One Company can have many BusinessSources.

    Attributes:
        source_id: Primary key
        company_id: Foreign key to companies table
        source_type: Type of source ('yp', 'google', 'yelp', 'bbb', 'facebook', 'citation')
        source_name: Human-readable source name ('Yellow Pages', 'Google Business Profile')
        source_url: Base URL of the source platform
        profile_url: Direct link to the business profile on this source
        name: Business name from this source
        phone: Raw phone number from this source
        phone_e164: Normalized phone in E.164 format
        address_raw: Raw address string from this source
        street: Parsed street address
        city: Parsed city
        state: Parsed state
        zip_code: Parsed ZIP code
        website: Website URL from this source
        categories: Business categories/tags from this source
        rating_value: Rating value (e.g., 4.5)
        rating_count: Number of reviews
        description: Business description from this source
        is_verified: Whether this is an owner-verified listing
        listing_status: Status ('claimed', 'unclaimed', 'found', 'needs_manual')
        data_quality_score: Computed quality score 0-100
        confidence_level: Data confidence ('high', 'medium', 'low')
        scraped_at: When this data was scraped
        updated_at: When this record was last updated
        metadata: Extended fields and raw data (JSONB)
    """

    __tablename__ = "business_sources"

    # Primary Key
    source_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign Key to Company
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Links to companies table"
    )

    # Source Metadata
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Source type: yp, google, yelp, bbb, facebook, citation, etc."
    )
    source_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Human-readable source name"
    )
    source_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Base URL of source platform"
    )
    profile_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        index=True,
        comment="Direct link to business profile"
    )

    # NAP Data from this source
    name: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Business name from this source"
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Raw phone number"
    )
    phone_e164: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="Normalized phone in E.164 format"
    )
    address_raw: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Raw address string from source"
    )
    street: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Parsed street address"
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        index=True,
        comment="Parsed city"
    )
    state: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Parsed state/province"
    )
    zip_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="Parsed ZIP/postal code"
    )

    # Additional Data
    website: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Website URL from this source"
    )
    categories: Mapped[Optional[list]] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Business categories/tags"
    )
    rating_value: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 2),
        nullable=True,
        comment="Rating value (e.g., 4.5)"
    )
    rating_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of reviews"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Business description"
    )

    # Quality Indicators
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Owner-verified listing"
    )
    listing_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="claimed, unclaimed, found, needs_manual"
    )
    data_quality_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Computed quality score 0-100"
    )
    confidence_level: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="high, medium, low"
    )

    # Timestamps
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="When this data was scraped"
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        onupdate=func.now(),
        nullable=True,
        comment="Last update timestamp"
    )

    # Extended Metadata (renamed from 'metadata' to avoid SQLAlchemy reserved name conflict)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata",  # Column name in database is still 'metadata'
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="Extended fields, raw data, parsing metadata"
    )

    def __repr__(self) -> str:
        """String representation of BusinessSource."""
        return f"<BusinessSource(id={self.source_id}, company_id={self.company_id}, source='{self.source_type}', name='{self.name}')>"


class DomainBrowserSettings(Base):
    """
    Domain-specific browser settings for hybrid headless/headed mode.

    Tracks which domains require headed (visible) browser mode due to
    bot detection. Starts with headless for efficiency, upgrades to
    headed when detection is triggered.

    Attributes:
        id: Primary key
        domain: Domain name (unique, e.g., 'google.com')
        requires_headed: Whether domain requires headed browser
        detection_count: Number of times bot detection was triggered
        last_detection: Last detection timestamp
        detection_reason: Reason for last detection (CAPTCHA, 403, etc.)
        success_count_headed: Successful requests in headed mode
        success_count_headless: Successful requests in headless mode
        fail_count_headed: Failed requests in headed mode
        fail_count_headless: Failed requests in headless mode
        profile_path: Path to persistent browser profile for this domain
        cookies_stored: Whether cookies are stored for this domain
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "domain_browser_settings"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Domain (unique index)
    domain: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
        comment="Domain name (e.g., 'google.com', 'yelp.com')"
    )

    # Browser Mode Settings
    requires_headed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Whether domain requires headed (visible) browser"
    )

    # Detection Tracking
    detection_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of times bot detection was triggered"
    )
    last_detection: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Last detection timestamp"
    )
    detection_reason: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Reason for last detection (CAPTCHA, 403_FORBIDDEN, BOT_DETECTED)"
    )

    # Success/Failure Statistics
    success_count_headed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Successful requests in headed mode"
    )
    success_count_headless: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Successful requests in headless mode"
    )
    fail_count_headed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Failed requests in headed mode"
    )
    fail_count_headless: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Failed requests in headless mode"
    )

    # Browser Profile Persistence
    profile_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="Path to persistent browser profile for this domain"
    )
    cookies_stored: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether cookies/storage are persisted for this domain"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        """String representation of DomainBrowserSettings."""
        mode = "headed" if self.requires_headed else "headless"
        return f"<DomainBrowserSettings(domain='{self.domain}', mode='{mode}', detections={self.detection_count})>"



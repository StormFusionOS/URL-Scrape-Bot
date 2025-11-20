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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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


# ============================================================================
# SEO Intelligence Models (Canonical Schema for AI SEO System)
# ============================================================================


class SearchQuery(Base):
    """
    Tracked keywords for SERP monitoring.

    Attributes:
        id: Primary key
        query_text: The search keyword/phrase
        search_engine: Search engine (e.g., 'Google', 'Bing')
        locale: Search locale (e.g., 'en-US')
        location: Geographic location for localized results
        track: Whether to actively track this query
        priority: Priority for tracking (1=high, 2=medium, 3=low)
        created_at: Record creation timestamp
        last_checked: Last SERP capture timestamp
    """

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_text: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="Search keyword or phrase"
    )
    search_engine: Mapped[str] = mapped_column(
        String(50), nullable=False, default='Google',
        comment="Search engine (Google, Bing, etc.)"
    )
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default='en-US',
        comment="Locale for search results"
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Geographic location for localized results"
    )
    track: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
        comment="Whether to actively track this query"
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False,
        comment="1=high, 2=medium, 3=low"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_checked: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Last SERP capture timestamp"
    )

    # Unique constraint on query + search_engine + locale
    __table_args__ = (
        Index('ix_query_engine_locale', 'query_text', 'search_engine', 'locale', unique=True),
    )

    def __repr__(self) -> str:
        return f"<SearchQuery(id={self.id}, query='{self.query_text}', engine='{self.search_engine}')>"


class SerpSnapshot(Base):
    """
    Daily SERP snapshot for a tracked query.

    Stores one snapshot per query per day to track ranking changes over time.

    Attributes:
        id: Primary key
        query_id: Foreign key to search_queries
        snapshot_date: Date of snapshot (DATE type for partitioning)
        search_engine: Search engine used
        our_rank: Our ranking position (if found in results)
        featured_snippet: Whether a featured snippet was present
        featured_snippet_data: JSON with featured snippet text/URL
        paa_questions: JSON array of People Also Ask questions
        created_at: Snapshot creation timestamp
    """

    __tablename__ = "serp_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('search_queries.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    snapshot_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True,
        comment="Date of snapshot (for daily tracking and partitioning)"
    )
    search_engine: Mapped[str] = mapped_column(
        String(50), nullable=False, default='Google'
    )
    our_rank: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Our ranking position if found in top results"
    )
    featured_snippet: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether a featured snippet was present"
    )
    featured_snippet_data: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSON with featured snippet text, URL, type"
    )
    paa_questions: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSON array of People Also Ask questions with answers"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Unique constraint: one snapshot per query per day
    __table_args__ = (
        Index('ix_serp_query_date', 'query_id', 'snapshot_date', unique=True),
    )

    def __repr__(self) -> str:
        return f"<SerpSnapshot(id={self.id}, query_id={self.query_id}, date={self.snapshot_date}, our_rank={self.our_rank})>"


class SerpResult(Base):
    """
    Individual SERP result (top 10 organic results per snapshot).

    Attributes:
        id: Primary key
        snapshot_id: Foreign key to serp_snapshots
        rank: Position in SERP (1-10)
        url: Result URL
        title: Page title
        snippet: Meta description / snippet text
        domain: Domain extracted from URL
        is_ours: Whether this result belongs to our domain
        created_at: Record creation timestamp
    """

    __tablename__ = "serp_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('serp_snapshots.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    rank: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Position in SERP (1-10)"
    )
    url: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    title: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    snippet: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    domain: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Domain extracted from URL"
    )
    is_ours: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Whether this result belongs to our domain"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SerpResult(id={self.id}, snapshot_id={self.snapshot_id}, rank={self.rank}, domain='{self.domain}')>"


class Competitor(Base):
    """
    Competitor domain tracking.

    Attributes:
        id: Primary key
        domain: Competitor domain (unique)
        name: Business/site name
        category: Business category
        priority: Tracking priority (1=high, 2=medium, 3=low)
        active: Whether actively tracking this competitor
        created_at: Record creation timestamp
        last_crawled: Last crawl timestamp
    """

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False,
        comment="Competitor domain (e.g., 'example.com')"
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Business/site name"
    )
    category: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Business category"
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False,
        comment="1=high, 2=medium, 3=low"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
        comment="Whether actively tracking this competitor"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_crawled: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Last crawl timestamp"
    )

    def __repr__(self) -> str:
        return f"<Competitor(id={self.id}, domain='{self.domain}', name='{self.name}')>"


class CompetitorPage(Base):
    """
    Competitor page data with hashing, snapshots, and structured data.

    Tracks individual pages from competitor sites with:
    - Content hashing for change detection
    - Structured on-page signals (meta, H1/H2, schema, links, etc.)
    - HTML snapshot archival
    - Page type classification

    Attributes:
        id: Primary key
        site_id: Foreign key to competitors
        url: Page URL (unique per site)
        page_type: Page classification (homepage, service, blog, contact, listing, other)
        meta_title: Page title
        meta_description: Meta description
        h1_text: H1 heading text
        h2_text: H2 headings (JSON array)
        canonical_url: Canonical URL from meta tag
        robots_meta: Robots meta directives
        last_hash: SHA-256 hash of normalized DOM
        last_scraped: Last scrape timestamp
        status_code: HTTP status code from last fetch
        data: JSONB with structured signals (schema.ld_json, links, images, video, etc.)
        html_snapshot_path: Path to archived HTML snapshot
        created_at: Record creation timestamp
        last_updated: Last update timestamp
    """

    __tablename__ = "competitor_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('competitors.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    url: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="Page URL"
    )
    page_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default='other', index=True,
        comment="homepage, service, blog, contact, listing, other"
    )
    meta_title: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    meta_description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    h1_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="H1 heading text"
    )
    h2_text: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSON array of H2 headings"
    )
    canonical_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    robots_meta: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Robots meta directives (e.g., 'noindex, nofollow')"
    )
    last_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SHA-256 hash of normalized DOM for change detection"
    )
    last_scraped: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    status_code: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="HTTP status code from last fetch"
    )
    data: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSONB with structured signals: schema.ld_json[], links.internal[], links.external[], images.alt_coverage, video.embeds[], etc."
    )
    html_snapshot_path: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Path to archived HTML snapshot file"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )

    # Unique constraint: one URL per site
    __table_args__ = (
        Index('ix_competitor_pages_site_url', 'site_id', 'url', unique=True),
    )

    def __repr__(self) -> str:
        return f"<CompetitorPage(id={self.id}, site_id={self.site_id}, url='{self.url}', type='{self.page_type}')>"


class Backlink(Base):
    """
    Backlink tracking (source → target).

    Discovered from competitor outbound links or other sources.
    Tracks link presence, anchor text, and relationship attributes.

    Attributes:
        id: Primary key
        source_url: URL where the link was found
        target_url: URL being linked to
        source_domain: Source domain (for aggregation)
        target_domain: Target domain
        anchor_text: Link anchor text
        rel_attr: Rel attribute (e.g., 'nofollow', 'sponsored', 'ugc')
        position: Link position (in-body, nav, footer, aside)
        first_seen: First discovery timestamp
        last_checked: Last verification timestamp
        alive: Whether link is still present
        created_at: Record creation timestamp
    """

    __tablename__ = "backlinks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="URL where the link was found"
    )
    target_url: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="URL being linked to"
    )
    source_domain: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Source domain for aggregation"
    )
    target_domain: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Target domain"
    )
    anchor_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    rel_attr: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Rel attribute: nofollow, sponsored, ugc, etc."
    )
    position: Mapped[str] = mapped_column(
        String(50), nullable=False, default='unknown',
        comment="in-body, nav, footer, aside"
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
        comment="First discovery timestamp"
    )
    last_checked: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="Last verification timestamp"
    )
    alive: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
        comment="Whether link is still present"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Unique constraint: one link per source-target pair
    __table_args__ = (
        Index('ix_backlinks_source_target', 'source_url', 'target_url', unique=True),
    )

    def __repr__(self) -> str:
        return f"<Backlink(id={self.id}, source='{self.source_domain}', target='{self.target_domain}', alive={self.alive})>"


class ReferringDomain(Base):
    """
    Domain-level backlink aggregates for Local Authority Score (LAS).

    Periodically updated via nightly aggregation job.

    Attributes:
        id: Primary key
        domain: Domain being aggregated
        backlink_count: Total backlinks to this domain
        inbody_link_count: Count of in-body links (weighted higher for LAS)
        authority_score: Computed LAS (0-100, normalized across competitor set)
        last_updated: Last aggregation timestamp
        created_at: Record creation timestamp
    """

    __tablename__ = "referring_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False,
        comment="Domain being aggregated"
    )
    backlink_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Total backlinks to this domain"
    )
    inbody_link_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Count of in-body links (weighted higher)"
    )
    authority_score: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False, index=True,
        comment="Local Authority Score (0-100, normalized)"
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="Last aggregation timestamp"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ReferringDomain(domain='{self.domain}', backlinks={self.backlink_count}, LAS={self.authority_score:.1f})>"


class Citation(Base):
    """
    Citations tracking (directory presence, NAP matching, reviews).

    Tracks business listings on directories like Yelp, BBB, Angi, etc.

    Attributes:
        id: Primary key
        site_name: Directory name (e.g., 'Yelp', 'BBB', 'Angi')
        profile_url: URL to business profile
        listed: Whether business is listed on this directory
        nap_match: Whether NAP (Name, Address, Phone) matches canonical data
        business_name: Name as listed on directory
        phone: Phone as listed
        address: Address as listed
        rating: Average rating (if available)
        review_count: Number of reviews
        last_audited: Last audit timestamp
        first_seen: First discovery timestamp
        issues: Text description of any issues (e.g., "NAP mismatch: phone differs")
        data: JSONB with extended fields (review samples, operating hours, etc.)
        created_at: Record creation timestamp
    """

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Directory name (e.g., 'Yelp', 'BBB', 'Angi')"
    )
    profile_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="URL to business profile on directory"
    )
    listed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Whether business is listed on this directory"
    )
    nap_match: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether NAP (Name, Address, Phone) matches canonical data"
    )
    business_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    address: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    rating: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Average rating (if available)"
    )
    review_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Number of reviews"
    )
    last_audited: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True,
        comment="Last audit timestamp"
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
        comment="First discovery timestamp"
    )
    issues: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Text description of issues (e.g., NAP mismatch details)"
    )
    data: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
        comment="JSONB with extended fields (review samples, hours, etc.)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Unique constraint: one citation per site
    __table_args__ = (
        Index('ix_citations_site_name', 'site_name', unique=True),
    )

    def __repr__(self) -> str:
        return f"<Citation(id={self.id}, site='{self.site_name}', listed={self.listed}, nap_match={self.nap_match})>"


class PageAudit(Base):
    """
    Page-level technical/accessibility audit summary.

    Records summary of technical audit for a page (render vs raw comparison,
    indexability checks, performance proxies).

    Attributes:
        id: Primary key
        page_url: URL audited
        audit_date: Audit timestamp
        status_code: HTTP status code
        indexable: Whether page is indexable (no robots blocks)
        render_differs: Whether rendered DOM differs significantly from raw HTML
        performance_proxy: Estimated performance score (0-100)
        issues_found: Count of issues detected
        notes: Optional notes about the audit
        created_at: Record creation timestamp
    """

    __tablename__ = "page_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_url: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="URL audited"
    )
    audit_date: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True,
        comment="Audit timestamp"
    )
    status_code: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="HTTP status code"
    )
    indexable: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="Whether page is indexable (no robots blocks)"
    )
    render_differs: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether rendered DOM differs from raw HTML"
    )
    performance_proxy: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Estimated performance score (0-100)"
    )
    issues_found: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Count of issues detected"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Optional notes about the audit"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<PageAudit(id={self.id}, url='{self.page_url}', issues={self.issues_found})>"


class AuditIssue(Base):
    """
    Individual technical/accessibility audit issue.

    Records specific issues found during page audits.

    Attributes:
        id: Primary key
        audit_id: Foreign key to page_audits
        issue_type: Type of issue (e.g., 'render_js_only_text', 'no_canonical', 'a11y_alt_missing')
        description: Detailed description of the issue
        severity: Issue severity (high, medium, low)
        fixed: Whether issue has been fixed
        fixed_date: When issue was fixed
        created_at: Record creation timestamp
    """

    __tablename__ = "audit_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('page_audits.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    issue_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Type: render_js_only_text, no_canonical, a11y_alt_missing, html_error, etc."
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Detailed description of the issue"
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default='medium',
        comment="high, medium, low"
    )
    fixed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Whether issue has been fixed"
    )
    fixed_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="When issue was fixed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditIssue(id={self.id}, type='{self.issue_type}', severity='{self.severity}', fixed={self.fixed})>"


class TaskLog(Base):
    """
    Task execution logging for governance and accountability.

    Every scraping/analysis job writes a row to this table with execution details.

    Attributes:
        id: Primary key
        task_name: Name of the task (e.g., 'serp_scraper', 'competitor_crawler')
        module: Module name (e.g., 'serp', 'competitor', 'backlinks')
        started_at: Task start timestamp
        completed_at: Task completion timestamp
        status: Execution status (success, failed, partial, timeout)
        message: Summary message or error details
        items_processed: Number of items processed
        items_new: Number of new items created
        items_updated: Number of items updated
        items_failed: Number of items that failed
        created_at: Record creation timestamp
    """

    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Name of the task (e.g., 'serp_scraper', 'competitor_crawler')"
    )
    module: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Module name (e.g., 'serp', 'competitor', 'backlinks')"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True,
        comment="Task start timestamp"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Task completion timestamp"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="success, failed, partial, timeout"
    )
    message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Summary message or error details"
    )
    items_processed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of items processed"
    )
    items_new: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of new items created"
    )
    items_updated: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of items updated"
    )
    items_failed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Number of items that failed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TaskLog(id={self.id}, task='{self.task_name}', status='{self.status}', items={self.items_processed})>"


class ChangeLog(Base):
    """
    SEO change proposals for review-mode governance.

    All SEO change proposals flow through this table with status='pending'.
    Changes are never applied directly - they must be reviewed and approved.

    Attributes:
        id: Primary key
        module: Module that proposed the change (e.g., 'serp', 'internal_linking')
        change_type: Type of change (e.g., 'title_update', 'schema_add', 'internal_link')
        target_url: URL to be modified
        proposed_change: JSON with change details
        rationale: Explanation of why this change is recommended
        status: Change status (pending, approved, rejected, executed, reverted)
        priority: Priority (1=high, 2=medium, 3=low)
        created_at: Proposal creation timestamp
        reviewed_at: When change was reviewed
        reviewed_by: Who reviewed the change
        executed_at: When change was applied
        reverted_at: When change was reverted (if applicable)
    """

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Module that proposed the change"
    )
    change_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Type: title_update, schema_add, internal_link, meta_update, etc."
    )
    target_url: Mapped[str] = mapped_column(
        Text, nullable=False, index=True,
        comment="URL to be modified"
    )
    proposed_change: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
        comment="JSON with change details (before/after, anchor text, etc.)"
    )
    rationale: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Explanation of why this change is recommended"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default='pending', index=True,
        comment="pending, approved, rejected, executed, reverted"
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False,
        comment="1=high, 2=medium, 3=low"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True,
        comment="Proposal creation timestamp"
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="When change was reviewed"
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Who reviewed the change"
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="When change was applied"
    )
    reverted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="When change was reverted"
    )

    def __repr__(self) -> str:
        return f"<ChangeLog(id={self.id}, type='{self.change_type}', status='{self.status}', url='{self.target_url}')>"

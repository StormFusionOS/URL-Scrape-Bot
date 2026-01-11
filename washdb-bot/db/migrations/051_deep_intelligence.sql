-- Migration 051: Deep Competitor Intelligence Tables
-- Adds support for: Reviews, Pricing, Content, Social tracking

-- ============================================================================
-- PART 1: REVIEWS & REPUTATION
-- ============================================================================

-- Individual review records
CREATE TABLE IF NOT EXISTS competitor_reviews (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,              -- google, yelp, facebook, bbb
    external_review_id VARCHAR(255),          -- Platform's review ID if available

    -- Reviewer info (privacy-conscious)
    reviewer_name_hash VARCHAR(64),           -- SHA-256 hash of name
    reviewer_display VARCHAR(100),            -- First name + last initial (e.g., "John S.")
    reviewer_review_count INTEGER,            -- How many reviews they've written
    reviewer_is_local_guide BOOLEAN,          -- Google Local Guide status

    -- Rating & Content
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    review_text_snippet VARCHAR(500),         -- First 500 chars for quick display
    word_count INTEGER,

    -- Dates
    review_date DATE,
    review_relative_date VARCHAR(50),         -- "2 weeks ago"
    captured_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),

    -- Owner Response
    has_owner_response BOOLEAN DEFAULT FALSE,
    owner_response_text TEXT,
    owner_response_date DATE,
    response_delay_days INTEGER,

    -- Sentiment Analysis
    sentiment_score DECIMAL(5,2) CHECK (sentiment_score BETWEEN -1 AND 1),
    sentiment_label VARCHAR(20),              -- positive, negative, neutral, mixed
    sentiment_confidence DECIMAL(3,2),

    -- Category Extraction
    complaint_categories JSONB DEFAULT '[]',
    praise_categories JSONB DEFAULT '[]',
    keywords_extracted JSONB DEFAULT '[]',

    -- Flags
    is_suspicious BOOLEAN DEFAULT FALSE,
    suspicious_reason VARCHAR(255),
    is_verified_purchase BOOLEAN,

    metadata JSONB DEFAULT '{}',

    UNIQUE(competitor_id, source, COALESCE(external_review_id, LEFT(review_text, 100)))
);

CREATE INDEX idx_competitor_reviews_competitor ON competitor_reviews(competitor_id);
CREATE INDEX idx_competitor_reviews_source ON competitor_reviews(source);
CREATE INDEX idx_competitor_reviews_date ON competitor_reviews(review_date DESC);
CREATE INDEX idx_competitor_reviews_rating ON competitor_reviews(competitor_id, rating);
CREATE INDEX idx_competitor_reviews_sentiment ON competitor_reviews(sentiment_label);
CREATE INDEX idx_competitor_reviews_suspicious ON competitor_reviews(competitor_id) WHERE is_suspicious = true;

-- Computed review statistics
CREATE TABLE IF NOT EXISTS competitor_review_stats (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,
    computed_at TIMESTAMP DEFAULT NOW(),

    -- Volume Metrics
    total_reviews INTEGER DEFAULT 0,
    reviews_7d INTEGER DEFAULT 0,
    reviews_30d INTEGER DEFAULT 0,
    reviews_90d INTEGER DEFAULT 0,
    avg_reviews_per_month DECIMAL(5,2),

    -- Rating Metrics
    rating_avg DECIMAL(3,2),
    rating_distribution JSONB DEFAULT '{}',
    rating_trend_30d DECIMAL(3,2),

    -- Response Metrics
    response_rate DECIMAL(5,2),
    response_rate_negative DECIMAL(5,2),
    avg_response_time_days DECIMAL(5,2),
    uses_response_templates BOOLEAN,

    -- Sentiment Metrics
    sentiment_avg DECIMAL(5,2),
    sentiment_trend_30d DECIMAL(5,2),
    pct_positive DECIMAL(5,2),
    pct_negative DECIMAL(5,2),

    -- Category Breakdown
    top_complaints JSONB DEFAULT '[]',
    top_praise JSONB DEFAULT '[]',

    -- Anomaly Detection
    suspicious_review_count INTEGER DEFAULT 0,
    suspicious_review_pct DECIMAL(5,2),

    UNIQUE(competitor_id, source, DATE(computed_at))
);

CREATE INDEX idx_review_stats_competitor ON competitor_review_stats(competitor_id);

-- Extend competitor_reviews_aggregate
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_reviews_aggregate' AND column_name = 'response_rate_negative') THEN
        ALTER TABLE competitor_reviews_aggregate ADD COLUMN response_rate_negative DECIMAL(5,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_reviews_aggregate' AND column_name = 'avg_response_time_days') THEN
        ALTER TABLE competitor_reviews_aggregate ADD COLUMN avg_response_time_days DECIMAL(5,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_reviews_aggregate' AND column_name = 'suspicious_review_count') THEN
        ALTER TABLE competitor_reviews_aggregate ADD COLUMN suspicious_review_count INTEGER DEFAULT 0;
    END IF;
END $$;


-- ============================================================================
-- PART 2: PRICING INTELLIGENCE
-- ============================================================================

-- Price history (time-series snapshots)
CREATE TABLE IF NOT EXISTS competitor_price_history (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    service_id INTEGER REFERENCES competitor_services(id) ON DELETE CASCADE,

    -- Price snapshot
    price_min DECIMAL(10,2),
    price_max DECIMAL(10,2),
    price_unit VARCHAR(50),
    pricing_model VARCHAR(50),

    -- Context
    is_promotional BOOLEAN DEFAULT FALSE,
    promotion_name VARCHAR(255),
    promotion_end_date DATE,

    -- Source tracking
    source_url TEXT,
    extraction_confidence DECIMAL(3,2),

    captured_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(service_id, DATE(captured_at))
);

CREATE INDEX idx_price_history_competitor ON competitor_price_history(competitor_id);
CREATE INDEX idx_price_history_service ON competitor_price_history(service_id);
CREATE INDEX idx_price_history_date ON competitor_price_history(captured_at DESC);

-- Pricing pages tracking
CREATE TABLE IF NOT EXISTS competitor_pricing_pages (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,

    url TEXT NOT NULL,
    page_title VARCHAR(500),
    page_type VARCHAR(50) DEFAULT 'pricing',

    -- Detection signals
    has_prices_visible BOOLEAN DEFAULT FALSE,
    has_quote_form BOOLEAN DEFAULT FALSE,
    has_calculator BOOLEAN DEFAULT FALSE,
    requires_location BOOLEAN DEFAULT FALSE,

    -- Change detection
    content_hash VARCHAR(64),
    prices_hash VARCHAR(64),
    last_checked_at TIMESTAMP,
    last_changed_at TIMESTAMP,
    change_count INTEGER DEFAULT 0,

    discovered_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(competitor_id, url)
);

CREATE INDEX idx_pricing_pages_competitor ON competitor_pricing_pages(competitor_id);

-- Package/Bundle offers
CREATE TABLE IF NOT EXISTS competitor_packages (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,

    package_name VARCHAR(255) NOT NULL,
    package_type VARCHAR(50),

    -- Included services
    included_services JSONB DEFAULT '[]',

    -- Pricing
    package_price DECIMAL(10,2),
    individual_total DECIMAL(10,2),
    savings_amount DECIMAL(10,2),
    savings_percent DECIMAL(5,2),

    -- Validity
    is_seasonal BOOLEAN DEFAULT FALSE,
    season_name VARCHAR(100),
    valid_from DATE,
    valid_until DATE,

    -- Source
    source_url TEXT,
    extraction_confidence DECIMAL(3,2),

    is_active BOOLEAN DEFAULT TRUE,
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_packages_competitor ON competitor_packages(competitor_id);
CREATE INDEX idx_packages_active ON competitor_packages(competitor_id) WHERE is_active = true;

-- Quote form analysis
CREATE TABLE IF NOT EXISTS competitor_quote_forms (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,

    form_url TEXT NOT NULL,
    form_type VARCHAR(50),

    -- Required fields detected
    requires_name BOOLEAN DEFAULT FALSE,
    requires_email BOOLEAN DEFAULT FALSE,
    requires_phone BOOLEAN DEFAULT FALSE,
    requires_address BOOLEAN DEFAULT FALSE,
    requires_sqft BOOLEAN DEFAULT FALSE,
    requires_service_selection BOOLEAN DEFAULT FALSE,

    -- Field details
    form_fields JSONB DEFAULT '[]',
    total_required_fields INTEGER DEFAULT 0,

    -- Friction assessment
    complexity_score INTEGER DEFAULT 0,
    estimated_friction VARCHAR(20),

    last_analyzed_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(competitor_id, form_url)
);

-- Competitive pricing comparison
CREATE TABLE IF NOT EXISTS pricing_comparisons (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    service_category VARCHAR(100) NOT NULL,
    market_segment VARCHAR(255),
    captured_date DATE DEFAULT CURRENT_DATE,

    -- Our pricing
    our_price_min DECIMAL(10,2),
    our_price_max DECIMAL(10,2),

    -- Market statistics
    market_avg_min DECIMAL(10,2),
    market_avg_max DECIMAL(10,2),
    market_median_min DECIMAL(10,2),
    market_lowest_min DECIMAL(10,2),
    market_highest_max DECIMAL(10,2),

    -- Position
    our_position VARCHAR(20),
    price_gap_percent DECIMAL(5,2),
    competitors_cheaper INTEGER DEFAULT 0,
    competitors_pricier INTEGER DEFAULT 0,

    competitor_prices JSONB DEFAULT '[]',
    opportunity_score INTEGER,

    UNIQUE(company_id, service_category, captured_date)
);

-- Extend competitor_services
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'is_starting_at') THEN
        ALTER TABLE competitor_services ADD COLUMN is_starting_at BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'minimum_charge') THEN
        ALTER TABLE competitor_services ADD COLUMN minimum_charge DECIMAL(10,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'pricing_tiers') THEN
        ALTER TABLE competitor_services ADD COLUMN pricing_tiers JSONB;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'previous_price_min') THEN
        ALTER TABLE competitor_services ADD COLUMN previous_price_min DECIMAL(10,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'previous_price_max') THEN
        ALTER TABLE competitor_services ADD COLUMN previous_price_max DECIMAL(10,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitor_services' AND column_name = 'price_last_changed_at') THEN
        ALTER TABLE competitor_services ADD COLUMN price_last_changed_at TIMESTAMP;
    END IF;
END $$;


-- ============================================================================
-- PART 3: CONTENT & SEO DEEP DIVE
-- ============================================================================

-- Full content archive
CREATE TABLE IF NOT EXISTS competitor_content_archive (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    page_type VARCHAR(100),

    -- Full content
    full_text TEXT,
    full_text_hash VARCHAR(64),
    word_count INTEGER,

    -- Content metadata
    readability_score DECIMAL(5,2),
    reading_time_minutes INTEGER,
    paragraph_count INTEGER,

    -- Keyword analysis
    primary_keywords JSONB DEFAULT '[]',
    keyword_density_map JSONB DEFAULT '{}',

    -- Change tracking
    previous_hash VARCHAR(64),
    change_detected BOOLEAN DEFAULT FALSE,
    change_percentage DECIMAL(5,2),
    diff_summary TEXT,

    captured_at TIMESTAMP DEFAULT NOW(),
    first_seen_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(competitor_id, url, DATE(captured_at))
);

CREATE INDEX idx_content_archive_competitor ON competitor_content_archive(competitor_id);
CREATE INDEX idx_content_archive_change ON competitor_content_archive(change_detected) WHERE change_detected = true;

-- Blog/Content tracking
CREATE TABLE IF NOT EXISTS competitor_blog_posts (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    author VARCHAR(255),

    excerpt TEXT,
    full_content TEXT,
    content_hash VARCHAR(64),
    word_count INTEGER,

    published_date DATE,
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_checked_at TIMESTAMP,

    category VARCHAR(100),
    tags JSONB DEFAULT '[]',

    meta_title TEXT,
    meta_description TEXT,

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_blog_posts_competitor ON competitor_blog_posts(competitor_id);
CREATE INDEX idx_blog_posts_date ON competitor_blog_posts(published_date DESC);

-- Content velocity tracking
CREATE TABLE IF NOT EXISTS competitor_content_velocity (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    blog_posts_published INTEGER DEFAULT 0,
    pages_added INTEGER DEFAULT 0,
    pages_updated INTEGER DEFAULT 0,
    total_words_published INTEGER DEFAULT 0,

    posts_per_week DECIMAL(5,2),
    velocity_trend VARCHAR(20),

    captured_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(competitor_id, period_start, period_end)
);

-- Keyword gap analysis
CREATE TABLE IF NOT EXISTS competitor_keyword_gaps (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,

    keyword TEXT NOT NULL,

    our_position INTEGER,
    competitor_position INTEGER,
    position_gap INTEGER,

    estimated_volume INTEGER,
    keyword_type VARCHAR(50),

    opportunity_score DECIMAL(5,2),
    priority VARCHAR(20),

    captured_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, competitor_id, keyword, DATE(captured_at))
);

CREATE INDEX idx_keyword_gaps_company ON competitor_keyword_gaps(company_id);
CREATE INDEX idx_keyword_gaps_priority ON competitor_keyword_gaps(priority);


-- ============================================================================
-- PART 4: SOCIAL & MARKETING
-- ============================================================================

-- Social media profiles
CREATE TABLE IF NOT EXISTS competitor_social_profiles (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    profile_url TEXT,
    profile_id VARCHAR(255),
    handle VARCHAR(255),

    is_verified BOOLEAN DEFAULT FALSE,
    profile_name TEXT,
    bio TEXT,

    follower_count INTEGER,
    following_count INTEGER,
    post_count INTEGER,

    avg_likes_per_post INTEGER,
    avg_comments_per_post INTEGER,
    engagement_rate DECIMAL(5,2),

    last_post_date DATE,
    posts_per_week DECIMAL(5,2),

    first_discovered_at TIMESTAMP DEFAULT NOW(),
    last_checked_at TIMESTAMP,

    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',

    UNIQUE(competitor_id, platform)
);

CREATE INDEX idx_social_profiles_competitor ON competitor_social_profiles(competitor_id);
CREATE INDEX idx_social_profiles_platform ON competitor_social_profiles(platform);

-- Social posts (limited tracking)
CREATE TABLE IF NOT EXISTS competitor_social_posts (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES competitor_social_profiles(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,

    post_id VARCHAR(255),
    post_url TEXT,

    post_type VARCHAR(50),
    content_text TEXT,
    media_urls JSONB DEFAULT '[]',
    hashtags JSONB DEFAULT '[]',

    like_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    view_count INTEGER,

    posted_at TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT NOW(),

    post_category VARCHAR(100),
    is_promotional BOOLEAN DEFAULT FALSE,

    metadata JSONB DEFAULT '{}',

    UNIQUE(platform, post_id)
);

CREATE INDEX idx_social_posts_competitor ON competitor_social_posts(competitor_id);
CREATE INDEX idx_social_posts_date ON competitor_social_posts(posted_at DESC);

-- Ad detection
CREATE TABLE IF NOT EXISTS competitor_ads (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,

    detection_method VARCHAR(100),
    detection_confidence DECIMAL(3,2),

    ad_id VARCHAR(255),
    ad_type VARCHAR(100),
    headline TEXT,
    description TEXT,
    destination_url TEXT,
    display_url TEXT,

    image_url TEXT,

    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP,

    detected_keywords JSONB DEFAULT '[]',

    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_ads_competitor ON competitor_ads(competitor_id);
CREATE INDEX idx_ads_platform ON competitor_ads(platform);
CREATE INDEX idx_ads_active ON competitor_ads(is_active) WHERE is_active = true;

-- Marketing activity events
CREATE TABLE IF NOT EXISTS competitor_marketing_events (
    id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,

    severity VARCHAR(20) DEFAULT 'info',
    title VARCHAR(255),
    description TEXT,

    related_table VARCHAR(100),
    related_id INTEGER,

    detected_at TIMESTAMP DEFAULT NOW(),

    alert_generated BOOLEAN DEFAULT FALSE,
    alert_id INTEGER REFERENCES competitor_alerts(id),

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_marketing_events_competitor ON competitor_marketing_events(competitor_id);
CREATE INDEX idx_marketing_events_type ON competitor_marketing_events(event_type);


-- ============================================================================
-- PART 5: MODULE TRACKING EXTENSIONS
-- ============================================================================

-- Add new module flags to competitors table
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_content_archive_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_content_archive_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_blog_track_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_blog_track_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_keyword_gaps_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_keyword_gaps_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_social_track_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_social_track_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_ad_detect_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_ad_detect_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_review_deep_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_review_deep_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_pricing_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_pricing_done BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'competitors' AND column_name = 'intel_marketing_done') THEN
        ALTER TABLE competitors ADD COLUMN intel_marketing_done BOOLEAN DEFAULT FALSE;
    END IF;
END $$;


-- ============================================================================
-- RECORD MIGRATION
-- ============================================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('051', 'Deep Intelligence Tables - Reviews, Pricing, Content, Social', NOW())
ON CONFLICT (version) DO NOTHING;

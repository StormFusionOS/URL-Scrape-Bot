-- ============================================================================
-- Migration 028: SEO Intelligence Enhancement Tables
-- ============================================================================
-- Adds comprehensive SEO data collection capabilities:
--
-- Phase 1: Core Web Vitals
--   - Add CWV columns to page_audits (lcp_ms, cls_value, fid_ms, etc.)
--
-- Phase 2: Keyword Intelligence
--   - keyword_metrics: Volume, difficulty, opportunity scores
--   - keyword_suggestions: Google autocomplete suggestions
--
-- Phase 3: Content Analysis
--   - content_analysis: Readability, freshness, topic clustering
--   - topic_clusters: K-means clustering of content
--
-- Phase 4: Competitive Intelligence
--   - backlink_gaps: Domains linking to competitors but not us
--   - keyword_gaps: Keywords competitors rank for that we don't
--   - engagement_signals: Traffic estimation proxies
--   - competitor_rankings_history: Position tracking over time
--   - ranking_trends: RISING, FALLING, STABLE classification
--
-- All data is collected via scraping and local analysis (no external APIs).
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('028', 'add_seo_enhancements', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- PHASE 1: CORE WEB VITALS ENHANCEMENTS
-- ============================================================================

-- Add CWV columns to existing page_audits table
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS lcp_ms DECIMAL(10,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS cls_value DECIMAL(6,4);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS fid_ms DECIMAL(10,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS tti_ms DECIMAL(10,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS fcp_ms DECIMAL(10,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS ttfb_ms DECIMAL(10,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS cwv_score DECIMAL(5,2);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS lcp_rating VARCHAR(20);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS cls_rating VARCHAR(20);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS fid_rating VARCHAR(20);
ALTER TABLE page_audits ADD COLUMN IF NOT EXISTS cwv_element TEXT;

-- Indexes for CWV filtering and reporting
CREATE INDEX IF NOT EXISTS idx_page_audits_lcp ON page_audits(lcp_ms);
CREATE INDEX IF NOT EXISTS idx_page_audits_cls ON page_audits(cls_value);
CREATE INDEX IF NOT EXISTS idx_page_audits_cwv_score ON page_audits(cwv_score DESC);
CREATE INDEX IF NOT EXISTS idx_page_audits_lcp_rating ON page_audits(lcp_rating);

COMMENT ON COLUMN page_audits.lcp_ms IS 'Largest Contentful Paint in milliseconds';
COMMENT ON COLUMN page_audits.cls_value IS 'Cumulative Layout Shift score (0-1+)';
COMMENT ON COLUMN page_audits.fid_ms IS 'First Input Delay in milliseconds';
COMMENT ON COLUMN page_audits.tti_ms IS 'Time to Interactive in milliseconds';
COMMENT ON COLUMN page_audits.fcp_ms IS 'First Contentful Paint in milliseconds';
COMMENT ON COLUMN page_audits.ttfb_ms IS 'Time to First Byte in milliseconds';
COMMENT ON COLUMN page_audits.cwv_score IS 'Composite Core Web Vitals score (0-100)';
COMMENT ON COLUMN page_audits.lcp_rating IS 'LCP rating: GOOD, NEEDS_IMPROVEMENT, POOR';
COMMENT ON COLUMN page_audits.cls_rating IS 'CLS rating: GOOD, NEEDS_IMPROVEMENT, POOR';
COMMENT ON COLUMN page_audits.fid_rating IS 'FID rating: GOOD, NEEDS_IMPROVEMENT, POOR';
COMMENT ON COLUMN page_audits.cwv_element IS 'Element selector for LCP target';

-- ============================================================================
-- PHASE 2: KEYWORD INTELLIGENCE TABLES
-- ============================================================================

-- Keyword metrics with SERP-based volume/difficulty estimation
CREATE TABLE IF NOT EXISTS keyword_metrics (
    metric_id SERIAL PRIMARY KEY,
    keyword_text VARCHAR(500) NOT NULL,

    -- Volume estimation (1-5 tier based on SERP signals)
    volume_tier INTEGER CHECK (volume_tier BETWEEN 1 AND 5),
    volume_signals JSONB,  -- Raw signals: result_count, features, etc.

    -- Difficulty calculation (0-100)
    keyword_difficulty INTEGER CHECK (keyword_difficulty BETWEEN 0 AND 100),
    difficulty_factors JSONB,  -- Breakdown: big_brands, auth_sites, content_depth

    -- Opportunity scoring
    opportunity_score DECIMAL(5,2),  -- Calculated opportunity
    current_position INTEGER,  -- Our current ranking (null if not ranking)

    -- Search intent classification
    search_intent VARCHAR(50),  -- informational, transactional, navigational, local

    -- Timestamps
    calculated_at TIMESTAMP DEFAULT NOW(),
    serp_snapshot_id INTEGER REFERENCES serp_snapshots(snapshot_id),

    CONSTRAINT unique_keyword_metric UNIQUE (keyword_text)
);

CREATE INDEX IF NOT EXISTS idx_keyword_metrics_text ON keyword_metrics(keyword_text);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_volume ON keyword_metrics(volume_tier DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_difficulty ON keyword_metrics(keyword_difficulty);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_opportunity ON keyword_metrics(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_intent ON keyword_metrics(search_intent);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_signals ON keyword_metrics USING GIN(volume_signals);

COMMENT ON TABLE keyword_metrics IS 'SERP-based keyword volume, difficulty, and opportunity metrics';

-- Keyword suggestions from Google Autocomplete
CREATE TABLE IF NOT EXISTS keyword_suggestions (
    suggestion_id SERIAL PRIMARY KEY,
    seed_keyword VARCHAR(500) NOT NULL,
    suggestion_text VARCHAR(500) NOT NULL,
    source VARCHAR(50) DEFAULT 'google_autocomplete',
    position INTEGER,  -- Position in autocomplete dropdown (1-10)
    suggestion_type VARCHAR(50),  -- normal, question, comparison, etc.
    discovered_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    frequency_count INTEGER DEFAULT 1,  -- How many times we've seen this

    CONSTRAINT unique_suggestion UNIQUE (seed_keyword, suggestion_text, source)
);

CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_seed ON keyword_suggestions(seed_keyword);
CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_text ON keyword_suggestions(suggestion_text);
CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_source ON keyword_suggestions(source);
CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_position ON keyword_suggestions(position);
CREATE INDEX IF NOT EXISTS idx_keyword_suggestions_discovered ON keyword_suggestions(discovered_at DESC);

COMMENT ON TABLE keyword_suggestions IS 'Keyword suggestions from autocomplete sources';

-- ============================================================================
-- PHASE 3: CONTENT ANALYSIS TABLES
-- ============================================================================

-- Topic clusters for content grouping
CREATE TABLE IF NOT EXISTS topic_clusters (
    cluster_id SERIAL PRIMARY KEY,
    cluster_name VARCHAR(255),
    representative_keyword VARCHAR(500),
    centroid_vector BYTEA,  -- Serialized embedding centroid
    keyword_count INTEGER DEFAULT 0,
    page_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB  -- Top keywords, themes, etc.
);

CREATE INDEX IF NOT EXISTS idx_topic_clusters_name ON topic_clusters(cluster_name);
CREATE INDEX IF NOT EXISTS idx_topic_clusters_keyword ON topic_clusters(representative_keyword);
CREATE INDEX IF NOT EXISTS idx_topic_clusters_metadata ON topic_clusters USING GIN(metadata);

COMMENT ON TABLE topic_clusters IS 'K-means topic clusters for content organization';

-- Content analysis with readability and freshness
CREATE TABLE IF NOT EXISTS content_analysis (
    analysis_id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES competitor_pages(page_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    domain VARCHAR(500),

    -- Readability metrics (Flesch-Kincaid, Gunning Fog)
    flesch_kincaid_grade DECIMAL(4,1),
    flesch_reading_ease DECIMAL(5,1),
    gunning_fog_index DECIMAL(4,1),
    avg_sentence_length DECIMAL(5,1),
    avg_word_length DECIMAL(4,2),
    complex_word_ratio DECIMAL(4,3),

    -- Content statistics
    word_count INTEGER,
    sentence_count INTEGER,
    paragraph_count INTEGER,
    heading_count INTEGER,
    image_count INTEGER,

    -- Freshness indicators
    published_date TIMESTAMP,
    modified_date TIMESTAMP,
    freshness_score DECIMAL(5,2),  -- 0-100 based on recency
    date_source VARCHAR(50),  -- schema, meta, http_header, inferred

    -- Topic clustering
    topic_cluster_id INTEGER REFERENCES topic_clusters(cluster_id),
    topic_relevance_score DECIMAL(5,3),  -- Distance from cluster centroid

    -- Timestamps
    analyzed_at TIMESTAMP DEFAULT NOW(),
    content_hash VARCHAR(64),  -- For change detection

    CONSTRAINT unique_content_analysis UNIQUE (url, analyzed_at)
);

CREATE INDEX IF NOT EXISTS idx_content_analysis_page ON content_analysis(page_id);
CREATE INDEX IF NOT EXISTS idx_content_analysis_url ON content_analysis(url);
CREATE INDEX IF NOT EXISTS idx_content_analysis_domain ON content_analysis(domain);
CREATE INDEX IF NOT EXISTS idx_content_analysis_fk_grade ON content_analysis(flesch_kincaid_grade);
CREATE INDEX IF NOT EXISTS idx_content_analysis_reading_ease ON content_analysis(flesch_reading_ease);
CREATE INDEX IF NOT EXISTS idx_content_analysis_cluster ON content_analysis(topic_cluster_id);
CREATE INDEX IF NOT EXISTS idx_content_analysis_freshness ON content_analysis(freshness_score DESC);
CREATE INDEX IF NOT EXISTS idx_content_analysis_analyzed ON content_analysis(analyzed_at DESC);

COMMENT ON TABLE content_analysis IS 'Readability, freshness, and topic analysis for pages';

-- ============================================================================
-- PHASE 4: COMPETITIVE INTELLIGENCE TABLES
-- ============================================================================

-- Backlink gaps (domains linking to competitors but not us)
CREATE TABLE IF NOT EXISTS backlink_gaps (
    gap_id SERIAL PRIMARY KEY,
    our_domain VARCHAR(500) NOT NULL,
    referring_domain VARCHAR(500) NOT NULL,

    -- Which competitors have links from this domain
    links_to_competitors TEXT[],  -- Array of competitor domains
    competitor_count INTEGER DEFAULT 0,

    -- Domain quality metrics
    domain_authority_estimate DECIMAL(5,2),  -- Estimated DA (0-100)
    dofollow_ratio DECIMAL(4,3),

    -- Prioritization
    acquisition_priority DECIMAL(5,2),  -- Calculated priority score
    priority_factors JSONB,  -- Breakdown of priority calculation

    -- Status tracking
    status VARCHAR(50) DEFAULT 'identified',  -- identified, contacted, acquired, rejected
    notes TEXT,

    -- Timestamps
    identified_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_backlink_gap UNIQUE (our_domain, referring_domain)
);

CREATE INDEX IF NOT EXISTS idx_backlink_gaps_our_domain ON backlink_gaps(our_domain);
CREATE INDEX IF NOT EXISTS idx_backlink_gaps_referring ON backlink_gaps(referring_domain);
CREATE INDEX IF NOT EXISTS idx_backlink_gaps_priority ON backlink_gaps(acquisition_priority DESC);
CREATE INDEX IF NOT EXISTS idx_backlink_gaps_status ON backlink_gaps(status);
CREATE INDEX IF NOT EXISTS idx_backlink_gaps_competitors ON backlink_gaps USING GIN(links_to_competitors);

COMMENT ON TABLE backlink_gaps IS 'Backlink acquisition opportunities from competitor analysis';

-- Keyword gaps (keywords competitors rank for that we don't)
CREATE TABLE IF NOT EXISTS keyword_gaps (
    gap_id SERIAL PRIMARY KEY,
    our_domain VARCHAR(500) NOT NULL,
    query_text VARCHAR(500) NOT NULL,

    -- Competitor ranking data
    competitor_rankings JSONB NOT NULL,  -- {competitor: position, ...}
    competitor_count INTEGER DEFAULT 0,
    avg_competitor_position DECIMAL(5,2),

    -- Our status
    our_position INTEGER,  -- null if not ranking

    -- Opportunity metrics
    opportunity_score DECIMAL(5,2),
    opportunity_factors JSONB,  -- demand, ease, serp_difficulty

    -- SERP characteristics
    serp_difficulty INTEGER,  -- 0-100
    has_featured_snippet BOOLEAN DEFAULT FALSE,
    serp_features TEXT[],  -- PAA, local_pack, knowledge_panel, etc.

    -- Status tracking
    status VARCHAR(50) DEFAULT 'identified',  -- identified, targeting, ranking, abandoned

    -- Timestamps
    identified_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_keyword_gap UNIQUE (our_domain, query_text)
);

CREATE INDEX IF NOT EXISTS idx_keyword_gaps_our_domain ON keyword_gaps(our_domain);
CREATE INDEX IF NOT EXISTS idx_keyword_gaps_query ON keyword_gaps(query_text);
CREATE INDEX IF NOT EXISTS idx_keyword_gaps_opportunity ON keyword_gaps(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_gaps_status ON keyword_gaps(status);
CREATE INDEX IF NOT EXISTS idx_keyword_gaps_rankings ON keyword_gaps USING GIN(competitor_rankings);

COMMENT ON TABLE keyword_gaps IS 'Keyword opportunities from competitor ranking analysis';

-- Engagement signals for traffic estimation
CREATE TABLE IF NOT EXISTS engagement_signals (
    signal_id SERIAL PRIMARY KEY,
    domain VARCHAR(500) NOT NULL,

    -- SERP visibility (sum of 1/position for all keywords)
    serp_visibility_score DECIMAL(8,4),
    keywords_ranking INTEGER,  -- Count of keywords in top 20
    avg_position DECIMAL(5,2),

    -- Social engagement (scraped)
    facebook_shares INTEGER,
    twitter_shares INTEGER,
    pinterest_shares INTEGER,
    linkedin_shares INTEGER,
    total_social_signals INTEGER,

    -- Review velocity
    review_velocity_30d INTEGER,  -- New reviews in last 30 days
    review_count_total INTEGER,
    avg_review_rating DECIMAL(3,2),

    -- Content freshness (aggregate)
    pages_updated_30d INTEGER,
    avg_content_age_days INTEGER,

    -- Backlink growth
    new_backlinks_30d INTEGER,
    lost_backlinks_30d INTEGER,
    backlink_velocity INTEGER,  -- Net change

    -- Calculated traffic estimate (relative score)
    relative_traffic_score DECIMAL(5,2),  -- 0-100
    traffic_factors JSONB,  -- Weight breakdown

    -- Timestamps
    captured_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_engagement_signal UNIQUE (domain, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_engagement_signals_domain ON engagement_signals(domain);
CREATE INDEX IF NOT EXISTS idx_engagement_signals_traffic ON engagement_signals(relative_traffic_score DESC);
CREATE INDEX IF NOT EXISTS idx_engagement_signals_visibility ON engagement_signals(serp_visibility_score DESC);
CREATE INDEX IF NOT EXISTS idx_engagement_signals_captured ON engagement_signals(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_engagement_signals_factors ON engagement_signals USING GIN(traffic_factors);

COMMENT ON TABLE engagement_signals IS 'Traffic estimation from engagement proxy signals';

-- Competitor rankings history for trend detection
CREATE TABLE IF NOT EXISTS competitor_rankings_history (
    history_id SERIAL PRIMARY KEY,
    competitor_id INTEGER REFERENCES competitors(competitor_id) ON DELETE CASCADE,
    query_id INTEGER REFERENCES search_queries(query_id) ON DELETE CASCADE,
    domain VARCHAR(500) NOT NULL,
    query_text VARCHAR(500) NOT NULL,

    -- Position data
    position INTEGER,
    previous_position INTEGER,
    position_delta INTEGER,

    -- SERP snapshot reference
    snapshot_id INTEGER REFERENCES serp_snapshots(snapshot_id),

    -- Timestamps
    captured_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rankings_history_competitor ON competitor_rankings_history(competitor_id);
CREATE INDEX IF NOT EXISTS idx_rankings_history_query ON competitor_rankings_history(query_id);
CREATE INDEX IF NOT EXISTS idx_rankings_history_domain ON competitor_rankings_history(domain);
CREATE INDEX IF NOT EXISTS idx_rankings_history_position ON competitor_rankings_history(position);
CREATE INDEX IF NOT EXISTS idx_rankings_history_captured ON competitor_rankings_history(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_rankings_history_delta ON competitor_rankings_history(position_delta);

COMMENT ON TABLE competitor_rankings_history IS 'Historical ranking positions for trend analysis';

-- Ranking trends (aggregated trend classification)
CREATE TABLE IF NOT EXISTS ranking_trends (
    trend_id SERIAL PRIMARY KEY,
    domain VARCHAR(500) NOT NULL,
    query_text VARCHAR(500) NOT NULL,

    -- Trend classification
    trend_type VARCHAR(50) NOT NULL,  -- RISING, FALLING, STABLE, VOLATILE, NEW, LOST

    -- Position metrics
    current_position INTEGER,
    position_7d_ago INTEGER,
    position_30d_ago INTEGER,
    position_change_7d INTEGER,
    position_change_30d INTEGER,

    -- Volatility metrics
    std_deviation DECIMAL(5,2),
    volatility_score DECIMAL(5,2),

    -- Metadata
    analysis_period_days INTEGER DEFAULT 30,
    data_points INTEGER,  -- Number of snapshots analyzed

    -- Timestamps
    analyzed_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_ranking_trend UNIQUE (domain, query_text)
);

CREATE INDEX IF NOT EXISTS idx_ranking_trends_domain ON ranking_trends(domain);
CREATE INDEX IF NOT EXISTS idx_ranking_trends_query ON ranking_trends(query_text);
CREATE INDEX IF NOT EXISTS idx_ranking_trends_type ON ranking_trends(trend_type);
CREATE INDEX IF NOT EXISTS idx_ranking_trends_change ON ranking_trends(position_change_7d);
CREATE INDEX IF NOT EXISTS idx_ranking_trends_analyzed ON ranking_trends(analyzed_at DESC);

COMMENT ON TABLE ranking_trends IS 'Ranking trend classification and velocity tracking';

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Top backlink gap opportunities
CREATE OR REPLACE VIEW v_backlink_gap_opportunities AS
SELECT
    bg.gap_id,
    bg.our_domain,
    bg.referring_domain,
    bg.competitor_count,
    bg.domain_authority_estimate,
    bg.acquisition_priority,
    bg.status,
    array_to_string(bg.links_to_competitors, ', ') as competitors_linked
FROM backlink_gaps bg
WHERE bg.status = 'identified'
ORDER BY bg.acquisition_priority DESC
LIMIT 100;

COMMENT ON VIEW v_backlink_gap_opportunities IS 'Top 100 backlink acquisition opportunities';

-- View: Top keyword gap opportunities
CREATE OR REPLACE VIEW v_keyword_gap_opportunities AS
SELECT
    kg.gap_id,
    kg.our_domain,
    kg.query_text,
    kg.competitor_count,
    kg.avg_competitor_position,
    kg.opportunity_score,
    kg.has_featured_snippet,
    kg.status
FROM keyword_gaps kg
WHERE kg.status = 'identified'
ORDER BY kg.opportunity_score DESC
LIMIT 100;

COMMENT ON VIEW v_keyword_gap_opportunities IS 'Top 100 keyword targeting opportunities';

-- View: CWV performance summary
CREATE OR REPLACE VIEW v_cwv_summary AS
SELECT
    url,
    audited_at,
    lcp_ms,
    lcp_rating,
    cls_value,
    cls_rating,
    fid_ms,
    fid_rating,
    cwv_score,
    CASE
        WHEN lcp_rating = 'GOOD' AND cls_rating = 'GOOD' AND fid_rating = 'GOOD' THEN 'PASSED'
        WHEN lcp_rating = 'POOR' OR cls_rating = 'POOR' OR fid_rating = 'POOR' THEN 'FAILED'
        ELSE 'NEEDS_IMPROVEMENT'
    END as cwv_assessment
FROM page_audits
WHERE lcp_ms IS NOT NULL
ORDER BY audited_at DESC;

COMMENT ON VIEW v_cwv_summary IS 'Core Web Vitals performance summary with pass/fail assessment';

-- View: Rising competitors
CREATE OR REPLACE VIEW v_rising_competitors AS
SELECT
    rt.domain,
    rt.query_text,
    rt.current_position,
    rt.position_change_7d,
    rt.position_change_30d,
    rt.trend_type
FROM ranking_trends rt
WHERE rt.trend_type = 'RISING'
    AND rt.position_change_7d < -3
ORDER BY rt.position_change_7d ASC
LIMIT 50;

COMMENT ON VIEW v_rising_competitors IS 'Competitors gaining significant ranking positions';

-- View: Content readability summary by domain
CREATE OR REPLACE VIEW v_readability_by_domain AS
SELECT
    domain,
    COUNT(*) as pages_analyzed,
    AVG(flesch_kincaid_grade) as avg_grade_level,
    AVG(flesch_reading_ease) as avg_reading_ease,
    AVG(gunning_fog_index) as avg_fog_index,
    AVG(word_count) as avg_word_count,
    AVG(freshness_score) as avg_freshness
FROM content_analysis
GROUP BY domain
ORDER BY pages_analyzed DESC;

COMMENT ON VIEW v_readability_by_domain IS 'Content readability metrics aggregated by domain';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function: Calculate keyword opportunity score
CREATE OR REPLACE FUNCTION calc_keyword_opportunity(
    p_volume_tier INTEGER,
    p_difficulty INTEGER,
    p_current_position INTEGER
) RETURNS DECIMAL(5,2) AS $$
DECLARE
    v_opportunity DECIMAL(5,2);
    v_volume_weight DECIMAL(5,2);
    v_difficulty_weight DECIMAL(5,2);
    v_position_bonus DECIMAL(5,2);
BEGIN
    -- Volume weight (tier 5 = 100, tier 1 = 20)
    v_volume_weight := p_volume_tier * 20;

    -- Difficulty weight (lower = better, inverted)
    v_difficulty_weight := 100 - p_difficulty;

    -- Position bonus (closer to page 1 = higher bonus)
    IF p_current_position IS NULL THEN
        v_position_bonus := 0;  -- Not ranking yet
    ELSIF p_current_position <= 10 THEN
        v_position_bonus := 30;  -- Page 1
    ELSIF p_current_position <= 20 THEN
        v_position_bonus := 20;  -- Page 2
    ELSIF p_current_position <= 50 THEN
        v_position_bonus := 10;  -- Pages 3-5
    ELSE
        v_position_bonus := 5;  -- Deep pages
    END IF;

    -- Weighted calculation
    v_opportunity := (v_volume_weight * 0.35) + (v_difficulty_weight * 0.45) + (v_position_bonus * 0.20);

    RETURN LEAST(100, GREATEST(0, v_opportunity));
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calc_keyword_opportunity IS 'Calculate keyword opportunity score from volume, difficulty, and position';

-- Function: Classify ranking trend
CREATE OR REPLACE FUNCTION classify_ranking_trend(
    p_position_change_7d INTEGER,
    p_position_change_30d INTEGER,
    p_std_deviation DECIMAL
) RETURNS VARCHAR(50) AS $$
BEGIN
    -- Check for volatility first
    IF p_std_deviation > 5 THEN
        RETURN 'VOLATILE';
    END IF;

    -- Rising trend (negative change = better position)
    IF p_position_change_7d < -3 OR p_position_change_30d < -5 THEN
        RETURN 'RISING';
    END IF;

    -- Falling trend (positive change = worse position)
    IF p_position_change_7d > 3 OR p_position_change_30d > 5 THEN
        RETURN 'FALLING';
    END IF;

    -- Stable
    RETURN 'STABLE';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION classify_ranking_trend IS 'Classify ranking trend as RISING, FALLING, STABLE, or VOLATILE';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    table_count INTEGER;
    new_columns INTEGER;
BEGIN
    -- Count new tables
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_name IN (
        'keyword_metrics', 'keyword_suggestions',
        'topic_clusters', 'content_analysis',
        'backlink_gaps', 'keyword_gaps',
        'engagement_signals', 'competitor_rankings_history', 'ranking_trends'
    );

    -- Count new CWV columns in page_audits
    SELECT COUNT(*) INTO new_columns
    FROM information_schema.columns
    WHERE table_name = 'page_audits'
    AND column_name IN ('lcp_ms', 'cls_value', 'fid_ms', 'cwv_score');

    RAISE NOTICE 'Migration 028 completed successfully.';
    RAISE NOTICE '  - % new SEO intelligence tables created', table_count;
    RAISE NOTICE '  - % CWV columns added to page_audits', new_columns;
    RAISE NOTICE '';
    RAISE NOTICE 'Phase 1 (Core Web Vitals):';
    RAISE NOTICE '  - page_audits: lcp_ms, cls_value, fid_ms, cwv_score';
    RAISE NOTICE '';
    RAISE NOTICE 'Phase 2 (Keyword Intelligence):';
    RAISE NOTICE '  - keyword_metrics: Volume, difficulty, opportunity';
    RAISE NOTICE '  - keyword_suggestions: Autocomplete data';
    RAISE NOTICE '';
    RAISE NOTICE 'Phase 3 (Content Analysis):';
    RAISE NOTICE '  - topic_clusters: K-means clustering';
    RAISE NOTICE '  - content_analysis: Readability, freshness';
    RAISE NOTICE '';
    RAISE NOTICE 'Phase 4 (Competitive Intelligence):';
    RAISE NOTICE '  - backlink_gaps: Link acquisition opportunities';
    RAISE NOTICE '  - keyword_gaps: Keyword targeting opportunities';
    RAISE NOTICE '  - engagement_signals: Traffic estimation';
    RAISE NOTICE '  - competitor_rankings_history: Position tracking';
    RAISE NOTICE '  - ranking_trends: Trend classification';
END $$;

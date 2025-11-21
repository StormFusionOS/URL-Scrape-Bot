-- ============================================================================
-- Migration 022: Create SERP PAA (People Also Ask) Table
-- ============================================================================
-- Creates dedicated table for storing PAA questions as first-class data
-- instead of embedded in JSONB. Enables:
-- - Delta detection (questions added/removed over time)
-- - Direct querying of questions
-- - FAQ generation from PAA trends
-- - Historical PAA tracking per query
-- ============================================================================

-- Track this migration
INSERT INTO schema_migrations (version, name, applied_at)
VALUES ('022', 'create_serp_paa_table', NOW())
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- CREATE serp_paa TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS serp_paa (
    -- Primary Key
    paa_id SERIAL PRIMARY KEY,

    -- Foreign Keys
    snapshot_id INTEGER NOT NULL REFERENCES serp_snapshots(snapshot_id) ON DELETE CASCADE,
    query_id INTEGER NOT NULL REFERENCES search_queries(query_id) ON DELETE CASCADE,

    -- PAA Question Data
    question TEXT NOT NULL,
    answer_snippet TEXT,
    source_url TEXT,
    source_domain VARCHAR(255),
    position INTEGER,  -- Position in PAA list (1-based)

    -- Timestamps
    captured_at TIMESTAMP DEFAULT NOW() NOT NULL,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),

    -- Extended Metadata
    metadata JSONB,

    -- Constraints
    CONSTRAINT chk_position_positive CHECK (position > 0)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Foreign key indexes
CREATE INDEX IF NOT EXISTS idx_serp_paa_snapshot
ON serp_paa(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_serp_paa_query
ON serp_paa(query_id);

-- Position index for ordering
CREATE INDEX IF NOT EXISTS idx_serp_paa_position
ON serp_paa(snapshot_id, position);

-- Source domain index for source analysis
CREATE INDEX IF NOT EXISTS idx_serp_paa_source_domain
ON serp_paa(source_domain);

-- Time-based indexes
CREATE INDEX IF NOT EXISTS idx_serp_paa_captured
ON serp_paa(captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_serp_paa_first_seen
ON serp_paa(query_id, first_seen_at);

-- Full-text search on questions
CREATE INDEX IF NOT EXISTS idx_serp_paa_question_fulltext
ON serp_paa USING GIN (to_tsvector('english', question));

-- Metadata JSONB index
CREATE INDEX IF NOT EXISTS idx_serp_paa_metadata
ON serp_paa USING GIN (metadata);

-- Composite index for query + question deduplication
CREATE INDEX IF NOT EXISTS idx_serp_paa_query_question
ON serp_paa(query_id, question);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE serp_paa IS
'People Also Ask questions extracted from Google SERPs. Enables PAA delta detection and FAQ generation.';

COMMENT ON COLUMN serp_paa.paa_id IS 'Primary key';
COMMENT ON COLUMN serp_paa.snapshot_id IS 'Links to serp_snapshots (specific SERP capture)';
COMMENT ON COLUMN serp_paa.query_id IS 'Links to search_queries (which query this PAA appeared for)';
COMMENT ON COLUMN serp_paa.question IS 'The PAA question text';
COMMENT ON COLUMN serp_paa.answer_snippet IS 'Answer text from the PAA dropdown (up to 500 chars)';
COMMENT ON COLUMN serp_paa.source_url IS 'URL of the source page answering this question';
COMMENT ON COLUMN serp_paa.source_domain IS 'Domain of the source (extracted from source_url)';
COMMENT ON COLUMN serp_paa.position IS 'Position in PAA list (1 = first question)';
COMMENT ON COLUMN serp_paa.captured_at IS 'When this PAA was captured from SERP';
COMMENT ON COLUMN serp_paa.first_seen_at IS 'First time this question appeared for this query';
COMMENT ON COLUMN serp_paa.last_seen_at IS 'Most recent time this question appeared';
COMMENT ON COLUMN serp_paa.metadata IS 'Extended fields and raw data (JSONB)';

-- ============================================================================
-- HELPER VIEW: PAA Question Frequency
-- ============================================================================

CREATE OR REPLACE VIEW v_paa_question_frequency AS
SELECT
    paa.query_id,
    sq.query_text,
    paa.question,
    COUNT(DISTINCT paa.snapshot_id) as appearance_count,
    AVG(paa.position) as avg_position,
    MIN(paa.first_seen_at) as earliest_seen,
    MAX(paa.last_seen_at) as most_recent_seen,
    ARRAY_AGG(DISTINCT paa.source_domain) as source_domains
FROM serp_paa paa
JOIN search_queries sq ON paa.query_id = sq.query_id
GROUP BY paa.query_id, sq.query_text, paa.question
ORDER BY appearance_count DESC, avg_position;

COMMENT ON VIEW v_paa_question_frequency IS
'Shows how often each PAA question appears for each query with position stats';

-- ============================================================================
-- HELPER VIEW: PAA Delta Detection (Questions Added/Removed)
-- ============================================================================

CREATE OR REPLACE VIEW v_paa_delta_recent AS
WITH ranked_snapshots AS (
    SELECT
        query_id,
        snapshot_id,
        captured_at,
        ROW_NUMBER() OVER (PARTITION BY query_id ORDER BY captured_at DESC) as rn
    FROM serp_snapshots
),
current_paa AS (
    SELECT
        paa.query_id,
        paa.question
    FROM serp_paa paa
    JOIN ranked_snapshots rs ON paa.snapshot_id = rs.snapshot_id
    WHERE rs.rn = 1
),
previous_paa AS (
    SELECT
        paa.query_id,
        paa.question
    FROM serp_paa paa
    JOIN ranked_snapshots rs ON paa.snapshot_id = rs.snapshot_id
    WHERE rs.rn = 2
)
SELECT
    COALESCE(c.query_id, p.query_id) as query_id,
    sq.query_text,
    c.question as current_question,
    p.question as previous_question,
    CASE
        WHEN c.question IS NOT NULL AND p.question IS NULL THEN 'added'
        WHEN c.question IS NULL AND p.question IS NOT NULL THEN 'removed'
        ELSE 'unchanged'
    END as change_type
FROM current_paa c
FULL OUTER JOIN previous_paa p ON c.query_id = p.query_id AND c.question = p.question
JOIN search_queries sq ON COALESCE(c.query_id, p.query_id) = sq.query_id
WHERE (c.question IS NULL OR p.question IS NULL)
ORDER BY query_id, change_type;

COMMENT ON VIEW v_paa_delta_recent IS
'Compares most recent 2 SERP snapshots to detect which PAA questions were added or removed';

-- ============================================================================
-- HELPER VIEW: Top PAA Source Domains
-- ============================================================================

CREATE OR REPLACE VIEW v_paa_top_sources AS
SELECT
    source_domain,
    COUNT(*) as total_paa_answers,
    COUNT(DISTINCT query_id) as queries_answered,
    AVG(position) as avg_position,
    MIN(first_seen_at) as earliest_appearance,
    MAX(last_seen_at) as most_recent_appearance
FROM serp_paa
WHERE source_domain IS NOT NULL
GROUP BY source_domain
ORDER BY total_paa_answers DESC;

COMMENT ON VIEW v_paa_top_sources IS
'Shows which domains appear most frequently as PAA answer sources';

-- ============================================================================
-- HELPER FUNCTION: Get PAA Questions for Query
-- ============================================================================

CREATE OR REPLACE FUNCTION get_paa_for_query(
    p_query_id INT,
    p_limit INT DEFAULT 20
)
RETURNS TABLE (
    question TEXT,
    answer_snippet TEXT,
    source_url TEXT,
    paa_position INT,
    appearance_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        paa.question,
        paa.answer_snippet,
        paa.source_url,
        paa.position as paa_position,
        COUNT(DISTINCT paa.snapshot_id) as appearance_count
    FROM serp_paa paa
    WHERE paa.query_id = p_query_id
    GROUP BY paa.question, paa.answer_snippet, paa.source_url, paa.position
    ORDER BY appearance_count DESC, paa.position
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_paa_for_query IS
'Get PAA questions for a specific query, ordered by frequency and position';

-- ============================================================================
-- HELPER FUNCTION: Upsert PAA Question
-- ============================================================================

CREATE OR REPLACE FUNCTION upsert_paa_question(
    p_snapshot_id INT,
    p_query_id INT,
    p_question TEXT,
    p_answer_snippet TEXT DEFAULT NULL,
    p_source_url TEXT DEFAULT NULL,
    p_source_domain VARCHAR(255) DEFAULT NULL,
    p_position INT DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
)
RETURNS INT AS $$
DECLARE
    v_paa_id INT;
    v_existing_paa_id INT;
BEGIN
    -- Check if this exact question already exists for this snapshot
    SELECT paa_id INTO v_existing_paa_id
    FROM serp_paa
    WHERE snapshot_id = p_snapshot_id
    AND question = p_question;

    IF v_existing_paa_id IS NOT NULL THEN
        -- Update existing
        UPDATE serp_paa
        SET
            answer_snippet = COALESCE(p_answer_snippet, answer_snippet),
            source_url = COALESCE(p_source_url, source_url),
            source_domain = COALESCE(p_source_domain, source_domain),
            position = COALESCE(p_position, position),
            last_seen_at = NOW(),
            metadata = COALESCE(p_metadata, metadata)
        WHERE paa_id = v_existing_paa_id;

        RETURN v_existing_paa_id;
    ELSE
        -- Insert new
        INSERT INTO serp_paa (
            snapshot_id,
            query_id,
            question,
            answer_snippet,
            source_url,
            source_domain,
            position,
            metadata
        ) VALUES (
            p_snapshot_id,
            p_query_id,
            p_question,
            p_answer_snippet,
            p_source_url,
            p_source_domain,
            p_position,
            p_metadata
        )
        RETURNING paa_id INTO v_paa_id;

        RETURN v_paa_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION upsert_paa_question IS
'Insert or update a PAA question. Updates last_seen_at if question already exists for this snapshot.';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    index_count INTEGER;
    view_count INTEGER;
    function_count INTEGER;
BEGIN
    -- Check table exists
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'serp_paa'
    ) INTO table_exists;

    IF NOT table_exists THEN
        RAISE WARNING 'Migration 022: serp_paa table was not created';
        RETURN;
    END IF;

    -- Count indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'serp_paa';

    -- Count views
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_name LIKE 'v_paa%';

    -- Count functions
    SELECT COUNT(*) INTO function_count
    FROM information_schema.routines
    WHERE routine_name LIKE '%paa%';

    RAISE NOTICE 'Migration 022 completed successfully.';
    RAISE NOTICE '  - serp_paa table created';
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - % views created', view_count;
    RAISE NOTICE '  - % functions created', function_count;
END $$;

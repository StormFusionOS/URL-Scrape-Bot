-- Migration: Add Claude Auto-Tuning System Tables
-- Created: 2025-12-05
-- Purpose: Support Claude 3.5 Sonnet review queue, audit trail, prompt versioning, and rate limiting

-- ==============================================================================
-- TABLE 1: claude_review_queue
-- ==============================================================================
-- Queue of companies waiting for Claude review
-- Priority-based processing (lower number = higher priority)

CREATE TABLE IF NOT EXISTS claude_review_queue (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 100,  -- Lower = higher priority (10=urgent, 50=borderline, 100=normal)
    score DECIMAL(5,4),             -- Original verification score (0.45-0.55 borderline range)
    queued_at TIMESTAMP DEFAULT NOW(),
    processing_started_at TIMESTAMP NULL,
    processed_at TIMESTAMP NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, completed, failed
    retry_count INTEGER DEFAULT 0,
    error_message TEXT NULL,
    last_error_at TIMESTAMP NULL,

    CONSTRAINT chk_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

-- Indexes for efficient queue processing
CREATE INDEX idx_queue_status_priority ON claude_review_queue(status, priority, queued_at)
    WHERE status IN ('pending', 'processing');

CREATE INDEX idx_queue_company ON claude_review_queue(company_id);

CREATE INDEX idx_queue_processed_at ON claude_review_queue(processed_at)
    WHERE processed_at IS NOT NULL;

-- Partial unique constraint: only one pending/processing entry per company
CREATE UNIQUE INDEX idx_queue_unique_pending_company ON claude_review_queue(company_id, status)
    WHERE status IN ('pending', 'processing');


-- ==============================================================================
-- TABLE 2: claude_review_audit
-- ==============================================================================
-- Comprehensive audit trail of all Claude reviews
-- Stores input context, Claude's decision, reasoning, and performance metrics

CREATE TABLE IF NOT EXISTS claude_review_audit (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    reviewed_at TIMESTAMP DEFAULT NOW(),

    -- Input context (what was sent to Claude)
    input_score DECIMAL(5,4),              -- Verification score
    input_metadata JSONB,                   -- All signals sent to Claude (ML predictions, red flags, etc.)
    prompt_version VARCHAR(50),             -- Prompt version used for this review

    -- Claude's response
    decision VARCHAR(20) NOT NULL,          -- approve, deny, unclear
    confidence DECIMAL(5,4),                -- 0.0-1.0
    reasoning TEXT,                         -- Claude's explanation
    primary_services TEXT[],                -- Extracted services (e.g., ['pressure washing', 'window cleaning'])
    identified_red_flags TEXT[],            -- Red flags Claude identified
    is_provider BOOLEAN,                    -- True if legitimate provider
    raw_response JSONB,                     -- Full JSON response from Claude

    -- Performance metrics
    api_latency_ms INTEGER,                 -- How long the API call took
    tokens_input INTEGER,                   -- Input tokens
    tokens_output INTEGER,                  -- Output tokens
    cached_tokens INTEGER,                  -- Tokens served from cache
    cost_estimate DECIMAL(10,6),           -- Estimated cost in USD

    -- Human override tracking
    human_reviewed BOOLEAN DEFAULT FALSE,
    human_decision VARCHAR(20) NULL,        -- If human overrode Claude
    human_reviewed_at TIMESTAMP NULL,

    CONSTRAINT chk_decision CHECK (decision IN ('approve', 'deny', 'unclear')),
    CONSTRAINT chk_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_human_decision CHECK (human_decision IN ('approve', 'deny', 'provider', 'non_provider') OR human_decision IS NULL)
);

-- Indexes for analytics and monitoring
CREATE INDEX idx_audit_company ON claude_review_audit(company_id);
CREATE INDEX idx_audit_reviewed_at ON claude_review_audit(reviewed_at DESC);
CREATE INDEX idx_audit_prompt_version ON claude_review_audit(prompt_version);
CREATE INDEX idx_audit_decision ON claude_review_audit(decision);
CREATE INDEX idx_audit_human_reviewed ON claude_review_audit(company_id, human_reviewed)
    WHERE human_reviewed = TRUE;

-- JSONB indexes for filtering by metadata
CREATE INDEX idx_audit_input_metadata ON claude_review_audit USING GIN (input_metadata);
CREATE INDEX idx_audit_raw_response ON claude_review_audit USING GIN (raw_response);


-- ==============================================================================
-- TABLE 3: claude_prompt_versions
-- ==============================================================================
-- Version control for Claude prompts
-- Tracks performance metrics for each prompt version to enable A/B testing

CREATE TABLE IF NOT EXISTS claude_prompt_versions (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) UNIQUE NOT NULL,    -- e.g., 'v1.0', 'v2.3'
    prompt_text TEXT NOT NULL,              -- Full system prompt
    few_shot_examples JSONB,                -- Array of example objects
    deployed_at TIMESTAMP DEFAULT NOW(),
    deprecated_at TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,         -- Only one version should be active

    -- Performance metrics (updated periodically)
    total_reviews INTEGER DEFAULT 0,
    accuracy_vs_human DECIMAL(5,4) NULL,    -- % agreement with human labels
    avg_confidence DECIMAL(5,4) NULL,
    approval_rate DECIMAL(5,4) NULL,        -- % of approvals vs total
    avg_latency_ms INTEGER NULL,

    notes TEXT,                             -- Description of changes in this version
    created_by VARCHAR(100) DEFAULT 'system'
);

-- Only one active version at a time
CREATE UNIQUE INDEX idx_prompt_active ON claude_prompt_versions(is_active)
    WHERE is_active = TRUE;

CREATE INDEX idx_prompt_version ON claude_prompt_versions(version);
CREATE INDEX idx_prompt_deployed ON claude_prompt_versions(deployed_at DESC);

-- JSONB index for few-shot examples
CREATE INDEX idx_prompt_examples ON claude_prompt_versions USING GIN (few_shot_examples);


-- ==============================================================================
-- TABLE 4: claude_rate_limits
-- ==============================================================================
-- Track API usage per hour for rate limiting and cost monitoring
-- Helps ensure we stay within Claude Pro limits (50 req/min)

CREATE TABLE IF NOT EXISTS claude_rate_limits (
    id SERIAL PRIMARY KEY,
    hour_bucket TIMESTAMP NOT NULL,         -- Truncated to hour (e.g., '2025-12-05 14:00:00')
    requests_made INTEGER DEFAULT 0,
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    cost_estimate DECIMAL(10,6) DEFAULT 0,  -- Total cost for this hour
    updated_at TIMESTAMP DEFAULT NOW()
);

-- One row per hour
CREATE UNIQUE INDEX idx_rate_limits_hour ON claude_rate_limits(hour_bucket);

CREATE INDEX idx_rate_limits_updated ON claude_rate_limits(updated_at DESC);


-- ==============================================================================
-- SEED DATA: Initial Prompt Version
-- ==============================================================================
-- Create v1.0 prompt as starting point

INSERT INTO claude_prompt_versions (version, prompt_text, few_shot_examples, notes, is_active)
VALUES (
    'v1.0',
    'You are a business verification specialist. Your task is to determine if a company is a legitimate service provider (e.g., pressure washing, window cleaning) or a non-provider (directory, equipment seller, training course, blog, lead generation agency).

## Context
You have access to:
- Automated verification signals (scores, ML predictions, red flags)
- Website content (services, about, homepage text)
- Business info (name, contact, location)

## Decision Criteria
APPROVE (legitimate provider) if:
- Offers direct services to customers (residential or commercial)
- Has clear contact info (phone, address, or service area)
- No red flags indicating directory/agency/franchise

DENY (non-provider) if:
- Directory or listing site
- Equipment sales only
- Training courses only
- Lead generation agency
- Blog or information-only site
- Franchise directory

UNCLEAR if:
- Insufficient information
- Conflicting signals
- Legitimate provider BUT also sells equipment/training

## Output Format
Respond with JSON:
{
  "decision": "approve" | "deny" | "unclear",
  "confidence": 0.85,  // 0.0-1.0
  "reasoning": "Brief explanation of decision (2-3 sentences)",
  "primary_services": ["pressure washing", "window cleaning"],
  "red_flags": ["franchise"] | [],
  "is_provider": true | false
}',
    '[]'::jsonb,  -- Empty examples initially - will be populated by optimizer
    'Initial prompt version - baseline for testing',
    TRUE
);


-- ==============================================================================
-- GRANT PERMISSIONS (if using specific database user)
-- ==============================================================================
-- Uncomment if you have a dedicated application user

-- GRANT SELECT, INSERT, UPDATE, DELETE ON claude_review_queue TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON claude_review_audit TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON claude_prompt_versions TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON claude_rate_limits TO your_app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO your_app_user;


-- ==============================================================================
-- VERIFICATION QUERIES
-- ==============================================================================

-- Verify tables were created
SELECT
    tablename,
    schemaname
FROM pg_tables
WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits')
ORDER BY tablename;

-- Verify indexes
SELECT
    tablename,
    indexname
FROM pg_indexes
WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits')
ORDER BY tablename, indexname;

-- Verify initial prompt version
SELECT version, deployed_at, is_active FROM claude_prompt_versions;

-- Show table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits')
ORDER BY tablename;

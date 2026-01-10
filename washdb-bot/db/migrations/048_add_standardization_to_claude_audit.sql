-- Migration 048: Add standardization columns to claude_review_audit
-- Purpose: Capture name standardization data alongside verification for training data
-- Date: 2026-01-03

-- Add standardization columns to claude_review_audit table
ALTER TABLE claude_review_audit
ADD COLUMN IF NOT EXISTS standardized_name TEXT,
ADD COLUMN IF NOT EXISTS standardization_confidence FLOAT DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS standardization_source TEXT,
ADD COLUMN IF NOT EXISTS standardization_reasoning TEXT;

-- Add index for querying standardization results
CREATE INDEX IF NOT EXISTS idx_claude_audit_standardization
ON claude_review_audit (standardized_name)
WHERE standardized_name IS NOT NULL;

-- Add index for high-confidence standardizations (useful for training data export)
CREATE INDEX IF NOT EXISTS idx_claude_audit_std_confidence
ON claude_review_audit (standardization_confidence DESC)
WHERE standardization_confidence >= 0.7;

-- Comment on columns
COMMENT ON COLUMN claude_review_audit.standardized_name IS 'Business name extracted by Claude from website data';
COMMENT ON COLUMN claude_review_audit.standardization_confidence IS 'Confidence score (0.0-1.0) for name extraction';
COMMENT ON COLUMN claude_review_audit.standardization_source IS 'Source of name: json_ld, og_tag, title, h1, copyright, domain';
COMMENT ON COLUMN claude_review_audit.standardization_reasoning IS 'Claude reasoning for name extraction (for training data)';

-- View for exporting unified training data (verification + standardization)
CREATE OR REPLACE VIEW v_claude_training_data AS
SELECT
    cra.company_id,
    c.name AS original_name,
    c.website,
    cra.reviewed_at,
    -- Verification training data
    cra.decision,
    cra.confidence AS verification_confidence,
    cra.reasoning AS verification_reasoning,
    cra.primary_services,
    cra.identified_red_flags,
    cra.is_provider,
    -- Standardization training data
    cra.standardized_name,
    cra.standardization_confidence,
    cra.standardization_source,
    cra.standardization_reasoning,
    -- Input context (for prompt reconstruction)
    cra.input_metadata,
    c.parse_metadata->'title' AS page_title,
    c.parse_metadata->'og_site_name' AS og_site_name,
    c.parse_metadata->'h1_text' AS h1_text
FROM claude_review_audit cra
JOIN companies c ON c.id = cra.company_id
WHERE cra.confidence >= 0.7  -- Only high-confidence for training
ORDER BY cra.reviewed_at DESC;

COMMENT ON VIEW v_claude_training_data IS 'Export view for unified LLM training data (verification + standardization)';

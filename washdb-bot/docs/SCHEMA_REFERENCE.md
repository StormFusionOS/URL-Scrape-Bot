# washdb-bot Database Schema Reference

> **Last Updated:** 2025-11-21
> **Database:** `washbot_db`
> **Version:** 1.0
> **Status:** Canonical Source of Truth

This document describes the actual implemented database schema for washdb-bot's SEO Intelligence system. It supersedes Section 3.5 of the internal PDF guide where schema drift has occurred.

---

## Table of Contents

1. [Backlinks Table](#backlinks-table)
2. [Citations Table](#citations-table)
3. [Supporting Tables](#supporting-tables)
4. [Schema Evolution Notes](#schema-evolution-notes)

---

## Backlinks Table

Tracks inbound links from external sites to target domains. Essential for link building analysis, competitive intelligence, and Local Authority Score (LAS) calculation.

### Schema Definition

```sql
CREATE TABLE IF NOT EXISTS backlinks (
    backlink_id SERIAL PRIMARY KEY,
    target_domain VARCHAR(500) NOT NULL,     -- Domain being linked to
    target_url TEXT NOT NULL,                -- Full URL being linked to
    source_domain VARCHAR(500) NOT NULL,     -- Domain containing the backlink
    source_url TEXT NOT NULL,                -- Full URL containing the backlink
    anchor_text TEXT,                        -- Link anchor text (visible clickable text)
    link_type VARCHAR(50),                   -- 'dofollow', 'nofollow', 'sponsored', 'ugc'
    discovered_at TIMESTAMP DEFAULT NOW(),   -- When backlink was first discovered
    last_seen_at TIMESTAMP DEFAULT NOW(),    -- Last verification timestamp
    is_active BOOLEAN DEFAULT TRUE,          -- Whether backlink is still present
    metadata JSONB,                          -- Extended data (context, position, surrounding text)

    CONSTRAINT unique_backlink UNIQUE (target_url, source_url)
);
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `backlink_id` | SERIAL | Yes (PK) | Unique identifier for each backlink record |
| `target_domain` | VARCHAR(500) | Yes | Domain being linked to (e.g., 'washcarwash.com'). Denormalized for query performance |
| `target_url` | TEXT | Yes | Complete URL being linked to (e.g., 'https://washcarwash.com/services') |
| `source_domain` | VARCHAR(500) | Yes | Domain where the backlink originates (e.g., 'localblog.com') |
| `source_url` | TEXT | Yes | Complete URL containing the backlink (e.g., 'https://localblog.com/best-carwashes') |
| `anchor_text` | TEXT | No | Visible clickable text of the link. Critical for SEO relevance analysis |
| `link_type` | VARCHAR(50) | No | Link relationship type. Values: `dofollow` (passes authority), `nofollow` (no authority), `sponsored` (paid), `ugc` (user-generated content) |
| `discovered_at` | TIMESTAMP | Yes | When the backlink was first discovered. Used for time-series analysis |
| `last_seen_at` | TIMESTAMP | Yes | Last successful verification. Used to detect broken/removed links |
| `is_active` | BOOLEAN | Yes | Current status. `TRUE` = link still exists, `FALSE` = link removed/404 |
| `metadata` | JSONB | No | Extensible field for: context (surrounding text), position (header/footer/body), HTTP status, etc. |

### Constraints

- **Primary Key:** `backlink_id`
- **Unique:** `(target_url, source_url)` - Prevents duplicate backlink records

### Indexes

```sql
CREATE INDEX idx_backlinks_target_domain ON backlinks(target_domain);
CREATE INDEX idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX idx_backlinks_active ON backlinks(is_active);
CREATE INDEX idx_backlinks_discovered ON backlinks(discovered_at DESC);
CREATE INDEX idx_backlinks_metadata ON backlinks USING GIN(metadata);
```

**Index Rationale:**
- `target_domain`: Fast lookups for "who links to us?"
- `source_domain`: Domain-level backlink aggregation
- `is_active`: Filter for current/broken links
- `discovered_at`: Time-series queries and recent link discovery
- `metadata` (GIN): JSONB queries for context/position filtering

### Common Queries

```sql
-- Find all active backlinks to a domain
SELECT * FROM backlinks
WHERE target_domain = 'washcarwash.com' AND is_active = TRUE;

-- Count backlinks by link type
SELECT link_type, COUNT(*)
FROM backlinks
WHERE target_domain = 'washcarwash.com'
GROUP BY link_type;

-- Find recently lost backlinks
SELECT * FROM backlinks
WHERE target_domain = 'washcarwash.com'
  AND is_active = FALSE
  AND last_seen_at > NOW() - INTERVAL '7 days';
```

---

## Citations Table

Tracks business listings on directories and platforms (Yelp, Google Business, Yellow Pages, etc.). Essential for local SEO, NAP (Name-Address-Phone) consistency, and Local Authority Score calculation.

### Schema Definition

```sql
CREATE TABLE IF NOT EXISTS citations (
    citation_id SERIAL PRIMARY KEY,
    directory_name VARCHAR(500) NOT NULL,      -- Directory/platform name
    directory_url TEXT,                        -- Homepage of directory
    listing_url TEXT,                          -- URL to business profile on directory
    business_name VARCHAR(500),                -- Business name as listed
    address TEXT,                              -- Business address as listed
    phone VARCHAR(50),                         -- Business phone as listed
    nap_match_score DECIMAL(5,2),             -- 0-100 consistency score vs canonical NAP
    has_website_link BOOLEAN DEFAULT FALSE,    -- Whether citation includes website link
    is_claimed BOOLEAN DEFAULT FALSE,          -- Whether listing is claimed/verified
    rating DECIMAL(3,2),                       -- Business rating (0.00-5.00 typical)
    review_count INTEGER,                      -- Number of reviews
    discovered_at TIMESTAMP DEFAULT NOW(),     -- When citation was first found
    last_verified_at TIMESTAMP DEFAULT NOW(),  -- Last verification timestamp
    metadata JSONB,                            -- Hours, categories, photos, etc.

    CONSTRAINT unique_citation UNIQUE (directory_name, listing_url)
);
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `citation_id` | SERIAL | Yes (PK) | Unique identifier for each citation record |
| `directory_name` | VARCHAR(500) | Yes | Name of directory/platform (e.g., 'Yelp', 'Google Business Profile', 'Yellow Pages') |
| `directory_url` | TEXT | No | Homepage of the directory (e.g., 'https://www.yelp.com') |
| `listing_url` | TEXT | No | Direct URL to business profile (e.g., 'https://yelp.com/biz/wash-carwash-austin') |
| `business_name` | VARCHAR(500) | No | Business name as it appears on the directory. Used for NAP consistency analysis |
| `address` | TEXT | No | Business address as it appears. Used for NAP consistency analysis |
| `phone` | VARCHAR(50) | No | Business phone as it appears. Used for NAP consistency analysis |
| `nap_match_score` | DECIMAL(5,2) | No | **Critical field**: 0-100 score measuring consistency with canonical NAP data. 100 = perfect match, <80 = inconsistency issues |
| `has_website_link` | BOOLEAN | No | Whether the citation includes a link back to the business website. Important for referral traffic and SEO |
| `is_claimed` | BOOLEAN | No | Whether the business owner has claimed/verified the listing. Claimed listings rank higher in local search |
| `rating` | DECIMAL(3,2) | No | Average customer rating (typically 0-5.00 scale) |
| `review_count` | INTEGER | No | Total number of customer reviews. Used for reputation monitoring and LAS calculation |
| `discovered_at` | TIMESTAMP | Yes | When the citation was first discovered |
| `last_verified_at` | TIMESTAMP | Yes | Last time the citation was verified as still active |
| `metadata` | JSONB | No | Extensible field for: business hours, categories, photos, special offers, service areas, etc. |

### NAP Consistency Scoring

The `nap_match_score` field is automatically calculated by comparing the citation's NAP data against canonical values:

```python
# Example scoring logic
nap_match_score = (
    (40 if name_matches else 0) +
    (40 if address_matches else 0) +
    (20 if phone_matches else 0)
)
```

**Score Interpretation:**
- **100**: Perfect NAP match
- **80-99**: Minor inconsistencies (e.g., abbreviation differences)
- **60-79**: Moderate inconsistencies (missing components)
- **<60**: Severe inconsistencies (wrong NAP data) - requires immediate attention

### Constraints

- **Primary Key:** `citation_id`
- **Unique:** `(directory_name, listing_url)` - Prevents duplicate citations per directory

### Indexes

```sql
CREATE INDEX idx_citations_directory ON citations(directory_name);
CREATE INDEX idx_citations_nap_score ON citations(nap_match_score DESC);
CREATE INDEX idx_citations_claimed ON citations(is_claimed);
CREATE INDEX idx_citations_discovered ON citations(discovered_at DESC);
CREATE INDEX idx_citations_metadata ON citations USING GIN(metadata);
```

**Index Rationale:**
- `directory_name`: Group citations by directory
- `nap_match_score`: Find inconsistent citations requiring attention
- `is_claimed`: Filter for claimed vs unclaimed listings
- `discovered_at`: Time-series analysis and recent discovery tracking
- `metadata` (GIN): JSONB queries for hours, categories, etc.

### Common Queries

```sql
-- Find all citations with NAP inconsistencies
SELECT directory_name, business_name, address, phone, nap_match_score
FROM citations
WHERE nap_match_score < 80
ORDER BY nap_match_score ASC;

-- Find unclaimed listings (opportunity to claim)
SELECT directory_name, listing_url
FROM citations
WHERE is_claimed = FALSE;

-- Count citations by directory
SELECT directory_name, COUNT(*) as citation_count
FROM citations
GROUP BY directory_name
ORDER BY citation_count DESC;

-- Find citations with high review volume
SELECT directory_name, review_count, rating
FROM citations
WHERE review_count > 50
ORDER BY review_count DESC;
```

---

## Supporting Tables

The backlinks and citations tables work in conjunction with:

### referring_domains
Aggregates domain-level backlink metrics. Calculated from `backlinks` table.

```sql
CREATE TABLE referring_domains (
    domain_id SERIAL PRIMARY KEY,
    domain VARCHAR(500) NOT NULL UNIQUE,
    total_backlinks INTEGER,
    dofollow_count INTEGER,
    nofollow_count INTEGER,
    local_authority_score DECIMAL(5,2),  -- 0-100 composite score
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_updated_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);
```

### search_queries, serp_snapshots, serp_results
Track keyword rankings and SERP positions. See separate documentation for SERP tracking tables.

### competitors, competitor_pages
Track competitor websites and content. See separate documentation for competitor analysis tables.

---

## Schema Evolution Notes

### Evolution from PDF Documentation

The current implementation represents a significant evolution from the original PDF specifications (Section 3.5). Key improvements:

#### Backlinks Table Evolution

| PDF Field | Current Field | Evolution Rationale |
|-----------|--------------|---------------------|
| `nofollow` (BOOLEAN) | `link_type` (VARCHAR) | **Enhanced**: Now supports 4 link types (dofollow/nofollow/sponsored/ugc) per Google's modern link attributes |
| `first_seen` (DATE) | `discovered_at` (TIMESTAMP) | **Improved naming** + higher precision for time-series analysis |
| `last_checked` (DATE) | `last_seen_at` (TIMESTAMP) | **Improved naming** + higher precision |
| `alive` (BOOLEAN) | `is_active` (BOOLEAN) | **Clearer naming convention** |
| `source_domain` (VARCHAR) | `source_domain` (VARCHAR(500) NOT NULL) | Added length constraint + NOT NULL for data quality |
| *(missing)* | `target_domain` (VARCHAR(500) NOT NULL) | **New field**: Enables domain-level aggregation without URL parsing |
| *(missing)* | `metadata` (JSONB) | **New field**: Extensible storage for context, position, HTTP status |
| `domain_rating` (INT) | *(not implemented)* | **Removed**: Can be calculated from referring_domains.local_authority_score |

#### Citations Table Evolution

| PDF Field | Current Field | Evolution Rationale |
|-----------|--------------|---------------------|
| `site_name` (VARCHAR) | `directory_name` (VARCHAR(500) NOT NULL) | **Improved naming** + length constraint |
| `profile_url` (TEXT) | `listing_url` (TEXT) | **More specific naming** |
| `last_audited` (DATE) | `last_verified_at` (TIMESTAMP) | **Improved naming** + higher precision |
| `listed` (BOOLEAN) | *(not implemented)* | **Removed**: Presence implied by record existence |
| `issues` (TEXT) | *(embedded in metadata)* | **Enhanced**: Now in structured JSONB format |
| `fixed` (BOOLEAN) | *(not implemented)* | **Removed**: Use change_log table for issue tracking |
| *(missing)* | `directory_url` (TEXT) | **New field**: Separates directory homepage from listing URL |
| *(missing)* | `business_name` (VARCHAR(500)) | **New field**: Critical for NAP consistency |
| *(missing)* | `address` (TEXT) | **New field**: Critical for NAP consistency |
| *(missing)* | `phone` (VARCHAR(50)) | **New field**: Critical for NAP consistency |
| *(missing)* | `nap_match_score` (DECIMAL(5,2)) | **New field**: Automated consistency scoring |
| *(missing)* | `has_website_link` (BOOLEAN) | **New field**: Tracks citation quality |
| *(missing)* | `is_claimed` (BOOLEAN) | **New field**: Tracks ownership status |
| *(missing)* | `rating` (DECIMAL(3,2)) | **New field**: Reputation tracking |
| *(missing)* | `review_count` (INTEGER) | **New field**: Review volume tracking |
| *(missing)* | `discovered_at` (TIMESTAMP) | **New field**: Audit trail |
| *(missing)* | `metadata` (JSONB) | **New field**: Extensible storage for hours, categories, photos |

### Key Improvements

1. **NAP Consistency System**: The citations table now includes a complete Name-Address-Phone consistency tracking system with automated `nap_match_score` calculation. This is essential for local SEO but was completely absent from the PDF.

2. **Modern Link Attributes**: The `link_type` field supports Google's current link attribute system (sponsored, UGC) beyond simple nofollow/dofollow.

3. **Extensibility via JSONB**: Both tables include `metadata` fields for schema evolution without migrations.

4. **Comprehensive Indexing**: Strategic indexes optimize common query patterns.

5. **Data Quality**: Added NOT NULL constraints and length limits where appropriate.

### Migration History

- **Migration 005**: Initial SEO Intelligence tables creation
  - Created backlinks, citations, and 10 other SEO tables
  - Implemented current schema as documented above

---

## Related Documentation

- [PDF Deprecation Notice](./PDF_DEPRECATION_NOTICE.md) - Why PDF Section 3.5 is outdated
- [Field Migration Guide](./FIELD_MIGRATION_GUIDE.md) - Complete PDF → Implementation mapping
- [SEO Intelligence CLI Guide](../seo_intelligence/README.md) - How to use the SEO system

---

## Maintenance

**Document Owner:** washdb-bot development team
**Review Frequency:** After any schema migrations
**Last Schema Change:** Migration 005 (2025-11-20)

For schema change proposals, use the `change_log` table governance system:
```bash
python -m seo_intelligence changes --propose
```

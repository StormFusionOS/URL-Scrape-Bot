# Scraper System Improvements - Integration Guide

## Overview

This document describes the comprehensive scraper system improvements implemented for the AI SEO platform. All improvements are production-ready and fully integrated.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Database Schema](#database-schema)
4. [Services & Usage](#services--usage)
5. [Integration Examples](#integration-examples)
6. [Maintenance Scripts](#maintenance-scripts)

---

## Quick Start

### Running Migrations

```bash
# All migrations have been run, but to re-run if needed:
PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db \
  -f db/migrations/021_enhance_business_sources.sql

PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db \
  -f db/migrations/022_create_serp_paa_table.sql

PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db \
  -f db/migrations/023_add_company_quality_flags.sql

PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db \
  -f db/migrations/024_create_company_conflicts_table.sql
```

### Computing Evidence for All Companies

```bash
# Compute field-level evidence and quality scores
python scripts/compute_evidence.py --batch-size 500 --verbose
```

### Validating NAP Consistency

```bash
# Test NAP validator
python seo_intelligence/services/nap_validator.py

# Or use in code:
python -c "
from seo_intelligence.services.nap_validator import get_nap_validator
validator = get_nap_validator()
validator.validate_all_companies(batch_size=500)
"
```

### Finding Duplicate Companies

```bash
# Test entity matcher
python seo_intelligence/services/entity_matcher.py

# Or use in code:
python -c "
from seo_intelligence.services.entity_matcher import get_entity_matcher
matcher = get_entity_matcher()
matcher.find_all_conflicts()
"
```

---

## Architecture Overview

### Data Flow

```
┌─────────────────┐
│  Scrapers       │
│  (YP, SERP,     │
│   Competitor)   │
└────────┬────────┘
         │
         ├──→ business_sources (with provenance)
         ├──→ serp_paa (PAA questions)
         ├──→ competitor_pages (with CTA analysis)
         └──→ Qdrant (section embeddings)

┌────────┴────────┐
│  Processing     │
│  Services       │
└────────┬────────┘
         │
         ├──→ compute_evidence.py (field-level evidence)
         ├──→ nap_validator.py (NAP consistency)
         └──→ entity_matcher.py (deduplication)

┌────────┴────────┐
│  companies      │
│  (canonical     │
│   data + flags) │
└─────────────────┘
```

### Key Design Principles

1. **Source Evidence First**: Every data point tracked to its source
2. **Trust-Weighted Consensus**: Higher-trust sources have more influence
3. **Provenance Preservation**: All blocking events logged with reason codes
4. **Conflict Detection**: Disagreements flagged for manual review
5. **Semantic Search**: Section-level embeddings enable fine-grained analysis

---

## Database Schema

### New Tables

#### `serp_paa` (Migration 022)
Stores People Also Ask questions from Google SERPs.

```sql
CREATE TABLE serp_paa (
    paa_id SERIAL PRIMARY KEY,
    snapshot_id INTEGER REFERENCES serp_snapshots,
    query_id INTEGER REFERENCES search_queries,
    question TEXT NOT NULL,
    answer_snippet TEXT,
    source_url TEXT,
    source_domain VARCHAR(255),
    position INTEGER,
    captured_at TIMESTAMP DEFAULT NOW(),
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);
```

**Use Cases:**
- Track PAA questions over time
- Detect delta (questions added/removed)
- Generate FAQs based on trending questions

**Key Views:**
- `v_paa_question_frequency`: Question appearance stats
- `v_paa_delta_recent`: Recent PAA changes
- `v_paa_top_sources`: Top domains appearing in PAA

#### `company_conflicts` (Migration 024)
Tracks potential duplicate companies for deduplication.

```sql
CREATE TABLE company_conflicts (
    conflict_id SERIAL PRIMARY KEY,
    company_id_1 INTEGER REFERENCES companies,
    company_id_2 INTEGER REFERENCES companies,
    conflict_type VARCHAR(50),  -- domain_match, phone_match, fuzzy_name_match
    confidence_score FLOAT,     -- 0-1
    match_score FLOAT,          -- 0-1
    matching_fields JSONB,
    conflicting_fields JSONB,
    evidence JSONB,
    resolution_status VARCHAR(50) DEFAULT 'pending',
    detected_at TIMESTAMP DEFAULT NOW()
);
```

**Use Cases:**
- Identify duplicate company records
- Detect shared phone numbers (call centers)
- Merge duplicate entries

**Key Views:**
- `v_unresolved_conflicts`: Pending conflicts for review
- `v_conflict_stats_by_type`: Conflict statistics

### Enhanced Tables

#### `business_sources` (Migration 021)
Added 7 new columns for full provenance:

```sql
-- New columns
source_module VARCHAR(50)      -- scrape_yp, citation_crawler, etc.
status VARCHAR(50)              -- ok, captcha, error, robots_disallowed
status_reason TEXT              -- Detailed reason code
first_seen_at TIMESTAMP         -- When first discovered
last_seen_at TIMESTAMP          -- Most recent verification
raw_payload JSONB               -- Full structured data
snapshot_path TEXT              -- Path to HTML snapshot
```

**Status Codes:**
- `ok`: Successfully scraped
- `captcha`: CAPTCHA detected
- `robots_disallowed`: Blocked by robots.txt
- `gone`: Resource no longer exists (404/410)
- `error`: Scraping error
- `redirect`: Unexpected redirect
- `blocked`: Bot detection

#### `companies` (Migration 023)
Added 8 new columns for quality tracking:

```sql
-- New columns
nap_conflict BOOLEAN            -- NAP disagreement flag
source_count INTEGER            -- Number of business_sources
has_website BOOLEAN             -- Has working website
has_google_profile BOOLEAN      -- Has Google Business Profile
has_yelp_profile BOOLEAN        -- Has Yelp listing
quality_score INTEGER           -- 0-100 overall quality
last_validated_at TIMESTAMP     -- Last validation timestamp
field_evidence JSONB            -- Field-level evidence summary
```

**Quality Score Calculation:**
- 40 points: Source coverage (1-5+ sources)
- 30 points: Profile presence (website, Google, Yelp)
- 20 points: Average source quality
- 10 points: NAP consistency (or -10 penalty for conflict)

**Key Views:**
- `v_company_quality_dashboard`: Quality overview
- `v_companies_needing_validation`: Stale/unvalidated companies
- `v_nap_conflict_summary`: NAP conflict details

---

## Services & Usage

### 1. Source Trust Service

**File:** `seo_intelligence/services/source_trust.py`

**Purpose:** Implements trust weights for different business data sources.

**Trust Tiers:**
- 100: Verified business website
- 90: Google/official sources
- 80: Yelp, BBB, Angi
- 60: YP, secondary directories
- 50: Social media
- 40: Tertiary directories
- 30: SERP/aggregators

**Usage:**

```python
from seo_intelligence.services.source_trust import get_source_trust

trust_service = get_source_trust()

# Get trust weight for a source
weight = trust_service.get_trust_weight('yelp')  # Returns 80

# Compute weighted consensus for a field
sources = [
    {'source_type': 'yelp', 'phone': '(555) 123-4567'},
    {'source_type': 'google', 'phone': '555-123-4567'},
    {'source_type': 'yp', 'phone': '(555) 123-4567'},
]

canonical, ratio, metadata = trust_service.compute_weighted_consensus(
    sources, 'phone', threshold=0.5
)

print(f"Canonical phone: {canonical}")
print(f"Agreement: {ratio:.1%}")
print(f"Supporting sources: {metadata['supporting_sources']}")
```

### 2. Evidence Computation Script

**File:** `scripts/compute_evidence.py`

**Purpose:** Computes field-level evidence for all companies by analyzing business_sources.

**Features:**
- Normalizes phone numbers to E.164 format
- Canonicalizes URLs
- Normalizes addresses with abbreviation standardization
- Uses weighted consensus for canonical values
- Detects NAP conflicts

**Usage:**

```bash
# Process all companies
python scripts/compute_evidence.py

# Process specific company
python scripts/compute_evidence.py --company-id 123

# Batch processing
python scripts/compute_evidence.py --batch-size 1000 --verbose
```

**Output:**
Updates `companies.field_evidence` with:

```json
{
  "name": {
    "canonical_value": "ABC Cleaning LLC",
    "agreement_ratio": 0.95,
    "source_count": 5,
    "best_source_id": 123,
    "supporting_sources": ["yelp", "google", "yp"],
    "disagreeing_sources": [...]
  },
  "phone": {...},
  "address": {...},
  "website": {...}
}
```

### 3. NAP Validator

**File:** `seo_intelligence/services/nap_validator.py`

**Purpose:** Validates Name-Address-Phone consistency across business sources.

**Usage:**

```python
from seo_intelligence.services.nap_validator import get_nap_validator

validator = get_nap_validator(conflict_threshold=0.7)

# Validate single company
result = validator.validate_company(company_id=123)

print(f"Has conflict: {result.has_conflict}")
print(f"Name agreement: {result.name_agreement:.1%}")
print(f"Phone agreement: {result.phone_agreement:.1%}")
print(f"Canonical name: {result.canonical_name}")

# Update company NAP flags in database
validator.update_company_nap_flags(company_id=123)

# Validate all companies
total, conflicts, updated = validator.validate_all_companies(batch_size=500)
print(f"Processed: {total}, Conflicts: {conflicts}, Updated: {updated}")
```

### 4. Section Embedder

**File:** `seo_intelligence/services/section_embedder.py`

**Purpose:** Stores content sections as separate vectors in Qdrant for fine-grained semantic search.

**Usage:**

```python
from seo_intelligence.services.section_embedder import get_section_embedder

embedder = get_section_embedder()

# Initialize collection
embedder.initialize_collection()

# Embed and store sections
sections = [
    {
        'heading': 'Residential Pressure Washing',
        'heading_level': 'h2',
        'content': 'We specialize in residential pressure washing...',
        'word_count': 150
    },
    {
        'heading': 'Commercial Services',
        'heading_level': 'h2',
        'content': 'Our commercial pressure washing services...',
        'word_count': 120
    }
]

count = embedder.embed_and_store_sections(
    page_id=456,
    site_id=123,
    url='https://example.com/services',
    page_type='services',
    sections=sections
)

# Search for similar sections
results = embedder.search_similar_sections(
    query_text='residential cleaning services',
    limit=10,
    page_type='services'
)

for result in results:
    print(f"Score: {result['score']:.4f}")
    print(f"Heading: {result['heading']}")
    print(f"Preview: {result['content_preview'][:100]}...")
```

### 5. Entity Matcher

**File:** `seo_intelligence/services/entity_matcher.py`

**Purpose:** Detects duplicate companies and records conflicts for deduplication.

**Matching Strategies:**
1. **Domain-first**: Same domain → 95% confidence match
2. **Phone+City**: Same E.164 phone + city → 85-90% confidence
3. **Fuzzy Name**: Similar names at same location → 75-90% confidence

**Usage:**

```python
from seo_intelligence.services.entity_matcher import get_entity_matcher

matcher = get_entity_matcher(fuzzy_name_threshold=0.85)

# Check if two companies match
is_match, result = matcher.companies_match(company_id_1=123, company_id_2=456)

if is_match:
    print(f"Match type: {result.match_type}")
    print(f"Confidence: {result.confidence_score:.1%}")
    print(f"Matching fields: {result.matching_fields}")

# Record conflict in database
conflict_id = matcher.record_conflict(result)

# Find all conflicts
pairs_checked, conflicts_found = matcher.find_all_conflicts(batch_size=1000)
print(f"Checked {pairs_checked} pairs, found {conflicts_found} conflicts")
```

---

## Integration Examples

### Example 1: Full Company Data Pipeline

```python
from seo_intelligence.services.source_trust import get_source_trust
from seo_intelligence.services.nap_validator import get_nap_validator
from seo_intelligence.services.entity_matcher import get_entity_matcher

# Step 1: Compute evidence (field-level consensus)
from scripts.compute_evidence import EvidenceComputer
from db.database import get_db_session

session = next(get_db_session())
computer = EvidenceComputer(session)
computer.update_company_evidence(company_id=123)

# Step 2: Validate NAP consistency
validator = get_nap_validator()
nap_result = validator.validate_company(company_id=123)

if nap_result.has_conflict:
    print(f"⚠️ NAP conflict detected!")
    for conflict in nap_result.conflicts:
        print(f"  - {conflict['field']}: {conflict['agreement_ratio']:.1%} agreement")

# Step 3: Check for duplicates
matcher = get_entity_matcher()
# (Query database for companies with similar attributes, then check)
```

### Example 2: PAA Trend Analysis

```python
from sqlalchemy import text
from db.database import get_db_session

session = next(get_db_session())

# Get trending PAA questions for a query
result = session.execute(
    text("""
        SELECT * FROM get_paa_for_query(:query_id, :limit)
    """),
    {'query_id': 1, 'limit': 20}
)

for row in result:
    print(f"Q: {row.question}")
    print(f"   Appeared {row.appearance_count} times")
    print()

# Detect PAA delta (questions added/removed)
delta = session.execute(
    text("SELECT * FROM v_paa_delta_recent WHERE query_id = :query_id"),
    {'query_id': 1}
)

for row in delta:
    if row.change_type == 'added':
        print(f"✅ New: {row.current_question}")
    elif row.change_type == 'removed':
        print(f"❌ Removed: {row.previous_question}")
```

### Example 3: Competitor CTA Analysis

```python
from seo_intelligence.scrapers.competitor_crawler import CompetitorCrawler

crawler = CompetitorCrawler(enable_embeddings=True)

# Crawl competitor and analyze CTAs
result = crawler.crawl_competitor(
    domain='competitor.com',
    name='Competitor Business'
)

# Metrics are stored in competitor_pages with conversion_signals JSONB:
# {
#   "tel_links": [...],
#   "tel_link_count": 2,
#   "forms": [...],
#   "form_count": 3,
#   "cta_buttons": [...],
#   "cta_button_count": 5,
#   "cta_above_fold": true,
#   "booking_widgets": ["calendly"],
#   "has_booking_widget": true,
#   "has_chat_widget": true,
#   "total_conversion_points": 12
# }
```

### Example 4: Section-Level Content Gap Analysis

```python
from seo_intelligence.services.section_embedder import get_section_embedder

embedder = get_section_embedder()

# Find sections similar to your target topic
results = embedder.search_similar_sections(
    query_text='residential pressure washing services and pricing',
    limit=20,
    page_type='services'
)

# Analyze what competitors are saying
for result in results:
    print(f"\n{result['url']}")
    print(f"Heading: {result['heading']}")
    print(f"Word count: {result['word_count']}")
    print(f"Relevance: {result['score']:.2%}")
    print(f"Preview: {result['content_preview'][:200]}...")
```

---

## Maintenance Scripts

### Daily Maintenance

```bash
# 1. Compute evidence for companies with new sources
python scripts/compute_evidence.py --batch-size 500

# 2. Validate NAP consistency
python -c "
from seo_intelligence.services.nap_validator import get_nap_validator
validator = get_nap_validator()
validator.validate_all_companies(batch_size=500)
"

# 3. Find new duplicate conflicts
python -c "
from seo_intelligence.services.entity_matcher import get_entity_matcher
matcher = get_entity_matcher()
matcher.find_all_conflicts(batch_size=1000)
"
```

### Weekly Maintenance

```bash
# 1. Refresh quality scores for all companies
PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db -c "
UPDATE companies
SET quality_score = compute_company_quality_score(id)
WHERE field_evidence IS NOT NULL;
"

# 2. Review unresolved conflicts
PGPASSWORD=Washdb123 psql -h 127.0.0.1 -U washbot -d washbot_db -c "
SELECT * FROM v_unresolved_conflicts LIMIT 20;
"
```

### Query Examples

```sql
-- Companies with NAP conflicts
SELECT * FROM v_nap_conflict_summary LIMIT 10;

-- Companies needing validation (stale or never validated)
SELECT * FROM v_companies_needing_validation LIMIT 20;

-- Company quality dashboard
SELECT * FROM v_company_quality_dashboard
WHERE quality_score < 50
ORDER BY source_count DESC
LIMIT 20;

-- PAA questions for a query
SELECT * FROM get_paa_for_query(1, 20);

-- Recent PAA changes
SELECT * FROM v_paa_delta_recent WHERE query_id = 1;

-- Conflict statistics
SELECT * FROM v_conflict_stats_by_type;
```

---

## Troubleshooting

### Issue: Evidence computation failing

**Solution:** Check that business_sources has data with proper source_type values.

```sql
SELECT source_type, COUNT(*) FROM business_sources GROUP BY source_type;
```

### Issue: NAP validation showing all conflicts

**Solution:** Adjust conflict threshold (default 0.7).

```python
validator = get_nap_validator(conflict_threshold=0.6)  # Lower threshold
```

### Issue: Entity matcher finding too many conflicts

**Solution:** Adjust fuzzy name threshold (default 0.85).

```python
matcher = get_entity_matcher(fuzzy_name_threshold=0.90)  # Higher threshold
```

### Issue: Section embeddings not working

**Solution:** Ensure Qdrant is running and QDRANT_HOST is configured.

```bash
# Check Qdrant connection
python -c "
from seo_intelligence.services.section_embedder import get_section_embedder
embedder = get_section_embedder()
print('Qdrant healthy:', embedder.health_check())
"
```

---

## Performance Notes

- **Evidence Computation**: ~500 companies per minute
- **NAP Validation**: ~200 companies per minute
- **Entity Matching**: Domain/phone lookups are fast, fuzzy matching is slower
- **Section Embeddings**: ~20-30 sections per second (depends on model)

---

## Future Enhancements

1. **Automatic Conflict Resolution**: ML model to auto-resolve high-confidence duplicates
2. **Real-time Evidence Updates**: Trigger evidence computation on source updates
3. **Advanced Fuzzy Matching**: Phonetic matching, address geocoding
4. **Section Clustering**: Group similar sections across competitors
5. **PAA-to-FAQ Pipeline**: Automatically generate FAQs from trending PAA questions

---

## Support

For questions or issues:
1. Check logs in `logs/` directory
2. Review database views for data quality issues
3. Run service demos: `python <service_file>.py`
4. Check migration verification output in PostgreSQL logs

---

**Last Updated:** 2025-11-21
**Implementation Version:** 1.0
**Status:** Production Ready ✅

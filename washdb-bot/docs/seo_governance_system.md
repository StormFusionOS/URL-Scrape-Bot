# SEO Intelligence Governance System

## Overview

The SEO Governance System implements a review-based approval workflow for all SEO data changes. All scrapers and analyzers must propose changes to the `change_log` table for review before they are applied to target tables.

This enables:
- Human review of AI-suggested changes
- Audit trail of all modifications
- Batch approval/rejection workflows
- AI-assisted review recommendations

## Architecture

### Core Components

**1. Governance Service** (`seo_intelligence/services/governance.py`)
- Central service managing all change proposals
- Handles approve/reject operations
- Provides bulk operations for efficiency
- Maintains audit trail

**2. Change Log Table** (`change_log`)
- Stores all proposed changes
- Tracks approval status
- Records reviewer actions
- Maintains change metadata

**3. Scraper Integration**
- All scrapers use governance service
- No direct database writes
- Changes flow through review queue
- Consistent change tracking

## Database Schema

### change_log Table

```sql
CREATE TABLE change_log (
    change_id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,      -- Target table
    record_id INTEGER,                      -- Target record ID
    operation VARCHAR(50) NOT NULL,         -- insert, update, delete
    proposed_data JSONB NOT NULL,          -- Proposed change data
    status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected
    reason TEXT,                            -- Change justification
    proposed_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    reviewed_by VARCHAR(200),              -- Reviewer identifier
    metadata JSONB,                        -- Additional context

    -- Step 3 enhancements (migration 026)
    change_type VARCHAR(100),              -- citations, technical_seo, etc.
    source VARCHAR(200),                   -- Which scraper proposed
    applied_at TIMESTAMP                   -- When change was applied
);
```

### Indexes

```sql
CREATE INDEX idx_change_log_table ON change_log(table_name);
CREATE INDEX idx_change_log_status ON change_log(status);
CREATE INDEX idx_change_log_change_type ON change_log(change_type);
CREATE INDEX idx_change_log_source ON change_log(source);
CREATE INDEX idx_change_log_status_type ON change_log(status, change_type);
```

## Change Types

Standard vocabulary for categorizing changes:

- `citations` - Citation/directory listing updates
- `technical_seo` - Technical audit issues
- `onpage` - On-page SEO modifications
- `backlinks` - Backlink discoveries
- `serp_tracking` - SERP position tracking
- `competitor_analysis` - Competitor insights
- `reviews` - Review data updates
- `unlinked_mentions` - Brand mention opportunities

## Usage

### 1. Proposing Changes (Scraper Side)

```python
from seo_intelligence.services.governance import propose_change, ChangeType

# Propose a citation update
change_id = propose_change(
    table_name='citations',
    operation='update',
    record_id=123,
    proposed_data={
        'rating_value': 4.5,
        'rating_count': 87,
        'metadata': {'last_scraped': '2025-01-15'}
    },
    change_type=ChangeType.REVIEWS,
    source='review_detail_scraper',
    reason='Fresh review data scraped from Google',
    metadata={
        'directory_name': 'google',
        'confidence': 0.95
    }
)
```

### 2. Reviewing Changes (GUI/CLI)

```python
from seo_intelligence.services.governance import (
    get_pending_changes,
    approve_change,
    reject_change
)

# Get pending changes for review
pending = get_pending_changes(change_type=ChangeType.REVIEWS, limit=10)

for change in pending:
    # Review logic here
    if meets_criteria(change):
        approve_change(
            change['change_id'],
            reviewed_by='ai_assistant',
            apply_immediately=True
        )
    else:
        reject_change(
            change['change_id'],
            reviewed_by='ai_assistant',
            rejection_reason='Confidence too low'
        )
```

### 3. Bulk Operations

```python
# Bulk approve low-risk changes
change_ids = [123, 124, 125]
results = service.bulk_approve_changes(
    change_ids=change_ids,
    reviewed_by='auto_approver',
    apply_immediately=True
)
# Results: {'approved': 3, 'applied': 3, 'failed': 0}
```

## Integrated Scrapers

### Step 2 Scrapers (Implemented)

**1. Unlinked Mentions Finder**
- Source: `unlinked_mentions_finder`
- Change type: `unlinked_mentions`
- Target table: `audit_issues`
- Operation: `insert`

**2. Review Detail Scraper**
- Source: `review_detail_scraper`
- Change type: `reviews`
- Target table: `citations`
- Operation: `update`

### Existing Scrapers (To Be Integrated)

**3. SERP Scraper**
- Source: `serp_scraper`
- Change type: `serp_tracking`
- Target tables: `search_queries`, `serp_snapshots`, `serp_results`, `serp_paa`

**4. Competitor Crawler**
- Source: `competitor_crawler`
- Change type: `competitor_analysis`
- Target tables: `competitors`, `competitor_pages`

**5. Backlink Crawler**
- Source: `backlink_crawler`
- Change type: `backlinks`
- Target tables: `backlinks`, `referring_domains`

**6. Citation Crawler**
- Source: `citation_crawler`
- Change type: `citations`
- Target table: `citations`

**7. Technical Auditor**
- Source: `technical_auditor`
- Change type: `technical_seo`
- Target tables: `page_audits`, `audit_issues`

## CLI Interface

The governance service includes a CLI for manual operations:

```bash
# List pending changes
python -m seo_intelligence.services.governance list --type citations --limit 20

# Approve a change
python -m seo_intelligence.services.governance approve 123 --reviewer admin_user

# Reject a change
python -m seo_intelligence.services.governance reject 124 \
    --reason "Duplicate entry" \
    --reviewer admin_user
```

## Testing

Run the governance integration test:

```bash
./venv/bin/python seo_intelligence/tests/test_governance_integration.py
```

Tests validate:
- Change proposal workflow
- Pending change retrieval
- Approval/rejection operations
- Change type vocabulary
- Bulk operations
- End-to-end integration

## Benefits

1. **Audit Trail**: Complete history of all SEO data modifications
2. **Quality Control**: Human/AI review before changes applied
3. **Transparency**: Clear tracking of who proposed and approved what
4. **Flexibility**: Easy to add new change types and sources
5. **Safety**: Rollback capability via change log
6. **Efficiency**: Bulk operations for high-volume scenarios

## Next Steps (Step 4)

1. Create master orchestration CLI (`cli_run_seo_cycle.py`)
2. Define execution order and frequencies
3. Add task scheduling configuration
4. Integrate with cron/systemd for automation

## GUI Integration (Step 5)

1. Build "SEO Review Queue" page in NiceGUI
2. Add filtering by change_type and source
3. Implement approve/reject buttons
4. Add AI assistance for review recommendations
5. Show approval statistics and trends

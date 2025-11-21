# Field Migration Guide: PDF → washdb-bot Implementation

**Purpose:** Map PDF documentation fields to actual washdb-bot database fields

**Audience:** Developers migrating from PDF specs, maintaining legacy code, or understanding schema evolution

---

## How to Use This Guide

If you're looking at the PDF documentation (Section 3.5) and need to find the equivalent field in the actual washdb-bot database:

1. Find the PDF field name in the tables below
2. Check the "Current Field" column for the implemented field name
3. Review the "Migration Notes" for usage differences

---

## Backlinks Table Field Mapping

### Direct Matches (No Changes)

| PDF Field | Current Field | Type | Notes |
|-----------|---------------|------|-------|
| `backlink_id` | `backlink_id` | SERIAL PRIMARY KEY | ✓ Exact match |
| `source_url` | `source_url` | TEXT | ✓ Exact match |
| `target_url` | `target_url` | TEXT NOT NULL | Same field, added NOT NULL constraint |
| `anchor_text` | `anchor_text` | TEXT | ✓ Exact match |

### Renamed Fields

| PDF Field | Current Field | Migration Notes |
|-----------|---------------|-----------------|
| `alive` | `is_active` | **Naming improvement**. Both are BOOLEAN.<br><br>**Migration:**<br>`WHERE alive = TRUE` → `WHERE is_active = TRUE`<br><br>**Rationale:** `is_active` follows standard boolean naming (is_*, has_*, can_*) |
| `first_seen` | `discovered_at` | **Type upgrade + naming improvement**<br><br>**PDF:** DATE<br>**Current:** TIMESTAMP DEFAULT NOW()<br><br>**Migration:**<br>`first_seen::date` → `discovered_at`<br><br>**Rationale:** TIMESTAMP provides hour/minute precision for better time-series analysis. "discovered_at" is more descriptive. |
| `last_checked` | `last_seen_at` | **Type upgrade + naming improvement**<br><br>**PDF:** DATE<br>**Current:** TIMESTAMP DEFAULT NOW()<br><br>**Migration:**<br>`last_checked::date` → `last_seen_at`<br><br>**Rationale:** TIMESTAMP provides precision. "last_seen_at" follows timestamp naming pattern (*_at suffix). |

### Enhanced/Replaced Fields

| PDF Field | PDF Type | Current Field | Current Type | Migration Notes |
|-----------|----------|---------------|--------------|-----------------|
| `nofollow` | BOOLEAN | `link_type` | VARCHAR(50) | **Significant enhancement**<br><br>**PDF Logic:**<br>`nofollow = TRUE` → Link doesn't pass authority<br>`nofollow = FALSE` → Link passes authority<br><br>**Current Logic:**<br>`link_type = 'nofollow'` → No authority<br>`link_type = 'dofollow'` → Passes authority<br>`link_type = 'sponsored'` → Paid link (Google rel attribute)<br>`link_type = 'ugc'` → User-generated content<br><br>**Migration:**<br>```sql<br>CASE <br>  WHEN nofollow = TRUE THEN 'nofollow'<br>  WHEN nofollow = FALSE THEN 'dofollow'<br>  ELSE NULL<br>END<br>```<br><br>**Rationale:** Google's link attribute system evolved beyond simple nofollow. Modern SEO requires distinguishing sponsored/UGC links. |
| `source_domain` | VARCHAR | `source_domain` | VARCHAR(500) NOT NULL | **Enhanced with constraints**<br><br>**Changes:**<br>- Added explicit length limit (500 chars)<br>- Added NOT NULL constraint<br><br>**Migration:** Direct mapping, but NULL values will fail<br><br>**Rationale:** Data quality enforcement |

### Fields Removed from Implementation

| PDF Field | PDF Type | Reason for Removal | Alternative |
|-----------|----------|-------------------|-------------|
| `domain_rating` | INT | Redundant | Use `referring_domains.local_authority_score` instead<br><br>**Query:**<br>```sql<br>SELECT b.*, rd.local_authority_score<br>FROM backlinks b<br>JOIN referring_domains rd ON b.source_domain = rd.domain<br>```<br><br>**Rationale:** Domain rating is domain-level, not link-level. Moved to `referring_domains` table for proper normalization. |

### Fields Added to Implementation

| Current Field | Type | Purpose | Usage |
|---------------|------|---------|-------|
| `target_domain` | VARCHAR(500) NOT NULL | Domain being linked to | **Not in PDF**<br><br>Denormalized field for query performance. Enables fast domain-level backlink aggregation without URL parsing.<br><br>**Example:**<br>```sql<br>-- Count backlinks by target domain<br>SELECT target_domain, COUNT(*)<br>FROM backlinks<br>GROUP BY target_domain<br>```<br><br>**Value:** Extracted from `target_url` (e.g., 'https://washcarwash.com/page' → 'washcarwash.com') |
| `metadata` | JSONB | Extensible storage | **Not in PDF**<br><br>Stores additional context without schema changes:<br>- Link position (header, footer, body)<br>- Surrounding text/context<br>- HTTP status codes<br>- Custom tags<br><br>**Example:**<br>```json<br>{<br>  "position": "body",<br>  "context": "Best car wash in Austin",<br>  "http_status": 200,<br>  "verified": true<br>}<br>```<br><br>**Query:**<br>```sql<br>-- Find body links only<br>SELECT * FROM backlinks<br>WHERE metadata->>'position' = 'body'<br>``` |

---

## Citations Table Field Mapping

### Direct Matches (No Changes)

| PDF Field | Current Field | Type | Notes |
|-----------|---------------|------|-------|
| `citation_id` | `citation_id` | SERIAL PRIMARY KEY | ✓ Exact match |

### Renamed Fields

| PDF Field | Current Field | Migration Notes |
|-----------|---------------|-----------------|
| `site_name` | `directory_name` | **Naming improvement**. Both are VARCHAR.<br><br>**Migration:**<br>`site_name` → `directory_name`<br><br>**Rationale:** "directory" is more specific than "site" for citation sources (Yelp, Yellow Pages are directories, not generic "sites") |
| `profile_url` | `listing_url` | **Naming improvement**. Both are TEXT.<br><br>**Migration:**<br>`profile_url` → `listing_url`<br><br>**Rationale:** "listing" is more specific for business directory entries |
| `last_audited` | `last_verified_at` | **Type upgrade + naming improvement**<br><br>**PDF:** DATE<br>**Current:** TIMESTAMP DEFAULT NOW()<br><br>**Migration:**<br>`last_audited::date` → `last_verified_at`<br><br>**Rationale:** "verified" is clearer than "audited". TIMESTAMP provides precision. Follows *_at naming pattern. |

### Fields Removed from Implementation

| PDF Field | PDF Type | Reason for Removal | Alternative |
|-----------|----------|-------------------|-------------|
| `listed` | BOOLEAN | Redundant | **Rationale:** If a citation record exists, the business IS listed. No need for separate flag.<br><br>To track "opportunity citations" (places where business COULD be listed but isn't), use a separate `citation_opportunities` table or track in metadata.<br><br>**Migration:** If `listed = FALSE` in old data, delete the record or move to opportunities table. |
| `issues` | TEXT | Replaced by structured data | **Alternative 1:** Use `metadata` JSONB field:<br>```json<br>{<br>  "issues": [<br>    {<br>      "type": "nap_mismatch",<br>      "field": "phone",<br>      "expected": "(512) 555-1234",<br>      "found": "512-555-1234",<br>      "severity": "low"<br>    }<br>  ]<br>}<br>```<br><br>**Alternative 2:** Use `change_log` table for issue tracking with governance workflow.<br><br>**Rationale:** Structured JSONB enables automated issue analysis. Free-text field was not queryable. |
| `fixed` | BOOLEAN | Replaced by governance system | **Alternative:** Use `change_log` table:<br>```sql<br>SELECT * FROM change_log<br>WHERE table_name = 'citations'<br>  AND record_id = 123<br>  AND status = 'applied'<br>```<br><br>**Rationale:** Issue resolution is better tracked through the change governance system with audit trail, approval workflow, and timestamps. |

### Fields Added to Implementation (NAP System)

These fields implement the **Name-Address-Phone (NAP) consistency system**, which is critical for local SEO but was completely missing from the PDF.

| Current Field | Type | Purpose | Usage |
|---------------|------|---------|-------|
| `directory_url` | TEXT | Homepage of directory | **Not in PDF**<br><br>Separates directory homepage from business listing URL.<br><br>**Example:**<br>`directory_url`: https://www.yelp.com<br>`listing_url`: https://www.yelp.com/biz/wash-carwash-austin |
| `business_name` | VARCHAR(500) | Business name as listed | **Not in PDF** - Part of NAP system<br><br>Stores how the business name appears on this directory for consistency checking.<br><br>**Example:**<br>Canonical: "Wash Car Wash"<br>Citation 1: "Wash Car Wash"<br>Citation 2: "Wash Carwash" (inconsistency!) |
| `address` | TEXT | Business address as listed | **Not in PDF** - Part of NAP system<br><br>Stores how the address appears for consistency checking.<br><br>**Example:**<br>Canonical: "123 Main St, Austin, TX 78701"<br>Citation 1: "123 Main Street, Austin, Texas 78701" (minor inconsistency) |
| `phone` | VARCHAR(50) | Business phone as listed | **Not in PDF** - Part of NAP system<br><br>Stores how the phone appears for consistency checking.<br><br>**Example:**<br>Canonical: "(512) 555-1234"<br>Citation 1: "512-555-1234" (format inconsistency) |
| `nap_match_score` | DECIMAL(5,2) | Automated consistency score (0-100) | **Not in PDF** - **CRITICAL ADDITION**<br><br>Automatically calculated by comparing citation NAP against canonical values:<br>- 100 = Perfect match<br>- 80-99 = Minor inconsistencies<br>- 60-79 = Moderate issues<br>- <60 = Severe issues<br><br>**Query:**<br>```sql<br>-- Find citations needing attention<br>SELECT directory_name, nap_match_score<br>FROM citations<br>WHERE nap_match_score < 80<br>ORDER BY nap_match_score ASC<br>```<br><br>**Value:** Enables automated NAP consistency monitoring at scale. Manual checking is error-prone and time-consuming. |

### Fields Added to Implementation (Citation Quality)

| Current Field | Type | Purpose | Usage |
|---------------|------|---------|-------|
| `has_website_link` | BOOLEAN DEFAULT FALSE | Does citation link to website? | **Not in PDF**<br><br>Tracks whether the citation includes a link back to the business website.<br><br>**Value:** Citations with website links provide referral traffic and SEO benefit. Citations without links are less valuable.<br><br>**Query:**<br>```sql<br>-- Find citations missing website links<br>SELECT directory_name, listing_url<br>FROM citations<br>WHERE has_website_link = FALSE<br>``` |
| `is_claimed` | BOOLEAN DEFAULT FALSE | Is listing claimed/verified? | **Not in PDF**<br><br>Tracks whether the business owner has claimed ownership of the listing.<br><br>**Value:** Claimed listings rank higher in local search. Unclaimed listings represent opportunities.<br><br>**Query:**<br>```sql<br>-- Find unclaimed opportunities<br>SELECT directory_name, listing_url<br>FROM citations<br>WHERE is_claimed = FALSE<br>``` |
| `rating` | DECIMAL(3,2) | Business rating | **Not in PDF**<br><br>Stores average customer rating (typically 0-5.00 scale).<br><br>**Value:** Monitors reputation across directories. |
| `review_count` | INTEGER | Number of reviews | **Not in PDF**<br><br>Stores total review count.<br><br>**Value:** Used for Local Authority Score calculation and reputation monitoring. |
| `discovered_at` | TIMESTAMP DEFAULT NOW() | When citation was found | **Not in PDF**<br><br>Audit trail for when the citation was first discovered.<br><br>**Value:** Time-series analysis of citation growth. |
| `metadata` | JSONB | Extensible storage | **Not in PDF**<br><br>Stores:<br>- Business hours<br>- Categories<br>- Photos<br>- Special offers<br>- Service areas<br>- Custom fields<br><br>**Example:**<br>```json<br>{<br>  "hours": {<br>    "monday": "8am-6pm",<br>    "tuesday": "8am-6pm"<br>  },<br>  "categories": ["Car Wash", "Detailing"],<br>  "photos_count": 12<br>}<br>``` |

---

## Code Migration Examples

### Example 1: Query All Active Backlinks

**PDF-style code:**
```sql
SELECT * FROM backlinks
WHERE alive = TRUE
ORDER BY first_seen DESC;
```

**Current implementation:**
```sql
SELECT * FROM backlinks
WHERE is_active = TRUE
ORDER BY discovered_at DESC;
```

### Example 2: Check Link Authority

**PDF-style code:**
```sql
SELECT
  source_url,
  CASE WHEN nofollow = TRUE THEN 'No Authority' ELSE 'Passes Authority' END as authority
FROM backlinks;
```

**Current implementation:**
```sql
SELECT
  source_url,
  link_type,
  CASE
    WHEN link_type = 'dofollow' THEN 'Passes Authority'
    WHEN link_type = 'nofollow' THEN 'No Authority'
    WHEN link_type = 'sponsored' THEN 'Paid Link (No Authority)'
    WHEN link_type = 'ugc' THEN 'User Content (No Authority)'
  END as authority
FROM backlinks;
```

### Example 3: Find Citation Issues

**PDF-style code:**
```sql
SELECT site_name, issues
FROM citations
WHERE issues IS NOT NULL AND fixed = FALSE;
```

**Current implementation (Option 1 - JSONB):**
```sql
SELECT
  directory_name,
  metadata->'issues' as issues
FROM citations
WHERE metadata->'issues' IS NOT NULL;
```

**Current implementation (Option 2 - NAP Score):**
```sql
SELECT
  directory_name,
  nap_match_score,
  business_name,
  address,
  phone
FROM citations
WHERE nap_match_score < 80  -- Automated issue detection
ORDER BY nap_match_score ASC;
```

### Example 4: Find Citations Needing Attention

**PDF-style code:**
```sql
SELECT site_name, profile_url
FROM citations
WHERE listed = TRUE AND last_audited < NOW() - INTERVAL '30 days';
```

**Current implementation:**
```sql
SELECT
  directory_name,
  listing_url,
  last_verified_at,
  nap_match_score,
  is_claimed
FROM citations
WHERE last_verified_at < NOW() - INTERVAL '30 days'
   OR nap_match_score < 80  -- Consistency issues
   OR is_claimed = FALSE;    -- Unclaimed opportunities
```

---

## Summary: Quick Reference

### Backlinks Table

| PDF → Current | Change Type |
|--------------|-------------|
| `alive` → `is_active` | Renamed |
| `first_seen` → `discovered_at` | Renamed + type upgrade (DATE → TIMESTAMP) |
| `last_checked` → `last_seen_at` | Renamed + type upgrade (DATE → TIMESTAMP) |
| `nofollow` → `link_type` | Enhanced (BOOLEAN → VARCHAR with 4 values) |
| `domain_rating` → *(removed)* | Moved to `referring_domains` table |
| *(new)* `target_domain` | Added for performance |
| *(new)* `metadata` | Added for extensibility |

### Citations Table

| PDF → Current | Change Type |
|--------------|-------------|
| `site_name` → `directory_name` | Renamed |
| `profile_url` → `listing_url` | Renamed |
| `last_audited` → `last_verified_at` | Renamed + type upgrade (DATE → TIMESTAMP) |
| `listed` → *(removed)* | Redundant (presence = listed) |
| `issues` → *(metadata JSONB)* | Moved to structured storage |
| `fixed` → *(change_log table)* | Moved to governance system |
| *(new)* NAP fields (`business_name`, `address`, `phone`, `nap_match_score`) | **Critical addition for local SEO** |
| *(new)* Quality fields (`has_website_link`, `is_claimed`, `rating`, `review_count`) | Added for citation quality tracking |
| *(new)* `discovered_at` | Added for audit trail |
| *(new)* `metadata` | Added for extensibility |

---

**Document Version:** 1.0
**Last Updated:** 2025-11-21
**Related Docs:** [SCHEMA_REFERENCE.md](./SCHEMA_REFERENCE.md), [PDF_DEPRECATION_NOTICE.md](./PDF_DEPRECATION_NOTICE.md)

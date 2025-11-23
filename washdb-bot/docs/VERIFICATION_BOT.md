# Verification Bot - Complete Implementation Guide

**Status**: ✅ Phases 0-4 & 6.2 Complete (Core functionality ready)
**Date**: 2025-11-23
**Version**: 1.0 (Rule-based + GUI)

## Overview

The Verification Bot is an intelligent filtering system that verifies whether scraped companies actually offer our target services:
- **Residential & commercial pressure washing**
- **Residential & commercial window cleaning**
- **Residential & commercial wood restoration** (deck/fence/log home)

It filters out unwanted businesses like directories, equipment sellers, training sites, blogs, and agencies.

## Architecture

### Components Implemented

1. **Configuration** (`data/verification_services.json`)
   - Service keywords (pressure/window/wood)
   - Residential vs commercial context words
   - Negative filters (directories, equipment, training, etc.)
   - Provider vs informational phrases

2. **Core Verifier** (`scrape_site/service_verifier.py`)
   - Multi-label service detection
   - Tier classification (A/B/C/D)
   - Rule-based scoring (0.0-1.0)
   - Site structure analysis (navigation, headings)
   - JSON-LD schema.org parsing
   - ML model integration hooks (Phase 5)

3. **GUI Review Page** (`niceui/pages/verification.py`)
   - Real-time verification statistics dashboard
   - Batch verification job runner
   - Companies review table with filtering
   - Detail view with signal breakdown
   - Manual labeling (Target / Non-target)
   - Label storage for ML training

4. **Batch Job** (`db/verify_company_urls.py`)
   - Command-line batch verification
   - Website scraping + parsing
   - Combined scoring (discovery + website + reviews)
   - Database updates with parse_metadata

## How It Works

### Phase 1: Rule-Based Verification

The verifier analyzes website content for:

1. **Service Detection**
   ```json
   {
     "pressure": {"any": true, "residential": true, "commercial": true},
     "window": {"any": true, "residential": false, "commercial": true},
     "wood": {"any": true, "residential": true, "commercial": true}
   }
   ```

2. **Tier Classification**
   - **Tier A**: All 3 services with both res & commercial (strongest targets)
   - **Tier B**: ≥ 2 services with both res & commercial
   - **Tier C**: ≥ 1 service with both res & commercial
   - **Tier D**: Partial or unclear (likely non-target)

3. **Negative Filters**
   - Blocked domains: Yelp, HomeAdvisor, Amazon, Facebook, etc.
   - Training keywords: "academy", "bootcamp", "course", "enroll now"
   - Equipment keywords: "for sale", "add to cart", "checkout"
   - Informational keywords: "guide to", "how to start a business"

4. **Provider Language Detection**
   - **Provider phrases**: "we provide", "free estimate", "call today", "locally owned"
   - **Informational phrases**: "in this article", "step-by-step tutorial"
   - Penalizes sites with heavy informational content

5. **Local Business Artifacts**
   - Requires at least phone OR email
   - Bonus for physical address, service area
   - Penalty if no contact info despite content

### Phase 2: Site Structure Analysis

1. **Navigation & Headings**
   - Boosts score if service keywords in nav/headings
   - Distinguishes provider sites from blogs

2. **JSON-LD Schema.org**
   - Detects `@type: LocalBusiness`, `CleaningService`, etc.
   - Boosts score for local business schema

### Phase 3: Combined Scoring

Combines multiple signals:
```python
combined_score = (
    0.4 * discovery_filter_confidence +  # Google/YP filter
    0.4 * website_verification_score +   # Rule-based website analysis
    0.2 * review_score                   # Log-scaled review counts
)
```

**Thresholds**:
- `score >= 0.75` → **Auto-accept** (active=True)
- `score <= 0.35` → **Auto-reject** (active=False)
- `0.35 < score < 0.75` → **Needs manual review**

### Phase 4: Human Review UI

**Access**: http://localhost:8080/verification

**Features**:
1. **Statistics Dashboard**
   - Total verified, passed, failed, needs review
   - Labeled target / non-target counts

2. **Batch Verification Runner**
   - Start/stop batch job from GUI
   - Real-time progress updates
   - Live log streaming

3. **Companies Review Table**
   - Filter by status (needs_review, passed, failed, unknown, no_label)
   - Click row to see full detail view
   - Sortable by score, tier, name

4. **Detail View Dialog**
   - Verification score & tier
   - Services detected breakdown
   - Positive/negative signals
   - Manual labeling buttons

5. **Manual Labeling**
   - **Mark as TARGET** → Sets `label_human='target'`, `active=True`
   - **Mark as NON-TARGET** → Sets `label_human='non_target'`, `active=False`
   - Labels stored for ML training (Phase 5)

## Usage

### 1. Run Batch Verification Job

```bash
# Verify all unverified companies
python db/verify_company_urls.py

# Verify up to 100 companies
python db/verify_company_urls.py --max-companies 100

# Force re-verify already verified companies
python db/verify_company_urls.py --force-reverify

# Custom thresholds
python db/verify_company_urls.py --min-score 0.80 --max-score 0.30
```

**Output**:
```
======================================================================
BATCH VERIFICATION JOB STARTED
======================================================================
Max companies: all
Force reverify: False
Min score (auto-accept): 0.75
Max score (auto-reject): 0.35
----------------------------------------------------------------------
Found 1,234 companies to verify
[1/1234] Processing: ABC Pressure Washing
Verified ABC Pressure Washing: Status=passed, Score=0.82, Tier=A
[2/1234] Processing: XYZ Equipment Sales
Verified XYZ Equipment Sales: Status=failed, Score=0.15, Tier=D
...
======================================================================
BATCH VERIFICATION JOB COMPLETED
======================================================================
Total processed: 1234
Passed: 856 (69.4%)
Failed: 234 (19.0%)
Unknown (needs review): 144 (11.7%)
Errors: 0
======================================================================
```

### 2. Use GUI Review Page

1. **Start the dashboard**:
   ```bash
   ./scripts/dev/run-gui.sh
   ```

2. **Navigate to**: http://localhost:8080/verification

3. **Review companies**:
   - Filter to "needs_review"
   - Click a company to see details
   - Review signals (positive/negative)
   - Mark as Target or Non-target

4. **Run batch job from GUI**:
   - Set max companies (or leave empty for all)
   - Click "START BATCH VERIFICATION"
   - Monitor progress in real-time
   - View final statistics

### 3. Query Verification Results

```sql
-- Companies that passed verification
SELECT name, website, parse_metadata->'verification'->>'tier' as tier,
       parse_metadata->'verification'->>'score' as score
FROM companies
WHERE parse_metadata->'verification'->>'status' = 'passed'
ORDER BY (parse_metadata->'verification'->>'score')::float DESC;

-- Companies needing manual review
SELECT name, website, parse_metadata->'verification'->>'reason' as reason
FROM companies
WHERE parse_metadata->'verification'->>'needs_review' = 'true';

-- Companies with manual labels (for ML training)
SELECT
    parse_metadata->'verification'->>'label_human' as label,
    COUNT(*) as count
FROM companies
WHERE parse_metadata->'verification'->>'label_human' IS NOT NULL
GROUP BY label;
```

## Data Structure

Verification results are stored in `companies.parse_metadata['verification']`:

```json
{
  "verification": {
    "status": "passed",
    "score": 0.82,
    "combined_score": 0.85,
    "tier": "A",
    "services_detected": {
      "pressure": {"any": true, "residential": true, "commercial": true},
      "window": {"any": true, "residential": true, "commercial": true},
      "wood": {"any": true, "residential": true, "commercial": true}
    },
    "positive_signals": [
      "Pressure service keyword: pressure washing",
      "Pressure residential context: homeowners",
      "Pressure commercial context: commercial property",
      "Window service keyword: window cleaning",
      "Provider language detected (5 phrases)",
      "Call-to-action phrases detected (3)",
      "US phone number present",
      "Physical address present",
      "Pressure in navigation: pressure washing",
      "LocalBusiness schema detected: LocalBusiness"
    ],
    "negative_signals": [],
    "reason": "Verified target service company (Tier A)",
    "needs_review": false,
    "verified_at": "2025-11-23T10:30:00",
    "label_human": "target",
    "label_updated_at": "2025-11-23T11:45:00"
  }
}
```

## Configuration

### Service Keywords (`data/verification_services.json`)

Edit this file to:
- Add new service keywords
- Update residential/commercial context words
- Add negative filter keywords
- Modify provider/informational phrases

**Example**: Adding "soft wash" as a pressure washing keyword:
```json
{
  "pressure": {
    "keywords": [
      "pressure washing",
      "power washing",
      "soft wash",  // <-- Add here
      ...
    ]
  }
}
```

### Thresholds

Adjust in batch job command or code:
```bash
# More aggressive auto-accept
python db/verify_company_urls.py --min-score 0.70

# More conservative auto-reject
python db/verify_company_urls.py --max-score 0.40
```

## Pending Features (Phases 5-6)

### Phase 5: ML Classifier (Not Yet Implemented)

**Goal**: Handle edge cases rules can't capture.

**Steps**:
1. Export labelled dataset (150-300 target, 150-300 non-target)
2. Feature engineering (counts, booleans, discovery signals)
3. Train scikit-learn model (logistic regression or gradient boosting)
4. Integrate into service_verifier.py

**Hooks already in place**:
- `ServiceVerifier._load_ml_model()`
- `ServiceVerifier._get_ml_score()`
- `ServiceVerifier._extract_ml_features()`

### Phase 6: Optimization & Monitoring

**Remaining tasks**:
- **6.1**: Calibrate thresholds using precision/recall analysis
- **6.3**: Domain-level caching (avoid re-scraping same domain)
- **6.4**: Monitoring dashboard (track trends, alert on issues)

## Examples

### Example 1: Strong Target (Tier A, Passed)

**Company**: ABC Pressure Washing & Window Cleaning
**Website**: abc-power-wash.com
**Score**: 0.87
**Tier**: A
**Status**: passed

**Signals**:
- ✅ All 3 services detected (pressure, window, wood)
- ✅ Both residential and commercial context for all
- ✅ Provider language: "we provide", "free estimate", "call today"
- ✅ CTA phrases: "book now", "get a quote"
- ✅ Phone, email, address present
- ✅ LocalBusiness schema detected
- ✅ Services in navigation

### Example 2: Equipment Seller (Tier D, Failed)

**Company**: PowerWash Equipment Depot
**Website**: powerwash-equipment.com
**Score**: 0.12
**Tier**: D
**Status**: failed

**Signals**:
- ✅ Pressure washing keyword detected
- ❌ Equipment keywords: "for sale", "add to cart", "checkout"
- ❌ No provider language
- ❌ No service context (only product descriptions)
- ❌ No local business schema

### Example 3: Unclear (Tier C, Needs Review)

**Company**: ProClean Services
**Website**: proclean-blog.com
**Score**: 0.52
**Tier**: C
**Status**: unknown (needs review)

**Signals**:
- ✅ Pressure washing keyword detected
- ✅ Residential context
- ⚠️ Heavy informational content: "guide to", "how to"
- ⚠️ Provider language weak (only 1 phrase)
- ⚠️ No commercial context
- ⚠️ No local business schema

**Action**: Needs manual review to determine if this is a blog vs real service provider.

## Troubleshooting

### Issue: Batch job fails with "No module named 'scrape_site'"

**Solution**: Ensure you're running from the washdb-bot root directory:
```bash
cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
python db/verify_company_urls.py
```

### Issue: "Config file not found: data/verification_services.json"

**Solution**: Verify the config file exists:
```bash
ls -la data/verification_services.json
```

### Issue: Companies not showing in GUI review table

**Solution**: Run batch verification first to populate verification metadata:
```bash
python db/verify_company_urls.py --max-companies 50
```

### Issue: Website scraping fails with timeouts

**Solution**: Increase timeout in `scrape_site/site_scraper.py` or skip failed sites:
```python
REQUEST_TIMEOUT = 60  # Increase from 30 to 60 seconds
```

## Development Workflow

### 1. Make Changes to Config

Edit `data/verification_services.json` to add keywords or adjust filters.

### 2. Test Verification Logic

```bash
# Test on a small batch
python db/verify_company_urls.py --max-companies 10
```

### 3. Review Results in GUI

```bash
./scripts/dev/run-gui.sh
# Navigate to /verification
```

### 4. Manually Label Edge Cases

Use the GUI to mark companies as Target/Non-target for ML training.

### 5. Export Labels for ML (Phase 5)

```sql
COPY (
    SELECT
        id,
        name,
        website,
        parse_metadata->'verification'->>'label_human' as label,
        parse_metadata
    FROM companies
    WHERE parse_metadata->'verification'->>'label_human' IS NOT NULL
) TO '/tmp/labeled_companies.csv' CSV HEADER;
```

## Summary

**What's Complete**:
- ✅ Phase 0: Configuration and wiring
- ✅ Phase 1-3: Rule-based verifier with combined scoring
- ✅ Phase 4: GUI review page with manual labeling
- ✅ Phase 6.2: Batch verification job

**What's Pending**:
- ⏳ Phase 5: ML classifier (foundation ready, needs training data)
- ⏳ Phase 6.1, 6.3, 6.4: Threshold calibration, caching, monitoring

**Ready to Use**: You can start using the verification bot immediately for rule-based filtering and manual review!

---

**For detailed implementation plans**, see: `/home/rivercityscrape/Downloads/verification_bot_plans.md`
**For questions**, check: `docs/ARCHITECTURE.md` or GUI `/diagnostics` page

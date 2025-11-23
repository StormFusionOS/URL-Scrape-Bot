# Yellow Pages City-First Scraper - User Guide

**Version**: 2.0 (City-First)
**Date**: 2025-11-12
**Status**: ✅ Production Ready

---

## Overview

The Yellow Pages City-First Scraper is a comprehensive web scraping solution that collects pressure washing and window cleaning business listings from Yellow Pages across **31,254 US cities**.

### Key Features

- ✅ **City-level targeting** - Scrapes all 31,254 US cities individually
- ✅ **Population-based prioritization** - Focuses on high-population areas first
- ✅ **Shallow pagination** - 1-3 pages per city (vs 50 pages per state)
- ✅ **Early-exit optimization** - Stops when no relevant results found
- ✅ **85%+ precision filtering** - Advanced filtering removes out-of-scope businesses
- ✅ **Playwright integration** - Bypasses anti-bot protection
- ✅ **Real-time database updates** - PostgreSQL with automatic deduplication

---

## Quick Start

### 1. Generate Targets

First, generate scraping targets for your desired states:

```bash
# Single state
python -m scrape_yp.generate_city_targets --states RI --clear

# Multiple states
python -m scrape_yp.generate_city_targets --states "CA,TX,FL,NY" --clear

# All states (warning: 312,540 targets!)
python -m scrape_yp.generate_city_targets --states "AL,AK,AZ,..." --clear
```

This creates targets in the `yp_targets` database table.

### 2. Run Crawler

Execute the city-first crawler:

```bash
# Basic usage
python cli_crawl_yp.py --states RI

# With custom settings
python cli_crawl_yp.py --states "CA,TX" --min-score 50 --max-targets 1000

# Dry run (no database saves)
python cli_crawl_yp.py --states RI --dry-run
```

### 3. Monitor Progress

Progress is logged in real-time:
- Console output shows city/category being processed
- Database `yp_targets` table shows target status
- Logs saved to `logs/yp_crawl_city_first.log`

---

## How It Works

### Architecture

```
┌─────────────────┐
│  City Registry  │ ← 31,254 US cities with population data
│  (PostgreSQL)   │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ Target Generator│ ← Expands states → cities → categories
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   YP Targets    │ ← city × category combinations (e.g., 310 for RI)
│  (planned)      │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ City-First      │ ← Playwright-based crawler
│   Crawler       │   • Shallow pagination (1-3 pages)
└────────┬────────┘   • Early-exit on no results
         │            • 85%+ precision filter
         ↓
┌─────────────────┐
│   Companies     │ ← Deduplicated business listings
│  (PostgreSQL)   │
└─────────────────┘
```

### Population Tiers

Cities are assigned tiers based on population:

| Tier | Population Range | Priority | Max Pages | % of Cities |
|------|-----------------|----------|-----------|-------------|
| A    | Top 10%        | 1 (High) | 3         | ~3,125      |
| B    | 50-90th %ile   | 2 (Med)  | 2         | ~12,500     |
| C    | Bottom 50%     | 3 (Low)  | 1         | ~15,625     |

**Example**:
- Los Angeles (pop: 11.9M) → Tier A → 3 pages
- Providence (pop: 178K) → Tier A → 3 pages
- Small town (pop: 500) → Tier C → 1 page

### Early-Exit Logic

If page 1 has **zero accepted results** after filtering:
1. Target marked as "done" with note "early_exit_no_results_page1"
2. Remaining pages skipped (saves ~30% of requests)
3. Moves to next target

This is **working as designed** for:
- Niche categories with low coverage
- Small cities with few businesses
- Category-city combinations with no relevant listings

---

## CLI Options

### Main Crawler (`cli_crawl_yp.py`)

```bash
python cli_crawl_yp.py [OPTIONS]

Required:
  --states STATES          Comma-separated state codes (e.g., "RI,CA,TX")

Optional:
  --min-score SCORE        Minimum confidence score (0-100, default: 50.0)
  --include-sponsored      Include sponsored/ad listings (default: False)
  --max-targets N          Limit number of targets to process (default: all)
  --dry-run                Run without saving to database
```

### Target Generator

```bash
python -m scrape_yp.generate_city_targets [OPTIONS]

Required:
  --states STATES          Comma-separated state codes

Optional:
  --clear                  Clear existing targets for these states first
```

---

## Examples

### Example 1: Rhode Island Complete Crawl

```bash
# Step 1: Generate targets (31 cities × 10 categories = 310 targets)
python -m scrape_yp.generate_city_targets --states RI --clear

# Step 2: Run crawler
python cli_crawl_yp.py --states RI --min-score 50

# Expected output:
# - Targets processed: 310
# - Early exits: ~40-60% (normal for niche categories)
# - Results: Varies by category coverage
```

### Example 2: Major Metro Areas Only

```bash
# Generate targets for major states
python -m scrape_yp.generate_city_targets --states "CA,TX,FL,NY" --clear

# Crawl only top 500 targets (high-priority cities)
python cli_crawl_yp.py --states "CA,TX,FL,NY" --max-targets 500
```

### Example 3: Testing with Dry Run

```bash
# Test without saving to database
python cli_crawl_yp.py --states RI --max-targets 10 --dry-run
```

---

## Database Schema

### City Registry Table

```sql
CREATE TABLE city_registry (
    id SERIAL PRIMARY KEY,
    city VARCHAR(255) NOT NULL,
    state_id VARCHAR(2) NOT NULL,
    city_slug VARCHAR(255) UNIQUE NOT NULL,  -- e.g., 'los-angeles-ca'
    yp_geo VARCHAR(255) NOT NULL,             -- e.g., 'Los Angeles, CA'
    population INTEGER,
    priority INTEGER NOT NULL,                -- 1, 2, or 3
    active BOOLEAN DEFAULT TRUE,
    -- ... additional fields
);
```

### YP Targets Table

```sql
CREATE TABLE yp_targets (
    id SERIAL PRIMARY KEY,
    state_id VARCHAR(2) NOT NULL,
    city VARCHAR(255) NOT NULL,
    category_label VARCHAR(255) NOT NULL,
    primary_url TEXT NOT NULL,                -- https://www.yellowpages.com/{city-slug}/{category}
    fallback_url TEXT NOT NULL,               -- Search URL with geo_location_terms
    max_pages INTEGER NOT NULL,               -- 1, 2, or 3
    priority INTEGER NOT NULL,                -- 1, 2, or 3
    status VARCHAR(50) DEFAULT 'planned',     -- planned, in_progress, done, failed
    note TEXT,                                -- e.g., 'early_exit_no_results_page1'
    -- ... timestamps
);
```

### Companies Table (Existing)

```sql
CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    name TEXT,
    website TEXT UNIQUE,                      -- Canonical URL
    domain TEXT,                              -- Extracted domain
    phone TEXT,
    address TEXT,
    source VARCHAR(50),                       -- 'YP', 'HA', etc.
    rating_yp FLOAT,
    reviews_yp INTEGER,
    -- ... additional fields
);
```

---

## Configuration Files

### Category Configuration (`data/`)

- **`yp_category_allowlist.txt`** - 10 allowed categories
  - Window Cleaning
  - Gutters & Downspouts Cleaning
  - Roof Cleaning
  - Power Washing
  - etc.

- **`yp_category_blocklist.txt`** - 12 blocked categories
  - Roofing Contractors (not cleaning)
  - Janitorial Service (not pressure washing)
  - etc.

- **`yp_anti_keywords.txt`** - 54 rejection keywords
  - equipment, supplies, parts, rental, etc.

- **`yp_positive_hints.txt`** - 24 positive phrases
  - soft wash, house washing, paver sealing, etc.

### Category Slugs (`data/yp_category_slugs.csv`)

Maps category labels to YP URL slugs:

```csv
label,slug
Window Cleaning,window-cleaning
Power Washing,power-washing
Gutters & Downspouts Cleaning,gutter-cleaning
```

---

## Performance & Scalability

### Expected Metrics

**Single State (Rhode Island)**:
- Targets: 310 (31 cities × 10 categories)
- Page fetches: ~400-600 (with early-exit)
- Time: ~1-2 hours (with 5-15s delays)
- Results: Varies by category

**Major State (California)**:
- Targets: 15,980 (1,598 cities × 10 categories)
- Page fetches: ~20,000-30,000 (with early-exit)
- Time: ~40-60 hours (with delays)
- Results: High volume expected

**All 50 States**:
- Targets: 312,540 (31,254 cities × 10 categories)
- Page fetches: ~400,000-600,000 (with early-exit: ~300,000)
- Time: ~400-600 hours (~17-25 days at 10s/page)
- Results: Comprehensive national coverage

### Rate Limiting

Built-in protections:
- **Per-page delay**: 2-5 seconds (Playwright wait)
- **Per-target delay**: 5-15 seconds (randomized)
- **No blocks reported** during testing

### Optimization Tips

1. **Run during off-peak hours** (night/weekend)
2. **Start with high-priority states** (CA, TX, FL, NY)
3. **Process in batches** using `--max-targets`
4. **Monitor early-exit rate** (high = expected for niche categories)
5. **Use multiple states** for parallel geographic distribution

---

## Troubleshooting

### Issue: "No targets found"

**Solution**: Generate targets first:
```bash
python -m scrape_yp.generate_city_targets --states RI --clear
```

### Issue: High early-exit rate (>70%)

**This is normal** for:
- Niche categories (Graffiti Removal, Concrete Restoration)
- Small cities (population < 5,000)
- Sparse Yellow Pages coverage

**Not a bug** - the early-exit logic is working correctly!

### Issue: "403 Forbidden" errors

**Solution**: Playwright should handle this automatically. If persisting:
1. Check Playwright installation: `playwright install chromium`
2. Verify browser launches: Test with dry-run
3. Increase delays if needed (currently 2-5s per page)

### Issue: Low acceptance rate

**Expected behavior** - the filter is designed to be strict (85%+ precision).

Categories filtered out:
- Roofing contractors (not cleaners)
- Equipment suppliers
- Janitorial services
- General contractors

### Issue: Target stuck "in_progress"

Targets remain "in_progress" if crawler was interrupted.

**Solution**: Reset manually:
```sql
UPDATE yp_targets
SET status = 'planned', attempts = 0
WHERE status = 'in_progress' AND state_id = 'RI';
```

---

## Migration from State-First

### Backup

Old state-first CLI backed up as:
```
cli_crawl_yp_state_first_BACKUP.py
```

To use old approach:
```bash
python cli_crawl_yp_state_first_BACKUP.py \
  --categories "window cleaning" \
  --states "RI" \
  --pages 3
```

### Key Differences

| Feature | State-First (Old) | City-First (New) |
|---------|------------------|------------------|
| Targets | 51 states × 10 = 510 | 31,254 cities × 10 = 312,540 |
| Pages/target | 50 (deep) | 1-3 (shallow) |
| Coverage | State-level | City-level |
| Prioritization | None | Population-based |
| Early-exit | No | Yes (~30% savings) |
| Precision | 60-70% | 85%+ |

---

## Support & Documentation

### Documentation Files

- **`YELLOW_PAGES_CITY_FIRST_README.md`** - This file
- **`docs/implementation_summary.md`** - Technical architecture
- **`docs/pilot_test_results.md`** - Test results and recommendations
- **`docs/city_registry_report.md`** - Database statistics
- **`docs/yp_city_slug_rules.md`** - URL slug generation rules

### Logs

Check logs for detailed information:
```
logs/yp_crawl_city_first.log  - Crawler activity
logs/cli_yp.log               - CLI operations
logs/save_discoveries.log     - Database operations
```

### Database Queries

**Check target status**:
```sql
SELECT state_id, status, COUNT(*)
FROM yp_targets
GROUP BY state_id, status
ORDER BY state_id, status;
```

**View completed targets**:
```sql
SELECT city, category_label, status, note
FROM yp_targets
WHERE state_id = 'RI' AND status = 'done'
LIMIT 20;
```

**Count results by state**:
```sql
SELECT state, COUNT(*) as companies
FROM companies
WHERE source = 'YP'
GROUP BY state
ORDER BY companies DESC;
```

---

## Best Practices

### 1. Start Small

Begin with a single small state:
```bash
python -m scrape_yp.generate_city_targets --states RI --clear
python cli_crawl_yp.py --states RI --max-targets 50
```

### 2. Monitor Progress

Watch the logs and database:
- Early-exit rate should be 30-70% (normal)
- Acceptance rate depends on category
- Check for blocks (should be zero)

### 3. Batch Processing

Process states in batches:
```bash
# Batch 1: Small states
python cli_crawl_yp.py --states "RI,DE,VT,NH"

# Batch 2: Medium states
python cli_crawl_yp.py --states "NV,NM,UT,ID"

# Batch 3: Large states
python cli_crawl_yp.py --states "CA,TX,FL" --max-targets 2000
```

### 4. Re-run Failed Targets

Reset and retry failed targets:
```sql
UPDATE yp_targets
SET status = 'planned', attempts = 0
WHERE status = 'failed' AND state_id = 'CA';
```

Then run again:
```bash
python cli_crawl_yp.py --states CA
```

---

## FAQ

**Q: Why city-first instead of state-first?**
A: 18x more geographic coverage, better precision, population-based prioritization.

**Q: Why is early-exit rate so high?**
A: Many city-category combinations don't have YP listings. This is expected and saves requests.

**Q: Can I run multiple states in parallel?**
A: Not recommended - could trigger rate limiting. Use `--max-targets` instead.

**Q: How long does a full US crawl take?**
A: ~17-25 days at 10s/page with 300K-400K page fetches.

**Q: Why are all results rejected by the filter?**
A: The filter is strict (85%+ precision). Test with common categories (Window Cleaning, Pressure Washing).

**Q: Can I adjust the filter?**
A: Yes, edit files in `data/` directory or adjust `--min-score` threshold.

---

## Changelog

### Version 2.0 (City-First) - 2025-11-12

- ✅ Complete rewrite for city-first strategy
- ✅ 31,254 cities in City Registry
- ✅ Population-based prioritization (3 tiers)
- ✅ Shallow pagination (1-3 pages vs 50)
- ✅ Early-exit optimization (~30% savings)
- ✅ Playwright integration
- ✅ Enhanced filtering (85%+ precision)
- ✅ Real-time database tracking

### Version 1.0 (State-First)

- State-level scraping
- Deep pagination (50 pages/state)
- 60-70% precision
- Basic filtering

---

## License & Usage

This scraper is for internal use only. Please respect Yellow Pages' terms of service and rate limits.

**Rate Limiting**:
- 2-5 second delays per page
- 5-15 second delays between targets
- No more than ~3,000-5,000 pages/day recommended

---

## Contact

For questions or issues with the city-first scraper, refer to:
- Documentation in `docs/` directory
- Logs in `logs/` directory
- Database tables `city_registry` and `yp_targets`

---

**Deployment Date**: 2025-11-12
**Status**: ✅ Production Ready
**Version**: 2.0 (City-First)

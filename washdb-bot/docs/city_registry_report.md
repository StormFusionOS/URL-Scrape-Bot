# City Registry Implementation Report

**Date**: 2025-11-12
**Status**: ✅ **Phases 1-3 Complete** (Data Infrastructure & Target Generation)

---

## Executive Summary

Successfully implemented the foundational infrastructure for the Yellow Pages city-first scraper. The system is now ready for crawler implementation.

**Key Achievements**:
- ✅ **31,254 cities** loaded into PostgreSQL City Registry
- ✅ **310 Rhode Island targets** generated (31 cities × 10 categories)
- ✅ **Population-based prioritization** with 3-tier system
- ✅ **City slug normalization** with duplicate handling
- ✅ **URL generation** (primary + fallback) verified

---

## Phase 1: City Registry & Data Infrastructure ✅

### 1.1 Database Models Created

**Location**: `db/models.py`

**New Tables**:
1. **`city_registry`** (31,254 rows)
   - Fields: city, state_id, lat/lng, population, city_slug, yp_geo, priority
   - Indexes: state_id, city_slug (unique), population, priority, active
   - Population percentiles calculated: 90th = 13,854 | 50th = 948

2. **`yp_targets`** (310 rows for RI)
   - Fields: city_slug, category, primary_url, fallback_url, max_pages, status
   - Indexes: state_id, city, category_label, status, priority
   - Statuses: planned, in_progress, done, failed, parked

### 1.2 City Slug Normalization

**Module**: `scrape_yp/city_slug.py`

**Functions**:
- `generate_city_slug(city, state_id)` → "los-angeles-ca"
- `generate_yp_geo(city, state_id)` → "Los Angeles, CA"
- `calculate_population_tier(pop, p90, p50)` → 1, 2, or 3
- `tier_to_max_pages(tier)` → 3, 2, or 1

**Rules**:
- Lowercase, hyphenate, normalize abbreviations (St. → saint)
- Handles duplicates by appending county name
- All test cases pass ✓

**Documentation**: `docs/yp_city_slug_rules.md`

### 1.3 Population-Based Prioritization

| Tier | Description | Population Range | Priority | Max Pages |
|------|-------------|------------------|----------|-----------|
| A | High | Top 10% (≥13,854) | 1 | 3 |
| B | Medium | 50-90th percentile | 2 | 2 |
| C | Low | Bottom 50% (<948) | 3 | 1 |

**Rhode Island Example**:
- Providence: 178,042 pop → Tier A → 3 pages
- Cranston: 80,387 pop → Tier A → 3 pages
- Smaller cities: Tier B/C → 1-2 pages

---

## Phase 2: Configuration Assets ✅

### 2.1 Files Created

**Location**: `data/`

1. **`yp_category_slugs.csv`** (10 categories)
   ```csv
   label,slug
   Window Cleaning,window-cleaning
   Power Washing,power-washing
   ...
   ```

2. **`yp_synonym_queries.txt`** (23 terms)
   ```
   house washing
   soft wash
   paver sealing
   ...
   ```

3. **`yp_city_slug_exceptions.csv`** (empty - will populate during testing)
   ```csv
   city,state_id,override_slug,notes
   ```

### 2.2 Existing Files (Already Complete)
- ✅ `yp_category_allowlist.txt` (10 categories)
- ✅ `yp_category_blocklist.txt` (12 categories)
- ✅ `yp_anti_keywords.txt` (54 keywords)
- ✅ `yp_positive_hints.txt` (24 phrases)

---

## Phase 3: Target Generation ✅

### 3.1 Target Generator Module

**Location**: `scrape_yp/generate_city_targets.py`

**Usage**:
```bash
python -m scrape_yp.generate_city_targets --states RI --clear
```

**Features**:
- Expands states → all active cities → all categories
- Builds primary URLs: `/{city-slug}/{category-slug}`
- Builds fallback URLs: `/search?search_terms=...&geo_location_terms=...`
- Assigns max_pages based on population tier
- Batch inserts (1000/batch) for performance

### 3.2 Rhode Island Test Targets

**Generated**: 310 targets (31 cities × 10 categories)

**Sample URLs** (Providence, RI):
```
Primary:  https://www.yellowpages.com/providence-ri/window-cleaning
Fallback: https://www.yellowpages.com/search?search_terms=Window+Cleaning&geo_location_terms=Providence%2C+RI
```

**Target Distribution**:
- State: RI
- Cities: 31
- Categories: 10
- Targets: 310
- Status: All "planned"

---

## City Registry Statistics

### Cities by State (Top 10)

| State | State Name | Cities |
|-------|------------|--------|
| PA | Pennsylvania | 1,886 |
| TX | Texas | 1,836 |
| CA | California | 1,598 |
| IL | Illinois | 1,456 |
| OH | Ohio | 1,253 |
| MO | Missouri | 1,081 |
| IA | Iowa | 1,024 |
| IN | Indiana | 974 |
| NY | New York | 968 |
| FL | Florida | 944 |

### Rhode Island Cities (Test State)

**Total**: 31 cities

**Major Cities**:
- Providence (178,042 pop) - Tier A
- Cranston (80,387 pop) - Tier A
- Warwick (81,579 pop) - Tier A
- Pawtucket (71,172 pop) - Tier A
- East Providence (47,037 pop) - Tier A

**Tier Distribution** (estimated):
- Tier A: ~10 cities (3 pages each)
- Tier B: ~12 cities (2 pages each)
- Tier C: ~9 cities (1 page each)

---

## Files Created/Modified

### New Files

**Database Migrations**:
- `db/populate_city_registry.py` - Population script

**Core Modules**:
- `scrape_yp/city_slug.py` - Slug normalization
- `scrape_yp/generate_city_targets.py` - Target generator

**Documentation**:
- `docs/uscities_profile.md` - Dataset profile
- `docs/yp_city_slug_rules.md` - Slug generation rules
- `docs/city_registry_report.md` - This file

**Configuration**:
- `data/yp_category_slugs.csv`
- `data/yp_synonym_queries.txt`
- `data/yp_city_slug_exceptions.csv`

### Modified Files

**Database Models**:
- `db/models.py` - Added CityRegistry and YPTarget models

---

## Technical Validation

### Database Schema

**Tables Created**:
```sql
CREATE TABLE city_registry (
    id SERIAL PRIMARY KEY,
    city VARCHAR(255) NOT NULL,
    state_id VARCHAR(2) NOT NULL,
    city_slug VARCHAR(255) UNIQUE NOT NULL,
    yp_geo VARCHAR(255) NOT NULL,
    population INTEGER,
    priority INTEGER NOT NULL DEFAULT 2,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    -- ... 16 more fields
);

CREATE TABLE yp_targets (
    id SERIAL PRIMARY KEY,
    state_id VARCHAR(2) NOT NULL,
    city VARCHAR(255) NOT NULL,
    city_slug VARCHAR(255) NOT NULL,
    category_label VARCHAR(255) NOT NULL,
    category_slug VARCHAR(255) NOT NULL,
    primary_url TEXT NOT NULL,
    fallback_url TEXT NOT NULL,
    max_pages INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 2,
    status VARCHAR(50) NOT NULL DEFAULT 'planned',
    -- ... 6 more fields
);
```

### URL Validation

**Test Cases** (Providence, RI):
- ✅ Window Cleaning: `/providence-ri/window-cleaning`
- ✅ Power Washing: `/providence-ri/power-washing`
- ✅ Gutter Cleaning: `/providence-ri/gutter-cleaning`

**Fallback URLs**:
- ✅ Properly URL-encoded geo_location_terms
- ✅ Category labels preserved in search_terms

### Slug Normalization Tests

| Input | State | Expected | Result |
|-------|-------|----------|--------|
| Los Angeles | CA | `los-angeles-ca` | ✓ |
| St. Louis | MO | `saint-louis-mo` | ✓ |
| Fort Worth | TX | `fort-worth-tx` | ✓ |
| O'Fallon | IL | `o-fallon-il` | ✓ |
| Providence | RI | `providence-ri` | ✓ |

---

## Next Steps

### Phase 4: City-First Crawler (Pending)

**Tasks**:
1. Create `scrape_yp/yp_crawl_city_first.py`
   - Read targets from `yp_targets` table (status='planned')
   - Sort by priority (Tier A cities first)
   - Reuse existing `yp_parser_enhanced.py` and `yp_filter.py`

2. Implement shallow pagination:
   - Fetch pages 1 to `max_pages` (1-3)
   - Early exit if page 1 = 0 accepted listings
   - Update target status: planned → in_progress → done

3. Add rate limiting:
   - Maintain existing 10s delay + jitter
   - Park targets on block detection
   - Exponential backoff on failures

### Phase 5: Testing & Validation (Pending)

**Rhode Island Pilot**:
- Target: 310 targets (31 cities × 10 categories)
- Expected page fetches: ~600 (vs 500 for state-first)
- Validate: Precision ≥85%, no duplicate domains

**Metrics to Collect**:
- Targets processed
- Pages fetched (actual vs expected)
- Accepted listings
- Early-exit triggers
- Block events

### Phase 6: CLI & Finalization (Pending)

**Tasks**:
1. Update `cli_crawl_yp.py` for city-first only
2. Update NiceGUI dashboard pages
3. Generate run reports and final documentation

---

## Success Criteria ✅

### Completed

- ✅ City Registry contains 31,254 cities with valid slugs
- ✅ Population percentiles calculated and tiers assigned
- ✅ Target generator expands states correctly
- ✅ URLs generated for RI test (310 targets)
- ✅ Slug normalization passes all tests
- ✅ Duplicate city names handled (county suffix)

### Remaining

- ⏳ City-first crawler implementation
- ⏳ Rhode Island pilot crawl
- ⏳ Precision validation ≥85%
- ⏳ Early-exit reduces page fetches by 30%+
- ⏳ No duplicate domains in results
- ⏳ CLI and GUI updates

---

## Estimated Completion

**Time Spent**: ~3-4 hours (Phases 1-3)
**Remaining**: ~4-6 hours (Phases 4-6)
**Total**: ~8-10 hours (as estimated)

**Current Progress**: 60% complete

---

## Risk Mitigation

### Duplicate Slugs
- ✅ Resolved by appending county name when duplicates detected
- Example: `woodbury-ny` + `woodbury-ny-suffolk` + `woodbury-ny-nassau`

### Population Data Quality
- ✅ 31,254 valid population values
- ✅ Percentiles calculated: 90th = 13,854 | 50th = 948
- ✅ Default tier = 3 if population missing

### Database Performance
- ✅ Batch inserts (1000/batch) for fast population
- ✅ Indexes on state_id, city_slug, priority, status
- ✅ All 31,254 cities inserted in <30 seconds

---

## Conclusion

The foundational infrastructure for the city-first scraper is complete and validated. The City Registry provides a robust, population-prioritized dataset ready for crawler implementation. Target generation successfully expands states into city × category targets with correctly formatted URLs.

**Ready for Phase 4**: City-first crawler development

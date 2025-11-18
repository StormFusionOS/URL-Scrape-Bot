# HomeAdvisor ZIP Code Migration Guide

## Overview

HomeAdvisor has been migrated to use **ZIP code-based searches** instead of state-level searches for better targeting and results.

## Two Crawlers Available

### 1. Legacy State-Level Crawler (ha_crawl.py)
**Status**: Still works but NOT RECOMMENDED

```bash
python3 scrape_ha/ha_crawl.py --states AL TX --pages 3
```

**Limitations**:
- Returns fewer results
- Less targeted (entire state at once)
- May miss businesses in smaller cities

### 2. NEW ZIP Code-Based Crawler (ha_crawl_zip_based.py)
**Status**: RECOMMENDED - Production Ready

```bash
# Crawl major cities only (Tier A)
python3 scrape_ha/ha_crawl_zip_based.py --tiers A

# Crawl specific states with all tiers
python3 scrape_ha/ha_crawl_zip_based.py --states AL TX CA

# Limit to first 10 cities
python3 scrape_ha/ha_crawl_zip_based.py --max-cities 10

# Full production crawl
python3 scrape_ha/ha_crawl_zip_based.py
```

## Database Infrastructure

### city_registry Table
**31,252 US cities** loaded with:
- Primary ZIP code for each city
- Population-based tiers:
  - **Tier A** (466 cities): 100k+ population → 3 pages
  - **Tier B** (1,373 cities): 25k-100k → 2 pages
  - **Tier C** (29,342 cities): <25k → 1 page

### Query Examples

```sql
-- Get all Tier A cities in Alabama
SELECT city, state_id, primary_zip, population
FROM city_registry
WHERE state_id = 'AL' AND tier = 'A'
ORDER BY population DESC;

-- Count cities by tier
SELECT tier, COUNT(*) as count
FROM city_registry
GROUP BY tier;
```

## URL Format Differences

### Legacy (State-Level)
```
https://www.homeadvisor.com/near-me/power-washing/?state=AL&page=1
```

### New (ZIP Code-Based)
```
https://www.homeadvisor.com/find?postalCode=35218&query=power+washing&searchType=SiteTaskSearch&initialSearch=true
```

## Migration Path

### Phase 1: Testing (Current)
- Both crawlers work
- Old crawler uses legacy URLs
- New crawler uses ZIP code URLs

### Phase 2: Production Switch
Replace calls to `ha_crawl.py` with `ha_crawl_zip_based.py`:

**Before**:
```bash
python3 scrape_ha/ha_crawl.py --states AL --pages 3
```

**After**:
```bash
python3 scrape_ha/ha_crawl_zip_based.py --states AL --tiers A B
```

### Phase 3: Deprecation
Eventually remove `ha_crawl.py` once ZIP code crawler is proven in production.

## Performance Comparison

| Feature | Legacy (State) | New (ZIP Code) |
|---------|---------------|----------------|
| Targeting | Entire state | Per city/ZIP |
| Results | Limited | Comprehensive |
| Cities covered | ~50 hardcoded | 31,252 from DB |
| Prioritization | None | Population-based |
| Scalability | Low | High |

## Troubleshooting

### Error: "zip_code is required"
**Cause**: Old crawler trying to use new URL format
**Fix**: `build_search_url()` is now backward compatible - error should not occur

### No results from ZIP code searches
**Check**:
1. Playwright browser is installed: `pip3 install playwright-stealth`
2. ZIP code exists in city_registry: `SELECT * FROM city_registry WHERE primary_zip = '35218'`
3. Browser automation is working (check logs)

## Next Steps

1. Test ZIP code crawler with sample states
2. Compare results quality between old and new crawlers
3. Run parallel crawls to validate data quality
4. Switch production to ZIP code crawler
5. Deprecate old state-level crawler

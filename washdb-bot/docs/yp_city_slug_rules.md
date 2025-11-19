# Yellow Pages City Slug Rules

**Module**: `scrape_yp/city_slug.py`
**Purpose**: Generate YP-compatible city-state slugs for URL construction

---

## Overview

Yellow Pages uses city-state slugs in their URL structure for category browsing:
```
https://www.yellowpages.com/{city-slug}-{state}/category-slug
```

**Examples**:
- `https://www.yellowpages.com/los-angeles-ca/window-cleaning`
- `https://www.yellowpages.com/saint-louis-mo/pressure-washing`
- `https://www.yellowpages.com/fort-worth-tx/gutter-cleaning`

---

## Slug Generation Rules

### 1. Convert to Lowercase
All characters are converted to lowercase.

**Example**: `Los Angeles` → `los angeles`

### 2. Remove Periods
Periods are stripped from the city name before normalization.

**Example**: `St. Louis` → `St Louis` → `st louis`

### 3. Normalize Common Abbreviations
Abbreviations at the **start** of city names are expanded:

| Abbreviation | Normalized Form |
|--------------|----------------|
| `St.` or `St` | `saint` |
| `Ft.` or `Ft` | `fort` |
| `Mt.` or `Mt` | `mount` |

**Examples**:
- `St. Louis` → `saint-louis-mo`
- `Fort Worth` → `fort-worth-tx`
- `Mt. Vernon` → `mount-vernon-ny`

**Note**: Only abbreviations at the **start** of the name are normalized. Mid-name abbreviations are left as-is.

### 4. Replace Spaces and Punctuation with Hyphens
Any non-alphanumeric character (except existing hyphens) is replaced with a hyphen.

**Examples**:
- `O'Fallon` → `o-fallon-il`
- `Coeur d'Alene` → `coeur-d-alene-id`

### 5. Collapse Multiple Hyphens
Consecutive hyphens are collapsed to a single hyphen.

**Example**: `City--Name` → `city-name`

### 6. Remove Leading/Trailing Hyphens
Any hyphens at the start or end of the slug are removed.

**Example**: `-city-name-` → `city-name`

### 7. Append State Code
The 2-letter state code is appended in lowercase with a hyphen.

**Example**: `los-angeles` + `CA` → `los-angeles-ca`

---

## Test Cases

| Input City | State | Expected Slug | Status |
|------------|-------|---------------|--------|
| Los Angeles | CA | `los-angeles-ca` | ✓ |
| St. Louis | MO | `saint-louis-mo` | ✓ |
| Fort Worth | TX | `fort-worth-tx` | ✓ |
| Mt. Vernon | NY | `mount-vernon-ny` | ✓ |
| O'Fallon | IL | `o-fallon-il` | ✓ |
| Winston-Salem | NC | `winston-salem-nc` | ✓ |
| New York | NY | `new-york-ny` | ✓ |
| Washington | DC | `washington-dc` | ✓ |

---

## Edge Cases & Exceptions

### Problematic City Names
Some city names may not follow standard patterns or may have special YP handling. These are stored in:
```
data/yp_city_slug_exceptions.csv
```

**Format**:
```csv
city,state_id,override_slug,notes
"McKeesport","PA","mckeesport-pa","Standard slug works"
```

### Non-English City Names
City names with non-ASCII characters should be handled by the `city_ascii` field from uscities.csv.

**Example**: `Zürich` → uses `city_ascii` = `Zurich` → `zurich-xx`

### Hyphenated City Names
Cities that already contain hyphens preserve them.

**Example**: `Winston-Salem, NC` → `winston-salem-nc`

---

## Fallback Search Format

When city-specific URLs fail or return no results, we use a **search URL** with `geo_location_terms`:

```
https://www.yellowpages.com/search?search_terms={category}&geo_location_terms={City, ST}
```

The `yp_geo` field format: `"{City}, {ST}"`

**Examples**:
- `Los Angeles, CA`
- `St. Louis, MO`
- `Fort Worth, TX`

**Note**: The original city name (with abbreviations) is preserved in `yp_geo` for search accuracy.

---

## Implementation

### Function: `generate_city_slug(city, state_id)`
Generates the YP-compatible slug.

**Returns**: `str` (e.g., `"los-angeles-ca"`)

### Function: `generate_yp_geo(city, state_id)`
Generates the fallback search geo format.

**Returns**: `str` (e.g., `"Los Angeles, CA"`)

---

## Population Tiers & Page Limits

Cities are assigned priority tiers based on population percentiles:

| Tier | Description | Population Range | Priority | Max Pages |
|------|-------------|------------------|----------|-----------|
| 1 | High Priority | Top 10% | 1 | 3 |
| 2 | Medium Priority | Next 40% (50-90th percentile) | 2 | 2 |
| 3 | Low Priority | Bottom 50% | 3 | 1 |

### Function: `calculate_population_tier(population, percentile_90, percentile_50)`
Determines tier based on population thresholds.

**Returns**: `int` (1, 2, or 3)

### Function: `tier_to_max_pages(tier)`
Converts tier to maximum pages for scraping.

**Returns**: `int` (1-3)

---

## Validation Protocol

Before using a city slug in production:

1. **Generate slug** using `generate_city_slug()`
2. **Test URL** by fetching with a known category (e.g., "window-cleaning")
3. **Check response**:
   - ✓ 200 OK with results → Slug is valid
   - ✗ 404 Not Found → Add to exceptions file
   - ✗ 200 OK but "no results" → Try fallback URL
4. **Document exceptions** in `data/yp_city_slug_exceptions.csv`

---

## Related Files

- **Implementation**: `scrape_yp/city_slug.py`
- **Exceptions**: `data/yp_city_slug_exceptions.csv`
- **City Registry**: Database table `city_registry`
- **Dataset**: `/home/rivercityscrape/Downloads/uscities.csv`

---

## Future Enhancements

1. **Automated Validation**: Script to test top 100 cities and auto-populate exceptions
2. **Fuzzy Matching**: If primary slug fails, try variations (with/without abbreviations)
3. **State-Specific Rules**: Handle state-specific naming conventions
4. **International Support**: Extend to Canadian cities (provinces instead of states)

# uscities.csv Dataset Profile

**Source File**: `/home/rivercityscrape/Downloads/uscities.csv`
**Date Verified**: 2025-11-12
**Total Cities**: 31,255 (estimated based on file size)

---

## Column Headers

The CSV file contains the following 17 columns:

| Column | Data Type | Description |
|--------|-----------|-------------|
| `city` | String | Full city name (may include special characters) |
| `city_ascii` | String | ASCII-normalized city name |
| `state_id` | String | 2-letter state code (e.g., "CA", "TX", "NY") |
| `state_name` | String | Full state name (e.g., "California", "Texas") |
| `county_fips` | String | 5-digit FIPS code for county |
| `county_name` | String | County name |
| `lat` | Float | Latitude (decimal degrees) |
| `lng` | Float | Longitude (decimal degrees) |
| `population` | Integer | Population estimate |
| `density` | Float | Population density (per square mile) |
| `source` | String | Data source (typically "shape") |
| `military` | Boolean | Military base flag ("TRUE"/"FALSE") |
| `incorporated` | Boolean | Incorporation status ("TRUE"/"FALSE") |
| `timezone` | String | IANA timezone (e.g., "America/New_York") |
| `ranking` | Integer | City size ranking (1=largest, 5=smallest) |
| `zips` | String | Space-separated list of ZIP codes |
| `id` | String | Unique city identifier |

---

## Sample Data (First 10 Cities)

### 1. New York, NY
- **Population**: 18,832,416
- **Density**: 10,943.7 per sq mi
- **Coordinates**: 40.6943, -73.9249
- **Timezone**: America/New_York
- **Ranking**: 1 (largest)
- **County**: Queens
- **ZIP Codes**: 270+ ZIP codes

### 2. Los Angeles, CA
- **Population**: 11,885,717
- **Density**: 3,165.7 per sq mi
- **Coordinates**: 34.1141, -118.4068
- **Timezone**: America/Los_Angeles
- **Ranking**: 1
- **County**: Los Angeles

### 3. Chicago, IL
- **Population**: 8,489,066
- **Density**: 4,590.3 per sq mi
- **Coordinates**: 41.8375, -87.6866
- **Timezone**: America/Chicago
- **Ranking**: 1

### 4. Miami, FL
- **Population**: 6,113,982
- **Density**: 4,791.1 per sq mi
- **Coordinates**: 25.7840, -80.2101
- **Timezone**: America/New_York
- **Ranking**: 1

### 5. Houston, TX
- **Population**: 6,046,392
- **Density**: 1,386.2 per sq mi
- **Coordinates**: 29.7860, -95.3885
- **Timezone**: America/Chicago
- **Ranking**: 1

### 6. Dallas, TX
- **Population**: 5,843,632
- **Density**: 1,477.1 per sq mi
- **Coordinates**: 32.7935, -96.7667
- **Timezone**: America/Chicago
- **Ranking**: 1

### 7. Philadelphia, PA
- **Population**: 5,696,588
- **Density**: 4,548.5 per sq mi
- **Coordinates**: 40.0077, -75.1339
- **Timezone**: America/New_York
- **Ranking**: 1

### 8. Atlanta, GA
- **Population**: 5,211,164
- **Density**: 1,424.8 per sq mi
- **Coordinates**: 33.7628, -84.4220
- **Timezone**: America/New_York
- **Ranking**: 1

### 9. Washington, DC
- **Population**: 5,146,120
- **Density**: 4,245.2 per sq mi
- **Coordinates**: 38.9047, -77.0163
- **Timezone**: America/New_York
- **Ranking**: 1
- **State**: District of Columbia

### 10. Boston, MA
- **Population**: 4,355,184
- **Density**: 5,303.2 per sq mi
- **Coordinates**: 42.3188, -71.0852
- **Timezone**: America/New_York
- **Ranking**: 1

### 11. Phoenix, AZ
- **Population**: 4,065,338
- **Density**: 1,210.3 per sq mi
- **Coordinates**: 33.5722, -112.0892
- **Timezone**: America/Phoenix
- **Ranking**: 1

### 12. Detroit, MI
- **Population**: 3,716,929
- **Density**: 1,771.8 per sq mi
- **Coordinates**: 42.3834, -83.1024
- **Timezone**: America/Detroit
- **Ranking**: 1

### 13. Seattle, WA
- **Population**: 3,555,253
- **Density**: 3,408.0 per sq mi
- **Coordinates**: 47.6211, -122.3244
- **Timezone**: America/Los_Angeles
- **Ranking**: 1

### 14. San Francisco, CA
- **Population**: 3,364,862
- **Density**: 6,916.7 per sq mi
- **Coordinates**: 37.7558, -122.4449
- **Timezone**: America/Los_Angeles
- **Ranking**: 1

---

## Key Observations

1. **Population Range**: From major metros (18M+) to small towns
2. **Ranking System**: 1-5 scale where 1=largest cities
3. **Multiple Timezones**: Covers all US timezones (Eastern, Central, Mountain, Pacific, etc.)
4. **ZIP Code Coverage**: Most cities have multiple ZIP codes
5. **Military Bases**: Flagged separately (e.g., Fort Bragg)
6. **Incorporated vs Unincorporated**: Flag tracks incorporation status

---

## Usage for City-First Scraper

### Population Tiers
We will use population percentiles to determine scraping depth:

- **Tier A** (Top 10%): Cities with highest populations → `max_pages = 3`
- **Tier B** (Next 40%): Mid-sized cities → `max_pages = 2`
- **Tier C** (Bottom 50%): Smaller cities → `max_pages = 1`

### City Slug Generation
The `city_ascii` field will be used as the base for URL slugs, with additional normalization:
- Convert to lowercase
- Replace spaces/punctuation with hyphens
- Handle abbreviations (St. → saint, Ft. → fort, Mt. → mount)
- Append `-{state_id}` (e.g., "los-angeles-ca")

### Fallback Search Format
The `yp_geo` field will be generated as `"{city}, {state_id}"` for search URLs:
- Example: "Los Angeles, CA"
- Example: "Saint Louis, MO"

---

## Data Quality Notes

- All cities in the 50 US states + Washington DC
- Population data is estimated (source: "shape" indicates GIS boundaries)
- ZIP codes are space-separated strings (need to parse if using individually)
- Coordinates use WGS84 datum (standard GPS coordinates)
- Boolean fields use string values "TRUE"/"FALSE" (not native booleans)

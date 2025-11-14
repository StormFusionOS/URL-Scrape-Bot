# Google Business Scraper Design Guide

Based on washdb-bot YP scraper architecture, this guide outlines the implementation strategy for a Google Business/Maps scraper.

---

## 1. HIGH-LEVEL ARCHITECTURE

### Parallel Structure to YP Scraper

```
Current (YP):                          Proposed (Google):
scrape_yp/                             scrape_google/
├── yp_client.py ----+---->            ├── google_client.py
├── yp_crawl.py ---+-+-+---->           ├── google_crawl.py
└── parse utilities                     └── google_parse.py

Both share:
├── db/ (models, database ops)
├── niceui/ (frontend pages)
├── runner/ (logging, orchestration)
```

### Two-Phase Approach (Reuse Existing Model)

**Phase 1: Discovery**
- Search Google Maps/Business for categories × locations
- Extract business listings
- Store in companies table with source='Google'

**Phase 2: Enrichment**
- Use existing site_scraper.py to visit websites
- Merge Google data with website data
- Update companies with enriched details

---

## 2. GOOGLE-SPECIFIC IMPLEMENTATION

### 2.1 Google Client (scrape_google/google_client.py)

Three approaches exist, each with tradeoffs:

#### Option A: Google Maps API (Official)
**Best for**: Reliability, structured data, easy pagination

```python
# Dependencies: google-maps-services

import googlemaps

client = googlemaps.Client(key='YOUR_API_KEY')

def search_google_maps(query, location, radius=15000):
    """
    Search Google Maps for businesses.
    
    Args:
        query: Business type (e.g., "pressure washing")
        location: Coordinates tuple (lat, lng) or address string
        radius: Search radius in meters (default: 15km)
    
    Returns:
        List of place results with:
        - name, address, phone, website
        - rating, review_count
        - place_id (unique identifier)
        - geometry (lat/lng)
    """
    # Use nearby search with pagination
    results = []
    page_token = None
    
    while True:
        response = client.places_nearby(
            location=location,
            radius=radius,
            keyword=query,
            page_token=page_token
        )
        
        for place in response.get('results', []):
            results.append({
                'name': place.get('name'),
                'address': place.get('vicinity'),
                'phone': place.get('formatted_phone_number'),
                'website': place.get('website'),
                'rating': place.get('rating'),
                'reviews': place.get('user_ratings_total'),
                'place_id': place.get('place_id'),
                'lat': place['geometry']['location']['lat'],
                'lng': place['geometry']['location']['lng'],
            })
        
        page_token = response.get('next_page_token')
        if not page_token:
            break
        
        time.sleep(2)  # Respect rate limits
    
    return results

def get_place_details(place_id):
    """Get detailed info for a single place."""
    details = client.place(place_id=place_id)
    
    result = details['result']
    return {
        'name': result.get('name'),
        'phone': result.get('formatted_phone_number'),
        'website': result.get('website'),
        'address': result.get('formatted_address'),
        'opening_hours': result.get('opening_hours', {}).get('weekday_text'),
        'photos': [p['photo_reference'] for p in result.get('photos', [])],
        'rating': result.get('rating'),
        'reviews': result.get('user_ratings_total'),
    }
```

**Pros:**
- Official, reliable
- Built-in pagination
- Structured data
- Rate limiting handled

**Cons:**
- $7/1000 requests (after free credits)
- Need API key management
- Limited free tier (25,000/day)

**Cost estimate**: 
- 50 states × 10 categories × 10 businesses = 5,000 requests
- $35/month continuous, ~$0.07 per run

---

#### Option B: Google Search Web Scraping
**Best for**: No API costs, no auth needed

```python
# Dependencies: selenium, undetected-chromedriver (or Playwright)

from selenium import webdriver
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc

def search_google_business(query, location):
    """
    Search Google for business listings using web scraping.
    
    Uses: google.com/search?q="{query} {location}"
    Extracts from Google Business listings on SERPs
    """
    url = f"https://www.google.com/search?q={query}+{location}+near+me"
    
    # Use undetected Chrome to bypass anti-bot
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    driver = uc.Chrome(options=options)
    driver.get(url)
    
    # Wait for results to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CLASS_NAME, "F4CXce"))
    )
    
    results = []
    
    # Extract local business pack (top 3)
    local_results = driver.find_elements(By.CLASS_NAME, "VkpGBb")
    for item in local_results:
        try:
            name = item.find_element(By.CLASS_NAME, "qBrxHf").text
            address = item.find_element(By.CLASS_NAME, "LrzXr").text
            rating = item.find_element(By.CLASS_NAME, "lRVSyd").text
            
            # Phone/website might require click
            phone_elem = item.find_element(By.CSS_SELECTOR, "[data-phone]")
            phone = phone_elem.get_attribute("data-phone")
            
            results.append({
                'name': name,
                'address': address,
                'phone': phone,
                'rating': float(rating.split()[0]) if rating else None,
            })
        except:
            continue
    
    driver.quit()
    return results
```

**Pros:**
- Free (no API costs)
- Works with existing Playwright infrastructure
- Captures rich SERP data

**Cons:**
- More fragile (HTML changes break parsing)
- Slower (full browser rendering)
- Higher blocking risk
- No official support

---

#### Option C: Google Business Profile API (Hybrid)
**Best for**: Balance of cost and reliability (Recommended)

```python
# Combination approach: Use free info + limited API calls

def discover_google_businesses_hybrid(query, location):
    """
    1. Scrape Google search results (free)
    2. Use Google Maps API only for detailed info (cheap)
    """
    
    # Phase 1: Scrape SERP for initial results
    serp_results = search_google_business_serp(query, location)  # FREE
    
    # Phase 2: Enrich with API (only if high-quality result)
    results = []
    for item in serp_results:
        # Try to find place_id from search results
        place_id = find_place_id(item['name'], item['address'])  # $0.007
        
        if place_id:
            details = get_place_details(place_id)  # $0.017
            item.update(details)
        
        results.append(item)
    
    return results
```

**Recommended choice**: **Option A (Google Maps API)**
- Most reliable for production
- Built-in pagination
- Cost predictable (~$30-50/month)
- Structured data format

---

### 2.2 Google Crawl Orchestration (scrape_google/google_crawl.py)

**Parallel to yp_crawl.py**

```python
from scrape_google.google_client import search_google_maps, get_place_details
from db.models import canonicalize_url, domain_from_url
from runner.logging_setup import get_logger

logger = get_logger("google_crawl")

# Search parameters
GOOGLE_CATEGORIES = [
    "pressure washing service",
    "power washing",
    "soft washing",
    "window cleaning service",
    "gutter cleaning",
    "roof cleaning",
    "deck cleaning",
    "pressure wash",
    # ... more
]

# Geographic search points (instead of states)
US_METRO_AREAS = [
    # (latitude, longitude, name)
    (40.7128, -74.0060, "New York"),
    (34.0522, -118.2437, "Los Angeles"),
    (41.8781, -87.6298, "Chicago"),
    # ... major cities
]

def crawl_location_category(
    category: str,
    location: tuple,  # (lat, lng)
    location_name: str,
    max_results: int = 100
) -> list[dict]:
    """
    Search Google Maps for category × location.
    
    Returns:
        List of businesses with:
        - name, address, phone, website
        - rating, review_count
        - google_place_id
    """
    logger.info(f"Searching: {category} in {location_name}")
    
    all_results = []
    seen_places = set()
    
    try:
        # Google Maps API returns up to 60 results per query (with pagination)
        results = search_google_maps(
            query=category,
            location=location,
            radius=20000  # 20km radius
        )
        
        for place in results:
            # De-duplicate by place_id
            if place['place_id'] in seen_places:
                continue
            
            seen_places.add(place['place_id'])
            
            # Get full details
            try:
                details = get_place_details(place['place_id'])
                place.update(details)
            except:
                logger.warning(f"Failed to get details for {place['name']}")
            
            # Canonicalize website if present
            if place.get('website'):
                try:
                    place['website'] = canonicalize_url(place['website'])
                    place['domain'] = domain_from_url(place['website'])
                except:
                    place['website'] = None
                    place['domain'] = None
            
            place['source'] = 'Google'
            all_results.append(place)
    
    except Exception as e:
        logger.error(f"Error searching {category} in {location_name}: {e}")
    
    logger.info(f"Found {len(all_results)} results for {category} in {location_name}")
    return all_results

def crawl_all_locations(
    categories: list[str] = None,
    locations: list[tuple] = None,
) -> Generator[dict, None, None]:
    """
    Generator that yields batches of results.
    
    Yields:
        {
            'category': str,
            'location': str,
            'results': list[dict],
            'count': int
        }
    """
    if not categories:
        categories = GOOGLE_CATEGORIES
    if not locations:
        locations = US_METRO_AREAS
    
    for location_tuple in locations:
        lat, lng, location_name = location_tuple
        
        for category in categories:
            try:
                results = crawl_location_category(
                    category=category,
                    location=(lat, lng),
                    location_name=location_name
                )
                
                yield {
                    'category': category,
                    'location': location_name,
                    'results': results,
                    'count': len(results)
                }
                
                # Rate limiting
                import time, random
                delay = random.uniform(2, 4)  # 2-4s between requests
                time.sleep(delay)
            
            except Exception as e:
                logger.error(f"Error for {category} in {location_name}: {e}")
                yield {
                    'category': category,
                    'location': location_name,
                    'results': [],
                    'count': 0,
                    'error': str(e)
                }
```

---

### 2.3 Database Mapping

**Existing Company model already supports Google**:

```python
# In db/models.py Company model
source: str or None        # Will be 'Google' for Google results
rating_google: float       # Google rating
reviews_google: int        # Google review count
website: str              # Website URL (if available)
phone: str                # Phone from Google
```

**Add new optional fields** (if needed):
```python
# Extend Company model:
google_place_id: str      # For Google Maps tracking
hours_of_operation: str   # JSON or formatted string
photos: list              # JSON array of photo references
latitude: float
longitude: float
verified: bool            # Is this a verified Google Business Profile?
```

---

## 3. INTEGRATION WITH EXISTING SYSTEM

### 3.1 Update BackendFacade

```python
# niceui/backend_facade.py

class BackendFacade:
    # ... existing methods ...
    
    def discover_google(
        self,
        categories: List[str],
        locations: List[tuple],  # (lat, lng, name)
        cancel_flag: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None
    ) -> Dict[str, int]:
        """
        Run Google discovery across location × category.
        Similar to discover() but for Google instead of YP.
        """
        from scrape_google.google_crawl import crawl_all_locations
        from db.save_discoveries import upsert_discovered
        
        total_found = 0
        total_new = 0
        total_updated = 0
        total_errors = 0
        pairs_done = 0
        total_pairs = len(categories) * len(locations)
        
        for batch in crawl_all_locations(
            categories=categories,
            locations=locations
        ):
            # Check cancellation
            if cancel_flag and cancel_flag():
                break
            
            pairs_done += 1
            category = batch['category']
            location = batch['location']
            results = batch['results']
            
            # Progress: batch complete
            if progress_callback:
                progress_callback({
                    'type': 'batch_complete',
                    'pairs_done': pairs_done,
                    'pairs_total': total_pairs,
                    'category': category,
                    'location': location,
                    'found': len(results),
                })
            
            # Upsert to database
            try:
                inserted, skipped, updated = upsert_discovered(results)
                total_found += len(results)
                total_new += inserted
                total_updated += updated
            except Exception as e:
                total_errors += 1
                logger.error(f"Save error: {e}")
        
        return {
            'found': total_found,
            'new': total_new,
            'updated': total_updated,
            'errors': total_errors,
            'pairs_done': pairs_done,
            'pairs_total': total_pairs
        }
```

### 3.2 Create Google Discover Page

```python
# niceui/pages/google_discover.py

def google_discover_page():
    """Render Google discovery UI (parallel to discover.py)"""
    ui.label('Google Business Discovery').classes('text-3xl font-bold mb-4')
    
    # Similar structure to discover.py but with:
    # - Location/radius picker instead of states
    # - Google-specific categories
    # - Google API cost calculator
    
    # "Estimated cost: $25 for this search"
```

### 3.3 Logging Integration

```python
# Create logs/google_crawl.log automatically
from runner.logging_setup import get_logger

logger = get_logger("google_crawl")
logger.info("Google discovery started")
```

---

## 4. DATABASE FIELDS MAPPING

### YP Result → Company
```
YP Field        →  Company Field
─────────────────────────────────
name            →  name
phone           →  phone
address         →  address
website         →  website
rating_yp       →  rating_yp
reviews_yp      →  reviews_yp
source='YP'     →  source
```

### Google Result → Company
```
Google Field    →  Company Field
─────────────────────────────────
name            →  name
formatted_phone →  phone
address         →  address
website         →  website
rating          →  rating_google
user_ratings    →  reviews_google
source='Google' →  source
place_id        →  [new field]
lat/lng         →  [new fields]
```

---

## 5. COST COMPARISON

### Google Maps API (Recommended)

```
Pricing (as of 2024):
- Nearby Search: $7/1000 requests (first 25,000/month free)
- Place Details: $17/1000 requests (first 100,000/month free)

Scenario: 50 states × 10 categories
- Searches: 500 requests × $0.007 = $3.50
- Details: 5,000 results × $0.017 = $85

Total: ~$88.50 for full run
Or monthly: ~$200-300 if running 2-3 times/week
```

### Web Scraping (Free)

```
Cost: $0
Tradeoffs:
- More fragile (HTML changes)
- Slower (full browser)
- Higher blocking risk
- No pagination built-in
```

---

## 6. IMPLEMENTATION ROADMAP

### Phase 1: Basic Setup (Week 1)
- [ ] Set up Google Maps API key
- [ ] Create scrape_google/ directory
- [ ] Implement google_client.py with one search function
- [ ] Test with manual searches

### Phase 2: Crawl Integration (Week 2)
- [ ] Create google_crawl.py
- [ ] Implement batch searching
- [ ] Add de-duplication
- [ ] Test database insertion

### Phase 3: GUI Integration (Week 3)
- [ ] Add google_discover page to NiceGUI
- [ ] Update BackendFacade
- [ ] Real-time progress tracking
- [ ] Cost calculator in UI

### Phase 4: Production (Week 4)
- [ ] Error handling & retries
- [ ] Logging setup
- [ ] Cost monitoring
- [ ] Performance optimization

---

## 7. ANTI-BLOCKING FOR GOOGLE

### API-Based (Safest)
- Official Google Maps API → No blocking risk
- Standard rate limits (1000 QPS)
- Use backoff on 429 responses

### Web Scraping (If needed)
- Use Playwright (already in project)
- 5-10 second delays between requests
- Randomize user agents
- Rotate IPs if intensive

---

## 8. MIGRATION STRATEGY

### Option A: Separate sources, same table
```python
# Query all pressure washing companies:
SELECT * FROM companies 
WHERE (source='YP' OR source='Google')
AND name LIKE '%pressure%'
```

### Option B: Merge YP + Google results
```python
# Run both scrapers
# De-duplicate by canonical domain
# Merge ratings: take highest rating
# Merge reviews: combine counts

SELECT DISTINCT ON (domain) * FROM companies
ORDER BY domain, rating_google DESC, rating_yp DESC
```

---

## CONCLUSION

The Google Business scraper can be built as a **parallel module** to the YP scraper, reusing:
- Database schema and ORM
- Batch processing patterns
- GUI framework
- Logging infrastructure
- Deployment setup

Recommended approach:
1. Use Google Maps API for reliability
2. Follow yp_crawl.py pattern
3. Leverage existing BackendFacade
4. Share website enrichment phase
5. Plan for cost (~$200-300/month)

The architecture is designed for modularity, so Google integration should be straightforward.

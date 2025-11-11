# Bing Discovery Provider Integration Plan

**Project**: URL Scrape Bot (washdb-bot)
**Objective**: Add Bing as a discovery source alongside Yellow Pages, HomeAdvisor, and Google Maps
**Approach**: Minimal refactoring, parallel implementation pattern
**Branch**: `feature/bing-discovery`

---

## Executive Summary

This plan integrates Bing discovery capabilities into the existing scraper infrastructure. The implementation mirrors the Yellow Pages pattern (`scrape_yp/`) to maintain consistency and minimize architectural changes.

**Key Design Principles**:
- Mirror `scrape_yp/` structure for consistency
- Reuse existing database models and helpers
- Support both API and HTML scraping modes
- Maintain ethical scraping practices (rate limiting, robots.txt)
- Integrate seamlessly with existing CLI and GUI

---

## Phase 1: Core Bing Integration (Prompts 1-15)

### 1.1 Package Structure

**Create `scrape_bing/` package** mirroring `scrape_yp/`:

```
scrape_bing/
├── __init__.py          # Package exports
├── bing_client.py       # Fetch & parse logic
├── bing_crawl.py        # Multi-page orchestration
└── bing_config.py       # Configuration constants
```

**Key Responsibilities**:
- `bing_client.py`: Query building, HTTP/API fetching, HTML/JSON parsing, rate limiting
- `bing_crawl.py`: Multi-page iteration, de-duplication, batch processing
- `bing_config.py`: Default categories, states, API/HTML mode selection

---

### 1.2 Query Builder & Fetching (Prompts 3-4)

**Query Strategy**:
- Reuse categories from `scrape_yp/yp_crawl.py`: CATEGORIES constant
- Support category × location combinations (e.g., "pressure washing" + "TX")
- Generate query variants using service synonyms:
  - "pressure washing Peoria IL"
  - "power washing Peoria IL"
  - "soft wash Peoria IL"

**Fetch Modes**:

1. **API Mode** (preferred if `BING_API_KEY` set):
   - Use Bing Web Search API v7
   - Rate limit: respects API quotas
   - Returns structured JSON

2. **HTML Mode** (fallback):
   - Direct HTTP requests to Bing SERP
   - Rate limit: configurable delay (default 3-5s)
   - Requires robust HTML parsing

**HTTP Client**:
- Reuse `requests` library (same as YP)
- Apply same retry/backoff pattern from `scrape_yp/yp_client.py`
- Headers: realistic User-Agent, Accept headers
- Respect robots.txt (documented in code comments)

**Configuration**:
```python
# scrape_bing/bing_config.py
BING_BASE_URL = "https://www.bing.com/search"
DEFAULT_RESULTS_PER_PAGE = 10
MAX_PAGES_PER_QUERY = 5
CRAWL_DELAY_SECONDS = 3.0
```

---

### 1.3 Parser (Prompt 5)

**Parse Function Signature**:
```python
def parse_bing_results(payload: str | dict, mode: str = 'html') -> list[dict]:
    """
    Convert Bing SERP payload to normalized discovery dicts.

    Args:
        payload: HTML string or API JSON dict
        mode: 'html' or 'api'

    Returns:
        List of dicts with fields: name, website, domain, source='BING'
    """
```

**Normalization Contract**:
```python
{
    "name": str,           # Business name (from result title)
    "website": str,        # Canonical URL (normalized)
    "domain": str,         # Extracted domain (via db/models.py helper)
    "source": "BING",      # Source tag
    "snippet": str | None  # Optional description text
}
```

**Parsing Rules**:
- **Skip**: Ads, sponsored results, Bing Maps, knowledge panels
- **Extract**: Organic web results only
- **Defensive**: Return empty list on parse errors (never crash)
- **Canonicalize**: Use `canonicalize_url()` from `db/models.py`

---

### 1.4 Crawl Orchestrator (Prompt 6)

**Function Signature**:
```python
def crawl_category_location(
    category: str,
    location: str,
    max_pages: int = 5,
    page_callback: callable = None,
) -> list[dict]:
    """
    Crawl Bing for category × location across multiple pages.

    Returns:
        List of de-duplicated business dicts
    """
```

**De-duplication Strategy**:
1. **Within-batch**: Track seen domains and websites in sets
2. **Canonicalization**: Normalize URLs before comparison
3. **Cross-source**: Database handles conflicts via unique constraint on `website`

**Iteration Logic**:
```
for page in 1..max_pages:
    fetch page HTML/JSON
    parse results
    for each result:
        canonicalize URL → website, domain
        if domain not seen:
            add to batch
            mark as seen

    if no new results:
        break (end of results)
```

**Batch Generator** (mirroring YP):
```python
def crawl_all_states(
    categories: list[str] = None,
    states: list[str] = None,
    limit_per_state: int = 3,
    page_callback: callable = None,
) -> Generator[dict, None, None]:
    """
    Yield batches for each state × category combination.
    """
```

---

### 1.5 Database Integration (Prompt 7)

**Upsert Path**: Extend `db/operations.py` or create `db/save_discoveries.py`

**Upsert Logic**:
```python
def upsert_discovery(session, company_dict: dict):
    """
    Insert or update company record.

    Conflict resolution:
    - Unique constraint on `website` (canonical URL)
    - On conflict: UPDATE existing record
    - Set source='BING' for new rows
    - Preserve source for existing rows (unless empty)
    - Phone/email left NULL (enriched later by site scraper)
    """
```

**SQL Behavior**:
```sql
INSERT INTO companies (name, website, domain, source, ...)
VALUES (...)
ON CONFLICT (website) DO UPDATE SET
    name = COALESCE(EXCLUDED.name, companies.name),
    source = COALESCE(companies.source, EXCLUDED.source),
    last_updated = NOW()
```

**Logging**:
- "Inserted 15 new companies (source=BING)"
- "Updated 3 existing companies"
- "Skipped 2 duplicates (already in batch)"

---

### 1.6 CLI Integration (Prompt 8)

**Add to `runner/main.py`**:

```bash
python -m runner.main discover --source bing --categories "pressure washing" --states TX --pages-per-pair 5
python -m runner.main discover --source yp,bing --categories "pressure washing" --states TX,CA
python -m runner.main discover --source both --categories "pressure washing" --states TX
```

**Argument Spec**:
```python
parser.add_argument(
    '--source',
    choices=['yp', 'bing', 'google', 'ha', 'both', 'all'],
    default='yp',
    help='Discovery source(s) to use'
)
```

**Execution Flow**:
1. Parse `--source` argument
2. If `bing` or `both` or `all` selected:
   - Call `scrape_bing.crawl_all_states()`
   - Pass same categories, states, pages_per_pair
3. Aggregate results across sources
4. Print per-source summary:
   ```
   Yellow Pages: 150 found, 145 new, 5 duplicates
   Bing: 95 found, 87 new, 8 duplicates
   Total: 232 unique companies discovered
   ```

---

### 1.7 GUI Integration (Prompt 9)

**Update `niceui/pages/discover.py`**:

**UI Changes**:
1. **Source Selection**:
   ```python
   sources_select = ui.select(
       options=['Yellow Pages', 'HomeAdvisor', 'Google Maps', 'Bing'],
       multiple=True,
       label='Discovery Sources'
   ).classes('w-full')
   ```

2. **Bing-Specific Settings** (collapsible section):
   ```python
   with ui.expansion('Bing Settings', icon='settings'):
       bing_crawl_delay = ui.number(
           'Crawl Delay (seconds)',
           value=3.0,
           min=1.0,
           max=10.0
       )
       bing_pages_per_pair = ui.number(
           'Pages per Category/Location',
           value=5,
           min=1,
           max=20
       )
       bing_mode = ui.select(
           options=['API (if key set)', 'HTML'],
           value='API (if key set)',
           label='Fetch Mode'
       )
   ```

3. **Job Name Generation**:
   ```python
   job_name = f"Discover (Bing, {bing_pages_per_pair} pages/pair) — {len(categories)} categories × {', '.join(states)}"
   # Example: "Discover (Bing, 5 pages/pair) — 10 categories × TX, CA, FL"
   ```

4. **Config Persistence**:
   ```python
   # Save to config_manager
   config_manager.set('bing.crawl_delay', bing_crawl_delay.value)
   config_manager.set('bing.pages_per_pair', bing_pages_per_pair.value)
   config_manager.set('bing.mode', bing_mode.value)
   ```

**Log Streaming**:
- Reuse existing `job_state.streamer` (CLIStreamer)
- Stream Bing logs to Status page
- Color-code by source: Blue for Bing, Yellow for YP, etc.

---

### 1.8 Configuration & Environment (Prompt 10)

**Add to `.env`**:
```bash
# Bing Discovery Settings
BING_API_KEY=                      # Optional: Bing Web Search API v7 key
BING_CRAWL_DELAY_SECONDS=3.0       # Rate limiting delay
BING_PAGES_PER_PAIR=5              # Default pagination depth
BING_MODE=auto                     # auto|api|html (auto uses API if key set)
```

**Add to `.env.example`**:
```bash
# Bing Discovery (optional)
BING_API_KEY=your-bing-api-key-here
BING_CRAWL_DELAY_SECONDS=3.0
BING_PAGES_PER_PAIR=5
BING_MODE=auto
```

**Config Loading** (`scrape_bing/bing_config.py`):
```python
import os
from dotenv import load_dotenv

load_dotenv()

BING_API_KEY = os.getenv("BING_API_KEY")
CRAWL_DELAY_SECONDS = float(os.getenv("BING_CRAWL_DELAY_SECONDS", "3.0"))
PAGES_PER_PAIR = int(os.getenv("BING_PAGES_PER_PAIR", "5"))
MODE = os.getenv("BING_MODE", "auto")  # auto|api|html

# Determine fetch mode
USE_API = MODE == "api" or (MODE == "auto" and BING_API_KEY)
```

**Fail Gracefully**:
- If API mode selected but no key: log warning, fallback to HTML
- If HTML mode fails: log error, skip source (don't crash entire job)

---

### 1.9 Tests (Prompt 11)

**Test Structure**:
```
tests/
├── fixtures/
│   ├── bing_serp_sample.html          # Saved Bing HTML
│   ├── bing_api_response.json         # Saved API JSON
│   └── bing_serp_no_results.html      # Edge case
├── unit/
│   ├── test_bing_parser_html.py       # Test parse_bing_results(html)
│   ├── test_bing_parser_api.py        # Test parse_bing_results(json)
│   └── test_bing_pagination.py        # Test offset calculation
└── integration/
    ├── test_bing_crawl.py              # Test crawl loop with mocks
    ├── test_bing_db_upsert.py          # Test DB de-dupe & source tagging
    └── test_bing_cli.py                # Smoke test CLI --source bing
```

**Unit Tests**:
```python
def test_parse_bing_html():
    """Test parsing of Bing HTML SERP."""
    with open('tests/fixtures/bing_serp_sample.html') as f:
        html = f.read()

    results = parse_bing_results(html, mode='html')

    assert len(results) >= 8  # Expected organic results
    assert all(r['source'] == 'BING' for r in results)
    assert all('website' in r and 'domain' in r for r in results)
    assert all(r['domain'] != 'bing.com' for r in results)  # No self-refs
```

**Integration Tests**:
```python
@mock.patch('scrape_bing.bing_client.fetch_bing_search_page')
def test_crawl_loop_pagination(mock_fetch):
    """Test crawl loop handles pagination correctly."""
    mock_fetch.side_effect = [
        load_fixture('bing_page1.html'),
        load_fixture('bing_page2.html'),
        load_fixture('bing_no_results.html'),  # End of results
    ]

    results = crawl_category_location('pressure washing', 'TX', max_pages=10)

    assert mock_fetch.call_count == 3  # Stopped at empty page
    assert len(results) >= 15  # Combined unique results
    assert len(set(r['domain'] for r in results)) == len(results)  # All unique
```

**DB Upsert Test**:
```python
def test_upsert_bing_source_tagging(db_session):
    """Test that new Bing discoveries are tagged source='BING'."""
    company = {
        'name': 'Test Pressure Wash',
        'website': 'https://testpw.com',
        'domain': 'testpw.com',
        'source': 'BING'
    }

    upsert_discovery(db_session, company)

    record = db_session.query(Company).filter_by(domain='testpw.com').one()
    assert record.source == 'BING'

    # Update from another source - source should remain BING
    company2 = {**company, 'name': 'Updated Name', 'source': 'YP'}
    upsert_discovery(db_session, company2)

    record = db_session.query(Company).filter_by(domain='testpw.com').one()
    assert record.source == 'BING'  # Source not overwritten
    assert record.name == 'Updated Name'  # Name updated
```

---

### 1.10 Status & History Integration (Prompt 12)

**Add to `niceui/utils/history_manager.py`**:

Track Bing discovery runs:
```python
history_manager.add_run(
    job_type='Discovery - Bing',
    args={
        'categories': categories,
        'states': states,
        'pages_per_pair': pages_per_pair
    },
    duration_sec=elapsed,
    exit_code=0,
    counts={
        'found': result['found'],
        'new': result['new'],
        'duplicates': result['duplicates']
    },
    notes=f"Processed {result['pairs_done']}/{result['pairs_total']} category×state pairs"
)
```

**Update `niceui/pages/status.py`**:

Add Bing to discovery sources visual:
```python
discovery_sources = [
    ('Discovery - Yellow Pages', 'Yellow Pages', 'yellow'),
    ('Discovery - HomeAdvisor', 'HomeAdvisor', 'orange'),
    ('Discovery - Google Maps', 'Google Maps', 'blue'),
    ('Discovery - Bing', 'Bing', 'cyan'),  # New
]
```

**Logging Standards**:
```
INFO - Starting Bing crawl: 10 categories × 3 states × 5 pages = 150 queries
INFO - [1/150] Crawling: pressure washing in TX (page 1/5)
INFO - Parsed 10 results from page 1
INFO - Added 8 new unique results (2 duplicates)
INFO - [1/150] Complete: pressure washing in TX - 42 results (38 unique)
INFO - Bing crawl complete: 150 queries, 1,234 results, 987 unique domains
INFO - Database: 850 inserted, 137 updated, 0 skipped
```

---

### 1.11 Documentation (Prompt 14)

**Update `README.md`**:

```markdown
## Discovery Sources

The bot supports multiple discovery sources:

- **Yellow Pages**: Business directory listings
- **HomeAdvisor**: Home services marketplace
- **Google Maps**: Local business search
- **Bing** (new): Web search for service providers

### Enabling Bing Discovery

1. **API Mode** (recommended):
   ```bash
   # Get API key from https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
   BING_API_KEY=your-key-here
   ```

2. **HTML Mode** (fallback):
   - No API key required
   - Lower rate limits
   - Subject to CAPTCHA/blocking

**Usage**:
```bash
# CLI
python -m runner.main discover --source bing --categories "pressure washing" --states TX

# GUI
Visit http://localhost:8080/discover, select "Bing" from Sources
```

**Configuration**:
```bash
BING_API_KEY=                      # Optional API key
BING_CRAWL_DELAY_SECONDS=3.0       # Rate limit delay
BING_PAGES_PER_PAIR=5              # Pagination depth
BING_MODE=auto                     # auto|api|html
```

**Known Limitations**:
- API mode: 1,000 queries/month on free tier
- HTML mode: Subject to rate limiting and bot detection
- Excludes: Ads, maps, knowledge panels
- Respects: robots.txt, Terms of Service
```

---

## Phase 2: Advanced Features (Prompts A-M)

*These prompts add sophisticated taxonomy, classification, and lead scoring. Defer to Phase 2.*

**Summary of Phase 2 Features**:
- **Service Taxonomy** (Prompt B): Canonical categories with synonyms
- **Negative Keywords** (Prompt C): Filter irrelevant results
- **Geo Targeting** (Prompt D): Peoria 45-mile radius coverage
- **Query Recipes** (Prompt E): Multi-variant query generation
- **Classification Rules** (Prompt F): Multi-label service detection
- **Lead Scoring** (Prompt G): Fit score (0-100) for River City
- **Entity Resolution** (Prompt H): Cross-source merging
- **UI/CLI Enhancements** (Prompt I): Service/geo presets
- **Acceptance Tests** (Prompt J): Fixture-based validation
- **Growth Categories** (Prompt K): Adjacent niche services
- **Ops Guardrails** (Prompt L): Compliance & ethics
- **Runbook Presets** (Prompt M): Pre-configured sweeps

**Deferred Rationale**: Phase 1 establishes core Bing integration. Phase 2 adds intelligence and optimization.

---

## Implementation Checklist

### Pre-Implementation
- [x] Read implementation plan
- [ ] Create feature branch `feature/bing-discovery`
- [ ] Review existing `scrape_yp/` structure

### Phase 1.1: Package Skeleton
- [ ] Create `scrape_bing/` directory
- [ ] Create `__init__.py`, `bing_client.py`, `bing_crawl.py`, `bing_config.py`
- [ ] Add docstrings describing responsibilities
- [ ] Add function signatures with TODOs

### Phase 1.2: Query & Fetch
- [ ] Implement query builder (reuse YP categories)
- [ ] Implement API fetch mode (Bing Web Search API v7)
- [ ] Implement HTML fetch mode (direct HTTP)
- [ ] Add rate limiting and retry logic
- [ ] Test both modes with real queries

### Phase 1.3: Parser
- [ ] Implement HTML parser (BeautifulSoup)
- [ ] Implement API parser (JSON)
- [ ] Add defensive parsing (skip ads, handle structure changes)
- [ ] Normalize results to discovery dict schema
- [ ] Test with fixture files

### Phase 1.4: Crawl Orchestrator
- [ ] Implement `crawl_category_location()`
- [ ] Implement `crawl_all_states()` generator
- [ ] Add within-batch de-duplication
- [ ] Add pagination logic
- [ ] Test with mocked fetches

### Phase 1.5: Database Integration
- [ ] Create/extend `db/save_discoveries.py`
- [ ] Implement upsert logic with source='BING'
- [ ] Test conflict resolution (unique website constraint)
- [ ] Add logging for insert/update/skip counts

### Phase 1.6: CLI Integration
- [ ] Add `--source` argument to `runner/main.py`
- [ ] Wire Bing discovery into CLI flow
- [ ] Test CLI: `--source bing`, `--source both`
- [ ] Verify per-source summary output

### Phase 1.7: GUI Integration
- [ ] Add Bing to sources multi-select (`niceui/pages/discover.py`)
- [ ] Add Bing settings expansion (crawl delay, pages, mode)
- [ ] Persist settings to `config_manager`
- [ ] Generate human-readable job names
- [ ] Test GUI job execution

### Phase 1.8: Config & Environment
- [ ] Add Bing settings to `.env` and `.env.example`
- [ ] Implement config loading in `bing_config.py`
- [ ] Add graceful fallback (API → HTML, missing key)
- [ ] Document environment variables

### Phase 1.9: Tests
- [ ] Create `tests/fixtures/` with Bing HTML/JSON samples
- [ ] Write unit tests for parser (HTML & API modes)
- [ ] Write unit tests for pagination logic
- [ ] Write integration tests for crawl loop (mocked)
- [ ] Write DB upsert test (source tagging, de-dupe)
- [ ] Write CLI smoke test (`--source bing`)

### Phase 1.10: Status & History
- [ ] Add Bing to `history_manager` job types
- [ ] Add Bing to status page discovery sources
- [ ] Test history tracking (success, error, cancelled)
- [ ] Verify visual display on History page

### Phase 1.11: Documentation
- [ ] Update README with Bing section
- [ ] Document API key acquisition
- [ ] Document configuration options
- [ ] Document known limitations
- [ ] Add usage examples (CLI & GUI)

### Phase 1.12: Code Review & Cleanup
- [ ] Run linter/formatter
- [ ] Remove debug prints
- [ ] Add meaningful log messages
- [ ] Review error handling
- [ ] Check for TODOs

### Phase 1.13: Integration Testing
- [ ] Run full discovery job (YP + Bing)
- [ ] Verify database records (source='BING')
- [ ] Check history persistence
- [ ] Test GUI controls and log streaming
- [ ] Verify de-duplication across sources

### Phase 1.14: Merge & Deploy
- [ ] Open PR with summary and screenshots
- [ ] Address review feedback
- [ ] Merge to main
- [ ] Deploy to production
- [ ] Monitor first production runs

---

## Success Criteria

✅ **Functional**:
- Bing discovery runs successfully via CLI and GUI
- Results are de-duplicated and tagged with source='BING'
- API and HTML modes both work
- Pagination handles end-of-results gracefully
- Database upsert respects unique constraints

✅ **Quality**:
- Code mirrors `scrape_yp/` patterns
- Tests cover parser, crawl loop, DB upsert
- Logs are clear and actionable
- No crashes on parse errors or network failures

✅ **User Experience**:
- GUI shows Bing as a source option
- Job names are human-readable
- History page shows Bing runs with stats
- Configuration persists across sessions

✅ **Ethics & Compliance**:
- Rate limiting prevents abuse
- robots.txt is respected
- Ads and sponsored results are skipped
- API key is optional (HTML fallback works)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Bing blocks HTML scraping | Use API mode, graceful fallback, exponential backoff |
| API quota exceeded | Log warning, switch to HTML, limit pages_per_pair |
| Parse failures (HTML structure changes) | Defensive parsing, return empty list, log error |
| Duplicate results across sources | Database unique constraint + domain de-dupe |
| Poor query relevance | Phase 2: Add negative keywords, synonyms, classification |

---

## Timeline Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| 1.1 | Package skeleton | 1 hour |
| 1.2 | Query & fetch | 4 hours |
| 1.3 | Parser | 3 hours |
| 1.4 | Crawl orchestrator | 3 hours |
| 1.5 | Database integration | 2 hours |
| 1.6 | CLI integration | 2 hours |
| 1.7 | GUI integration | 4 hours |
| 1.8 | Config & environment | 1 hour |
| 1.9 | Tests | 6 hours |
| 1.10 | Status & history | 2 hours |
| 1.11 | Documentation | 2 hours |
| 1.12-1.14 | Review, testing, deploy | 4 hours |
| **Total** | | **34 hours** (~5 days) |

---

## Next Steps

1. Review this plan with team/stakeholder
2. Create feature branch
3. Begin Phase 1.1 (package skeleton)
4. Implement step-by-step following checklist
5. Open PR when Phase 1 complete

---

**Questions? Contact**: [Your contact info]
**Document Version**: 1.0
**Last Updated**: 2025-11-11

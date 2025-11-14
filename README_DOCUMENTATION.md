# washdb-bot Scraper Analysis - Documentation Index

This directory contains comprehensive analysis of the washdb-bot scraper architecture and design guidance for implementing a Google Business scraper.

## Documentation Files

### 1. EXPLORATION_SUMMARY.txt (Quick Reference)
**Size**: 20 KB | **Length**: 500+ lines

The executive summary with all key findings organized into 12 sections:
- Overall architecture (two-phase design)
- File structure (15 core directories)
- Discovery workflow (Yellow Pages)
- Enrichment workflow (website scraping)
- Database schema (PostgreSQL)
- GUI integration (NiceGUI)
- Logging implementation
- Anti-blocking strategies
- Key execution flows
- Design insights for Google scraper
- Cost & performance estimates
- Summary of key findings

**Best for**: Quick reference, understanding the big picture, architecture overview

---

### 2. WASHDB_BOT_SCRAPER_ARCHITECTURE.md (Detailed Reference)
**Size**: 26 KB | **Length**: 780 lines

In-depth architectural documentation covering:
- Project overview and tech stack
- Complete file structure with directory tree
- Yellow Pages discovery workflow (Phase 1)
  - fetch_yp_search_page() function details
  - parse_yp_results() function details
  - crawl_category_location() logic
  - crawl_all_states() generator pattern
- Website enrichment workflow (Phase 2)
  - scrape_website() multi-page logic
  - parse_site_content() implementation
  - discover_internal_links() keyword matching
  - merge_results() conflict resolution
- Database schema (Company model)
  - All 20+ columns with descriptions
  - Unique constraints and indexes
  - Helper functions (canonicalize_url, domain_from_url)
- GUI integration points
  - NiceGUI pages (discover, scrape, single_url, dashboard, etc.)
  - BackendFacade API methods
  - Progress callback system
  - Real-time communication patterns
- Logging implementation
  - Setup configuration
  - Usage patterns
  - Log files and rotation
- Anti-blocking strategies (both implemented and documented)
- Complete data flow diagrams (ASCII art)
- Key execution flows (CLI, GUI, enrichment)
- Integration considerations for Google scraper

**Best for**: Deep understanding, implementation reference, architecture decisions

---

### 3. GOOGLE_SCRAPER_DESIGN_GUIDE.md (Implementation Blueprint)
**Size**: 19 KB | **Length**: 668 lines

Practical guide for implementing Google Business scraper:
- High-level architecture (parallel structure to YP scraper)
- Three implementation approaches with pros/cons:
  - Option A: Google Maps API (recommended)
  - Option B: Google Search web scraping
  - Option C: Hybrid approach
- Complete code examples for google_client.py
  - search_google_maps() function
  - get_place_details() function
- Google crawl orchestration (google_crawl.py)
  - crawl_location_category() logic
  - crawl_all_locations() generator pattern
- Database field mappings
  - YP → Company schema
  - Google → Company schema
- Integration with existing system
  - BackendFacade updates
  - New GUI page (google_discover.py)
  - Logging integration
- Cost comparison
  - Google Maps API pricing: $7/1000 searches, $17/1000 details
  - Web scraping: free but fragile
  - Estimated monthly cost: $200-300
- 4-phase implementation roadmap
  - Phase 1: Basic setup (Week 1)
  - Phase 2: Crawl integration (Week 2)
  - Phase 3: GUI integration (Week 3)
  - Phase 4: Production (Week 4)
- Anti-blocking strategies for Google
- Migration strategies (merge sources vs separate)
- Key recommendations and conclusions

**Best for**: Implementing Google scraper, cost estimation, roadmap planning

---

## Quick Start Guide

### Understanding the Current System
1. **Start here**: Read EXPLORATION_SUMMARY.txt (5-10 min)
2. **Dive deeper**: Review WASHDB_BOT_SCRAPER_ARCHITECTURE.md sections 1-6
3. **Understand flows**: Read section 8 (Key Execution Flows) for practical examples

### Planning Google Integration
1. **Read**: GOOGLE_SCRAPER_DESIGN_GUIDE.md sections 1-2 (architecture + approaches)
2. **Compare**: Section 5 (cost analysis) to decide on implementation method
3. **Plan**: Section 6 (implementation roadmap) for timeline
4. **Design**: Reference sections 3-4 for code structure

### Deep Implementation Reference
- **Discovery logic**: WASHDB_BOT_SCRAPER_ARCHITECTURE.md section 2.1
- **Enrichment logic**: WASHDB_BOT_SCRAPER_ARCHITECTURE.md section 2.2
- **Database design**: WASHDB_BOT_SCRAPER_ARCHITECTURE.md section 3
- **GUI patterns**: WASHDB_BOT_SCRAPER_ARCHITECTURE.md section 4
- **Google implementation**: GOOGLE_SCRAPER_DESIGN_GUIDE.md section 2

---

## Key Findings Summary

### Current Architecture Strengths
- Modular two-phase design (discovery + enrichment)
- Sophisticated anti-bot measures (fingerprinting, human behavior simulation)
- Real-time GUI with progress tracking
- Generic database schema supports multiple sources
- Clean separation of concerns
- Comprehensive logging and monitoring

### Google Integration Opportunity
- Can add as parallel module (scrape_google/)
- Reuse 90% of infrastructure
- Main new work: Google-specific client code
- Database schema already supports multiple sources
- Estimated effort: 2-4 weeks for full implementation

### Recommended Approach
1. Use Google Maps API (most reliable, ~$30-50/month)
2. Create scrape_google/ directory parallel to scrape_yp/
3. Follow yp_crawl.py pattern for orchestration
4. Leverage existing BackendFacade and database
5. Add google_discover page to GUI
6. Reuse website enrichment phase (site_scraper.py)

---

## File Locations in Codebase

### Core Scraper Modules
- `/washdb-bot/scrape_yp/` - Yellow Pages discovery
- `/washdb-bot/scrape_site/` - Website enrichment
- `/washdb-bot/scrape_google/` - (Proposed) Google Business discovery

### Database Layer
- `/washdb-bot/db/models.py` - SQLAlchemy Company model
- `/washdb-bot/db/save_discoveries.py` - Upsert logic
- `/washdb-bot/db/update_details.py` - Batch enrichment

### GUI & Backend
- `/washdb-bot/niceui/backend_facade.py` - API bridge
- `/washdb-bot/niceui/pages/discover.py` - Discovery UI
- `/washdb-bot/niceui/pages/` - All GUI pages

### Orchestration
- `/washdb-bot/runner/main.py` - CLI entry point
- `/washdb-bot/runner/logging_setup.py` - Logging config

---

## Architecture Diagrams

### Two-Phase Flow
```
User Input (categories, locations)
    ↓
Phase 1: Discovery
    ├─ Fetch search results (10s delay + jitter)
    ├─ Parse listings (name, phone, address, website, rating)
    ├─ De-duplicate by domain
    └─ Database upsert
    ↓
Phase 2: Enrichment
    ├─ Fetch company website
    ├─ Parse content (JSON-LD, regex, keywords)
    ├─ Discover internal pages (contact, about, services)
    ├─ Fetch up to 3 additional pages
    ├─ Merge results
    └─ Database update
    ↓
Output: Database records with complete information
```

### Data Flow
```
NiceGUI Frontend (async)
    ↓
BackendFacade (sync wrapper)
    ↓
Scraper modules (yp_client, site_scraper, etc.)
    ↓
Progress callbacks
    ↓
Frontend real-time updates
```

---

## Terminology

- **Discovery**: Finding new businesses from search/API (Yellow Pages, Google)
- **Enrichment**: Visiting business websites to extract detailed information
- **Canonicalize**: Normalize URL to standard form (add https, remove www, etc.)
- **De-duplicate**: Remove duplicate entries by comparing domains/URLs
- **Upsert**: Insert new record or update existing one (SQL UPSERT operation)
- **Stale**: Company data that hasn't been updated in N days
- **Jitter**: Random variation added to delay to avoid detection

---

## Next Steps

1. **Review Documentation**: Read all three files in order (summary → architecture → design guide)
2. **Understand Current System**: Study the yp_client.py and yp_crawl.py implementations
3. **Plan Google Integration**: Use GOOGLE_SCRAPER_DESIGN_GUIDE.md to create implementation plan
4. **Set Up Google API**: Get API credentials and add to .env
5. **Implement google_client.py**: Start with basic search functionality
6. **Build Crawl Logic**: Implement google_crawl.py following yp_crawl.py pattern
7. **Integrate GUI**: Add google_discover page using discover.py as template
8. **Test & Deploy**: Use existing testing/deployment infrastructure

---

## Document Statistics

| File | Size | Lines | Focus |
|------|------|-------|-------|
| EXPLORATION_SUMMARY.txt | 20 KB | 500+ | Quick reference |
| WASHDB_BOT_SCRAPER_ARCHITECTURE.md | 26 KB | 780 | Detailed architecture |
| GOOGLE_SCRAPER_DESIGN_GUIDE.md | 19 KB | 668 | Implementation blueprint |
| **Total** | **65 KB** | **1,948** | **Comprehensive analysis** |

---

## Questions This Documentation Answers

### Architecture Questions
- What is the overall system architecture?
- How does the discovery phase work?
- How does the enrichment phase work?
- What is the database schema?
- How does the GUI integrate with scrapers?

### Implementation Questions
- What files do what?
- What are the key functions and their signatures?
- How do I add a new scraper source?
- How do I integrate with the GUI?
- What anti-blocking techniques are used?

### Google Scraper Questions
- Should I use Google Maps API or web scraping?
- What will it cost?
- How do I structure the code?
- How do I integrate with existing system?
- What's the implementation timeline?

---

Created: 2025-11-10
Analysis Level: Very Thorough
Coverage: All major components and workflows


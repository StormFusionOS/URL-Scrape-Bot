# WashDB-Bot - Claude Code Memory

This is a web scraping and SEO intelligence system for discovering and verifying local service businesses.

## Quick Reference

### Truth Documentation
Comprehensive documentation is in `.claude/claude_truth_docs_washdb_bot/`:
- `TRUTH_00_README.md` - Overview and index
- `TRUTH_01_REPO_MAP.md` - Directory structure and entry points
- `TRUTH_02_SETUP_AND_RUN.md` - Local dev setup
- `TRUTH_03_CONFIGURATION_ENV_VARS.md` - All environment variables
- `TRUTH_04_DATABASE_SCHEMA.md` - DB tables and migrations
- `TRUTH_05_DISCOVERY_SCRAPERS.md` - YP, Google Maps, Yelp scrapers
- `TRUTH_06_VERIFICATION_PIPELINE.md` - Website verification workflow
- `TRUTH_07_NAME_STANDARDIZATION.md` - Name standardization for SEO
- `TRUTH_08_SEO_INTELLIGENCE.md` - SERP, backlinks, citations, audits
- `TRUTH_09_UI_AND_SERVICES.md` - NiceGUI and systemd services
- `TRUTH_10_KNOWN_ISSUES_GAPS.md` - Known bugs and drift
- `TRUTH_11_ZIP_ROOT_DOCS.md` - Additional design docs

## Primary Subsystems

### Discovery Scrapers
- **Yellow Pages**: `scrape_yp/` - City-first crawling
- **Google Maps**: `scrape_google/` - City-first crawling
- **Yelp**: `scrape_yelp/` - WIP/fragile

### Website Verification
- `scrape_site/` - Site fetch, parse, verify
- `verification/` - Worker pool orchestration

### SEO Intelligence
- `seo_intelligence/` - SERP, competitors, backlinks, citations, audits, embeddings

### UI
- `niceui/` - NiceGUI web interface

### Database
- `db/models.py` - SQLAlchemy models
- `db/migrations/` - SQL migrations

## Key Entry Points

```bash
# UI
python -m niceui.main

# DB setup
python -m db.init_db
python db/populate_city_registry.py

# Generate targets
python -m scrape_yp.generate_city_targets --states RI,MA --clear
python -m scrape_google.generate_city_targets --states RI,MA --clear

# Run scrapers
python cli_crawl_yp.py --states RI
python cli_crawl_google_city_first.py --states RI --max-targets 10 --save

# Worker pools
python -m scrape_yp.state_worker_pool
python -m scrape_google.state_worker_pool
```

## Critical Requirements

1. `DATABASE_URL` must be set (PostgreSQL)
2. `data/verification_services.json` must exist for verification
3. Ollama with `unified-washdb` model for LLM verification AND name standardization
4. Playwright installed for browser automation

## Unified LLM

The system uses a single fine-tuned Mistral model (`unified-washdb`) for:
- Business verification (is this a legitimate exterior cleaning provider?)
- Name standardization (extract proper business name from website)

Key module: `verification/unified_llm.py`

```python
from verification.unified_llm import get_unified_llm

llm = get_unified_llm()

# Verify a company
result = llm.verify_company(company_name="Pro Power Wash", website="https://...")

# Standardize a name
result = llm.standardize_name(current_name="Pro", page_title="Pro Power Wash LLC")
```

## Source of Truth

When information conflicts:
1. Running code wins (Python modules)
2. Next: repo docs under `docs/`
3. Lowest: `archive/` content

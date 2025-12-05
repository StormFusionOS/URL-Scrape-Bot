# 01 – URL Verification System Overview (Continuous Scrapers Edition)

**Audience:** Claude (or another AI dev) working inside the `washdb-bot` repo.  
**Goal:** Explain how the new continuous Yellow Pages + Google scrapers fit with the verification pipeline, and where to implement improvements.

Repo highlights relevant to verification:

- **Continuous discovery**
  - `scrape_yp/` + `cli_crawl_yp.py` + `washbot-yp-scraper.service`
  - `scrape_google/` + `cli_crawl_google_city_first.py` + `washbot-google-scraper.service`
  - These run 24/7 and upsert companies into the `companies` table via `db/save_discoveries.py` and SQLAlchemy models in `db/models.py`.
- **Verification pipeline (current)**
  - Manual / batch: `db/verify_company_urls.py`
  - Continuous worker(s): `verification/verification_worker.py` + `verification/verification_worker_pool.py`
  - LLM stack: `scrape_site/llm_verifier.py` + `scrape_site/service_verifier.py`
  - Shared GPU queue: `verification/llm_service.py` + `verification/llm_queue.py`
  - Website scraping & parsing: `scrape_site/site_scraper.py` + `scrape_site/site_parse.py`

The **plan from the previous docs is still correct** in spirit:

- Crawl website → extract rich signals → heuristics → LLM JSON classification → final triage (`accept / reject / needs_review`) → human review loop → training + evaluation.

But now we need to **anchor it to this repo’s actual code** and the fact that YP + Google run continuously.

---

## 1. High-Level Data Flow (as it exists now)

1. **Continuous discovery (YP + Google)**
   - YP and Google crawlers run as systemd services:
     - `washbot-yp-scraper.service`
     - `washbot-google-scraper.service`
   - They write discovered businesses into `companies` via `db/models.Company` and helpers in `db/save_discoveries.py`.
   - Discovery metadata lives in `Company.parse_metadata` JSONB:
     - `parse_metadata['yp_filter']`
     - `parse_metadata['google_filter']`
     - etc.

2. **Verification workers (continuous)**
   - `verification/verification_worker.py`:
     - `acquire_company_for_verification(...)` selects rows from `companies` where:
       - `website IS NOT NULL`
       - `parse_metadata['verification']` is missing or incomplete.
     - Marks them as `status = 'in_progress'` in `parse_metadata['verification']`.
     - Fetches homepage HTML via `scrape_site.site_scraper.fetch_page`.
     - Parses HTML via `scrape_site.site_parse.parse_site_content`.
     - Runs service verification via `scrape_site.service_verifier.create_verifier().verify_company(...)`.
     - Combines discovery + website + reviews via `db.verify_company_urls.calculate_combined_score`.
     - Calls `verification.update_company_verification(...)` to write back:
       - `parse_metadata['verification'] = { ... }`
       - `companies.active` flag.

   - `verification/verification_worker_pool.py` manages multiple workers and uses `llm_queue` to keep the GPU busy.

3. **Batch / manual verification**
   - `db/verify_company_urls.py` provides a CLI job that does a similar flow as the worker, but in batch.
   - This is now effectively **part of the test suite / manual tools**, not 24/7.

---

## 2. What needs to change (conceptually)

The main architectural improvements we still want (adapted to this repo):

1. **Richer website context for the LLM**
   - Use more than just naïve truncation of the services/about/homepage text in `scrape_site/llm_verifier.py::_build_context`.
   - Optionally use `scrape_site/site_scraper.scrape_website` to pull Contact/About/Services pages when the homepage is too thin.

2. **Explicit heuristics + triage logic**
   - Today, `scrape_site/service_verifier.py` already has:
     - Rule-based scoring
     - LLM integration
     - Red flags for agencies / blogs / directories / franchise-type sites
     - A `status` field and `score` field.
   - But the DB update functions (`db/verify_company_urls.update_company_verification` and `verification.verification_worker.update_company_verification`) **throw away** this status and rely only on `is_legitimate`.
   - We want:
     - A true three-way outcome:
       - `accepted_provider` → `active = true`
       - `rejected_non_provider` → `active = false`
       - `needs_review` → `active = false`, `parse_metadata['verification']['needs_review'] = true`
     - Thresholds that use:
       - `verification_result['score']`
       - `calculate_combined_score(...)`
       - LLM legitimacy + red flags.

3. **“Needs review” + training loop**
   - Log every decision (especially `needs_review`) into `parse_metadata['verification']`.
   - Expose them in your GUI / CLI review tools (this repo already has NiceGUI and diagnostics wiring).
   - Add scripts to export labeled data for training a small classifier or for prompt refinement.

4. **Evaluation + monitoring**
   - Leverage the existing logging and test infrastructure (`tests/`, `test_hybrid_verification.py`, etc.) to build an evaluation harness that runs the full pipeline against labeled companies.

---

## 3. How the updated docs map to this repo

The rest of the Markdown files in this zip are updated specifically for this codebase:

1. **02-crawling-and-content-extraction-improvements.md**
   - Talks about tightening `fetch_page`, `parse_site_content`, and optionally using `scrape_site.site_scraper.scrape_website` when the homepage is too thin.
   - Explains how to reuse the existing multi-page discovery (contact/about/services) only where it adds value.

2. **03-heuristics-and-rule-based-filtering.md**
   - Maps heuristic ideas to the actual `scrape_site/service_verifier.py` module:
     - Where to add / adjust positive/negative signals.
     - How to ensure blogs, agencies, directories, and franchise sites are penalized consistently.

3. **04-llm-verification-and-scoring-pipeline.md**
   - Grounded in `scrape_site/llm_verifier.py`, `verification/llm_service.py`, and `verification/llm_queue.py`.
   - Shows how to:
     - Improve `_build_context`.
     - Keep using the queue-based LLM service.
     - Combine LLM outputs with heuristics + discovery to get a final triage decision.

4. **05-human-review-loop-and-training-data.md**
   - Uses `parse_metadata['verification']` as the canonical store of decisions + notes.
   - Shows how to extend that JSON and add scripts for:
     - Review queues.
     - Exporting labeled datasets.

5. **06-evaluation-monitoring-and-configuration.md**
   - Focuses on:
     - Configuration via `.env` and constants used in the workers.
     - Evaluation scripts you can add under `scripts/` or `tests/`.
     - Logging and monitoring patterns that fit your systemd services and logrotate config.

You can drop this zip into Claude, say:

> “You’re working in `washdb-bot`. Use these docs to implement the verification upgrades,”

and it will have repo-specific guidance instead of generic pseudo-architecture.

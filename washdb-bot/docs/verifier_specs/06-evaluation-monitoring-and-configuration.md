# 06 – Evaluation, Monitoring & Configuration (continuous mode aware)

**Goal for Claude**  
Add evaluation tools, monitoring, and configuration that fit this repo’s continuous scraper + worker setup:

- YP + Google systemd services
- Verification workers + shared LLM service
- logrotate and diagnostics already in place

---

## 1. Configuration: centralize verifier settings

Create a small config module, e.g. `verification/config_verifier.py`, with constants like:

```python
# Scoring thresholds
HEUR_PROVIDER_THRESHOLD = 0.75
HEUR_NON_PROVIDER_THRESHOLD = 0.25
COMBINED_HIGH_THRESHOLD = 0.75   # auto-accept
COMBINED_LOW_THRESHOLD  = 0.35   # auto-reject

# Thin-site + deep-scrape
THIN_TEXT_THRESHOLD = 500        # chars
MAX_DEEP_SCRAPES_PER_HOUR = 50

# JS rendering budgets
ENABLE_JS_RENDERING = True
MAX_RENDERED_PAGES_PER_RUN = 50
MAX_RENDERED_PAGES_PER_DOMAIN = 2

# LLM / worker rate limits
MAX_LLM_VERIFICATIONS_PER_HOUR = 300
```

Then:

- Import these constants in:
  - `verification/verification_worker.py`
  - `db/verify_company_urls.py`
  - `scrape_site/llm_verifier.py` (for truncation lengths)
  - `scrape_site/service_verifier.py` (for status/score thresholds, if needed)

Replace hard-coded numbers in those files with references to this config.

---

## 2. Offline evaluation harness

Add `scripts/evaluate_verifier.py`:

1. Accept input (e.g. JSONL or a DB query) of companies with human labels:

   - Either the JSONL from `export_verification_training_data.py`.
   - Or directly from the DB where `parse_metadata['verification']['human_label']` is set.

2. For each example:

   - Run the full pipeline as the worker would:
     - Fetch/parse website (fast + optional deep path).
     - `service_verifier.verify_company`.
     - `calculate_combined_score`.
     - Triage with the updated `update_company_verification` logic (in memory).
   - Record:
     - `pred_final_label` (what the pipeline would set: passed/failed/needs_review).
     - `human_label`.

3. Compute metrics:

   - For “provider vs non_provider”:
     - Precision, recall, F1.
   - For more detailed labels:
     - Confusion matrix between human labels vs pipeline decisions (or vs LLM `overall_label` if you expose it).
   - % of items landing in `needs_review`.

4. Print a summary and optionally write JSON/Markdown reports under `logs/eval/`.

This script lets you test threshold changes or heuristic tweaks *before* rolling them out.

---

## 3. Production monitoring

You already have:

- `washdb-bot.service` and logrotate configuration `washdb-bot-logrotate`.
- NiceGUI dashboard and diagnostics.

Extend monitoring with:

1. **Daily or hourly metrics script**, e.g. `scripts/report_verification_stats.py`:

   Query DB for a time window (last 24h):

   - Count:
     - Total companies processed by workers.
     - How many ended as:
       - `status='passed'`
       - `status='failed'`
       - `status='unknown'` (needs_review)
   - Average `combined_score` per bucket.
   - Number of JS-rendered sites.
   - Number of deep-scraped sites.

   Print a human-readable summary and optionally log a JSON blob.

2. **Alerts for anomalies** (can be simple for now):

   - If `% needs_review` spikes above, say, 50% over a day.
   - If `status='passed'` drops to near zero for an extended period.
   - If the number of companies with `parse_metadata['verification']` missing grows unexpectedly (indicates worker failure).

You can emit these as log lines that are picked up by systemd, or integrate into your diagnostics page.

---

## 4. Handling failures gracefully

### 4.1 LLM failures

In `verification_worker` and `db/verify_company_urls`:

- If LLM calls fail or `llm_verifier` returns `None`:
  - Still run rule-based verification.
  - Set:
    - `verification_result['is_legitimate'] = False`
    - `verification_result['red_flags'].append('LLM verification failed')`
  - Force `needs_review = True` at triage time.
- Log the error clearly with worker ID and company ID.

### 4.2 JS rendering failures

When JS rendering is enabled:

- If Playwright fails or times out:
  - Log a warning.
  - Proceed with static HTML metadata.
  - Don’t keep retrying rendering for the same domain repeatedly (use a simple “render_attempted” flag in `parse_metadata['verification']`).

### 4.3 Worker resilience

`verification_worker` already uses row locking and prefetch buffering. Ensure:

- `shutdown_requested` flags are handled cleanly.
- Any exception in `_prefetch_loop` or `start()` is logged with enough context to debug.
- On startup, workers can safely pick up any companies stuck with `status='in_progress'` for too long (e.g., older than X minutes).

You can add a small cleanup script to reset stale `in_progress` statuses to “unverified” for reprocessing.

---

## 5. Documentation & runbooks

Add or update a short operator-focused doc, e.g. `docs/VERIFICATION_RUNBOOK.md`, to cover:

- **How to start/stop services**:
  - `washbot-yp-scraper.service`
  - `washbot-google-scraper.service`
  - `washdb-bot.service` (which runs verification workers and possibly the LLM service).
- **How to tail logs for verification**:
  - Paths under `logs/verification*`.
  - Using the NiceGUI log viewer.
- **How to review `needs_review` companies**:
  - Run the CLI review script.
  - Or navigate to a future NiceGUI “Verification Review” page, if implemented.
- **How to run evaluations**:
  - Commands for `evaluate_verifier.py` and stats scripts.

This ensures future maintainers (or another AI) can safely adjust thresholds and behavior without re-analyzing the entire codebase.

---

## 6. Checklist

- [ ] Create `verification/config_verifier.py` and replace hard-coded thresholds with imports.
- [ ] Implement `scripts/evaluate_verifier.py` for offline evaluation with labeled data.
- [ ] Implement `scripts/report_verification_stats.py` for daily/weekly metrics.
- [ ] Add error-handling paths for LLM and JS rendering failures that mark items as `needs_review`.
- [ ] Add/update a `docs/VERIFICATION_RUNBOOK.md` explaining how to operate and tune the system in production.

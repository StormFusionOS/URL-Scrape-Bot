# 02 – Crawling & Content Extraction Improvements (anchored to washdb-bot)

**Goal for Claude**  
Upgrade the website context that feeds verification, using the code that already exists in this repo:

- `scrape_site/site_scraper.py`
- `scrape_site/site_parse.py`
- `verification/verification_worker.py`
- `db/verify_company_urls.py`

We’re not reinventing the scraper; we’re tightening how it’s used in the verification pipeline.

---

## 1. Current behavior

In the **continuous verification worker** (`verification/verification_worker.py`):

- `acquire_company_for_verification` selects a company from `companies`.
- `_prefetch_loop` calls:
  - `scrape_site.site_scraper.fetch_page(website)` → HTML
  - `scrape_site.site_parse.parse_site_content(html, website)` → `metadata` dict with:
    - `name`, `phones`, `emails`, `services`, `service_area`, `address`, `json_ld`, `homepage_text`, etc.
- `verify_prefetched_company` passes this to:
  - `scrape_site.service_verifier.create_verifier().verify_company(...)`

The **batch script** (`db/verify_company_urls.py`) mirrors this logic for manual runs.

Right now, the verification worker only fetches **one page (homepage)** per domain in its fast path.

---

## 2. When and how to fetch more than the homepage

We already have a multi-page website scraper in `scrape_site/site_scraper.py`:

- `scrape_website(url)`:
  - Fetches homepage.
  - Discovers internal `Contact`, `About`, and `Services` pages via `discover_internal_links(...)`.
  - Fetches up to 3 additional pages.
  - Merges metadata via `merge_results(...)`.

We want to use this **selectively**, so the GPU isn’t waiting on network I/O for every company.

### 2.1 Fast path (current behavior)

Keep the existing fast path for the majority of companies:

- Use `fetch_page` + `parse_site_content` on the homepage only.
- This is what `_prefetch_loop` currently does.

### 2.2 Deep path (for thin or ambiguous sites)

Add a conditional “deep scrape” that uses `scrape_website` **only when it’s worth it**:

In `verification/verification_worker.py` inside `_prefetch_loop`:

1. After the first `parse_site_content` call, inspect `metadata`:

   - If:
     - `len(metadata.get("services") or "") < SMALL_THRESHOLD`
       **and**
     - `len(metadata.get("homepage_text") or "") < SMALL_THRESHOLD`
   - Then treat this as a **thin site**.

2. For thin sites *and* only when we haven’t exceeded an hourly budget, call:

   ```python
   from scrape_site.site_scraper import scrape_website

   try:
       scraper_result = scrape_website(website)
       # scraper_result already includes merged metadata
       metadata = scraper_result  # or merge carefully with existing metadata
   except Exception as e:
       logger.warning(f"Deep scrape failed for {website}: {e}")
       # Fall back to the original metadata
   ```

3. SMALL_THRESHOLD can be 500–800 characters of text; add it to a config (see doc 06).

4. Limit how many “deep scrapes” you do per hour or per worker to preserve throughput:
   - e.g., `MAX_DEEP_SCRAPES_PER_HOUR = 50`.

This gives the LLM better context for **small/minimal sites**, which were a major false-negative source.

---

## 3. JS-rendered content (headless fallback)

The repo already uses Playwright heavily for YP and Google — the site scraper is currently using plain `requests`/`httpx` for websites.

We want a **light** JS fallback for sites where static HTML is basically empty:

1. Add a headless render helper (you can reuse the patterns from `scrape_yp` / `scrape_google` stealth modules):

   ```python
   # e.g., scrape_site/js_render.py
   async def render_page(url: str, timeout_ms: int = 20000) -> str:
       # Playwright browser launch (headless)
       # Block images/fonts/video for speed
       # Wait for network idle or timeout
       # Return page.content()
   ```

2. Detection conditions (in verification worker):

   - After `fetch_page` + `parse_site_content`:
     - If:
       - `len(metadata.get("homepage_text") or "") < 300`
       - and there are many `<script>` tags (you can count in the raw HTML)
       - and no phone/email/address was detected
     - Then, **once per domain**, try the JS-render path:
       - Store a small in-memory or DB-level flag `js_rendered` in `parse_metadata['verification']` or in a local cache so we don’t re-render repeatedly.

3. Re-run `parse_site_content` on the rendered HTML.

4. Guardrails:
   - `MAX_RENDERED_PAGES_PER_RUN` and `MAX_RENDERED_PAGES_PER_DOMAIN` in config.
   - If rendering fails or times out, log and continue with static HTML.

This tackles false negatives where the contact info and services are all injected via JavaScript.

---

## 4. Metadata fields that matter most

`parse_site_content` already provides a rich metadata dict. For verification, ensure the following keys are reliably populated and passed into `service_verifier.verify_company`:

- `name`
- `services`
- `service_area`
- `address`
- `phones`
- `emails`
- `homepage_text`
- `json_ld` (for schema.org)
- `reviews` (if available)

If needed, adjust `site_parse.py` to:

- Recognize additional synonyms and niche terminology for:
  - Pressure washing, soft washing, exterior cleaning, etc.
  - Window cleaning, glass cleaning.
  - Wood restoration, deck/fence/log home refinishing.
- Normalize phone numbers and addresses consistently so the verifier’s local-business checks are robust.

---

## 5. Domain-level aggregation

While we don’t need a formal `DomainSnapshot` class, we effectively create one via `website_metadata`:

- After the fast and optional deep paths, ensure `website_metadata` has:

  - Combined text:
    - `services`
    - `about` (from about page if fetched)
    - `homepage_text`
  - Boolean flags:
    - Has phone?
    - Has email?
    - Has address?
    - Has service area?
    - Has clear service phrases vs blog/agency/franchise language?

These are consumed by `service_verifier` and `llm_verifier` already; our goal is to **feed them richer, more complete data**.

---

## 6. Checklist for implementation

- [ ] In `verification/verification_worker.py`, add an optional deep-scrape path using `scrape_site.site_scraper.scrape_website` for thin sites.
- [ ] Add a JS-render fallback module and call it only when static HTML is clearly insufficient.
- [ ] Add configuration constants for:
  - Thin-site thresholds
  - Deep-scrape budgets
  - JS-render budgets
- [ ] Ensure `website_metadata` passed into `service_verifier.verify_company(...)` includes all key fields.
- [ ] Extend `site_parse.py` term lists for niche exterior cleaning terminology as needed.

# 02 – Crawling & Content Extraction Improvements

**Goal for Claude**  
Ensure the verifier has **rich, accurate context** for each URL by:
- Crawling a small but meaningful subset of pages per site.
- Handling JS‑rendered content and contact info.
- Extracting structured signals needed by heuristics and the LLM.

Assume there is already some code that fetches URLs and passes HTML to an LLM.  
Your job is to **upgrade** that layer, not to rewrite everything from scratch.

---

## 1. Define a `PageSnapshot` structure

Add (or extend) a structured type to represent a crawled page.

Example (Python‑style pseudocode; adapt to repo language):

```python
class PageSnapshot(BaseModel):
    url: str
    status_code: int
    final_url: str         # after redirects
    html: str
    text: str              # cleaned visible text
    title: str | None
    meta_description: str | None
    h1: list[str]
    h2: list[str]
    links_internal: list[str]
    links_external: list[str]
    has_contact_form: bool
    has_phone_number: bool
    has_email_address: bool
    has_service_area_terms: bool
    has_pricing_or_quote_language: bool
```
You don’t have to use Pydantic – the key point is to unify what’s extracted from each page.

---

## 2. Small site crawl strategy per domain

For each **input URL** to verify:

1. **Normalize URL**
   - Force scheme (https if missing).
   - Strip obvious tracking params (`utm_*`, `fbclid`, etc.).

2. **Seed URLs for the domain**
   - Always include:
     - The given URL
     - The domain root (homepage) if different
   - After fetching those, add up to **N internal links** whose anchor/text matches:
     - “services”, “service”, “exterior cleaning”, “pressure washing”, “window cleaning”, “wood restoration”
     - “about”, “our company”, “who we are”
     - “contact”, “request a quote”, “get a quote”, “book now”

3. **Limit**
   - Add a config constant, e.g. `MAX_PAGES_PER_DOMAIN = 5–8`.
   - Only crawl that many pages per verification run.

4. **Respect robots/timeout**
   - Make sure requests obey any existing robot/timeout code in the repo.
   - Set a sane timeout (e.g. 10–15s) to avoid hanging.

Result: for each domain you should end up with a **list of PageSnapshot** objects.

---

## 3. JS‑rendered & minimal HTML handling

**Problem:** Some small sites render key content via JS (SPAs, page builders, dynamic contact widgets).  
**Solution:** Add a **headless browser fallback** used *only when needed*.

1. Add a headless renderer module
   - Use Playwright, Puppeteer, or an existing headless stack in the repo.
   - API shape (pseudo):

```python
async def render_page(url: str, timeout: int = 20000) -> str:
    """
    Return fully rendered HTML for `url` (after JS execution).
    Should block heavy resources (images/fonts) to keep it light.
    """
```

   - Configure it to:
     - Block images, fonts, video.
     - Wait until network idle or a fixed timeout (whichever first).
     - Return `page.content()`.

2. Detection logic – when to use headless
   - After fetching a page with normal HTTP:
     - If `len(text)` is below a small threshold (e.g. < 500 chars), **and**
     - DOM contains lots of `<script>` tags, or
     - You detect common SPA markers (e.g. root `<div id="app">`, `<div id="__next">`)
   - Then call `render_page(url)` once and re‑extract the text & features from the rendered HTML.

3. Avoid overuse
   - Add limit constants:
     - `MAX_RENDERED_PAGES_PER_DOMAIN` (e.g. 2)
     - `MAX_RENDERED_PAGES_PER_RUN` (e.g. 50)
   - Track counters in the process and skip rendering when limits are hit.

---

## 4. Text extraction & cleaning

Implement a function like:

```python
def extract_visible_text(html: str) -> str:
    # 1) Parse HTML with lxml/BeautifulSoup/etc.
    # 2) Remove <script>, <style>, <noscript>, <head>, and hidden elements.
    # 3) Join text blocks with whitespace normalized.
```

Guidelines:

- Remove nav/footer boilerplate where possible.
- Collapse multiple spaces & newlines.
- Keep headings and body paragraphs – they are valuable to the LLM.

---

## 5. Signal extraction (for later stages)

For each `PageSnapshot`, set the following booleans or counters:

1. **Contact & NAP signals**
   - Phone detection:
     - Regex for patterns like `(xxx) xxx-xxxx` or `xxx-xxx-xxxx` or international forms.
   - Email detection:
     - Regex for `something@something`.
   - Address cues:
     - Look for tokens like “Street”, “St.”, “Road”, “Rd.”, zip codes, city names if available.
   - Form detection:
     - Check for `<form>` plus inputs like `name`, `phone`, `email`, `message`.

2. **Service‑intent language**
   - Search (case‑insensitive) for phrases like:
     - “pressure washing”, “power washing”, “soft washing”
     - “window cleaning”, “gutter cleaning”, “house washing”, “roof cleaning”
     - “deck staining”, “wood restoration”, “fence staining”
   - Set `has_service_area_terms` when you find “serving [city]”, “we serve [area]”, etc.
   - Set `has_pricing_or_quote_language` when you find “get a quote”, “free estimate”, “schedule service”, etc.

3. **Non‑provider cues**
   - Blog / tutorial language:
     - “how to”, “guide”, “tips”, “DIY”, “step‑by‑step guide” in titles/headings.
   - Marketing/agency cues:
     - “we build brands”, “digital marketing agency”, “SEO services”, “lead generation for contractors”.
   - Franchise/opportunity cues:
     - “franchise opportunity”, “be your own boss”, “territory available”, “invest”, “franchisee”.
   - Directory/aggregator cues:
     - “find a pro”, “compare local pros”, “get multiple quotes”, lists of many cities/companies.

Store these as simple fields so later modules can use them (heuristics & LLM prompt).

---

## 6. Aggregated view per domain

After crawling, create a **DomainSnapshot** (you don’t have to persist it, but make it a struct the verifier can use):

```python
class DomainSnapshot(BaseModel):
    domain: str
    pages: list[PageSnapshot]
    combined_text: str             # concat of page.text, truncated
    any_contact_form: bool
    any_phone_number: bool
    any_service_terms: bool
    any_pricing_or_quote_lang: bool
    any_directory_cues: bool
    any_agency_cues: bool
    any_franchise_cues: bool
    any_blog_cues: bool
```

- `combined_text` can be the concatenation of all page texts up to e.g. 10–20k characters, which you’ll pass into the LLM.

This gives later stages a **single, coherent object** for “this website’s evidence”.

---

## 7. Checklist

- [ ] Define/extend `PageSnapshot` with all the fields above.
- [ ] Implement small per‑domain crawl (seed URLs + limited internal links).
- [ ] Add JS rendering fallback with strict limits and detection logic.
- [ ] Implement robust `extract_visible_text` function.
- [ ] Populate contact, service, and non‑provider cues.
- [ ] Construct a `DomainSnapshot` used by the rest of the pipeline.

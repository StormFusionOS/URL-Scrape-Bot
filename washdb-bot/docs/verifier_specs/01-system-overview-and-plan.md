# URL Verification System – Overview & High‑Level Plan

**Context for Claude**  
You are working inside a repository that already scrapes URLs and uses an LLM to decide whether a site is a real *service provider* for:
- Pressure washing
- Window washing
- Wood restoration

The current issues to fix:

- **False negatives**
  - Tiny / minimal sites (one‑page, little text)
  - Sites with JS‑rendered content or contact info
  - Niche / local terminology not in generic corpora
- **False positives**
  - Blogs & tutorials
  - Marketing / SEO agencies
  - Franchise opportunity & “work for us” microsites
  - Generic templates or placeholder business pages

The owner is OK with:

- Adding a **“needs_review”** state for borderline cases  
- A **slower, gold‑standard path** for tricky URLs  
- Logging cases for **human review + future training**  
- Using an LLM more heavily if that improves accuracy

---

## 1. Target Architecture (high level)

Implement a **multi‑stage verification pipeline** for each URL:

1. **Fetch & Extract**
   - Fetch main page (and a few key internal pages).
   - Handle JS‑rendered sites using a headless browser fallback.
   - Normalize & store:
     - Main text content (cleaned)
     - Title, meta description, headings
     - Outgoing & internal links
     - Contact info blocks, address, phone, email
     - Basic HTML features (forms, CTAs, menu labels).

2. **Feature & Heuristic Scoring (lightweight, deterministic)**
   - Compute structured features:
     - Domain patterns & URL path patterns
     - Presence of service‑intent phrases vs blog/agency/franchise cues
     - Presence of pricing, “Get a quote / schedule service”, service area, service list
     - Presence of lead‑gen or “find a pro” aggregator language.
   - Produce a **heuristic_score** and a preliminary label
     - `HEUR_PROBABLY_PROVIDER`
     - `HEUR_PROBABLY_NOT_PROVIDER`
     - `HEUR_UNCERTAIN`

3. **LLM Classification (rich, JSON output)**
   - Build a structured prompt with:
     - Summarized page content
     - Extracted features
     - Business‑like signals (NAP, CTAs, service list)
   - Ask the LLM for a **strict JSON** classification with fields like:
     - `is_pressure_washing_provider`
     - `is_window_cleaning_provider`
     - `is_wood_restoration_provider`
     - `is_directory_or_aggregator`
     - `is_marketing_or_agency`
     - `is_blog_or_content_only`
     - `is_franchise_opportunity`
     - `overall_label` (one of: `service_provider`, `directory`, `agency`, `blog`, `franchise`, `unknown`)
     - `confidence_score` (0–1)
     - `needs_review` (bool)
     - `reason_short` (one short sentence).

4. **Decision Logic & “Needs Review”**
   - Combine **heuristics + LLM**:
     - If both strongly agree → auto decision.
     - If they disagree or confidence < threshold → `needs_review = true`.
   - Final states:
     - `ACCEPTED_PROVIDER`
     - `REJECTED_NON_PROVIDER`
     - `NEEDS_REVIEW`

5. **Human Review + Training Data**
   - Store all inputs & outputs for URLs, especially ones marked `needs_review` or mis‑classified.
   - Provide a simple way (CLI, admin script, or UI) to:
     - See pending reviews
     - Set final human label
     - Optionally correct categories (e.g. “actually a franchise microsite”).
   - Persist this as a **labeled dataset** (ideal for fine‑tuning or training a smaller classifier).

6. **Evaluation & Monitoring**
   - Add an offline evaluation script:
     - Run the pipeline on a labeled dataset.
     - Compute precision/recall for each class and per‑segment (tiny sites vs JS sites vs directories).
   - Log & track:
     - Confusion between `service_provider` vs `agency` vs `directory`
     - False negatives on small sites
     - False positives on content sites.

---

## 2. Implementation Steps (what other docs will cover)

The remaining Markdown docs in this folder break implementation into clear chunks:

1. **02-crawling-and-content-extraction-improvements.md**
   - Make sure we get enough usable text & signals per domain.
   - Add JS‑rendering fallback for pages where static HTML is too empty.

2. **03-heuristics-and-rule-based-filtering.md**
   - Implement deterministic rules that quickly eliminate obvious non‑providers and boost obvious providers.

3. **04-llm-verification-and-scoring-pipeline.md**
   - Design the LLM prompts, JSON schema, validation, retry logic, and scoring fusion with heuristics.

4. **05-human-review-loop-and-training-data.md**
   - Implement logging of decisions, a review queue, and storage of human labels for training.

5. **06-evaluation-monitoring-and-configuration.md**
   - Build test harnesses, metrics, and configuration toggles (thresholds, rendering limits, etc.).

Each doc is written so you can open it next to the codebase and implement the changes step‑by‑step.

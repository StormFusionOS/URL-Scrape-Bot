# 03 – Heuristics & Rule-Based Filtering (mapped to service_verifier.py)

**Goal for Claude**  
Tune and extend the heuristic layer that already exists in `scrape_site/service_verifier.py` so we:

- Boost obvious service providers.
- Aggressively penalize blogs, agencies, directories, and franchise/business-opportunity sites.
- Produce a `status` + `score` that the DB update functions will respect when deciding `accept / reject / needs_review`.

---

## 1. Where heuristics live today

File: `scrape_site/service_verifier.py`

Key components:

- `verify_company(...)`:
  - Builds a `result` dict with:
    - `status` (`'passed' | 'failed' | 'unknown'`)
    - `score` (0.0–1.0)
    - `tier` (`'A'..'D'`)
    - `services_detected`, `positive_signals`, `negative_signals`, `reason`
    - `is_legitimate`, `red_flags`, `quality_signals` (from LLM)
- `_analyze_language(...)`:
  - Uses `provider_phrases`, `informational_phrases`, `cta_phrases`.
- `_validate_local_business(...)`:
  - Checks for phone, email, address, service area.
- `_calculate_rule_score(...)`:
  - Computes a rule-based score from headings, service phrases, CTA phrases, and local-business artifacts.
- Phase 5 logic:
  - Combines LLM score + rule score (or ML score) into `result['score']`.

All of this is already close to what we want; we just need to **tighten it for your use case** and later wire the output into the DB.

---

## 2. Strengthening positive provider signals

Make sure the rule score strongly reflects being a real exterior cleaning provider:

- **Service terms**:
  - Expand `self.services` and `provider_phrases` in the config JSON to include:
    - soft wash / soft washing
    - house wash / house washing
    - roof washing / roof cleaning
    - driveway / sidewalk / concrete cleaning
    - paver cleaning / paver sealing
    - gutter brightening / gutter whitening
    - deck/fence/log home staining & restoration
- **Local business structure**:
  - Ensure `_validate_local_business` adds strong positive signals when:
    - At least one US phone is present.
    - At least one email is present.
    - A plausible address is present.
    - Service area text mentions cities/counties.
- **CTAs**:
  - In `_analyze_language`, boost `cta_phrase_count` for phrases like:
    - “get a quote”, “free estimate”, “schedule service”, “book now”.

In `_calculate_rule_score`, consider:

- Slightly increasing the weight of:
  - Provider phrases in headings and services text.
  - Local business artifacts (phone/email/address).
  - CTA phrases.
- Keeping the max total rule score in the same range so it still nicely mixes with LLM scores.

---

## 3. Hard negative patterns (blogs, agencies, directories, franchise)

The LLM side (`llm_verifier.py`) already asks:

- “Is this a marketing agency, lead generation service, or advertising company?”
- “Is this primarily a blog, tutorial site, or informational website?”
- “Is this a directory, listing site, or aggregator of multiple businesses?”
- “Is this a franchise opportunity or business opportunity site?”

And sets `type` and `description` accordingly.

In `service_verifier.verify_company`, when you process `llm_result`, make sure to:

1. Map LLM types to **structured red flags**:

   - `type == 6` → `"marketing_agency"`
   - `type == 5` → `"blog_or_informational"`
   - `type == 4` → `"directory_or_listing"`
   - `type == 3` or specific wording → `"franchise_opportunity"`

   Append these to `result['red_flags']` if not already present.

2. Apply **hard penalties** to `rule_score` or directly to `result['score']`:

   - If `"directory_or_listing"` in `red_flags`:
     - Cap `result['score']` at, say, 0.25.
   - If `"marketing_agency"` in `red_flags`:
     - Cap `result['score']` at 0.25.
   - If `"blog_or_informational"` in `red_flags` **and** there are no phone/email/address signals:
     - Cap `result['score']` at 0.25.
   - If `"franchise_opportunity"` in `red_flags`:
     - Cap `result['score']` at 0.20.

3. Reflect this in `status` logic:

   Inside the “Phase 5: Combined Scoring” section:

   ```python
   is_llm_legitimate = result.get('is_legitimate', False)

   if result['score'] >= 0.70 and is_llm_legitimate:
       result['status'] = 'passed'
       ...
   elif result['score'] >= 0.75:
       result['status'] = 'passed'
       ...
   elif result['score'] <= 0.30 or (
       llm_result and not is_llm_legitimate and len(result.get('red_flags', [])) >= 2
   ):
       result['status'] = 'failed'
       ...
   else:
       result['status'] = 'unknown'
       ...
   ```

You can tweak the thresholds, but the idea is:

- Strong negative patterns plus low score → `failed`.
- Mixed signals → `unknown` (which will become `needs_review` at the DB layer).

---

## 4. Heuristic output contract

At the end of `verify_company`, make sure `result` contains:

- `status` in `{'passed','failed','unknown'}`
- `score` ∈ [0,1]
- `is_legitimate` (bool, from LLM)
- `red_flags` (list of strings)
- `quality_signals` (list of strings, optional)
- `tier` (A–D)
- `services_detected` map

This is the information the DB-level decision logic will use in the next doc.

---

## 5. Checklist

- [ ] Expand `provider_phrases` and service-related phrases in the config JSON for `service_verifier`.
- [ ] Ensure `_validate_local_business` and `_analyze_language` reward real local-business artifacts.
- [ ] Map LLM `type` codes to structured `red_flags` in the verification result.
- [ ] Cap `score` aggressively for directories, agencies, blogs without NAP, and franchise-opportunity sites.
- [ ] Leave final `status` computation as the canonical heuristic outcome to be respected by DB update functions.

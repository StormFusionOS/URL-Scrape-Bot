# 03 – Heuristics & Rule‑Based Filtering

**Goal for Claude**  
Implement a fast, deterministic heuristic layer that:
- Quickly rejects obvious non‑providers (blogs, agencies, generic directories).
- Boosts confidence for obvious local service providers.
- Produces a **heuristic label + score** consumed by the LLM fusion logic.

You will build on top of the `DomainSnapshot` and `PageSnapshot` structures from doc 02.

---

## 1. Define heuristic output type

Create a small struct / dataclass:

```python
class HeuristicResult(BaseModel):
    label: str          # 'provider', 'non_provider', or 'uncertain'
    score: float        # 0..1, "confidence provider"
    reasons: list[str]  # human-readable notes
```

This will be combined later with LLM output.

---

## 2. Core positive provider signals

Compute a numeric `score` starting from 0.5 and adjusting up/down.

Increase score for:

1. **Service‑intent terms present**
   - If `any_service_terms`: `score += 0.25`
2. **Contact & NAP present**
   - If `any_contact_form` or `any_phone_number`: `score += 0.1`
   - If both phone + email + address evidence: `score += 0.1`
3. **Service‑style CTAs**
   - If `any_pricing_or_quote_lang`: `score += 0.1`
4. **Domain hints**
   - If domain contains words like `"pressurewash"`, `"pwashing"`, `"softwash"`, `"windowclean"`, `"exteriorclean"`, `"powerwash"`: `score += 0.15`

Add human‑readable reasons for each increment, e.g. `"found pressure washing keywords"`, `"has quote form"`, etc.

Clamp `score` to [0,1].

---

## 3. Strong negative signals

Decrease score and possibly **short‑circuit to non‑provider** when strong evidence exists.

Check for:

1. **Directory / aggregator**
   - `any_directory_cues` (e.g., “find a pro”, “compare local pros”, lists of many companies).
   - Many external links to different domains with names like businesses.
   - If strong: set `score = 0.0`, `label = 'non_provider'`, add reason `"directory/aggregator language"`.

2. **Marketing agency / SaaS / vendor**
   - `any_agency_cues` (e.g., “we provide SEO for home service businesses”, “lead generation agency”).
   - Frequent mentions of “clients”, “case studies”, “campaigns” rather than “our services”.
   - If strong: `score = 0.0`, `label = 'non_provider'`, reason `"marketing/agency site"`.

3. **Blog / pure content**
   - `any_blog_cues` (headlines like “How to pressure wash your deck” with no clear service CTA).
   - Many posts with bylines/dates, little evidence of a specific business.
   - If strong and no service CTAs: reduce score heavily, e.g. `score -= 0.3` and maybe label `'non_provider'` when `score < 0.2`.

4. **Franchise opportunity microsite**
   - `any_franchise_cues` (e.g., “territories available”, “become a franchisee”, “investment”).
   - If it’s clearly recruitment/investment only, `score = 0.0`, label `'non_provider'`, reason `"franchise opportunity site"`.

---

## 4. Final label from heuristics

After applying positives & negatives and clamping `score`:

- If `score >= 0.75` and no strong negative flag:
  - `label = 'provider'`
- Else if `score <= 0.25`:
  - `label = 'non_provider'`
- Else:
  - `label = 'uncertain'`

Return `HeuristicResult(label, score, reasons)`.

Keep the thresholds as constants so they can be tuned:

```python
HEUR_PROVIDER_THRESHOLD = 0.75
HEUR_NON_PROVIDER_THRESHOLD = 0.25
```

---

## 5. Integration point

Add a function like:

```python
def run_heuristics(domain_snapshot: DomainSnapshot) -> HeuristicResult:
    ...
```

Then, in the main verification flow:

1. Build `DomainSnapshot` (from doc 02).
2. Call `heur = run_heuristics(domain_snapshot)`.
3. Pass `heur` along with `domain_snapshot` into the LLM stage (doc 04).

---

## 6. Edge‑case handling & notes

1. **Very small sites**
   - If the domain has only 1–2 pages and some service cues but weak CTAs, avoid harsh penalties.
   - Bias slightly toward `uncertain` instead of `non_provider` to reduce false negatives.

2. **Multi‑service contractors**
   - Don’t penalize presence of other home services: e.g., “roofing, painting, pressure washing” should still be allowed – these can be legitimate providers.

3. **Geo‑targeted directories**
   - Treat things like “best pressure washing companies in [city]” lists as directories, not providers.

4. **Config**
   - All patterns (keywords, phrases) should live in a config array so they can be updated without changing core logic.

---

## 7. Checklist

- [ ] Create `HeuristicResult` struct.
- [ ] Implement scoring logic with adjustable thresholds.
- [ ] Encode positive provider signals.
- [ ] Encode strong negative patterns (directory, agency, blog, franchise).
- [ ] Wire heuristics into the main verification flow.
- [ ] Add unit tests for representative sites (service provider, agency, directory, blog, tiny site).

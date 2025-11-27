# 04 – LLM Verification & Scoring Pipeline

**Goal for Claude**  
Design and implement the **LLM classification** layer that:
- Takes `DomainSnapshot` + `HeuristicResult` as input.
- Calls the LLM with a structured prompt.
- Gets **strict JSON** back with detailed classification.
- Combines LLM + heuristics into a final decision & `needs_review` flag.

---

## 1. Define the LLM output schema

Create a strict schema object to validate against:

```python
class LlmClassification(BaseModel):
    overall_label: str                   # 'service_provider', 'directory', 'agency', 'blog', 'franchise', 'unknown'
    is_pressure_washing_provider: bool
    is_window_cleaning_provider: bool
    is_wood_restoration_provider: bool
    is_directory_or_aggregator: bool
    is_marketing_or_agency: bool
    is_blog_or_content_only: bool
    is_franchise_opportunity: bool
    confidence_score: float              # 0..1
    needs_review: bool
    reason_short: str
```
Adjust types to match the repository’s style, but keep these fields.

---

## 2. Prompt design

### 2.1 System message

Example (adapt to your LLM provider):

> You are a strict JSON‑only classifier for local home‑service websites.  
> You decide whether a website is a real business offering exterior cleaning services  
> (pressure washing, window cleaning, wood restoration) to paying customers, or something else  
> such as a directory, marketing agency, blog, or franchise opportunity.  
> You must obey the JSON schema the user provides and never return anything except valid JSON.

### 2.2 User message template

Pass in a **compressed, structured context**:

- Domain & URL
- High‑level heuristic summary
- Key extracted signals
- Truncated combined text

Example (pseudo):

```text
You will receive information about a website. 
Decide if it is a real local service provider for exterior cleaning services.

JSON schema you MUST follow:
{schema_definition}

Website info:
- Domain: {domain}
- Main URL: {main_url}

Heuristic summary:
- Heuristic label: {heur.label}
- Heuristic score: {heur.score}
- Reasons: {joined_heur_reasons}

Signals:
- Any contact form: {any_contact_form}
- Any phone number: {any_phone_number}
- Any service terms: {any_service_terms}
- Any pricing/quote language: {any_pricing_or_quote_lang}
- Directory cues: {any_directory_cues}
- Agency cues: {any_agency_cues}
- Blog cues: {any_blog_cues}
- Franchise cues: {any_franchise_cues}

Content sample (may be truncated):
"""
{combined_text_truncated}
"""

Rules:
1. If it looks like a genuine local business providing services to end customers, classify as a service provider.
2. If it is about helping OTHER businesses get customers (marketing/lead gen/agency/SaaS), classify as marketing/agency.
3. If it shows many providers, price comparisons, or "find a pro" functionality, classify as directory/aggregator.
4. If it is mostly articles/tutorials and not clearly selling services, classify as blog/content.
5. If it sells franchises or recruitment opportunities, classify as franchise.
6. If you are not sure, choose the label that best fits but set needs_review = true.

Return ONLY a JSON object matching the schema.
```

Truncate `combined_text` to ~10k characters or less to avoid context blowup.

---

## 3. LLM call + validation + retry

Implement a function, e.g.:

```python
def classify_with_llm(domain_snapshot: DomainSnapshot, heur: HeuristicResult) -> LlmClassification:
    # 1) Build system + user messages
    # 2) Call LLM API
    # 3) Parse JSON with strict validation
    # 4) Retry with error hint if parsing fails
```

### Steps:

1. **Call LLM**
   - Use the existing client in the repo (OpenAI, local model, etc.).
   - Request a single completion/response.

2. **Parse JSON**
   - Try `json.loads` on the raw text.
   - Validate against `LlmClassification` schema (or equivalent).

3. **On failure**
   - If parsing or validation fails:
     - Re‑prompt LLM with a short error hint, e.g.:  
       “Your previous response was not valid JSON: {error}. Return ONLY valid JSON.”
     - Limit retries (e.g., max 2 attempts).

4. **Logging**
   - Log raw responses & errors (redacted if necessary) for debugging.
   - Store the final accepted JSON along with the URL in logs or DB.

---

## 4. Fusion: heuristics + LLM → final decision

Define a final decision structure:

```python
class FinalDecision(BaseModel):
    final_label: str         # 'accepted_provider', 'rejected_non_provider', 'needs_review'
    raw_llm: LlmClassification
    raw_heur: HeuristicResult
```

Then combine as follows:

1. **Agreement**
   - If `heur.label == 'provider'` and `llm.overall_label == 'service_provider'` and `llm.confidence_score >= 0.75`:
     - `final_label = 'accepted_provider'`, `needs_review = False`

   - If `heur.label == 'non_provider'` and `llm.overall_label != 'service_provider'` and `llm.confidence_score >= 0.75`:
     - `final_label = 'rejected_non_provider'`, `needs_review = False`

2. **Disagreement or low confidence**
   - If labels conflict (one says provider, other non‑provider), OR `llm.confidence_score < 0.6`:
     - `final_label = 'needs_review'`

3. **LLM explicit needs_review**
   - If `llm.needs_review` is `true`, always set `final_label = 'needs_review'` even if everything else looks good.

4. **Bias for safety**
   - In ambiguous cases, prefer `needs_review` over automatic accept/reject.

You can persist `FinalDecision` plus underlying raw structures in your storage layer.

---

## 5. Integration into existing pipeline

Identify the existing entry point where a URL is currently sent to an LLM. Replace that with:

1. Build `DomainSnapshot` (doc 02).
2. Run `HeuristicResult = run_heuristics(snapshot)` (doc 03).
3. Run `LlmClassification = classify_with_llm(snapshot, heur)` (this doc).
4. Compute `FinalDecision`.
5. Emit final label + store full context for audit/training.

Make sure any calling code expects the three states: `accepted_provider`, `rejected_non_provider`, `needs_review`.

---

## 6. Checklist

- [ ] Define `LlmClassification` schema.
- [ ] Implement structured system + user prompts.
- [ ] Implement LLM call, JSON parsing, validation, and retries.
- [ ] Implement fusion logic → `FinalDecision`.
- [ ] Replace direct LLM calls with the new multi‑stage pipeline.
- [ ] Add logging for raw prompts/responses (with redaction if necessary).

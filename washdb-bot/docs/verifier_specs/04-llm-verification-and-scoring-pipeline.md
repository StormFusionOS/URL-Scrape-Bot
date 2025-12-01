# 04 – LLM Verification & Scoring Pipeline (llm_verifier + workers)

**Goal for Claude**  
Upgrade how the LLM is used and how its output is combined with heuristics, using these files:

- `scrape_site/llm_verifier.py`  (LLM logic)
- `scrape_site/service_verifier.py` (calls LLM and combines scores)
- `verification/llm_service.py` + `verification/llm_queue.py` (GPU queue)
- `verification/verification_worker.py` and `db/verify_company_urls.py` (DB updates)

---

## 1. Improve context building in `llm_verifier._build_context`

Current implementation (simplified):

```python
def _build_context(self, company_name, services_text, about_text, homepage_text):
    services_text = (services_text or "")[:600]
    about_text = (about_text or "")[:600]
    homepage_text = (homepage_text or "")[:400]
    ...
```

This can truncate away the only mentions of relevant services on small pages.

**Upgrade plan:**

1. Add a “smart truncation” helper:

   ```python
   def _truncate_smart(self, text: str, fallback_limit: int = 2000) -> str:
       if not text:
           return ""
       text = text.strip()
       if len(text) <= fallback_limit:
           return text

       keywords = [
           "pressure wash", "power wash", "soft wash",
           "house wash", "roof wash", "roof cleaning",
           "window cleaning", "glass cleaning",
           "gutter cleaning", "gutter brightening", "gutter whitening",
           "deck staining", "wood restoration", "fence staining",
           "exterior cleaning"
       ]
       sentences = re.split(r'(?<=[.!?])\s+', text)
       hits = [s for s in sentences if any(k in s.lower() for k in keywords)]

       selected = []
       for s in hits:
           if len(" ".join(selected + [s])) > fallback_limit:
               break
           selected.append(s)

       if selected:
           return " ".join(selected)[:fallback_limit]

       # Fallback: first N chars if no keyword-rich sentences found
       return text[:fallback_limit]
   ```

2. Use it in `_build_context`:

   ```python
   services_text = self._truncate_smart(services_text, 2000)
   about_text = self._truncate_smart(about_text, 2000)
   homepage_text = self._truncate_smart(homepage_text, 1500)
   ```

3. Keep the final context structure:

   ```python
   context = f"Company: {company_name}\n"
   if services_text:
       context += f"Services: {services_text}\n"
   if about_text:
       context += f"About: {about_text}\n"
   if homepage_text:
       context += f"Homepage: {homepage_text}\n"
   ```

This gives much richer input without blowing up context size and specifically focuses on service-related sentences.

---

## 2. Ensure we use the shared LLM queue (GPU-friendly)

`llm_verifier` already supports two modes:

- Direct (`_generate_direct`)
- Queue (`_generate_queued` via `verification.llm_queue.llm_generate`)

For 24/7 operation with multiple workers:

- Default `LLMVerifier` to **queue mode**.
- Verify all calls (e.g. `_ask_yesno`, `_call_json_model`) go through `_generate_queued` when queue mode is enabled.
- Ensure `verification/llm_service.py` is launched by systemd (or supervisor) and documented in the project runbook.

No major code changes needed beyond making queue mode the default and ensuring error handling falls back gracefully (e.g., mark an LLM failure and set `needs_review = True` higher up).

---

## 3. Classification schema and red flags (already present)

`llm_verifier.classify_company(...)` already:

- Detects:
  - Target services (pressure/window/wood).
  - Company type:
    - 1 = service provider
    - 4 = directory / listing
    - 5 = blog / informational
    - 6 = lead gen / marketing agency
    - (and franchise-style types via explanation text)
- Asks focused yes/no questions to determine:
  - Residential vs commercial scope.
  - Legitimacy as a real business vs training site, spam, etc.

Our main task is to:

- Make sure `service_verifier.verify_company` is **always** recording:
  - `llm_result`
  - `llm_score`
  - `is_legitimate`
  - `red_flags`
- And that the DB layer respects these when triaging (next section).

---

## 4. DB-level scoring & triage (verification_worker + verify_company_urls)

### 4.1 Combined score (already implemented)

`db/verify_company_urls.py` has:

```python
def calculate_combined_score(company: Dict, verification_result: Dict) -> float:
    # Uses google_filter.confidence, yp_filter.confidence,
    # verification_result['score'], and review counts
    ...
```

This function is already imported and used in:

- `db/verify_company_urls.main()` (batch job)
- `verification/verification_worker.py` (continuous worker)

We KEEP this function and use its output as `combined_score`.

### 4.2 Fixing `update_company_verification` (batch + worker)

Both:

- `db/verify_company_urls.update_company_verification`
- `verification/verification_worker.update_company_verification`

currently do:

```python
is_legitimate = verification_result.get('is_legitimate', False)
if is_legitimate:
    active = True
    verification_result['status'] = 'passed'
    verification_result['needs_review'] = False
else:
    active = False
    verification_result['status'] = 'failed'
    verification_result['needs_review'] = False
```

They **ignore**:

- `verification_result['score']`
- `verification_result['status']` set by `service_verifier`
- `combined_score`
- Red flags.

We want to replace this with a proper triage:

1. Define thresholds (in both files, or better: import from a shared config):

   ```python
   HIGH = min_score   # e.g. 0.75
   LOW  = max_score   # e.g. 0.35
   ```

2. Derive decision signals:

   ```python
   svc_status = verification_result.get('status')          # 'passed'/'failed'/'unknown'
   svc_score  = verification_result.get('score', 0.0)
   is_legit   = verification_result.get('is_legitimate', False)
   red_flags  = verification_result.get('red_flags', []) or []
   web_conf   = svc_score
   comb       = combined_score
   ```

3. Decision logic:

   ```python
   needs_review = False

   if comb >= HIGH and is_legit and svc_status == 'passed' and len(red_flags) == 0:
       active = True
       final_status = 'passed'
   elif comb <= LOW and (not is_legit or svc_status == 'failed' or len(red_flags) >= 2):
       active = False
       final_status = 'failed'
   else:
       active = False
       final_status = 'unknown'
       needs_review = True
   ```

4. Update `verification_result` before writing:

   ```python
   verification_result['status'] = final_status
   verification_result['needs_review'] = needs_review
   verification_result['combined_score'] = comb
   verification_result['verified_at'] = datetime.now().isoformat()
   ```

5. When building the SQL query, store `verification_json` into `parse_metadata['verification']` exactly as before, but now `needs_review` is meaningful.

For the **continuous worker**, also include `worker_id` (already present) in `verification_result` for debugging.

---

## 5. Interpreting outcomes

After this change, your three effective states are:

- **Auto-accepted provider**
  - `parse_metadata['verification']['status'] == 'passed'`
  - `active = true`
  - `needs_review = false`
- **Auto-rejected non-provider**
  - `status == 'failed'`
  - `active = false`
  - `needs_review = false`
- **Needs manual review**
  - `status == 'unknown'`
  - `active = false`
  - `needs_review = true`

Your NiceGUI dashboard or admin tools can then filter on:

- `parse_metadata->'verification'->>'needs_review' = 'true'`

to build a review queue (as described in doc 05).

---

## 6. Checklist

- [ ] Implement smart truncation in `scrape_site/llm_verifier._build_context`.
- [ ] Ensure queue mode is the default for LLM calls via `verification.llm_queue`.
- [ ] Verify that `service_verifier.verify_company` always populates `is_legitimate`, `red_flags`, `llm_score`, and `status`.
- [ ] Update both `update_company_verification` functions (batch + worker) to:
  - Use `combined_score`, `result['score']`, LLM legitimacy, and red flags.
  - Set `needs_review = True` only for ambiguous cases.
- [ ] Confirm that `parse_metadata['verification']` ends up with a rich, self-contained JSON blob for auditing and training.

# 05 – Human Review Loop & Training Data (using parse_metadata['verification'])

**Goal for Claude**  
Use the DB and logging mechanisms in this repo to:

- Create a durable **review queue** of ambiguous companies.
- Store human decisions.
- Export labeled data for training and prompt improvement.

---

## 1. Where to store decisions

We will use:

- The existing `companies` table (SQLAlchemy `Company` model in `db/models.py`).
- Its `parse_metadata` JSONB column, specifically the `"verification"` key.

Each verification run (batch or worker) already writes a JSON blob into:

```sql
parse_metadata -> 'verification'
```

We’ll extend that JSON to hold:

- `status` (passed / failed / unknown)
- `score` (0–1)
- `combined_score`
- `is_legitimate`
- `red_flags` (list)
- `tier`
- `worker_id` (for workers)
- `verified_at`
- `needs_review` (bool)

And we’ll add **human labeling fields**:

- `human_label`: one of `'provider' | 'non_provider' | 'directory' | 'agency' | 'blog' | 'franchise'`
- `human_notes`: free text
- `reviewed_at`: ISO timestamp
- (Optionally) `reviewed_by`: string username/initials

These can live either:

- Inside `parse_metadata['verification']`, or
- In a separate table if you want, but using JSONB keeps things simple.

For now, assume we keep them in the JSON.

---

## 2. Populating `needs_review`

After implementing the triage logic in doc 04:

- The DB update functions will set:

  - `needs_review = true` if:
    - Combined score is in the mid-band, or
    - Heuristics and LLM disagree, or
    - LLM confidence is low.
  - `needs_review = false` for clear pass/fail.

That alone gives you a list of candidates that require manual inspection.

---

## 3. Building a CLI review tool

Create a script, e.g. `scripts/review_verification_queue.py`:

High-level flow:

1. Connect to DB via `SQLAlchemy` using the existing engine pattern (`db/database_manager.py` or `db/verify_company_urls.py` style).
2. Query for companies with:

   ```sql
   WHERE
     parse_metadata->'verification'->>'needs_review' = 'true'
     AND (parse_metadata->'verification'->>'human_label' IS NULL)
   ORDER BY created_at DESC
   LIMIT 50;
   ```

3. For each company:

   - Print summary:
     - `id`, `name`, `website`, `source`
     - `verification.status`, `score`, `combined_score`, `is_legitimate`
     - `red_flags`
     - Short snippet from `parse_metadata['verification']['llm_classification']` if helpful.
   - Optionally fetch and print a short excerpt of `homepage_text` from `parse_metadata` or re-run `parse_site_content` for inspection.

4. Prompt the reviewer:

   - Input options:
     - `p` → provider
     - `n` → non_provider
     - `d` → directory
     - `a` → agency
     - `b` → blog
     - `f` → franchise
     - `s` → skip/next
   - Optional text input for notes.

5. Update the JSON:

   ```python
   verification = company.parse_metadata.get("verification", {})
   verification["human_label"] = selected_label
   verification["human_notes"] = notes
   verification["reviewed_at"] = datetime.now().isoformat()
   # optional: verification["reviewed_by"] = current_user
   company.parse_metadata["verification"] = verification
   session.commit()
   ```

6. Loop until the batch is processed.

This can be simple terminal interaction; if you prefer, you can later wire this into the NiceGUI dashboard.

---

## 4. Exporting a training dataset

Create another script, e.g. `scripts/export_verification_training_data.py`:

1. Select all companies with a human label:

   ```sql
   WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL
   ```

2. For each:

   - Extract features:
     - From `verification` JSON:
       - `status`, `score`, `combined_score`, `is_legitimate`
       - `red_flags` count
       - `tier`
       - `llm_score` and any LLM subfields you wish to use.
     - From discovery metadata:
       - `parse_metadata['yp_filter']['confidence']`
       - `parse_metadata['google_filter']['confidence']`
       - Ratings (`rating_yp`, `rating_google`, `reviews_yp`, `reviews_google`).
     - From website parse metadata:
       - `parse_metadata['website']['homepage_text_length']` (you can store this when scraping).
       - `has_phone`, `has_email`, `has_address` booleans.

   - Write each row as JSONL, e.g.:

     ```json
     {
       "url": "https://example.com",
       "domain": "example.com",
       "features": {
         "web_score": 0.83,
         "combined_score": 0.79,
         "is_legitimate": true,
         "red_flags_count": 0,
         "tier": "A",
         "yp_conf": 0.9,
         "google_conf": 0.85,
         "rating_google": 4.7,
         "reviews_google": 53,
         "has_phone": true,
         "has_address": true
       },
       "label": "provider"
     }
     ```

3. Save to a file like `data/verification_training.jsonl`.

You can feed this to:

- A small supervised model (logistic regression, XGBoost, etc.).
- Or use it to refine LLM prompts (analyze misclassifications).

---

## 5. Analysis script for misclassifications

Create `scripts/analyze_verification_errors.py`:

1. Load the JSONL training file.
2. For each entry, compare:

   - `verification.status` and `llm_overall_label`
   - Against `human_label`.

3. Group and count:

   - Cases where:
     - `human_label = 'provider'` but `status = 'failed'`.
     - `human_label = 'non_provider'` but `status = 'passed'`.
     - `human_label = 'agency'` but LLM marked as service provider.
     - etc.

4. Print top patterns:

   - Common red_flags on misclassified providers.
   - Score ranges where most misclassifications occur.
   - Frequent words or phrases in text snippets for problem cases.

Use these insights to:

- Adjust thresholds.
- Add or tweak `provider_phrases` / `informational_phrases`.
- Update LLM prompts to be stricter or more lenient in certain cases.

---

## 6. Optional: small supervised classifier

Once you have a few hundred labeled examples, you can:

- Train a small model in a separate script, e.g. `scripts/train_verification_classifier.py`.
- Serialize it with `joblib` and load it in `service_verifier._load_ml_model(...)`.
- Use it as an additional signal when `llm_result` is present or absent.

This is an optional “v3” step; the current focus is to get the triage + review + logging loop in place so future models have good data.

---

## 7. Checklist

- [ ] Extend `parse_metadata['verification']` to include human label fields.
- [ ] Implement `scripts/review_verification_queue.py` for CLI-based review.
- [ ] Implement `scripts/export_verification_training_data.py` for JSONL export.
- [ ] Implement `scripts/analyze_verification_errors.py` for misclassification analysis.
- [ ] (Optional) Add a small supervised classifier training script and integrate it into `service_verifier`.

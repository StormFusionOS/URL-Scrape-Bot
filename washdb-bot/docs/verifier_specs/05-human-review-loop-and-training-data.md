# 05 – Human Review Loop & Training Data

**Goal for Claude**  
Create a **feedback loop** where:
- Borderline or mis‑classified URLs are sent to human review.
- Final human labels are stored.
- This labeled data can be used to tune prompts or train models.

We want to support a long‑term improvement cycle, not just a one‑off classifier.

---

## 1. Storage for decisions & labels

Add (or extend) a persistent store for verification results.

If there is already a DB, add a table like `url_verification_log`. If only files are used, create a CSV/JSONL in a `data/` folder. Example schema:

```text
id                  (auto)
url                 (text)
domain              (text)
decision_label      ('accepted_provider' | 'rejected_non_provider' | 'needs_review')
heur_label          ('provider' | 'non_provider' | 'uncertain')
heur_score          (float)
llm_overall_label   (text)
llm_confidence      (float)
llm_reason_short    (text)
is_pressure_wash    (bool)
is_window_clean     (bool)
is_wood_restore     (bool)
needs_review        (bool)
human_label         (nullable text: 'provider', 'non_provider', 'directory', 'agency', 'blog', 'franchise')
human_notes         (nullable text)
created_at          (timestamp)
reviewed_at         (nullable timestamp)
```

You don’t need this exact schema, but you **must** capture:

- URL + domain  
- Model outputs (heuristics + LLM)  
- Final human label & notes

---

## 2. Writing entries as part of the pipeline

After computing `FinalDecision` (doc 04), write one log entry per URL verification:

1. Fill all model‑side fields (`decision_label`, heur & LLM fields).  
2. Set `human_label = NULL` and `reviewed_at = NULL` initially.  
3. Mark `needs_review` according to `FinalDecision`.

This gives you a queue of items to be reviewed (all rows with `needs_review = true` OR where there’s evidence of mis‑classification).

---

## 3. Simple review interface (CLI or lightweight UI)

You don’t have to build a full web app if the repo doesn’t already have one.  
A simple CLI or TUI is enough for now.

### 3.1 CLI approach

Create a management script, e.g. `scripts/review_urls.py` that:

1. Loads all rows where `human_label IS NULL` and `decision_label = 'needs_review'` (or by filter flags).
2. For each row, prints a summary:
   - URL  
   - Model decision & scores  
   - `llm_reason_short`  
   - A short excerpt of `DomainSnapshot.combined_text` (or the main page’s text).

3. Prompts reviewer for input:
   - `p` → mark as provider  
   - `n` → mark as non‑provider  
   - `d` → directory  
   - `a` → agency  
   - `b` → blog  
   - `f` → franchise  
   - `s` → skip for now  
   - Optional free‑form notes

4. Updates `human_label`, `human_notes`, and `reviewed_at` in the store.

### 3.2 Web admin (optional)

If there’s already an admin UI, add a “Verification Review” page that:

- Lists pending items.  
- Allows filtering by source, date, or decision type.  
- Shows key signals & text excerpt.  
- Has buttons or dropdown to set `human_label` + save.

---

## 4. Assembling a training dataset

Add a utility script, e.g. `scripts/export_training_data.py`, that:

1. Selects all rows where `human_label IS NOT NULL`.
2. For each row, re‑computes or loads the **features** used in the pipeline:
   - Domain features (from heuristics)
   - Aggregated text
   - LLM outputs (could be used as features for a second‑stage model)
3. Writes them to a machine‑learning‑friendly format, e.g. JSONL:

```json
{"url": "...", "domain": "...", "features": {...}, "label": "provider"}
{"url": "...", "domain": "...", "features": {...}, "label": "agency"}
...
```

This can be used later to:

- Fine‑tune an LLM (instruction tuning).
- Train a smaller classifier (e.g., gradient‑boosted trees or a local model) that runs before or after the LLM.

---

## 5. Using labels to improve prompts & thresholds

Create a script `scripts/analyze_misclassifications.py` that:

1. Loads all rows with `human_label` set.  
2. Compares `human_label` vs `llm_overall_label` and `heur_label`.  
3. Aggregates common error patterns, e.g.:
   - “Agency classified as provider”
   - “Small provider classified as blog”
   - “Directories mis‑labeled as provider”

Then:

- Use this analysis to refine:
  - Heuristic keyword lists / weights.  
  - LLM instructions (“Be stricter about agency vs provider”, etc.).  
  - Thresholds for auto accept/reject vs `needs_review`.

---

## 6. Checklist

- [ ] Add persistent log of every URL verification decision.
- [ ] Write the log entries from the main pipeline.
- [ ] Implement a review script or UI for `needs_review` items.
- [ ] Store human labels and notes.
- [ ] Implement dataset export for model training.
- [ ] Add an analysis script for mis‑classifications & pattern discovery.

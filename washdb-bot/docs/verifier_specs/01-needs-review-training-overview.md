# 01 – Needs-Review Queue → Training Module (Overview)

**Audience:** Claude (or another AI dev) working in the `washdb-bot` repo.  
**Goal:** Turn the existing `needs_review` queue into a proper training module that continually improves URL verification.

---

## 1. Core idea

You already have:

- Continuous discovery (YP + Google scrapers) that fill the `companies` table.
- Verification workers that:
  - Scrape the website.
  - Run `service_verifier` + `llm_verifier`.
  - Compute `combined_score` and triage into `passed / failed / unknown`.
  - Store a JSON blob in `companies.parse_metadata["verification"]`.

We will:

1. **Standardize** the verification JSON so every company has rich metadata + a `needs_review` flag.
2. **Use `needs_review` as a labeling inbox**: humans assign `human_label` to ambiguous cases via CLI or GUI.
3. **Export labeled records** into a training dataset (`JSONL`).
4. **Train a small classifier** on top of existing signals (heuristics + LLM + YP/Google).
5. **Integrate the classifier** back into the verifier to get a better calibrated final score.
6. **Repeat**: as more `needs_review` items get labeled, retrain periodically (active learning).

---

## 2. Data model in `parse_metadata["verification"]`

Minimally, each verification blob should include:

- Machine-generated fields (already present or easy to add):
  - `status`: `"passed" | "failed" | "unknown"`
  - `score`: float (0–1, from `service_verifier`)
  - `combined_score`: float (from `calculate_combined_score`)
  - `is_legitimate`: bool (from LLM)
  - `red_flags`: list of strings
  - `tier`: `"A" | "B" | "C" | "D"`
  - `needs_review`: bool
  - `verified_at`: ISO timestamp
  - (optional) `worker_id`, `llm_type`, etc.

- Human labeling fields (NEW):
  - `human_label`: one of  
    - `"provider"`  
    - `"non_provider"`  
    - `"directory"`  
    - `"agency"`  
    - `"blog"`  
    - `"franchise"`
  - `human_notes`: short free text
  - `reviewed_at`: ISO timestamp
  - `reviewed_by`: username/initials (optional but useful)

Example JSON blob:

```jsonc
"verification": {
  "status": "unknown",
  "score": 0.41,
  "combined_score": 0.52,
  "is_legitimate": false,
  "red_flags": ["blog_or_informational"],
  "tier": "C",
  "needs_review": true,
  "verified_at": "2025-11-27T10:00:00Z",

  // Set by humans later:
  "human_label": "provider",
  "human_notes": "Thin site but clearly offers PW + WC locally",
  "reviewed_at": "2025-11-27T10:15:00Z",
  "reviewed_by": "ab"
}
```

**Interpretation:**

- `needs_review = true` AND `human_label` is `null` → unlabeled, waiting for human.
- `human_label != null` → labeled example for training.

---

## 3. High-level training loop

The full training loop looks like this:

1. **Verification workers** run as normal and mark some companies as `needs_review = true`.
2. **Humans** use a CLI or GUI (see doc 02) to:
   - Inspect those companies.
   - Set `human_label` and `human_notes`.
3. A **training export script** (doc 03) runs:
   - Pulls all companies with `human_label` set.
   - Builds `features` + `label` for each.
   - Writes to `data/verification_training.jsonl`.
4. A **training script** (doc 03) runs:
   - Trains a small supervised model (e.g., logistic regression or gradient-boosted trees).
   - Saves the model (e.g., `models/verification_classifier.joblib`).
5. The **runtime verifier** (doc 04):
   - Loads the model at startup.
   - For each company:
     - Computes the same `features`.
     - Gets a probability that the domain is a provider.
     - Combines that with `combined_score` to get a stronger `final_score`.
     - Uses `final_score` in triage (passed/failed/needs_review).

Over time, as you label more `needs_review` items, the model learns your preferences and the number of ambiguous cases should drop.

---

## 4. GUI integration (big picture)

We want GUI to support at least:

1. **Review queue page**
   - Shows companies with `needs_review = true` and no `human_label`.
   - Lets you view details (source, website, text snippet, LLM reason / red_flags).
   - Lets you set `human_label` + `human_notes` via buttons or dropdowns.
   - Writes back into `parse_metadata["verification"]`.

2. **Training stats / overview page**
   - Shows counts:
     - How many labeled examples exist (per label).
     - Last training run time.
   - Optionally, a button to trigger training (or show last model metrics).

Implementation details for both pages are in doc 02 and 03.

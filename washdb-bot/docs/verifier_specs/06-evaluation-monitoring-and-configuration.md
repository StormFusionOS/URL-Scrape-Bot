# 06 – Evaluation, Monitoring & Configuration

**Goal for Claude**  
Provide a way to **measure and maintain** the quality of the URL verification system over time, and make it easy to tune thresholds and behavior.

---

## 1. Offline evaluation harness

Create a script, e.g. `scripts/evaluate_verifier.py`, that:

1. Loads a labeled dataset (from the review loop, or a curated CSV) with:
   - URL
   - Ground‑truth label (`provider`, `agency`, `directory`, `blog`, `franchise`, `non_provider`)
2. Runs the **full pipeline** on these URLs:
   - Crawl → DomainSnapshot
   - Heuristics
   - LLM classification
   - FinalDecision

3. Records for each item:
   - Predicted `final_label`
   - Predicted `llm_overall_label`
   - Whether it hit `needs_review`
   - Run time (ms)

4. Computes metrics per class:
   - Precision, recall, F1 for “provider” vs “non‑provider”.
   - Confusion matrix between `provider`, `agency`, `directory`, `blog`, `franchise`.
   - Fraction of items that end up as `needs_review` (target range e.g. 10–30%).

5. Prints and optionally saves a report (JSON + Markdown).

This lets you test changes (new heuristics, new prompts, new thresholds) **before** deploying.

---

## 2. Production logging & sampling

In the main verification pipeline, ensure that for each URL you log:

- `url`, `domain`
- `FinalDecision.final_label`
- `HeuristicResult.label`, `HeuristicResult.score`
- `LlmClassification.overall_label`, `confidence_score`
- Flags: directory/agency/blog/franchise detection
- Whether JS rendering was used

Optionally, for performance or privacy, sample detailed logging (e.g., 10% of requests).

Add a periodic analysis script (or cron job) that:

1. Aggregates decisions by day.
2. Computes:
   - Distribution of final labels.
   - % of items going to `needs_review`.
   - Average LLM confidence.
   - JS rendering usage frequency.
3. Flags anomalies:
   - Sudden spike in `needs_review`.
   - Sudden jump in provider rate for certain domains or TLDs.

---

## 3. Configuration & tuning

Create a central config module/file, e.g. `config_verifier.py` or `config/verifier.yaml`, with keys like:

```yaml
max_pages_per_domain: 6
max_rendered_pages_per_domain: 2
max_rendered_pages_per_run: 50

heur_provider_threshold: 0.75
heur_non_provider_threshold: 0.25

llm_confidence_auto_accept: 0.75
llm_confidence_low: 0.6

truncate_combined_text_chars: 10000

enable_js_rendering: true
enable_logging_samples: true
logging_sample_rate: 0.2
```

Make all magic numbers in previous docs reference this config instead of being hard‑coded.

When testing, you can easily change thresholds to trade off between:

- Precision vs recall for providers.
- Volume of items sent to `needs_review`.

---

## 4. Guardrails & failure modes

Handle the following cases gracefully:

1. **LLM unavailable or errors**
   - Fallback behavior:
     - If heuristics strongly say non‑provider → `rejected_non_provider` with a flag `"llm_unavailable": true`.
     - If heuristics indicate provider or uncertain → `needs_review` (do not auto‑accept without LLM).

2. **JS rendering failure**
   - If headless browser crashes or times out, log it and continue with static HTML.  
   - Mark a flag (e.g. `js_render_failed = true`) in logs for later inspection.

3. **Rate limits / cost control**
   - Add a simple rate limiter on LLM calls (e.g. max X URLs/minute).
   - Optionally batch low‑priority URLs or run them during off‑peak times.

---

## 5. Runbooks for maintainers

Add a short Markdown file in the repo (you can also re‑use this doc) that explains for operators:

- How to run offline evaluation:
  - `python scripts/evaluate_verifier.py --input labeled_data.jsonl`
- How to tune thresholds in `config_verifier`.
- How to run the review loop and see mis‑classification stats.
- How to safely roll back if a new heuristic or prompt degrades performance.

This makes it straightforward for future developers (or another AI assistant) to adjust behavior without relearning the entire system.

---

## 6. Checklist

- [ ] Implement `evaluate_verifier.py` with full pipeline execution.
- [ ] Compute precision/recall and confusion matrices from labeled data.
- [ ] Add production logging for decisions and important flags.
- [ ] Centralize all thresholds & limits in a config module/file.
- [ ] Implement safe fallbacks when LLM or JS rendering fails.
- [ ] Document how to run evaluations and tune the system.

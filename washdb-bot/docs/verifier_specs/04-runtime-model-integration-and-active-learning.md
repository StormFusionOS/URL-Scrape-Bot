# 04 – Runtime Model Integration & Active Learning

**Goal for Claude**  
Integrate the trained classifier into the verification pipeline and make the `needs_review` queue an ongoing active-learning loop.

---

## 1. Where to integrate the model

At runtime, the verification steps are:

1. Website scrape + parse (`site_scraper`, `site_parse`).
2. `service_verifier.verify_company(...)`:
   - Rule-based/heuristic scoring.
   - LLM classification.
   - Produces `verification_result` with `score`, `status`, `red_flags`, etc.
3. `calculate_combined_score(company, verification_result)`:
   - Mixes web score + YP/Google + reviews → `combined_score`.
4. DB update (`update_company_verification` in `verification_worker` and `db/verify_company_urls`):
   - Triages into `passed / failed / unknown` and sets `needs_review`.

We add the classifier **between steps 3 and 4**:

- Take `verification_result` + `combined_score` + discovery metadata → feature dict.
- Run the classifier → probability that this is a `provider`.
- Fuse that probability with `combined_score` into a single `final_score`.
- Use `final_score` in triage.

---

## 2. Loading the model

In a small helper module, e.g. `verification/ml_classifier.py`:

```python
import joblib
from pathlib import Path

_model_bundle = None

def load_model_bundle():
    global _model_bundle
    if _model_bundle is None:
        path = Path('models/verification_classifier.joblib')
        if path.exists():
            _model_bundle = joblib.load(path)
        else:
            _model_bundle = None
    return _model_bundle

def predict_provider_prob(features: dict) -> float | None:
    bundle = load_model_bundle()
    if not bundle:
        return None
    vec = bundle['vectorizer']
    clf = bundle['model']
    X_vec = vec.transform([features])
    # If binary, assume provider is class 1
    proba = clf.predict_proba(X_vec)[0]
    # Map to the 'provider' column
    try:
        provider_idx = list(clf.classes_).index('provider')
    except ValueError:
        return None
    return float(proba[provider_idx])
```

Make sure this module is imported in both the worker and batch code where you have the final triage logic.

---

## 3. Building the features at runtime

When you’re about to triage (in `update_company_verification`), you already have:

- `verification_result` dict.
- `combined_score` float.
- `company` row with `parse_metadata` including YP/Google filters, ratings, etc.

Construct the same feature dict you used in training, e.g.:

```python
def build_features(company, verification_result, combined_score) -> dict:
    v = verification_result or {}
    pm = company.parse_metadata or {}

    verification_pm = pm.get("verification", {})
    yp_filter = pm.get("yp_filter", {})
    google_filter = pm.get("google_filter", {})
    website_pm = pm.get("website", {})

    features = {
        "score": float(v.get("score", 0.0)),
        "combined_score": float(combined_score),
        "is_legitimate": 1.0 if v.get("is_legitimate") else 0.0,
        "red_flags_count": len(v.get("red_flags") or []),
        "tier": {"A": 3, "B": 2, "C": 1, "D": 0}.get(v.get("tier"), 0),
        "yp_confidence": float(yp_filter.get("confidence", 0.0)),
        "google_confidence": float(google_filter.get("confidence", 0.0)),
        "rating_google": float(google_filter.get("rating", 0.0)),
        "reviews_google": float(google_filter.get("reviews", 0)),
        "has_phone": 1.0 if website_pm.get("has_phone") else 0.0,
        "has_address": 1.0 if website_pm.get("has_address") else 0.0,
        "homepage_text_length": float(website_pm.get("homepage_text_length", 0)),
    }
    # Add any other features you trained on
    return features
```

Then call:

```python
from verification.ml_classifier import predict_provider_prob

features = build_features(company, verification_result, combined_score)
ml_prob = predict_provider_prob(features)
```

If `ml_prob` is `None` (no model yet), skip this step and use `combined_score` alone.

---

## 4. Computing final_score and triage

If `ml_prob` is available, fuse it with `combined_score`:

```python
if ml_prob is not None:
    final_score = 0.5 * combined_score + 0.5 * ml_prob
else:
    final_score = combined_score
```

Then use `final_score` in the same triage logic as before, but with a conservative bias to avoid false negatives:

```python
HIGH = 0.75   # auto-accept threshold
LOW  = 0.25   # auto-reject threshold

svc_status = verification_result.get('status')
is_legit   = verification_result.get('is_legitimate', False)
red_flags  = verification_result.get('red_flags', []) or []

needs_review = False

if final_score >= HIGH and svc_status == 'passed' and is_legit and len(red_flags) == 0:
    active = True
    final_status = 'passed'
elif final_score <= LOW and (svc_status == 'failed' or not is_legit) and len(red_flags) >= 1:
    active = False
    final_status = 'failed'
else:
    active = False
    final_status = 'unknown'
    needs_review = True
```

Update `verification_result` before storing:

```python
verification_result['final_score'] = final_score
verification_result['status'] = final_status
verification_result['needs_review'] = needs_review
```

This way, the classifier influences **where** items land but does not remove the `needs_review` safety net.

---

## 5. Active learning: making the queue smarter

To make the `needs_review` queue an **active learning loop**:

1. When selecting items for review (in CLI or GUI):
   - Prefer ones where the model is most uncertain:
     - E.g., `final_score` between 0.4 and 0.6.
   - Or where heuristics and model strongly disagree:
     - e.g., heuristics say high, model says low, or vice versa.

2. Periodically retrain:
   - New labeled data accumulates.
   - Re-run `export_verification_training_data.py` and `train_verification_classifier.py`.
   - Swap in the new `verification_classifier.joblib`.

3. Optionally, surface a **Training & Model** section in the GUI:
   - Shows how many labeled examples exist.
   - Shows last training date.
   - Shows simple metrics (accuracy on a hold-out set).

This keeps the system learning exactly where it struggles most.

---

## 6. Summary

After this doc is implemented, you will have:

- A trained classifier loaded alongside your LLM + heuristics.
- A fused `final_score` used for triage decisions.
- A `needs_review` queue that not only protects you from bad auto-decisions, but also feeds the training module with informative examples.
- A pattern for continuous improvement: label → export → train → deploy → label again.

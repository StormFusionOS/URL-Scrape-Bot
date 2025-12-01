# 03 – Export & Train: Turning Labeled Data into a Model

**Goal for Claude**  
Use the labels from the review queue to build a training dataset and train a small classifier that helps improve verification decisions.

---

## 1. Export training data

Create `scripts/export_verification_training_data.py`.

### 1.1. Select labeled companies

Use SQLAlchemy to query the `companies` table for records where `human_label` is present:

Conceptual SQL:

```sql
SELECT *
FROM companies
WHERE parse_metadata->'verification'->>'human_label' IS NOT NULL;
```

Translate to SQLAlchemy JSONB access using your dialect.

### 1.2. Build feature vectors

For each company, we want a `features` dict and a `label` string.

Suggested features (all derived from existing data):

From `parse_metadata["verification"]`:

- `score` (float)
- `combined_score` (float)
- `is_legitimate` (bool → 0/1)
- `status` (one-hot or ordinal: passed/failed/unknown)
- `tier` (e.g., map A/B/C/D to 3/2/1/0)
- `red_flags_count` (int)
- Optionally: boolean flags for specific red flags:
  - `has_directory_flag`, `has_agency_flag`, `has_blog_flag`, `has_franchise_flag`

From discovery metadata (`parse_metadata["yp_filter"]`, `"google_filter"`):

- `yp_confidence` (float)
- `google_confidence` (float)
- YP category features (e.g., `yp_is_pressure_washing`, `yp_is_window_cleaning`, etc.)
- Ratings & review counts (if available):

  - `rating_google`, `reviews_google`
  - `rating_yp`, `reviews_yp`

From website parse metadata (`parse_metadata["website"]` or similar):

- `has_phone` (bool)
- `has_email` (bool)
- `has_address` (bool)
- `homepage_text_length` (chars)
- `services_text_length` (chars)
- `service_keyword_count` (count of service phrases)

Example JSONL row:

```json
{
  "url": "https://example.com",
  "domain": "example.com",
  "features": {
    "score": 0.81,
    "combined_score": 0.79,
    "is_legitimate": 1,
    "red_flags_count": 0,
    "tier": 3,
    "yp_confidence": 0.92,
    "google_confidence": 0.88,
    "rating_google": 4.7,
    "reviews_google": 53,
    "has_phone": 1,
    "has_address": 1,
    "homepage_text_length": 1400
  },
  "label": "provider"
}
```

Write one JSON object per line in `data/verification_training.jsonl`.

---

## 2. Train a classifier

Create `scripts/train_verification_classifier.py`.

### 2.1. Load the dataset

- Read `data/verification_training.jsonl`.
- Extract:
  - `X` = list of feature dicts → convert to numeric matrix (e.g., `DictVectorizer` or manual mapping).
  - `y` = list of labels.

You can:

- Start with binary labels:
  - `provider` vs `non_provider` (merge directory/agency/blog/franchise into non_provider).
- Later, train a multi-class classifier if desired.

### 2.2. Choose a model

Use scikit-learn (or similar). For example:

- Logistic Regression
- RandomForestClassifier
- GradientBoostingClassifier / XGBoost / LightGBM

Start simple:

```python
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
```

Steps:

1. Vectorize features with `DictVectorizer`:

   ```python
   vec = DictVectorizer(sparse=False)
   X_vec = vec.fit_transform(X)
   ```

2. Split into train/valid:

   ```python
   X_train, X_val, y_train, y_val = train_test_split(X_vec, y, test_size=0.2, random_state=42)
   ```

3. Train model:

   ```python
   clf = LogisticRegression(max_iter=1000, class_weight='balanced')
   clf.fit(X_train, y_train)
   ```

4. Evaluate on `X_val, y_val`:

   ```python
   print(classification_report(y_val, clf.predict(X_val)))
   ```

5. Save both `vec` and `clf`:

   ```python
   joblib.dump({'vectorizer': vec, 'model': clf}, 'models/verification_classifier.joblib')
   ```

For a binary model you might want to map labels to `provider` vs `other` and train that first, then consider finer-grained classes later.

---

## 3. Evaluate before deploying

Add simple checks before you ship a new model:

- Ensure `provider` recall is high (we don’t want false negatives).
- Ensure precision isn’t terrible (you don’t want a flood of false positives either).
- Compare to a naive baseline (e.g., just using `combined_score` threshold) to make sure the model is actually improving things.

You can log metrics to a file or console; later, you might surface them in a GUI “training stats” page.

---

## 4. (Optional) Automate training

Later, you can set up a cron or background job to:

1. Re-export labeled data.
2. Retrain the model.
3. Save a new `verification_classifier.joblib` with a version number.
4. Optionally, only promote the new model if metrics are better than the previous one.

For now, keep it manual so you (the human) can oversee changes.

---

## 5. Summary

After this doc is implemented, you will have:

- A JSONL training dataset derived from human-labeled `needs_review` items.
- A small supervised classifier trained on top of your existing heuristics + LLM + YP/Google signals.
- A saved model file (`models/verification_classifier.joblib`) ready to be used in the runtime verifier.

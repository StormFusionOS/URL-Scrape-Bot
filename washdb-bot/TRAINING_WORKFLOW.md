# Verification Training Workflow

Complete guide for training and improving the verification system.

## Overview

The verification system uses **two components**:
1. **ML Classifier** - Fast sklearn model trained on labeled data
2. **LLM Verification** - Claude API for deep content analysis

## Prerequisites

### 1. Set Up Claude API

Edit `.env` and add your API key:
```bash
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
```

Configuration is already set:
- Model: `claude-3-5-sonnet-20241022`
- Temperature: `0.0` (deterministic)
- Max tokens: `4096`

### 2. Check Current Status

```bash
# Check labeled data
./venv/bin/python -c "
from db.database_manager import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT
            parse_metadata->\'verification\'->\'human_label\' as label,
            COUNT(*) as count
        FROM companies
        WHERE parse_metadata->\'verification\'->\'human_label\' IS NOT NULL
        GROUP BY label
    '''))
    for row in result:
        print(f'{row[0]}: {row[1]}')
"
```

## Workflow

### STEP 1: Export Companies for Labeling

Export companies that need manual review:

```bash
# Export 100 "unknown" status companies
./venv/bin/python scripts/export_for_review.py --limit 100

# Output: data/companies_for_review_unknown.csv
```

You can also export from other statuses:
```bash
# Export failed companies (might be false negatives)
./venv/bin/python scripts/export_for_review.py --limit 100 --status failed

# Export passed companies (to verify they're correct)
./venv/bin/python scripts/export_for_review.py --limit 50 --status passed
```

### STEP 2: Label the Companies

1. Open the CSV file: `data/companies_for_review_unknown.csv`
2. Visit each website
3. Fill in the **"Label (provider/non_provider)"** column:
   - `provider` - Direct service provider (pressure washing, window cleaning, etc.)
   - `non_provider` - Directory, lead gen, equipment seller, blog, etc.

**Labeling Guidelines:**
- **Provider**: Has services page, pricing, contact info, serves customers directly
- **Non-Provider**: Lists other businesses, sells products only, informational only
- **Leave blank** if unsure (better than guessing)

### STEP 3: Import Labeled Data

```bash
# Import and mark as reviewed
./venv/bin/python scripts/import_reviewed_labels.py data/companies_for_review_unknown.csv
```

This will:
- Import your human labels
- Change status from "unknown" to "verified"
- Add to training dataset

### STEP 4: Train the ML Model

Run the complete training pipeline:

```bash
./venv/bin/python scripts/training_pipeline.py
```

This will:
1. Export all human-labeled data
2. Train the ML classifier
3. Evaluate performance (precision, recall, F1)
4. Save the updated model

**Minimum Requirements:**
- At least 100 labeled samples
- At least 20 samples per class (provider/non_provider)

**Good Performance Indicators:**
- Accuracy > 90%
- F1 Score > 0.85
- Precision and Recall both > 80%

### STEP 5: Reset Verification (Optional)

If you want to re-verify everything with the new model:

```bash
# This backs up, then clears verification data (keeps human labels)
./venv/bin/python scripts/reset_verification.py --confirm

# Backup will be saved to: data/backups/verification_backup_TIMESTAMP.json
```

### STEP 6: Restart Verification Workers

```bash
# Restart all verification services
systemctl restart washdb-verification-orchestrator
systemctl restart washdb-verification-worker@{1..5}

# Check status
systemctl status washdb-verification-orchestrator
systemctl status washdb-verification-worker@1
```

Or use the reload script:
```bash
./reload_services.sh
```

## Monitoring Progress

### Check Verification Progress

```bash
./venv/bin/python -c "
from db.database_manager import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT
            parse_metadata->\'verification\'->\'status\' as status,
            COUNT(*) as count
        FROM companies
        WHERE parse_metadata->\'verification\' IS NOT NULL
        GROUP BY status
        ORDER BY count DESC
    '''))
    print('Verification Status:')
    for row in result:
        print(f'  {row[0]}: {row[1]}')
"
```

### Watch Worker Logs

```bash
# Tail all worker logs
tail -f logs/state_worker_*.log

# Check for errors
grep -i error logs/state_worker_*.log | tail -20
```

### Monitor via GUI

Navigate to: `http://127.0.0.1:8080/verification`
- View verification stats
- See recent verifications
- Train classifier
- Export data

## Continuous Improvement

### Regular Cycle (Recommended)

1. **Weekly**: Label 50-100 new companies
   - Focus on "unknown" status
   - Review some "failed" (catch false negatives)
   - Review some "passed" (catch false positives)

2. **After Every 50 Labels**: Retrain the model
   ```bash
   ./venv/bin/python scripts/training_pipeline.py
   ```

3. **Monthly**: Evaluate overall performance
   - Check false positive/negative rates
   - Adjust thresholds if needed
   - Review edge cases

### Target Metrics

- **ML Model**:
  - Training samples: 200-500+ (more is better)
  - Accuracy: >90%
  - F1 Score: >0.85

- **Verification System**:
  - False positive rate: <5%
  - False negative rate: <10%
  - Unknown rate: <20%

## Troubleshooting

### "Not enough labeled data"

```bash
# Check current count
./venv/bin/python -c "
from db.database_manager import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT COUNT(*) FROM companies
        WHERE parse_metadata->\'verification\'->\'human_label\' IS NOT NULL
    '''))
    print(f'Total labels: {result.scalar()}')
"

# Need at least 100. If less, export and label more:
./venv/bin/python scripts/export_for_review.py --limit 200
```

### "Model accuracy is poor"

1. Need more labeled data (aim for 200-300 samples)
2. Check label quality (review some examples)
3. Balance classes (equal provider/non_provider samples)

### "Verification workers not processing"

```bash
# Check worker status
systemctl status washdb-verification-worker@1

# Check for errors in logs
tail -50 logs/state_worker_1.log

# Restart workers
systemctl restart washdb-verification-worker@{1..5}
```

### "Claude API errors"

1. Check API key in `.env`
2. Verify you have credits
3. Check rate limits (Tier 1: 50 requests/min)
4. Review logs for specific error messages

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `export_for_review.py` | Export companies for manual labeling |
| `import_reviewed_labels.py` | Import labeled CSV back to database |
| `training_pipeline.py` | Complete training workflow |
| `reset_verification.py` | Reset verification data (preserve labels) |
| `export_training_data.py` | Export all labeled data for training |
| `train_verification_classifier.py` | Train ML model |

## Files Reference

| File | Purpose |
|------|---------|
| `data/companies_for_review_*.csv` | Exported companies for labeling |
| `data/training_data_*.csv` | Exported training data |
| `data/backups/verification_backup_*.json` | Verification data backups |
| `models/verification_classifier_*.joblib` | Trained ML model |
| `logs/state_worker_*.log` | Worker logs |

## Quick Commands

```bash
# Complete workflow from scratch
./venv/bin/python scripts/export_for_review.py --limit 200
# [Label the CSV manually]
./venv/bin/python scripts/import_reviewed_labels.py data/companies_for_review_unknown.csv
./venv/bin/python scripts/training_pipeline.py
./reload_services.sh

# Check progress
systemctl status washdb-verification-worker@1
tail -f logs/state_worker_1.log

# View stats in GUI
# Navigate to: http://127.0.0.1:8080/verification
```

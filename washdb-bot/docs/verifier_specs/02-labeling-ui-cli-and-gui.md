# 02 – Labeling UI: CLI + GUI Integration

**Goal for Claude**  
Provide both a **CLI tool** and a **NiceGUI page** to review `needs_review` companies, apply `human_label`s, and write them back into `parse_metadata["verification"]`.

---

## 1. CLI review tool

Create a script, e.g. `scripts/review_verification_queue.py`.

### 1.1. Query candidates

Use the existing DB engine / session patterns (see `db/verify_company_urls.py` and `db/database_manager.py`).

Pseudocode:

```python
from db.models import Company
from sqlalchemy import select

def get_needs_review_batch(session, limit=50):
    # Adjust JSONB access to your dialect; this is conceptual
    stmt = select(Company).where(
        Company.parse_metadata["verification"]["needs_review"].astext == "true",
        Company.parse_metadata["verification"]["human_label"].is_(None)
    ).limit(limit)

    return session.execute(stmt).scalars().all()
```

### 1.2. Present and label

For each company in the batch:

- Print:
  - `id`, `name`, `website`
  - `status`, `score`, `combined_score`
  - `red_flags`
- Optionally, print a short snippet of homepage text if stored, or re-run `parse_site_content` for display.
- Prompt:

  ```text
  [p] provider
  [n] non_provider
  [d] directory
  [a] agency
  [b] blog
  [f] franchise
  [s] skip
  > 
  ```

- After a choice (except `s`), ask for optional notes.

### 1.3. Save label

Update `parse_metadata["verification"]` in the DB:

```python
from datetime import datetime
import json

verification = company.parse_metadata.get("verification", {})
verification["human_label"] = label_str  # e.g. "provider"
verification["human_notes"] = notes or ""
verification["needs_review"] = False
verification["reviewed_at"] = datetime.utcnow().isoformat()

company.parse_metadata["verification"] = verification
session.add(company)
session.commit()
```

This gives you a fast labeling workflow for power users.

---

## 2. GUI review page (NiceGUI)

Your repo already has a NiceGUI admin/dashboard setup. We add a **“Verification Review”** page that surfaces the same data but with a more user-friendly interface.

### 2.1. Where to put it

- Find the module where the NiceGUI app is created (typically something like `main.py`, `app/ui.py`, or similar).
- Locate where other admin pages are registered (e.g., `@ui.page('/admin')` or menu items).
- Add a new route/page, e.g. `/verification-review`.

### 2.2. Page layout

Rough structure using NiceGUI (conceptual):

- A table (or cards) listing companies that need review.
- Filters:
  - Source (YP/Google/other).
  - City or state.
- For each row:
  - Company name, website (clickable link).
  - Source icons (YP/Google).
  - Current verification status, score, combined_score.
  - Red flags and a short LLM explanation (if stored).
  - Buttons: `Provider`, `Non-provider`, `Directory`, `Agency`, `Blog`, `Franchise`.
  - Optional text area for notes.

When a button is clicked:

1. Call a backend handler that:
   - Opens a DB session.
   - Updates `parse_metadata["verification"]` with `human_label`, `human_notes`, etc.
   - Sets `needs_review = False`.
2. Show a toast/notification: “Saved label for COMPANY_NAME”.

### 2.3. Example GUI flow (pseudo-code)

```python
from nicegui import ui
from db.session import get_session
from db.models import Company

def load_needs_review_companies(limit=50):
    # same logic as CLI, returning list of dicts for the UI
    ...

def save_label(company_id: int, label: str, notes: str):
    with get_session() as session:
        company = session.get(Company, company_id)
        verification = company.parse_metadata.get("verification", {})
        verification["human_label"] = label
        verification["human_notes"] = notes
        verification["needs_review"] = False
        verification["reviewed_at"] = datetime.utcnow().isoformat()
        company.parse_metadata["verification"] = verification
        session.add(company)
        session.commit()

@ui.page('/verification-review')
def verification_review_page():
    companies = load_needs_review_companies()

    with ui.column():
        ui.label('Verification Review Queue')

        for c in companies:
            with ui.card():
                ui.label(f'{c["name"]} – {c["website"]}')
                ui.label(f'Score: {c["score"]:.2f}, Combined: {c["combined_score"]:.2f}')
                ui.label(f'Red flags: {", ".join(c["red_flags"] or [])}')
                notes_area = ui.textarea(label='Notes')
                with ui.row():
                    for label in ['provider', 'non_provider', 'directory', 'agency', 'blog', 'franchise']:
                        ui.button(label.capitalize(), 
                                  on_click=lambda l=label, cid=c["id"]: (
                                      save_label(cid, l, notes_area.value),
                                      ui.notify(f'Saved {l} for {c["name"]}')
                                  ))
```

You’ll need to adapt the DB/session imports and how you pass `notes_area` per row (you can wrap each card in a function so closures are correct), but this shows the general pattern.

### 2.4. Navigation integration

- Add a menu item or button in your existing admin dashboard that links to `/verification-review`.
- Optionally, show a badge with the count of `needs_review` items.

```python
ui.link('Verification Review', '/verification-review')
```

Now non-technical users can help label the queue directly in the browser.

---

## 3. Summary

After this doc is implemented, you will have:

- A CLI tool for fast power-user labeling.
- A NiceGUI admin page where anyone on the team can review ambiguous companies and assign labels.

Those labels then form the basis of the training dataset and model integration described in docs 03 and 04.

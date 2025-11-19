# Yellow Pages Category Integration Guide

## 🔍 Understanding the Two-Layer System

### **Layer 1: Search Categories (GUI Checkboxes)**
**Location**: `niceui/pages/discover.py` → `DEFAULT_CATEGORIES`
**Purpose**: What you SEARCH for on Yellow Pages

```python
DEFAULT_CATEGORIES = [
    "pressure washing",    # Search term
    "power washing",       # Search term
    "window cleaning",     # Search term
    ...
]
```

These are **lowercase search queries** sent to Yellow Pages' search engine.

---

### **Layer 2: Filter Categories (Allowlist)**
**Location**: `data/yp_category_allowlist.txt`
**Purpose**: Official YP category tags that results MUST have to pass filter

```
Power Washing
Window Cleaning
Roof Cleaning
Gutters & Downspouts Cleaning
...
```

These are **official Yellow Pages category labels** (title case) that YP assigns to businesses.

---

## 🔄 How They Work Together

### **Example Workflow:**

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: User Selects Search Terms (GUI)                    │
├─────────────────────────────────────────────────────────────┤
│ ☑ pressure washing                                          │
│ ☑ window cleaning                                           │
│ ☐ soft washing                                              │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Yellow Pages Search                                 │
├─────────────────────────────────────────────────────────────┤
│ https://yellowpages.com/search?                             │
│   search_terms=pressure+washing                             │
│   geo_location_terms=Dallas,TX                              │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: YP Returns 50 Listings with Category Tags          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ Listing 1: "ABC Pressure Washing"                          │
│   Category Tags: ["Power Washing", "Window Cleaning"]      │
│   Description: "Professional soft wash services"            │
│                                                              │
│ Listing 2: "Equipment Supply Store"                        │
│   Category Tags: ["Pressure Cleaning Equipment & Supplies"]│
│   Description: "Pressure washer sales and rentals"         │
│                                                              │
│ Listing 3: "XYZ Janitorial"                                │
│   Category Tags: ["Janitorial Service", "Office Cleaning"] │
│   Description: "Commercial cleaning services"               │
│                                                              │
│ Listing 4: "Pro Wash Services"                             │
│   Category Tags: ["Pressure Washing Equipment & Services", │
│                   "Power Washing"]                          │
│   Description: "Soft wash and house washing"                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Enhanced Filter Evaluates Each Listing             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ Listing 1: ABC Pressure Washing                            │
│   ✓ Has "Power Washing" (in allowlist)                     │
│   ✓ Has "Window Cleaning" (in allowlist)                   │
│   ✓ No blocklist categories                                │
│   ✓ No anti-keywords in name                               │
│   → ACCEPTED (Score: 85/100)                               │
│                                                              │
│ Listing 2: Equipment Supply Store                          │
│   ✗ Name contains "equipment" (anti-keyword)               │
│   ✗ Name contains "store" (anti-keyword)                   │
│   → REJECTED (Score: 0/100)                                │
│                                                              │
│ Listing 3: XYZ Janitorial                                  │
│   ✗ "Janitorial Service" (in blocklist)                    │
│   ✗ No allowed category tags                               │
│   → REJECTED (Score: 0/100)                                │
│                                                              │
│ Listing 4: Pro Wash Services                               │
│   ✓ Has "Power Washing" (in allowlist)                     │
│   ✓ Has positive hints ("soft wash", "house washing")      │
│   ✓ No anti-keywords in name                               │
│   → ACCEPTED (Score: 85/100)                               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: Results Saved to Database                          │
├─────────────────────────────────────────────────────────────┤
│ ✓ ABC Pressure Washing (score: 85)                         │
│ ✓ Pro Wash Services (score: 85)                            │
│                                                              │
│ Filtered out: 2/4 (50%)                                     │
│ Acceptance rate: 50%                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Current Integration Status

### **No Changes Needed - It Works!**

The existing system is **correctly integrated**:

1. **GUI categories** → User selects what to search
2. **YP returns results** → With official category tags
3. **Filter checks tags** → Against allowlist/blocklist
4. **Only quality results** → Saved to database

### **What We Just Added:**

✅ Info box in GUI explaining the distinction
✅ Enhanced filtering section with controls
✅ Real-time acceptance rates in logs

---

## 📋 Category Mapping Reference

### **Search Terms → Expected Filter Categories**

| Search Term (GUI) | Expected YP Category Tags (Filter) |
|-------------------|-----------------------------------|
| "pressure washing" | Power Washing, Water Pressure Cleaning |
| "window cleaning" | Window Cleaning |
| "gutter cleaning" | Gutters & Downspouts Cleaning |
| "roof cleaning" | Roof Cleaning |
| "deck cleaning" | Deck Cleaning & Treatment |
| "concrete cleaning" | Concrete Restoration, Sealing & Cleaning |

### **Why Different Formats?**

- **Search terms**: Lowercase, generic (what users type)
- **Filter categories**: Title Case, official (what YP assigns)

Yellow Pages internally maps your search to their category taxonomy.

---

## 🎛️ Optional: Sync the Categories

### **Current Approach (Recommended):**
- Search terms stay broad ("pressure washing")
- Filter catches everything with broad net
- Post-filtering eliminates noise

### **Alternative Approach (More Precise):**
If you want tighter alignment:

1. **Use official YP categories as search terms:**
```python
DEFAULT_CATEGORIES = [
    "Power Washing",
    "Water Pressure Cleaning", 
    "Window Cleaning",
    # etc.
]
```

2. **Add query terms for broader coverage:**
```python
QUERY_TERMS = [
    "pressure washing",  # Generic
    "soft washing",      # Specialized
    "house washing",     # Specific service
]
```

But this is **NOT necessary** - the current broad + filter approach works great!

---

## 🔧 If You Want to Customize

### **Option 1: Change Search Terms (GUI)**
Edit `niceui/pages/discover.py`:
```python
DEFAULT_CATEGORIES = [
    "pressure washing",
    "your custom term",
]
```

### **Option 2: Change Filter Categories**
Edit `data/yp_category_allowlist.txt`:
```
Power Washing
Your Custom Category
```

### **Option 3: Add Query Terms**
Edit `data/yp_query_terms.txt`:
```
soft wash
custom search phrase
```

Then regenerate targets:
```bash
python scrape_yp/seed_targets.py
```

---

## 💡 Best Practice Recommendations

### **Keep Current Setup:**
✅ GUI checkboxes: Broad search terms (lowercase)
✅ Filter allowlist: Official YP categories (Title Case)
✅ Anti-keywords: Block noise
✅ Query terms: Cover specialized services

### **Why This Works Best:**

1. **Broad search** = Maximum coverage
2. **Strict filter** = High precision
3. **Flexible tuning** = Adjust filters without changing search logic

### **Example Result:**
```
Search "pressure washing" in TX:
  - Finds: 100 listings (broad coverage)
  - Filters: 80 irrelevant (85% noise removed)
  - Saves: 20 quality businesses (15-25% acceptance)
```

---

## 🎓 Summary

### **Two Separate Systems:**
1. **Search Categories** (GUI) = What you search FOR
2. **Filter Categories** (allowlist) = What results must HAVE

### **Integration:**
Search → YP Results → Filter Checks → Save Quality

### **Status:**
✅ Already working correctly
✅ No changes needed
✅ Optional info box added for clarity

### **Tune By Editing:**
- `niceui/pages/discover.py` → Search terms
- `data/yp_category_allowlist.txt` → Filter categories
- `data/yp_anti_keywords.txt` → Blocklist terms

---

**Questions?**
- Run test: `python test_enhanced_yp.py`
- Review logs: `tail -f logs/yp_crawl.log`
- Check acceptance rates: Should be 15-25%

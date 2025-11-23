# 🚀 START HERE

**Status**: ✅ **DEPLOYED AND READY TO USE**

## Quick Navigation

- **New to the project?** → See **[docs/QUICKSTART-dev.md](docs/QUICKSTART-dev.md)** for complete setup
- **Want the dashboard?** → Run `./scripts/dev/run-gui.sh` or `python niceui/main.py`
- **Just want to scrape?** → Follow the 2-step guide below

---

## Yellow Pages Scraper: Getting Started in 2 Steps

### Step 1: Generate Targets

```bash
python -m scrape_yp.generate_city_targets --states RI --clear
```

This creates scraping targets for Rhode Island (31 cities × 10 categories = 310 targets).

### Step 2: Run Scraper

```bash
python cli_crawl_yp.py --states RI
```

That's it! The scraper will now:
- Process all 310 targets automatically
- Use shallow pagination (1-3 pages per city)
- Apply 85%+ precision filtering
- Save results to database
- Early-exit when no results found

---

## Example Output

```
================================================================================
Yellow Pages Crawler - City-First (Default)
================================================================================
States: RI
Min Score: 50.0
Include Sponsored: False
Max Targets: All
Dry Run: False
Started: 2025-11-12 12:30:00
================================================================================

✓ Found 310 planned targets

Processing targets...
Target 1/310: Providence, RI - Window Cleaning
  Page 1: 30 listings parsed, 5 accepted
  Page 2: 28 listings parsed, 3 accepted
  Page 3: 25 listings parsed, 2 accepted
  Saved: 10 results

Target 2/310: Cranston, RI - Window Cleaning
  Page 1: 0 listings accepted
  Early exit (no results)

... continues for all 310 targets ...

================================================================================
Crawl Summary
================================================================================
Targets Processed: 310
Early Exits: 127 (41%)
Results Saved: 1,247
================================================================================
```

---

## More Examples

### Multiple States

```bash
# Generate targets
python -m scrape_yp.generate_city_targets --states "CA,TX,FL" --clear

# Run scraper (limit to 500 targets for testing)
python cli_crawl_yp.py --states "CA,TX,FL" --max-targets 500
```

### Dry Run (No Saving)

```bash
python cli_crawl_yp.py --states RI --dry-run
```

### Custom Settings

```bash
python cli_crawl_yp.py --states RI --min-score 40 --include-sponsored
```

---

## Documentation

For complete details, see:
- **`YELLOW_PAGES_CITY_FIRST_README.md`** - Complete user guide
- **`DEPLOYMENT_COMPLETE.md`** - Deployment summary
- **`docs/`** - Technical documentation

---

## Need Help?

### Check Target Status

```sql
SELECT status, COUNT(*) FROM yp_targets GROUP BY status;
```

### View Results

```sql
SELECT name, domain, city, state FROM companies
WHERE source = 'YP' ORDER BY created_at DESC LIMIT 20;
```

### Check Logs

```
logs/yp_crawl_city_first.log
logs/cli_yp.log
```

---

**Ready to start scraping!** 🎯

Simply run:
```bash
python -m scrape_yp.generate_city_targets --states RI --clear
python cli_crawl_yp.py --states RI
```

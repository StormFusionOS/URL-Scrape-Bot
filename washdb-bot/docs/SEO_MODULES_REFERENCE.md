# SEO Module System - Document of Truth

**Last Updated:** 2026-01-10
**Purpose:** Authoritative reference for SEO module architecture, preventing hallucinations during diagnostics.

---

## 1. THE 9 SEO MODULES

| # | Module Name | Timeout | Description | Browser Required |
|---|-------------|---------|-------------|------------------|
| 1 | `technical_audit` | 300s | Website technical SEO analysis | Yes |
| 2 | `core_vitals` | 180s | Core Web Vitals (LCP, FID, CLS) | Yes |
| 3 | `backlinks` | 480s | Inbound link discovery | Yes |
| 4 | `citations` | 300s | Business directory listings (8 directories) | Yes |
| 5 | `competitors` | 300s | Competitor website crawling | Yes |
| 6 | `serp` | 1800s | Google SERP keyword rankings | Yes (shared) |
| 7 | `autocomplete` | 3600s | Google autocomplete suggestions | Yes (shared) |
| 8 | `keyword_intel` | 3600s | Keyword opportunity analysis | Yes (shared) |
| 9 | `competitive_analysis` | 300s | Competitor comparison & keyword gaps | Yes |

**Google Browser Modules** (use shared browser, soft timeouts):
- `serp`, `autocomplete`, `keyword_intel`

---

## 2. KEY FILES

| File | Purpose |
|------|---------|
| `seo_intelligence/jobs/seo_module_jobs.py` | 9 job class definitions, timeouts, constants |
| `seo_intelligence/jobs/seo_job_orchestrator.py` | Main orchestrator, heartbeat, company processing |
| `seo_intelligence/utils/shared_executor.py` | Shared ThreadPoolExecutor (thread exhaustion fix) |
| `seo_intelligence/orchestrator/self_healing.py` | Infrastructure health monitoring |
| `seo_intelligence/drivers/browser_pool.py` | Browser session management |
| `seo_intelligence/drivers/chrome_process_manager.py` | Chrome process lifecycle |

---

## 3. DATABASE TABLES

### Job Tracking
```sql
-- seo_job_tracking: Individual job execution history
SELECT tracking_id, company_id, module_name, run_type, status,
       started_at, completed_at, duration_seconds,
       records_created, records_updated, error_message, retry_count
FROM seo_job_tracking;

-- Status values: 'pending', 'running', 'completed', 'failed', 'skipped'
-- Run types: 'initial', 'quarterly', 'deep_refresh', 'retry'
```

### Company Flags
```sql
-- companies table has these SEO tracking columns:
seo_initial_complete     -- BOOLEAN: all 9 modules completed once
seo_last_full_scrape     -- TIMESTAMP: when initial completed
seo_next_refresh_due     -- TIMESTAMP: 90 days after last scrape
seo_technical_audit_done -- BOOLEAN
seo_core_vitals_done     -- BOOLEAN
seo_backlinks_done       -- BOOLEAN
seo_citations_done       -- BOOLEAN
seo_competitors_done     -- BOOLEAN
seo_serp_done            -- BOOLEAN
seo_autocomplete_done    -- BOOLEAN
seo_keyword_intel_done   -- BOOLEAN
seo_competitive_analysis_done -- BOOLEAN
```

### Worker Health
```sql
-- job_heartbeats: Worker health monitoring
SELECT worker_name, status, last_heartbeat,
       companies_processed, jobs_completed, jobs_failed,
       current_company_id, current_module
FROM job_heartbeats;
```

---

## 4. SUCCESS RATE QUERIES

### Last N Hours by Module
```sql
SELECT
    module_name,
    COUNT(*) as total,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) /
          NULLIF(COUNT(*), 0), 1) as success_pct
FROM seo_job_tracking
WHERE started_at > NOW() - INTERVAL '4 hours'
GROUP BY module_name
ORDER BY success_pct DESC NULLS LAST;
```

### Recent Failures with Errors
```sql
SELECT module_name, company_id, error_message, started_at
FROM seo_job_tracking
WHERE status = 'failed'
  AND started_at > NOW() - INTERVAL '1 hour'
ORDER BY started_at DESC
LIMIT 20;
```

### Company Progress
```sql
SELECT
    COUNT(*) as total_companies,
    SUM(CASE WHEN seo_initial_complete THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN NOT seo_initial_complete AND verified THEN 1 ELSE 0 END) as pending
FROM companies
WHERE verified = true AND standardized_name IS NOT NULL;
```

---

## 5. MODULE EXECUTION ORDER

```python
INITIAL_SCRAPE_ORDER = [
    'technical_audit',      # 1. Technical modules first
    'core_vitals',          # 2.
    'backlinks',            # 3.
    'citations',            # 4.
    'competitors',          # 5.
    'serp',                 # 6. Google modules (rate-limited)
    'autocomplete',         # 7.
    'keyword_intel',        # 8.
    'competitive_analysis'  # 9. Depends on competitors + keywords
]
```

---

## 6. RATE LIMITS & DELAYS

| Context | Delay |
|---------|-------|
| Between technical modules | 5 seconds |
| Between Google modules | 30 seconds |
| Between companies | 60 seconds |
| No work available | 300 seconds |
| Heartbeat interval | 30 seconds |
| Stale worker threshold | 5 minutes |

---

## 7. THREAD SAFETY THRESHOLDS

| Metric | Threshold | Action |
|--------|-----------|--------|
| Thread warning | 2000 | Log warning |
| Thread critical | 3000 | Force GC, reject work |
| Max executor workers | 20 | Bounded pool |
| Chrome process warning | 60 | Clean orphans |
| Chrome process critical | 100 | Aggressive cleanup |

---

## 8. LOG FILES

| Log | Path |
|-----|------|
| Browser Pool | `logs/browser_pool.log` |
| Self-Healing | `logs/self_healing.log` |
| Chrome Manager | `logs/chrome_process_manager.log` |
| SEO Jobs | `logs/seo_jobs.log` |
| Xvfb Watchdog | `logs/xvfb_watchdog.log` |
| Citations | `logs/citation_crawler_selenium.log` |

---

## 9. COMMON FAILURE PATTERNS

| Error | Cause | Solution |
|-------|-------|----------|
| `can't start new thread` | Thread exhaustion | Shared executor fix (max 20 workers) |
| `cannot connect to chrome` | Browser crash/zombie | Chrome cleanup, Xvfb restart |
| `TimeoutError` | Module exceeded timeout | Check network, increase timeout |
| `resurrected 0 sessions` | Thread exhaustion blocking resurrection | Reduce thread count |
| Xvfb flapping | Health check timeout under load | Longer xdpyinfo timeout |
| Jobs stuck "running" forever | Browser hang, process crash | Stale job cleanup (auto, 2x timeout) |

---

## 9.1 TIMEOUT ARCHITECTURE

**Hard Timeout (ThreadPoolExecutor)**:
- ALL modules use `run_with_timeout()` via shared executor
- Google modules (serp, autocomplete, keyword_intel) also use ThreadPoolExecutor
- Hard timeout enforced even if browser hangs

**Soft Timeout (Internal Loop)**:
- Google modules check elapsed time in their loops
- Allows graceful shutdown before hard timeout
- Saves partial work on timeout

**Stale Job Cleanup**:
- Runs every orchestrator loop iteration
- Marks jobs stuck in 'running' for >2x timeout as 'failed'
- Handles orphaned jobs from crashes/restarts

---

## 10. HEALTH CHECK COMMANDS

```bash
# Service status
sudo systemctl status seo-job-worker

# Thread count
ps -u rivercityscrape -L | wc -l

# Chrome processes
pgrep -c -f chrom

# Recent self-healing
tail -20 /mnt/work/projects/URL-Scrape-Bot/washdb-bot/logs/self_healing.log

# Recent errors
grep -E "ERROR|CRITICAL" logs/browser_pool.log | tail -20

# Module success rates (last hour)
sudo -u postgres psql -d washbot_db -c "
SELECT module_name,
       COUNT(*) as total,
       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok,
       ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
FROM seo_job_tracking
WHERE started_at > NOW() - INTERVAL '1 hour'
GROUP BY module_name ORDER BY pct DESC;"
```

---

## 11. SCRAPERS BY MODULE

| Module | Scraper File | Class |
|--------|--------------|-------|
| technical_audit | `scrapers/technical_auditor_selenium.py` | `TechnicalAuditorSelenium` |
| core_vitals | `scrapers/core_web_vitals_selenium.py` | `CoreWebVitalsSelenium` |
| backlinks | `scrapers/backlink_crawler_selenium.py` | `BacklinkCrawlerSelenium` |
| citations | `scrapers/citation_crawler_selenium.py` | `CitationCrawlerSelenium` |
| competitors | `scrapers/competitor_crawler_selenium.py` | `CompetitorCrawlerSelenium` |
| serp | `scrapers/serp_scraper_selenium.py` | `SerpScraperSelenium` |
| autocomplete | `scrapers/autocomplete_scraper_selenium.py` | `AutocompleteScraperSelenium` |
| keyword_intel | `scrapers/keyword_intelligence_selenium.py` | `KeywordIntelligenceSelenium` |
| competitive_analysis | `scrapers/competitive_analysis_selenium.py` | `CompetitiveAnalysisSelenium` |

---

## 12. CITATION DIRECTORIES (8 Total)

1. yellowpages.com
2. yelp.com
3. bbb.org
4. manta.com
5. thumbtack.com
6. homeadvisor.com
7. mapquest.com
8. superpages.com

---

## 13. DATA OUTPUT TABLES

| Module | Primary Tables |
|--------|---------------|
| technical_audit | `page_audits`, `audit_issues` |
| core_vitals | `page_audits` (LCP, FID, CLS columns) |
| backlinks | `backlinks`, `referring_domains` |
| citations | `citations` |
| competitors | `competitors`, `competitor_pages` |
| serp | `search_queries`, `serp_snapshots`, `serp_results` |
| autocomplete | `keyword_suggestions` |
| keyword_intel | `keyword_intelligence` |
| competitive_analysis | Multiple (uses competitors + keywords) |

---

*This document is the authoritative reference for the SEO module system. Update it when architecture changes.*

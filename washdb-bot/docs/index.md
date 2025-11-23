# URL Scrape Bot - Documentation Index

Welcome to the URL Scrape Bot documentation! This index provides quick access to all documentation organized by topic.

## Quick Start

- **[QUICKSTART-dev.md](QUICKSTART-dev.md)** - Fast setup guide for new developers
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - High-level system architecture overview
- **[LOGS.md](LOGS.md)** - Log file locations and common error patterns

## Architecture & Design

Core architectural patterns and technical designs:

- [Advanced Anti-Blocking Strategies](architecture/ADVANCED_ANTI_BLOCKING.md)
- [Crash Recovery System](architecture/CRASH_RECOVERY.md)
- [Parallel Scraping Guide](architecture/PARALLEL_SCRAPING_GUIDE.md)
- [Scheduler Hardening](architecture/SCHEDULER_HARDENING.md)
- [Scraper Improvements Guide](architecture/SCRAPER_IMPROVEMENTS_GUIDE.md)

## Scraper-Specific Documentation

### Yellow Pages Scraper
- [Yellow Pages City-First README](scrapers/yp/YELLOW_PAGES_CITY_FIRST_README.md) - Main YP scraper docs
- [Enhanced YP Quick Start](scrapers/yp/ENHANCED_YP_QUICK_START.md) - Getting started with YP scraper
- [YP Blocking Issue](scrapers/yp/YP_BLOCKING_ISSUE.md) - Anti-blocking techniques
- [YP Enhanced Implementation Summary](scrapers/yp/YP_ENHANCED_IMPLEMENTATION_SUMMARY.md)
- [YP Parser Filter Traceability](scrapers/yp/YP_PARSER_FILTER_TRACEABILITY.md)
- [YP State Splitting Summary](scrapers/yp/YP_STATE_SPLITTING_SUMMARY.md)
- [Enhanced Filter Now Default](scrapers/yp/ENHANCED_FILTER_NOW_DEFAULT.md)
- [YP Stealth Features](YP_STEALTH_FEATURES.md) - Anti-detection capabilities

### Google Maps Scraper
- [Google Scraper Implementation Plan](scrapers/google/GOOGLE_SCRAPER_IMPLEMENTATION_PLAN.md)
- [Google Scraper README](scrapers/google/GOOGLE_SCRAPER_README.md) - Main Google scraper docs
- [Google City-First GUI Integration](scrapers/google/GOOGLE_CITY_FIRST_GUI_INTEGRATION.md)
- [Google Maps City-First Status](scrapers/google/GOOGLE_MAPS_CITY_FIRST_STATUS.md)

### Other Scrapers
- Bing Local Search scraper documentation (TBD)

## GUI & Dashboard

NiceGUI web dashboard documentation:

- [NiceGUI Operations Console](gui/NICEGUI_OPERATIONS_CONSOLE.md) - Main dashboard guide
- [GUI Integration Complete](gui/GUI_INTEGRATION_COMPLETE.md)
- [GUI Integration Implementation](gui/GUI_INTEGRATION_IMPLEMENTATION.md)
- [Keyword Dashboard Complete](gui/KEYWORD_DASHBOARD_COMPLETE.md)
- [Keyword Dashboard Guide](gui/KEYWORD_DASHBOARD_GUIDE.md)
- [Live Output Implementation Guide](gui/LIVE_OUTPUT_IMPLEMENTATION_GUIDE.md)

## Deployment & Operations

Production deployment and operational guides:

- [Deployment Complete](deployment/DEPLOYMENT_COMPLETE.md) - Deployment summary
- [Log Management](deployment/LOG_MANAGEMENT.md) - Log rotation and management
- [Browser Cache Fix](deployment/BROWSER_CACHE_FIX.md) - Troubleshooting browser issues

## Implementation Guides

Detailed implementation documentation:

- [Category Integration Guide](implementation/CATEGORY_INTEGRATION_GUIDE.md)
- [Integration Guide](implementation/INTEGRATION_GUIDE.md)
- [Integration Plan](implementation/INTEGRATION_PLAN.md)
- [Subprocess Implementation Status](implementation/SUBPROCESS_IMPLEMENTATION_STATUS.md)
- [Resumable Site Crawler Summary](implementation/RESUMABLE_SITE_CRAWLER_SUMMARY.md)

## Testing & Validation

Test documentation and validation reports:

- [tests/README.md](../tests/README.md) - How to run tests
- [Test Results Summary](testing/TEST_RESULTS_SUMMARY.md)
- [Validation Results](testing/VALIDATION_RESULTS.md)
- [Verification Report](testing/VERIFICATION_REPORT.md)
- [Repo Sweep Verification](testing/REPO_SWEEP_VERIFICATION.md)

## Project Summaries

Historical project summaries and progress reports:

- [Final Project Summary](summaries/FINAL_PROJECT_SUMMARY.md) - Complete project overview
- [Implementation Complete](summaries/IMPLEMENTATION_COMPLETE.md)
- [Progress Summary (Weeks 1-4)](summaries/PROGRESS_SUMMARY_WEEKS_1-4.md)
- [Crash Recovery Summary](summaries/CRASH_RECOVERY_SUMMARY.md)
- [Worker Pool Resilience Summary](summaries/WORKER_POOL_RESILIENCE_SUMMARY.md)
- [Week 1: Anti-Detection Summary](summaries/WEEK1_ANTI_DETECTION_SUMMARY.md)
- [Week 2-3: Data Quality Summary](summaries/WEEK2-3_DATA_QUALITY_SUMMARY.md)
- [Week 4: Advanced Anti-Detection Summary](summaries/WEEK4_ADVANCED_ANTI_DETECTION_SUMMARY.md)
- [Week 5: Data Validation Summary](summaries/WEEK5_DATA_VALIDATION_SUMMARY.md)
- [Week 6: Monitoring Summary](summaries/WEEK6_MONITORING_SUMMARY.md)
- [DX Improvements Changelog](summaries/DX_IMPROVEMENTS_CHANGELOG.md)

## Fixes & Troubleshooting

Bug fixes and cleanup documentation:

- [Cleanup Fixes](fixes/CLEANUP_FIXES.md)
- [Cleanup Summary](fixes/CLEANUP_SUMMARY.md)
- [Fixes Applied](fixes/FIXES_APPLIED.md)

## Database Documentation

- [Schema Reference](SCHEMA_REFERENCE.md) - Complete database schema
- [Field Migration Guide](FIELD_MIGRATION_GUIDE.md) - Schema migration guide
- [City Registry Report](city_registry_report.md) - US cities dataset analysis
- [US Cities Profile](uscities_profile.md) - Cities dataset profile
- [YP City Slug Rules](yp_city_slug_rules.md) - URL slug generation rules

## Reference Documentation

Additional reference materials:

- [Implementation Summary](implementation_summary.md)
- [Pilot Test Results](pilot_test_results.md)
- [PDF Deprecation Notice](PDF_DEPRECATION_NOTICE.md)

---

## For New Developers

If you're new to the project, start here:

1. **[QUICKSTART-dev.md](QUICKSTART-dev.md)** - Get up and running in 5 minutes
2. **[ARCHITECTURE.md](ARCHITECTURE.md)** - Understand the system design
3. **[../README.md](../README.md)** - Project overview and features
4. **[LOGS.md](LOGS.md)** - Learn where to find logs when debugging

## For Experienced Developers

Deep dive into specific areas:

- **Architecture**: See [Architecture & Design](#architecture--design) section
- **Scrapers**: See [Scraper-Specific Documentation](#scraper-specific-documentation) section
- **GUI Development**: See [GUI & Dashboard](#gui--dashboard) section
- **Testing**: See [Testing & Validation](#testing--validation) section

---

**Note**: Some documentation files remain in the project root:
- `../README.md` - Main project README
- `../START_HERE.md` - Quick start guide
- `../DB_CREDENTIALS.md` - Database credentials (do not commit!)

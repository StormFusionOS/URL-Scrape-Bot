#!/usr/bin/env python3
"""
Centralized configuration for the URL verification system.

All thresholds, limits, and tunable parameters for:
- Scoring and triage decisions
- Thin-site and deep-scrape behavior
- JS rendering budgets
- LLM and worker rate limits

Import from here instead of hardcoding values in individual modules.
"""

import os

# ==============================================================================
# SCORING THRESHOLDS
# ==============================================================================

# Combined score thresholds for final triage decision
COMBINED_HIGH_THRESHOLD = float(os.getenv('VERIFY_HIGH_THRESHOLD', '0.75'))  # Auto-accept
COMBINED_LOW_THRESHOLD = float(os.getenv('VERIFY_LOW_THRESHOLD', '0.35'))    # Auto-reject

# Heuristic-only thresholds (when LLM unavailable)
HEUR_PROVIDER_THRESHOLD = 0.75
HEUR_NON_PROVIDER_THRESHOLD = 0.25

# LLM confidence thresholds
LLM_CONFIDENCE_HIGH = 0.75      # Trust LLM decision fully
LLM_CONFIDENCE_LOW = 0.60       # Below this → needs_review

# LLM weight in combined scoring (vs rule-based)
LLM_WEIGHT = float(os.getenv('VERIFY_LLM_WEIGHT', '0.7'))  # 70% LLM, 30% rules

# Red flag thresholds
RED_FLAG_AUTO_REJECT_COUNT = 2  # Auto-reject if this many red flags + low score

# Score caps for specific red flag categories
SCORE_CAP_DIRECTORY = 0.25
SCORE_CAP_AGENCY = 0.25
SCORE_CAP_BLOG_NO_NAP = 0.25
SCORE_CAP_FRANCHISE = 0.20


# ==============================================================================
# CRAWLING & CONTENT EXTRACTION
# ==============================================================================

# Thin site detection (triggers deep scrape)
THIN_TEXT_THRESHOLD = int(os.getenv('VERIFY_THIN_THRESHOLD', '500'))  # chars

# Deep scrape limits (multi-page scraping for thin sites)
MAX_DEEP_SCRAPES_PER_HOUR = int(os.getenv('VERIFY_MAX_DEEP_SCRAPES', '50'))

# JS rendering configuration
ENABLE_JS_RENDERING = os.getenv('VERIFY_JS_RENDERING', 'true').lower() in ('true', '1', 'yes')
MAX_RENDERED_PAGES_PER_RUN = int(os.getenv('VERIFY_MAX_RENDERED_RUN', '50'))
MAX_RENDERED_PAGES_PER_DOMAIN = int(os.getenv('VERIFY_MAX_RENDERED_DOMAIN', '2'))

# JS render detection thresholds
JS_RENDER_TEXT_THRESHOLD = 300  # chars - below this may need JS rendering
JS_RENDER_SCRIPT_THRESHOLD = 5  # Many scripts suggest SPA/JS-heavy site


# ==============================================================================
# LLM CONTEXT BUILDING
# ==============================================================================

# Smart truncation limits for LLM context
LLM_SERVICES_TEXT_LIMIT = 2000
LLM_ABOUT_TEXT_LIMIT = 2000
LLM_HOMEPAGE_TEXT_LIMIT = 1500
LLM_TOTAL_CONTEXT_LIMIT = 6000

# Keywords for smart truncation (prioritize sentences with these)
LLM_PRIORITY_KEYWORDS = [
    "pressure wash", "power wash", "soft wash",
    "house wash", "roof wash", "roof cleaning",
    "window cleaning", "glass cleaning",
    "gutter cleaning", "gutter brightening", "gutter whitening",
    "deck staining", "wood restoration", "fence staining",
    "exterior cleaning", "concrete cleaning", "driveway cleaning",
    "paver cleaning", "paver sealing"
]


# ==============================================================================
# WORKER CONFIGURATION
# ==============================================================================

# Timing
MIN_DELAY_SECONDS = float(os.getenv('VERIFY_MIN_DELAY_SECONDS', '2.0'))
MAX_DELAY_SECONDS = float(os.getenv('VERIFY_MAX_DELAY_SECONDS', '5.0'))
EMPTY_QUEUE_DELAY = 60        # Seconds to wait when queue is empty
MAX_EMPTY_QUEUE_DELAY = 300   # Max backoff delay

# Prefetch buffer
PREFETCH_BUFFER_SIZE = int(os.getenv('VERIFY_PREFETCH_SIZE', '3'))

# Rate limits
MAX_LLM_VERIFICATIONS_PER_HOUR = int(os.getenv('VERIFY_MAX_LLM_HOUR', '300'))

# Stale in_progress cleanup (seconds)
STALE_IN_PROGRESS_TIMEOUT = 600  # 10 minutes


# ==============================================================================
# LOGGING & MONITORING
# ==============================================================================

# Logging sample rate for detailed logs (0.0 - 1.0)
LOGGING_SAMPLE_RATE = float(os.getenv('VERIFY_LOG_SAMPLE_RATE', '0.2'))

# Alert thresholds
ALERT_NEEDS_REVIEW_PERCENT = 50  # Alert if needs_review exceeds this %
ALERT_PASS_RATE_MIN = 5          # Alert if pass rate drops below this %


# ==============================================================================
# LEGACY COMPATIBILITY (map old env var names)
# ==============================================================================

# These were used in verification_worker.py - now use COMBINED thresholds
MIN_SCORE = COMBINED_HIGH_THRESHOLD  # Auto-pass threshold
MAX_SCORE = COMBINED_LOW_THRESHOLD   # Auto-reject threshold (confusing name, kept for compat)

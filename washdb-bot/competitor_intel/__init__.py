"""
Competitor Intelligence Module

A specialized module for tracking and analyzing local competitors with:
- Higher refresh frequency (daily vs quarterly)
- Deeper data collection (full site crawls, pricing, services)
- Competitor-specific analytics (SOV, threat scoring, alerts)

This module shares infrastructure with seo_intelligence but operates
independently with its own orchestrator and job scheduling.
"""

__version__ = "1.0.0"
__author__ = "WashDB Bot"

from competitor_intel.config import (
    REFRESH_INTERVALS,
    MODULE_ORDER,
    MODULE_TIMEOUTS,
)

__all__ = [
    "REFRESH_INTERVALS",
    "MODULE_ORDER",
    "MODULE_TIMEOUTS",
]

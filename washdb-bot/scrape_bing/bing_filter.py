#!/usr/bin/env python3
"""
Bing Local Search business filtering module.

Filters out unwanted businesses using shared filtering logic from Google.
The filtering criteria are identical across all sources:
- Equipment sellers/suppliers
- Ecommerce sites
- Installation/repair services
- Janitorial/interior cleaning
- Auto detailing
- Marketplaces and directories

This module simply wraps the Google filter for Bing use.
"""

from scrape_google.google_filter import GoogleFilter
from runner.logging_setup import get_logger

logger = get_logger("bing_filter")


class BingFilter(GoogleFilter):
    """
    Filter and score Bing Local Search businesses.

    Inherits all filtering logic from GoogleFilter since the criteria
    are identical across all data sources.
    """

    def __init__(
        self,
        anti_keywords_file: str = 'data/anti_keywords.txt',
        positive_hints_file: str = 'data/yp_positive_hints.txt'
    ):
        """
        Initialize filter with data files.

        Args:
            anti_keywords_file: Path to shared anti-keywords file
            positive_hints_file: Path to positive hint phrases
        """
        super().__init__(anti_keywords_file, positive_hints_file)

        # Override logger message for Bing
        logger.info(f"✓ Bing Filter initialized (using shared filter logic):")
        logger.info(f"  Anti-keywords: {len(self.anti_keywords)} terms")
        logger.info(f"  Positive hints: {len(self.positive_hints)} phrases")
        logger.info(f"  Blocked domains: {len(self.blocked_domains)} domains")


# Convenience function
def get_filter() -> BingFilter:
    """
    Get BingFilter instance with default settings.

    Returns:
        BingFilter instance
    """
    return BingFilter()

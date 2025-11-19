"""
Bing Local Search city-first scraper package.

Modules:
- bing_config: Configuration constants
- bing_parse: HTML parsing logic for Bing Local Search results
- bing_crawl_city_first: Main crawler implementation
- bing_filter: Business filtering logic
- generate_city_targets: Target generation for city × category combinations
"""

__all__ = [
    "bing_config",
    "bing_parse",
    "bing_crawl_city_first",
    "bing_filter",
    "generate_city_targets",
]

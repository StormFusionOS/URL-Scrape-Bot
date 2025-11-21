"""
SEO Intelligence System

AI-powered SEO intelligence tracking and analysis system.

This package provides:
- SERP monitoring and position tracking
- Competitor analysis and page crawling
- Backlink discovery and Local Authority Score (LAS)
- Citation tracking with NAP matching
- Technical/accessibility audits
- Review-mode governance for all changes

Architecture:
- Write-only data source (all changes go through change_log)
- No paid APIs (ethical scraping with robots.txt compliance)
- Token bucket rate limiting
- Content change detection via SHA-256 hashing
- Time-series data with partitioning support
"""

__version__ = "1.0.0"
__author__ = "Washbot Team"

__all__ = []

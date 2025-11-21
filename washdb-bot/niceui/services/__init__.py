"""
Services Module
Business logic and backend integration for Washbot dashboard
"""

from .seo_backend import SEOBackend, SEOSource, AnalysisResult, get_seo_backend

__all__ = [
    "SEOBackend",
    "SEOSource",
    "AnalysisResult",
    "get_seo_backend",
]

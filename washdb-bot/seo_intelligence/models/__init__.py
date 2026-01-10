# SEO Intelligence Models
# Data classes for scraper artifacts and quality profiles

from .artifacts import (
    PageArtifact,
    ScrapeQualityProfile,
    ArtifactStorage,
    DEFAULT_QUALITY_PROFILE,
    HIGH_QUALITY_PROFILE,
    FAST_PROFILE,
)

__all__ = [
    'PageArtifact',
    'ScrapeQualityProfile',
    'ArtifactStorage',
    'DEFAULT_QUALITY_PROFILE',
    'HIGH_QUALITY_PROFILE',
    'FAST_PROFILE',
]

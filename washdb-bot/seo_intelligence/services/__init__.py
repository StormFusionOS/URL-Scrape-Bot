"""
SEO Intelligence Services

This module contains core services:
- task_logger: Execution tracking and governance
- rate_limiter: Token bucket rate limiting
- robots_checker: Robots.txt compliance checking
- content_hasher: SHA-256 content change detection
- user_agent_rotator: User agent rotation for anti-detection
- proxy_manager: Proxy pool integration
- las_calculator: Local Authority Score calculation
- qdrant_manager: Vector database management for semantic search
- embedding_service: Text chunking and embedding generation
- source_trust: Trust-weighted consensus for canonical field selection
- section_embedder: Section-level embeddings for fine-grained search
- nap_validator: NAP consistency validation
- entity_matcher: Entity deduplication and matching
- url_canonicalizer: URL normalization and tracking parameter removal

All services support ethical scraping with rate limiting and robots.txt compliance.
"""

from .task_logger import TaskLogger, get_task_logger
from .rate_limiter import RateLimiter, get_rate_limiter, TIER_CONFIGS
from .robots_checker import RobotsChecker, get_robots_checker
from .content_hasher import ContentHasher, get_content_hasher
from .user_agent_rotator import UserAgentRotator, get_user_agent_rotator, DeviceType
from .proxy_manager import ProxyManager, get_proxy_manager
from .las_calculator import LASCalculator, LASResult, LASComponents, get_las_calculator
from .change_manager import ChangeManager, ChangeStatus, ChangeType, get_change_manager
from .qdrant_manager import QdrantManager, get_qdrant_manager
from .embedding_service import (
    ContentEmbedder,
    get_content_embedder,
    TextChunker,
    EmbeddingGenerator,
    extract_main_content
)
from .source_trust import SourceTrustConfig, SourceTrustService, get_source_trust
from .section_embedder import SectionEmbedder, get_section_embedder
from .nap_validator import NAPValidator, NAPValidationResult, get_nap_validator
from .entity_matcher import EntityMatcher, MatchResult, get_entity_matcher
from .url_canonicalizer import URLCanonicalizer, CanonicalURL, get_url_canonicalizer
from .domain_quarantine import (
    DomainQuarantine,
    QuarantineReason,
    QuarantineEntry,
    BackoffSchedule,
    get_domain_quarantine
)

__all__ = [
    "TaskLogger",
    "get_task_logger",
    "RateLimiter",
    "get_rate_limiter",
    "TIER_CONFIGS",
    "RobotsChecker",
    "get_robots_checker",
    "ContentHasher",
    "get_content_hasher",
    "UserAgentRotator",
    "get_user_agent_rotator",
    "DeviceType",
    "ProxyManager",
    "get_proxy_manager",
    "LASCalculator",
    "LASResult",
    "LASComponents",
    "get_las_calculator",
    "ChangeManager",
    "ChangeStatus",
    "ChangeType",
    "get_change_manager",
    "QdrantManager",
    "get_qdrant_manager",
    "ContentEmbedder",
    "get_content_embedder",
    "TextChunker",
    "EmbeddingGenerator",
    "extract_main_content",
    "SourceTrustConfig",
    "SourceTrustService",
    "get_source_trust",
    "SectionEmbedder",
    "get_section_embedder",
    "NAPValidator",
    "NAPValidationResult",
    "get_nap_validator",
    "EntityMatcher",
    "MatchResult",
    "get_entity_matcher",
    "URLCanonicalizer",
    "CanonicalURL",
    "get_url_canonicalizer",
    "DomainQuarantine",
    "QuarantineReason",
    "QuarantineEntry",
    "BackoffSchedule",
    "get_domain_quarantine",
]

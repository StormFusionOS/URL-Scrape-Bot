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
- cwv_metrics: Core Web Vitals thresholds and scoring
- readability_analyzer: Text readability scoring (Flesch-Kincaid, etc.)
- volume_estimator: SERP-based search volume estimation
- difficulty_calculator: Keyword difficulty from competition analysis
- opportunity_analyzer: Keyword opportunity prioritization
- topic_clusterer: Semantic keyword grouping and content pillar generation
- content_gap_analyzer: Content opportunity detection vs competitors
- backlink_gap_analyzer: Backlink opportunity identification
- keyword_gap_analyzer: Competitor keyword gap analysis
- engagement_analyzer: Page engagement metrics and UX signals
- traffic_estimator: CTR-based organic traffic estimation
- ranking_trends: Position change tracking and alerts

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
from .browser_profile_manager import (
    BrowserProfileManager,
    get_browser_profile_manager
)
from .cwv_metrics import (
    CWVMetricsService,
    CWVRating,
    CWV_THRESHOLDS,
    get_cwv_metrics_service
)
from .readability_analyzer import (
    ReadabilityAnalyzer,
    ReadabilityResult,
    get_readability_analyzer
)
from .volume_estimator import (
    VolumeEstimator,
    VolumeEstimate,
    VolumeCategory,
    get_volume_estimator
)
from .difficulty_calculator import (
    DifficultyCalculator,
    DifficultyResult,
    DifficultyLevel,
    get_difficulty_calculator
)
from .opportunity_analyzer import (
    OpportunityAnalyzer,
    KeywordOpportunity,
    OpportunityTier,
    SearchIntent,
    get_opportunity_analyzer
)
from .topic_clusterer import (
    TopicClusterer,
    TopicCluster,
    get_topic_clusterer
)
from .content_gap_analyzer import (
    ContentGapAnalyzer,
    ContentGap,
    GapType,
    get_content_gap_analyzer
)
from .backlink_gap_analyzer import (
    BacklinkGapAnalyzer,
    BacklinkOpportunity,
    LinkType,
    get_backlink_gap_analyzer
)
from .keyword_gap_analyzer import (
    KeywordGapAnalyzer,
    KeywordGap,
    GapCategory,
    get_keyword_gap_analyzer
)
from .engagement_analyzer import (
    EngagementAnalyzer,
    EngagementResult,
    EngagementLevel,
    EngagementSignals,
    get_engagement_analyzer
)
from .traffic_estimator import (
    TrafficEstimator,
    KeywordTraffic,
    DomainTraffic,
    TrafficQuality,
    get_traffic_estimator
)
from .ranking_trends import (
    RankingTrends,
    TrendAnalysis,
    TrendDirection,
    RankingAlert,
    AlertType,
    DomainTrendSummary,
    get_ranking_trends
)
from .serp_priority_queue import (
    SerpPriorityQueue,
    QueuedCompany,
    Priority,
    get_serp_priority_queue
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
    "BrowserProfileManager",
    "get_browser_profile_manager",
    "CWVMetricsService",
    "CWVRating",
    "CWV_THRESHOLDS",
    "get_cwv_metrics_service",
    "ReadabilityAnalyzer",
    "ReadabilityResult",
    "get_readability_analyzer",
    "VolumeEstimator",
    "VolumeEstimate",
    "VolumeCategory",
    "get_volume_estimator",
    "DifficultyCalculator",
    "DifficultyResult",
    "DifficultyLevel",
    "get_difficulty_calculator",
    "OpportunityAnalyzer",
    "KeywordOpportunity",
    "OpportunityTier",
    "SearchIntent",
    "get_opportunity_analyzer",
    # Phase 3: Content & Competitive Analysis
    "TopicClusterer",
    "TopicCluster",
    "get_topic_clusterer",
    "ContentGapAnalyzer",
    "ContentGap",
    "GapType",
    "get_content_gap_analyzer",
    "BacklinkGapAnalyzer",
    "BacklinkOpportunity",
    "LinkType",
    "get_backlink_gap_analyzer",
    "KeywordGapAnalyzer",
    "KeywordGap",
    "GapCategory",
    "get_keyword_gap_analyzer",
    # Phase 4: Traffic & Trends
    "EngagementAnalyzer",
    "EngagementResult",
    "EngagementLevel",
    "EngagementSignals",
    "get_engagement_analyzer",
    "TrafficEstimator",
    "KeywordTraffic",
    "DomainTraffic",
    "TrafficQuality",
    "get_traffic_estimator",
    "RankingTrends",
    "TrendAnalysis",
    "TrendDirection",
    "RankingAlert",
    "AlertType",
    "DomainTrendSummary",
    "get_ranking_trends",
    # Phase 5: SERP Priority Queue
    "SerpPriorityQueue",
    "QueuedCompany",
    "Priority",
    "get_serp_priority_queue",
]

"""
Competitor Intelligence Services

Business logic and analytics for competitor tracking:
- Threat scoring
- Share of Voice calculation
- Service/pricing extraction
- Review aggregation
- Alert management
- Sentiment analysis
- Anomaly detection
- Content analysis
- Social tracking
- Price tracking
- Marketing monitoring
"""

from competitor_intel.services.service_extractor import (
    ServiceExtractor,
    extract_services_for_competitor,
)
from competitor_intel.services.review_aggregator import (
    ReviewAggregator,
    aggregate_reviews_for_competitor,
)
from competitor_intel.services.threat_scorer import (
    ThreatScorer,
    calculate_threat_for_competitor,
)
from competitor_intel.services.sov_calculator import (
    SOVCalculator,
    calculate_market_sov,
)
from competitor_intel.services.alert_manager import (
    AlertManager,
    check_competitor_alerts,
)
from competitor_intel.services.sentiment_analyzer import (
    SentimentAnalyzer,
    SentimentResult,
    analyze_review_sentiment,
)
from competitor_intel.services.review_anomaly_detector import (
    ReviewAnomalyDetector,
    ReviewAnomaly,
    AnomalyReport,
    detect_review_anomalies,
)
from competitor_intel.services.response_tracker import (
    ResponseTracker,
    ResponseMetrics,
    analyze_owner_responses,
)
from competitor_intel.services.content_analyzer import (
    ContentAnalyzer,
    ContentAnalysis,
    analyze_page_content,
)
from competitor_intel.services.blog_tracker import (
    BlogTracker,
    BlogPost,
    BlogAnalysis,
    discover_blog_posts,
)
from competitor_intel.services.social_tracker import (
    SocialTracker,
    SocialProfile,
    SocialDiscoveryResult,
    discover_social_profiles,
)
from competitor_intel.services.price_tracker import (
    PriceTracker,
    PriceSnapshot,
    PriceChange,
    PriceTrend,
    record_price_snapshot,
)
from competitor_intel.services.ad_detector import (
    AdDetector,
    DetectedAd,
    AdIntelligence,
    detect_competitor_ads,
)
from competitor_intel.services.marketing_monitor import (
    MarketingMonitor,
    MarketingSnapshot,
    MarketingAlert,
    ActivityLevel,
    analyze_marketing_activity,
)

__all__ = [
    # Original services
    'ServiceExtractor',
    'extract_services_for_competitor',
    'ReviewAggregator',
    'aggregate_reviews_for_competitor',
    'ThreatScorer',
    'calculate_threat_for_competitor',
    'SOVCalculator',
    'calculate_market_sov',
    'AlertManager',
    'check_competitor_alerts',
    # Sentiment analysis
    'SentimentAnalyzer',
    'SentimentResult',
    'analyze_review_sentiment',
    # Anomaly detection
    'ReviewAnomalyDetector',
    'ReviewAnomaly',
    'AnomalyReport',
    'detect_review_anomalies',
    # Response tracking
    'ResponseTracker',
    'ResponseMetrics',
    'analyze_owner_responses',
    # Content analysis
    'ContentAnalyzer',
    'ContentAnalysis',
    'analyze_page_content',
    # Blog tracking
    'BlogTracker',
    'BlogPost',
    'BlogAnalysis',
    'discover_blog_posts',
    # Social tracking
    'SocialTracker',
    'SocialProfile',
    'SocialDiscoveryResult',
    'discover_social_profiles',
    # Price tracking
    'PriceTracker',
    'PriceSnapshot',
    'PriceChange',
    'PriceTrend',
    'record_price_snapshot',
    # Ad detection
    'AdDetector',
    'DetectedAd',
    'AdIntelligence',
    'detect_competitor_ads',
    # Marketing monitoring
    'MarketingMonitor',
    'MarketingSnapshot',
    'MarketingAlert',
    'ActivityLevel',
    'analyze_marketing_activity',
]

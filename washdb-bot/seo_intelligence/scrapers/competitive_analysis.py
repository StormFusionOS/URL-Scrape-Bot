"""
Competitive Analysis Orchestrator

Integrates all competitive intelligence components:
- Topic clusterer for semantic keyword grouping
- Content gap analyzer for content opportunities
- Backlink gap analyzer for link building opportunities
- Keyword gap analyzer for ranking opportunities

Provides unified competitive research workflow without external APIs.

Usage:
    from seo_intelligence.scrapers.competitive_analysis import CompetitiveAnalysis

    ca = CompetitiveAnalysis()

    # Full competitive analysis
    analysis = ca.analyze_competitor(
        your_domain="yourdomain.com",
        competitor_domains=["competitor1.com", "competitor2.com"]
    )

    # Get prioritized action plan
    action_plan = ca.generate_action_plan(analysis)
"""

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from runner.logging_setup import get_logger
from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.scrapers.serp_scraper import SerpScraper, get_serp_scraper
from seo_intelligence.scrapers.backlink_crawler import BacklinkCrawler
from seo_intelligence.services import (
    get_topic_clusterer,
    get_content_gap_analyzer,
    get_backlink_gap_analyzer,
    get_keyword_gap_analyzer,
    TopicCluster,
    ContentGap,
    GapType,
    BacklinkOpportunity,
    KeywordGap,
    GapCategory,
)


@dataclass
class CompetitorProfile:
    """Profile of a competitor domain."""
    domain: str
    keywords: Dict[str, int] = field(default_factory=dict)  # keyword -> position
    backlinks: List[Dict[str, Any]] = field(default_factory=list)
    content_pages: List[Dict[str, Any]] = field(default_factory=list)
    estimated_traffic: int = 0
    top_keywords_count: int = 0  # Keywords in top 10


@dataclass
class CompetitiveAnalysisResult:
    """Complete competitive analysis result."""
    your_domain: str
    competitors: List[str]
    topic_clusters: List[TopicCluster]
    content_gaps: List[ContentGap]
    backlink_opportunities: List[BacklinkOpportunity]
    keyword_gaps: List[KeywordGap]
    competitor_profiles: Dict[str, CompetitorProfile]
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "your_domain": self.your_domain,
            "competitors": self.competitors,
            "summary": {
                "topic_clusters": len(self.topic_clusters),
                "content_gaps": len(self.content_gaps),
                "backlink_opportunities": len(self.backlink_opportunities),
                "keyword_gaps": len(self.keyword_gaps),
            },
            "topic_clusters": [
                {
                    "name": c.name,
                    "keywords": c.keywords[:10],
                    "size": len(c.keywords),
                    "primary_intent": c.primary_intent.value if c.primary_intent else None,
                    "authority_score": c.authority_score,
                }
                for c in self.topic_clusters[:10]
            ],
            "content_gaps": [
                {
                    "topic": g.topic,
                    "gap_type": g.gap_type.value,
                    "priority": g.priority,
                    "competitor_coverage": g.competitor_coverage,
                    "recommended_action": g.recommended_action,
                }
                for g in self.content_gaps[:15]
            ],
            "backlink_opportunities": [
                {
                    "domain": o.domain,
                    "url": o.url,
                    "estimated_da": o.estimated_da,
                    "link_type": o.link_type.value,
                    "priority": o.priority,
                    "outreach_likelihood": o.outreach_likelihood,
                }
                for o in self.backlink_opportunities[:20]
            ],
            "keyword_gaps": [
                {
                    "keyword": g.keyword,
                    "category": g.category.value,
                    "opportunity_score": g.opportunity_score,
                    "competitor_best_position": g.competitor_best_position,
                    "your_position": g.your_position,
                }
                for g in self.keyword_gaps[:20]
            ],
            "analyzed_at": self.analyzed_at.isoformat(),
        }

    def get_quick_wins(self) -> Dict[str, List[Any]]:
        """Get quick win opportunities from all categories."""
        return {
            "content": [g for g in self.content_gaps if g.priority >= 7][:5],
            "backlinks": [o for o in self.backlink_opportunities if o.priority >= 7][:5],
            "keywords": [g for g in self.keyword_gaps if g.opportunity_score >= 70][:5],
        }


class CompetitiveAnalysis(BaseScraper):
    """
    Unified competitive intelligence orchestrator.

    Combines all competitive analysis capabilities into a single interface.
    """

    def __init__(
        self,
        tier: str = "D",  # Conservative for scraping
    ):
        """
        Initialize competitive analysis.

        Args:
            tier: Rate limit tier
        """
        super().__init__(
            name="competitive_analysis",
            tier=tier,
            headless=True,
            respect_robots=True,
            use_proxy=False,
            max_retries=3,
            page_timeout=30000,
        )

        self.logger = get_logger("competitive_analysis")

        # Initialize components
        self.serp_scraper = get_serp_scraper()
        self.topic_clusterer = get_topic_clusterer()
        self.content_gap_analyzer = get_content_gap_analyzer()
        self.backlink_gap_analyzer = get_backlink_gap_analyzer()
        self.keyword_gap_analyzer = get_keyword_gap_analyzer()

        # Statistics
        self.ca_stats = {
            "competitors_analyzed": 0,
            "keywords_collected": 0,
            "backlinks_collected": 0,
            "content_gaps_found": 0,
            "backlink_opportunities_found": 0,
            "keyword_gaps_found": 0,
        }

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain name."""
        domain = domain.lower().strip()
        if domain.startswith("http"):
            parsed = urlparse(domain)
            domain = parsed.netloc
        domain = domain.replace("www.", "")
        return domain

    def _collect_competitor_keywords(
        self,
        domain: str,
        seed_keywords: List[str],
        max_keywords: int = 100,
    ) -> Dict[str, int]:
        """
        Collect keywords a competitor ranks for.

        Args:
            domain: Competitor domain
            seed_keywords: Keywords to check
            max_keywords: Maximum keywords to collect

        Returns:
            dict: keyword -> position mapping
        """
        keywords = {}
        domain = self._normalize_domain(domain)

        for keyword in seed_keywords[:max_keywords]:
            try:
                serp_result = self.serp_scraper.scrape_serp(keyword)
                if not serp_result:
                    continue

                organic_results = serp_result.get("organic_results", [])
                for i, result in enumerate(organic_results[:20], 1):
                    result_domain = self._normalize_domain(
                        result.get("domain", result.get("url", ""))
                    )
                    if domain in result_domain or result_domain in domain:
                        keywords[keyword] = i
                        break

            except Exception as e:
                self.logger.debug(f"Error checking '{keyword}': {e}")
                continue

        self.ca_stats["keywords_collected"] += len(keywords)
        return keywords

    def _build_competitor_profile(
        self,
        domain: str,
        keywords: Dict[str, int],
        backlinks: List[Dict[str, Any]] = None,
    ) -> CompetitorProfile:
        """
        Build a competitor profile.

        Args:
            domain: Competitor domain
            keywords: keyword -> position mapping
            backlinks: List of backlinks

        Returns:
            CompetitorProfile: Complete profile
        """
        top_keywords = sum(1 for pos in keywords.values() if pos <= 10)

        # Estimate traffic from keyword positions
        traffic = 0
        for keyword, pos in keywords.items():
            if pos <= 3:
                traffic += 1000
            elif pos <= 10:
                traffic += 200
            elif pos <= 20:
                traffic += 50

        return CompetitorProfile(
            domain=domain,
            keywords=keywords,
            backlinks=backlinks or [],
            estimated_traffic=traffic,
            top_keywords_count=top_keywords,
        )

    def analyze_competitors(
        self,
        your_domain: str,
        competitor_domains: List[str],
        seed_keywords: List[str],
        include_backlinks: bool = True,
        max_keywords: int = 100,
    ) -> CompetitiveAnalysisResult:
        """
        Perform comprehensive competitive analysis.

        Args:
            your_domain: Your domain
            competitor_domains: List of competitor domains
            seed_keywords: Keywords to analyze
            include_backlinks: Whether to analyze backlinks
            max_keywords: Maximum keywords per competitor

        Returns:
            CompetitiveAnalysisResult: Complete analysis
        """
        your_domain = self._normalize_domain(your_domain)
        competitor_domains = [self._normalize_domain(d) for d in competitor_domains]

        self.logger.info(
            f"Starting competitive analysis: {your_domain} vs "
            f"{len(competitor_domains)} competitors"
        )

        # 1. Collect your keyword rankings
        self.logger.info("Collecting your keyword rankings...")
        your_keywords = self._collect_competitor_keywords(
            your_domain, seed_keywords, max_keywords
        )

        # 2. Collect competitor keyword rankings
        competitor_profiles = {}
        all_competitor_keywords = {}

        for domain in competitor_domains:
            self.logger.info(f"Analyzing competitor: {domain}")

            comp_keywords = self._collect_competitor_keywords(
                domain, seed_keywords, max_keywords
            )

            all_competitor_keywords[domain] = comp_keywords

            competitor_profiles[domain] = self._build_competitor_profile(
                domain, comp_keywords
            )

            self.ca_stats["competitors_analyzed"] += 1

        # 3. Analyze keyword gaps
        self.logger.info("Analyzing keyword gaps...")
        keyword_gaps = self.keyword_gap_analyzer.analyze_keyword_gaps(
            your_keywords=your_keywords,
            competitor_keywords=all_competitor_keywords,
            min_coverage=1,
        )
        self.ca_stats["keyword_gaps_found"] = len(keyword_gaps)

        # 4. Cluster keywords into topics
        self.logger.info("Clustering keywords into topics...")
        all_keywords = set(your_keywords.keys())
        for comp_keywords in all_competitor_keywords.values():
            all_keywords.update(comp_keywords.keys())

        topic_clusters = self.topic_clusterer.cluster_keywords(
            list(all_keywords),
            min_cluster_size=2,
        )

        # 5. Analyze content gaps
        self.logger.info("Analyzing content gaps...")
        # Build content data from keyword rankings
        your_content = [
            {"url": your_domain, "topics": list(your_keywords.keys())}
        ]
        competitor_content = []
        for domain, keywords in all_competitor_keywords.items():
            competitor_content.append({
                "url": domain,
                "topics": list(keywords.keys()),
            })

        content_gaps = self.content_gap_analyzer.analyze_content_gaps(
            your_content=your_content,
            competitor_content=competitor_content,
            min_coverage=1,
        )
        self.ca_stats["content_gaps_found"] = len(content_gaps)

        # 6. Analyze backlink gaps (if enabled)
        backlink_opportunities = []
        if include_backlinks:
            self.logger.info("Analyzing backlink opportunities...")
            # Note: This would need actual backlink data from backlink_crawler
            # For now, we create placeholder analysis
            your_backlinks = []  # Would come from database/crawler
            competitor_backlinks = {}  # Would come from database/crawler

            if competitor_backlinks:
                backlink_opportunities = self.backlink_gap_analyzer.analyze_backlink_gaps(
                    your_backlinks=your_backlinks,
                    competitor_backlinks=competitor_backlinks,
                    min_coverage=1,
                )
                self.ca_stats["backlink_opportunities_found"] = len(backlink_opportunities)

        # 7. Build result
        result = CompetitiveAnalysisResult(
            your_domain=your_domain,
            competitors=competitor_domains,
            topic_clusters=topic_clusters,
            content_gaps=content_gaps,
            backlink_opportunities=backlink_opportunities,
            keyword_gaps=keyword_gaps,
            competitor_profiles=competitor_profiles,
        )

        self.logger.info(
            f"Competitive analysis complete: "
            f"{len(keyword_gaps)} keyword gaps, "
            f"{len(content_gaps)} content gaps, "
            f"{len(topic_clusters)} topic clusters"
        )

        return result

    def analyze_serp_competitors(
        self,
        your_domain: str,
        target_keywords: List[str],
        top_n: int = 5,
    ) -> CompetitiveAnalysisResult:
        """
        Automatically discover and analyze competitors from SERP.

        Args:
            your_domain: Your domain
            target_keywords: Keywords to check
            top_n: Number of top competitors to analyze

        Returns:
            CompetitiveAnalysisResult: Analysis of discovered competitors
        """
        your_domain = self._normalize_domain(your_domain)

        self.logger.info(
            f"Discovering competitors for {your_domain} from {len(target_keywords)} keywords"
        )

        # Discover competitors from SERP
        competitor_counts: Dict[str, int] = {}

        for keyword in target_keywords[:20]:  # Limit for speed
            try:
                serp_result = self.serp_scraper.scrape_serp(keyword)
                if not serp_result:
                    continue

                organic_results = serp_result.get("organic_results", [])
                for result in organic_results[:10]:
                    domain = self._normalize_domain(
                        result.get("domain", result.get("url", ""))
                    )

                    # Skip your own domain
                    if your_domain in domain or domain in your_domain:
                        continue

                    # Skip non-competitors (social media, etc.)
                    skip_domains = [
                        "facebook.com", "twitter.com", "instagram.com",
                        "youtube.com", "linkedin.com", "pinterest.com",
                        "wikipedia.org", "yelp.com", "bbb.org",
                    ]
                    if any(skip in domain for skip in skip_domains):
                        continue

                    competitor_counts[domain] = competitor_counts.get(domain, 0) + 1

            except Exception as e:
                self.logger.debug(f"Error checking '{keyword}': {e}")
                continue

        # Get top competitors by appearance count
        sorted_competitors = sorted(
            competitor_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        top_competitors = [domain for domain, _ in sorted_competitors[:top_n]]

        self.logger.info(f"Discovered competitors: {top_competitors}")

        # Run full analysis
        return self.analyze_competitors(
            your_domain=your_domain,
            competitor_domains=top_competitors,
            seed_keywords=target_keywords,
            include_backlinks=False,  # Skip for auto-discovery
        )

    def generate_action_plan(
        self,
        analysis: CompetitiveAnalysisResult,
        max_items: int = 20,
    ) -> Dict[str, Any]:
        """
        Generate prioritized action plan from analysis.

        Args:
            analysis: Competitive analysis result
            max_items: Maximum items per category

        Returns:
            dict: Prioritized action plan
        """
        quick_wins = analysis.get_quick_wins()

        # Content priorities
        content_plan = self.content_gap_analyzer.generate_content_plan(
            analysis.content_gaps, max_items=max_items
        )

        # Keyword priorities
        keyword_plan = self.keyword_gap_analyzer.generate_targeting_plan(
            analysis.keyword_gaps, max_items=max_items
        )

        # Backlink priorities
        backlink_plan = self.backlink_gap_analyzer.generate_outreach_plan(
            analysis.backlink_opportunities, max_items=max_items
        )

        # Generate topic pillars
        content_pillars = self.topic_clusterer.generate_content_pillars(
            analysis.topic_clusters
        )

        return {
            "summary": {
                "your_domain": analysis.your_domain,
                "competitors_analyzed": len(analysis.competitors),
                "total_opportunities": (
                    len(analysis.content_gaps) +
                    len(analysis.keyword_gaps) +
                    len(analysis.backlink_opportunities)
                ),
            },
            "quick_wins": {
                "content": [
                    {"topic": g.topic, "action": g.recommended_action}
                    for g in quick_wins.get("content", [])
                ],
                "keywords": [
                    {"keyword": g.keyword, "current_pos": g.your_position}
                    for g in quick_wins.get("keywords", [])
                ],
                "backlinks": [
                    {"domain": o.domain, "da": o.estimated_da}
                    for o in quick_wins.get("backlinks", [])
                ],
            },
            "content_strategy": {
                "pillars": content_pillars[:5],
                "gaps_to_fill": content_plan[:10],
            },
            "keyword_strategy": keyword_plan[:10],
            "link_building": backlink_plan[:10],
            "recommendations": [
                "Focus on quick wins first for immediate impact",
                "Build content around identified topic pillars",
                "Target missing keywords where competitors rank 4-10",
                "Pursue backlink opportunities with high outreach likelihood",
                "Monitor competitor content for new opportunities",
            ],
        }

    def compare_domains(
        self,
        domain_a: str,
        domain_b: str,
        seed_keywords: List[str],
    ) -> Dict[str, Any]:
        """
        Direct comparison between two domains.

        Args:
            domain_a: First domain
            domain_b: Second domain
            seed_keywords: Keywords to compare

        Returns:
            dict: Head-to-head comparison
        """
        domain_a = self._normalize_domain(domain_a)
        domain_b = self._normalize_domain(domain_b)

        self.logger.info(f"Comparing {domain_a} vs {domain_b}")

        # Get keyword rankings for both
        keywords_a = self._collect_competitor_keywords(domain_a, seed_keywords)
        keywords_b = self._collect_competitor_keywords(domain_b, seed_keywords)

        # Calculate metrics
        all_keywords = set(keywords_a.keys()) | set(keywords_b.keys())

        a_wins = 0
        b_wins = 0
        ties = 0
        a_only = 0
        b_only = 0

        keyword_comparison = []

        for kw in all_keywords:
            pos_a = keywords_a.get(kw)
            pos_b = keywords_b.get(kw)

            if pos_a and pos_b:
                if pos_a < pos_b:
                    a_wins += 1
                    winner = domain_a
                elif pos_b < pos_a:
                    b_wins += 1
                    winner = domain_b
                else:
                    ties += 1
                    winner = "tie"
            elif pos_a:
                a_only += 1
                winner = domain_a
            else:
                b_only += 1
                winner = domain_b

            keyword_comparison.append({
                "keyword": kw,
                f"{domain_a}_position": pos_a,
                f"{domain_b}_position": pos_b,
                "winner": winner,
            })

        # Sort by importance (lower combined position = more important)
        keyword_comparison.sort(
            key=lambda x: (x.get(f"{domain_a}_position") or 100) +
                          (x.get(f"{domain_b}_position") or 100)
        )

        return {
            "comparison": {
                "domain_a": domain_a,
                "domain_b": domain_b,
                "total_keywords": len(all_keywords),
            },
            "scores": {
                f"{domain_a}_wins": a_wins,
                f"{domain_b}_wins": b_wins,
                "ties": ties,
                f"{domain_a}_unique": a_only,
                f"{domain_b}_unique": b_only,
            },
            "winner": domain_a if (a_wins + a_only) > (b_wins + b_only) else domain_b,
            "keyword_breakdown": keyword_comparison[:30],
        }

    def run(
        self,
        your_domain: str,
        competitor_domains: Optional[List[str]] = None,
        seed_keywords: Optional[List[str]] = None,
        auto_discover: bool = False,
        save_to_db: bool = True,
    ) -> Dict[str, Any]:
        """
        Run full competitive analysis workflow.

        Args:
            your_domain: Your domain
            competitor_domains: Competitor domains (optional if auto_discover)
            seed_keywords: Keywords to analyze
            auto_discover: Auto-discover competitors from SERP
            save_to_db: Whether to save results

        Returns:
            dict: Complete analysis results
        """
        if not seed_keywords:
            self.logger.error("seed_keywords are required")
            return {"error": "seed_keywords are required"}

        # Auto-discover or use provided competitors
        if auto_discover or not competitor_domains:
            analysis = self.analyze_serp_competitors(
                your_domain=your_domain,
                target_keywords=seed_keywords,
                top_n=5,
            )
        else:
            analysis = self.analyze_competitors(
                your_domain=your_domain,
                competitor_domains=competitor_domains,
                seed_keywords=seed_keywords,
            )

        # Generate action plan
        action_plan = self.generate_action_plan(analysis)

        # Save to database if requested
        if save_to_db:
            self._save_analysis(analysis)

        return {
            "analysis": analysis.to_dict(),
            "action_plan": action_plan,
            "stats": self.ca_stats,
        }

    def _save_analysis(self, analysis: CompetitiveAnalysisResult):
        """Save analysis results to database."""
        # Save keyword gaps
        self.keyword_gap_analyzer.save_gaps(analysis.keyword_gaps)

        # Save content gaps
        self.content_gap_analyzer.save_gaps(analysis.content_gaps)

        # Save backlink opportunities
        self.backlink_gap_analyzer.save_opportunities(analysis.backlink_opportunities)

        # Save topic clusters
        self.topic_clusterer.save_clusters(analysis.topic_clusters)

        self.logger.info("Analysis results saved to database")

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics."""
        base_stats = super().get_stats()
        return {**base_stats, **self.ca_stats}


# Module-level singleton
_competitive_analysis_instance = None


def get_competitive_analysis() -> CompetitiveAnalysis:
    """Get or create the singleton CompetitiveAnalysis instance."""
    global _competitive_analysis_instance

    if _competitive_analysis_instance is None:
        _competitive_analysis_instance = CompetitiveAnalysis()

    return _competitive_analysis_instance

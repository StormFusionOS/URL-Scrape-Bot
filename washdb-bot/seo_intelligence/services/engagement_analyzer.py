"""
Engagement Analyzer Service

Analyzes user engagement signals from page interactions:
- Scroll depth tracking
- Time on page estimation
- Content engagement metrics
- UX quality indicators

No external APIs - uses Playwright for data collection.

Usage:
    from seo_intelligence.services.engagement_analyzer import get_engagement_analyzer

    analyzer = get_engagement_analyzer()

    # Analyze page engagement potential
    result = analyzer.analyze_page(url, page_content)

    # Compare engagement across pages
    comparison = analyzer.compare_pages(pages)
"""

import re
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from runner.logging_setup import get_logger
from db.database_manager import get_db_manager


class EngagementLevel(Enum):
    """Engagement quality level."""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    VERY_POOR = "very_poor"


class ContentType(Enum):
    """Type of content for engagement analysis."""
    ARTICLE = "article"
    PRODUCT = "product"
    SERVICE = "service"
    LANDING = "landing"
    BLOG = "blog"
    TOOL = "tool"
    UNKNOWN = "unknown"


@dataclass
class EngagementSignals:
    """Raw engagement signals from a page."""
    word_count: int = 0
    paragraph_count: int = 0
    heading_count: int = 0
    image_count: int = 0
    video_count: int = 0
    link_count: int = 0
    internal_links: int = 0
    external_links: int = 0
    form_count: int = 0
    cta_count: int = 0
    list_count: int = 0
    table_count: int = 0
    code_block_count: int = 0
    estimated_read_time: float = 0.0  # minutes
    scroll_depth_needed: float = 0.0  # percentage


@dataclass
class EngagementResult:
    """Complete engagement analysis result."""
    url: str
    engagement_score: float  # 0-100
    level: EngagementLevel
    content_type: ContentType
    signals: EngagementSignals
    estimated_time_on_page: float  # seconds
    bounce_risk: float  # 0-1 probability
    scroll_engagement: float  # 0-100
    content_depth: float  # 0-100
    interactivity: float  # 0-100
    recommendations: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "engagement_score": self.engagement_score,
            "level": self.level.value,
            "content_type": self.content_type.value,
            "signals": {
                "word_count": self.signals.word_count,
                "paragraph_count": self.signals.paragraph_count,
                "heading_count": self.signals.heading_count,
                "image_count": self.signals.image_count,
                "video_count": self.signals.video_count,
                "internal_links": self.signals.internal_links,
                "external_links": self.signals.external_links,
                "form_count": self.signals.form_count,
                "cta_count": self.signals.cta_count,
                "estimated_read_time": self.signals.estimated_read_time,
            },
            "estimated_time_on_page": self.estimated_time_on_page,
            "bounce_risk": self.bounce_risk,
            "scroll_engagement": self.scroll_engagement,
            "content_depth": self.content_depth,
            "interactivity": self.interactivity,
            "recommendations": self.recommendations,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


# Engagement scoring weights
ENGAGEMENT_WEIGHTS = {
    "content_depth": 0.30,
    "interactivity": 0.20,
    "visual_appeal": 0.15,
    "navigation": 0.15,
    "readability": 0.10,
    "freshness_signals": 0.10,
}

# Benchmarks for engagement
BENCHMARKS = {
    "min_word_count": 300,
    "optimal_word_count": 1500,
    "max_word_count": 3000,
    "min_paragraphs": 5,
    "optimal_paragraphs": 15,
    "min_headings": 3,
    "optimal_headings": 8,
    "min_images": 1,
    "optimal_images": 5,
    "optimal_read_time": 7.0,  # minutes (sweet spot)
    "max_read_time": 15.0,  # minutes
}

# CTA patterns
CTA_PATTERNS = [
    r'\b(?:buy|order|shop|purchase)\s+now\b',
    r'\b(?:get|start|begin|try)\s+(?:started|now|today|free)\b',
    r'\b(?:sign|log)\s+(?:up|in)\b',
    r'\bcontact\s+us\b',
    r'\bget\s+(?:a\s+)?quote\b',
    r'\brequest\s+(?:a\s+)?(?:demo|quote|consultation)\b',
    r'\bsubscribe\b',
    r'\bdownload\b',
    r'\blearn\s+more\b',
    r'\bfree\s+(?:trial|consultation|quote)\b',
    r'\bschedule\b',
    r'\bbook\s+(?:now|today|appointment)\b',
    r'\bclaim\s+(?:your|now)\b',
]


class EngagementAnalyzer:
    """
    Analyzes page engagement potential.

    Uses content structure and interactive elements to estimate
    user engagement metrics without external APIs.
    """

    def __init__(self):
        """Initialize the engagement analyzer."""
        self.logger = get_logger("engagement_analyzer")
        self.db = get_db_manager()

        # Compile CTA patterns
        self.cta_regex = re.compile(
            '|'.join(CTA_PATTERNS),
            re.IGNORECASE
        )

        self.logger.info("EngagementAnalyzer initialized")

    def _extract_signals(
        self,
        html_content: str,
        text_content: str,
    ) -> EngagementSignals:
        """
        Extract engagement signals from page content.

        Args:
            html_content: Raw HTML
            text_content: Extracted text

        Returns:
            EngagementSignals: Extracted signals
        """
        signals = EngagementSignals()

        # Word count
        words = text_content.split()
        signals.word_count = len(words)

        # Paragraph count
        paragraphs = re.findall(r'<p[^>]*>', html_content, re.IGNORECASE)
        signals.paragraph_count = len(paragraphs)

        # Heading count
        headings = re.findall(r'<h[1-6][^>]*>', html_content, re.IGNORECASE)
        signals.heading_count = len(headings)

        # Image count
        images = re.findall(r'<img[^>]*>', html_content, re.IGNORECASE)
        signals.image_count = len(images)

        # Video count
        videos = re.findall(
            r'<(?:video|iframe)[^>]*(?:youtube|vimeo|video)[^>]*>',
            html_content,
            re.IGNORECASE
        )
        signals.video_count = len(videos)

        # Link analysis
        all_links = re.findall(r'<a[^>]*href=["\']([^"\']*)["\']', html_content, re.IGNORECASE)
        signals.link_count = len(all_links)

        # Classify links
        for link in all_links:
            if link.startswith('#') or link.startswith('/') or not link.startswith('http'):
                signals.internal_links += 1
            else:
                signals.external_links += 1

        # Form count
        forms = re.findall(r'<form[^>]*>', html_content, re.IGNORECASE)
        signals.form_count = len(forms)

        # CTA count
        cta_matches = self.cta_regex.findall(text_content)
        signals.cta_count = len(cta_matches)

        # List count
        lists = re.findall(r'<(?:ul|ol)[^>]*>', html_content, re.IGNORECASE)
        signals.list_count = len(lists)

        # Table count
        tables = re.findall(r'<table[^>]*>', html_content, re.IGNORECASE)
        signals.table_count = len(tables)

        # Code block count
        code_blocks = re.findall(r'<(?:pre|code)[^>]*>', html_content, re.IGNORECASE)
        signals.code_block_count = len(code_blocks)

        # Estimated read time (average 200 words/minute)
        signals.estimated_read_time = signals.word_count / 200.0

        # Scroll depth needed (estimate based on content length)
        # Assume ~500 words per viewport
        viewports_needed = signals.word_count / 500.0
        signals.scroll_depth_needed = min(100, viewports_needed * 100 / max(1, viewports_needed))

        return signals

    def _detect_content_type(
        self,
        url: str,
        signals: EngagementSignals,
        text_content: str,
    ) -> ContentType:
        """
        Detect the type of content.

        Args:
            url: Page URL
            signals: Extracted signals
            text_content: Page text

        Returns:
            ContentType: Detected type
        """
        url_lower = url.lower()
        text_lower = text_content.lower()

        # URL-based detection
        if '/blog/' in url_lower or '/post/' in url_lower or '/article/' in url_lower:
            return ContentType.BLOG

        if '/product/' in url_lower or '/shop/' in url_lower:
            return ContentType.PRODUCT

        if '/service' in url_lower:
            return ContentType.SERVICE

        if '/tool' in url_lower or '/calculator' in url_lower:
            return ContentType.TOOL

        # Content-based detection
        if signals.form_count > 0 and signals.word_count < 500:
            return ContentType.LANDING

        if signals.word_count > 1000 and signals.heading_count >= 3:
            return ContentType.ARTICLE

        if 'price' in text_lower and ('buy' in text_lower or 'order' in text_lower):
            return ContentType.PRODUCT

        if signals.word_count > 500:
            return ContentType.BLOG

        return ContentType.UNKNOWN

    def _calculate_content_depth(self, signals: EngagementSignals) -> float:
        """
        Calculate content depth score (0-100).

        Args:
            signals: Engagement signals

        Returns:
            float: Content depth score
        """
        score = 0.0

        # Word count contribution (max 40 points)
        if signals.word_count >= BENCHMARKS["optimal_word_count"]:
            score += 40
        elif signals.word_count >= BENCHMARKS["min_word_count"]:
            ratio = (signals.word_count - BENCHMARKS["min_word_count"]) / \
                    (BENCHMARKS["optimal_word_count"] - BENCHMARKS["min_word_count"])
            score += 40 * ratio
        else:
            score += max(0, 20 * (signals.word_count / BENCHMARKS["min_word_count"]))

        # Heading structure (max 20 points)
        if signals.heading_count >= BENCHMARKS["optimal_headings"]:
            score += 20
        elif signals.heading_count >= BENCHMARKS["min_headings"]:
            ratio = (signals.heading_count - BENCHMARKS["min_headings"]) / \
                    (BENCHMARKS["optimal_headings"] - BENCHMARKS["min_headings"])
            score += 20 * ratio
        else:
            score += max(0, 10 * (signals.heading_count / BENCHMARKS["min_headings"]))

        # Paragraph structure (max 20 points)
        if signals.paragraph_count >= BENCHMARKS["optimal_paragraphs"]:
            score += 20
        elif signals.paragraph_count >= BENCHMARKS["min_paragraphs"]:
            ratio = (signals.paragraph_count - BENCHMARKS["min_paragraphs"]) / \
                    (BENCHMARKS["optimal_paragraphs"] - BENCHMARKS["min_paragraphs"])
            score += 20 * ratio

        # Supplementary content (max 20 points)
        if signals.list_count > 0:
            score += min(5, signals.list_count * 2)
        if signals.table_count > 0:
            score += min(5, signals.table_count * 2)
        if signals.code_block_count > 0:
            score += min(5, signals.code_block_count * 2)
        if signals.image_count > 0:
            score += min(5, signals.image_count)

        return min(100, score)

    def _calculate_interactivity(self, signals: EngagementSignals) -> float:
        """
        Calculate interactivity score (0-100).

        Args:
            signals: Engagement signals

        Returns:
            float: Interactivity score
        """
        score = 0.0

        # CTAs (max 30 points)
        if signals.cta_count >= 3:
            score += 30
        else:
            score += signals.cta_count * 10

        # Forms (max 25 points)
        if signals.form_count >= 1:
            score += min(25, signals.form_count * 15)

        # Videos (max 20 points)
        if signals.video_count >= 1:
            score += min(20, signals.video_count * 10)

        # Internal links (max 15 points) - navigation depth
        if signals.internal_links >= 5:
            score += 15
        else:
            score += signals.internal_links * 3

        # External links (max 10 points) - credibility
        if signals.external_links >= 3:
            score += 10
        else:
            score += signals.external_links * 3

        return min(100, score)

    def _calculate_visual_appeal(self, signals: EngagementSignals) -> float:
        """
        Calculate visual appeal score (0-100).

        Args:
            signals: Engagement signals

        Returns:
            float: Visual appeal score
        """
        score = 0.0

        # Images (max 50 points)
        if signals.image_count >= BENCHMARKS["optimal_images"]:
            score += 50
        elif signals.image_count >= BENCHMARKS["min_images"]:
            score += 20 + (signals.image_count * 6)
        elif signals.image_count > 0:
            score += signals.image_count * 10

        # Videos (max 30 points)
        if signals.video_count >= 1:
            score += min(30, signals.video_count * 15)

        # Formatting elements (max 20 points)
        formatting_score = 0
        if signals.list_count > 0:
            formatting_score += min(7, signals.list_count * 2)
        if signals.table_count > 0:
            formatting_score += min(7, signals.table_count * 3)
        if signals.heading_count >= 3:
            formatting_score += min(6, signals.heading_count)
        score += formatting_score

        return min(100, score)

    def _calculate_bounce_risk(
        self,
        signals: EngagementSignals,
        content_depth: float,
        interactivity: float,
    ) -> float:
        """
        Calculate bounce risk probability (0-1).

        Args:
            signals: Engagement signals
            content_depth: Content depth score
            interactivity: Interactivity score

        Returns:
            float: Bounce risk probability
        """
        risk = 0.5  # Start at baseline

        # Thin content increases bounce risk
        if signals.word_count < BENCHMARKS["min_word_count"]:
            risk += 0.2

        # No CTAs increases bounce risk
        if signals.cta_count == 0:
            risk += 0.1

        # No images increases bounce risk
        if signals.image_count == 0:
            risk += 0.1

        # Very long content can increase bounce risk
        if signals.estimated_read_time > BENCHMARKS["max_read_time"]:
            risk += 0.1

        # Good content depth decreases risk
        if content_depth > 70:
            risk -= 0.2
        elif content_depth > 50:
            risk -= 0.1

        # Good interactivity decreases risk
        if interactivity > 60:
            risk -= 0.15
        elif interactivity > 40:
            risk -= 0.1

        # Videos significantly decrease bounce risk
        if signals.video_count > 0:
            risk -= 0.15

        return max(0.1, min(0.9, risk))

    def _estimate_time_on_page(
        self,
        signals: EngagementSignals,
        bounce_risk: float,
    ) -> float:
        """
        Estimate average time on page in seconds.

        Args:
            signals: Engagement signals
            bounce_risk: Bounce probability

        Returns:
            float: Estimated time in seconds
        """
        # Base time from read time
        read_time_seconds = signals.estimated_read_time * 60

        # Adjust for actual engagement (not everyone reads everything)
        engagement_factor = 1 - (bounce_risk * 0.5)

        # Account for videos
        video_time = signals.video_count * 60  # Assume 1 min average watch

        # Account for forms
        form_time = signals.form_count * 30  # 30 seconds per form interaction

        # Calculate total
        base_time = (read_time_seconds * 0.6 + video_time + form_time) * engagement_factor

        # Apply reasonable bounds
        return max(10, min(600, base_time))  # 10 seconds to 10 minutes

    def _generate_recommendations(
        self,
        signals: EngagementSignals,
        content_depth: float,
        interactivity: float,
        visual_appeal: float,
    ) -> List[str]:
        """
        Generate engagement improvement recommendations.

        Args:
            signals: Engagement signals
            content_depth: Content depth score
            interactivity: Interactivity score
            visual_appeal: Visual appeal score

        Returns:
            list: Recommendations
        """
        recommendations = []

        # Content depth recommendations
        if signals.word_count < BENCHMARKS["min_word_count"]:
            recommendations.append(
                f"Add more content - current {signals.word_count} words, "
                f"aim for at least {BENCHMARKS['min_word_count']}"
            )

        if signals.heading_count < BENCHMARKS["min_headings"]:
            recommendations.append(
                f"Add more headings to improve scannability "
                f"(current: {signals.heading_count}, recommended: {BENCHMARKS['min_headings']}+)"
            )

        if signals.paragraph_count < BENCHMARKS["min_paragraphs"]:
            recommendations.append(
                "Break content into more paragraphs for better readability"
            )

        # Visual recommendations
        if signals.image_count == 0:
            recommendations.append(
                "Add at least one relevant image to increase engagement"
            )
        elif signals.image_count < BENCHMARKS["optimal_images"]:
            recommendations.append(
                f"Consider adding more images (current: {signals.image_count}, "
                f"optimal: {BENCHMARKS['optimal_images']})"
            )

        if signals.video_count == 0 and content_depth > 50:
            recommendations.append(
                "Consider adding a video to significantly boost engagement"
            )

        # Interactivity recommendations
        if signals.cta_count == 0:
            recommendations.append(
                "Add clear call-to-action buttons to guide user actions"
            )

        if signals.form_count == 0 and signals.cta_count > 0:
            recommendations.append(
                "Consider adding a form for lead capture or user interaction"
            )

        if signals.internal_links < 3:
            recommendations.append(
                "Add internal links to related content to reduce bounce rate"
            )

        # Formatting recommendations
        if signals.list_count == 0 and signals.word_count > 500:
            recommendations.append(
                "Use bullet points or numbered lists to improve scannability"
            )

        # Read time recommendations
        if signals.estimated_read_time > BENCHMARKS["max_read_time"]:
            recommendations.append(
                f"Content is very long ({signals.estimated_read_time:.1f} min read). "
                "Consider breaking into multiple pages or adding a table of contents"
            )

        return recommendations[:5]  # Limit to top 5

    def _determine_level(self, score: float) -> EngagementLevel:
        """
        Determine engagement level from score.

        Args:
            score: Engagement score (0-100)

        Returns:
            EngagementLevel: Quality level
        """
        if score >= 80:
            return EngagementLevel.EXCELLENT
        elif score >= 65:
            return EngagementLevel.GOOD
        elif score >= 45:
            return EngagementLevel.AVERAGE
        elif score >= 25:
            return EngagementLevel.POOR
        else:
            return EngagementLevel.VERY_POOR

    def analyze_page(
        self,
        url: str,
        html_content: str,
        text_content: str,
    ) -> EngagementResult:
        """
        Analyze engagement potential of a page.

        Args:
            url: Page URL
            html_content: Raw HTML content
            text_content: Extracted text content

        Returns:
            EngagementResult: Complete analysis
        """
        self.logger.info(f"Analyzing engagement for: {url}")

        # Extract signals
        signals = self._extract_signals(html_content, text_content)

        # Detect content type
        content_type = self._detect_content_type(url, signals, text_content)

        # Calculate component scores
        content_depth = self._calculate_content_depth(signals)
        interactivity = self._calculate_interactivity(signals)
        visual_appeal = self._calculate_visual_appeal(signals)

        # Calculate navigation score (based on internal links)
        navigation = min(100, signals.internal_links * 10)

        # Estimate readability from structure
        readability = 50  # Baseline
        if signals.paragraph_count >= 5:
            readability += 20
        if signals.heading_count >= 3:
            readability += 15
        if signals.list_count > 0:
            readability += 15
        readability = min(100, readability)

        # Freshness signals (limited without metadata)
        freshness = 50  # Baseline

        # Calculate overall score
        engagement_score = (
            content_depth * ENGAGEMENT_WEIGHTS["content_depth"] +
            interactivity * ENGAGEMENT_WEIGHTS["interactivity"] +
            visual_appeal * ENGAGEMENT_WEIGHTS["visual_appeal"] +
            navigation * ENGAGEMENT_WEIGHTS["navigation"] +
            readability * ENGAGEMENT_WEIGHTS["readability"] +
            freshness * ENGAGEMENT_WEIGHTS["freshness_signals"]
        )

        # Calculate bounce risk
        bounce_risk = self._calculate_bounce_risk(
            signals, content_depth, interactivity
        )

        # Estimate time on page
        time_on_page = self._estimate_time_on_page(signals, bounce_risk)

        # Calculate scroll engagement
        scroll_engagement = min(100, content_depth * 0.7 + visual_appeal * 0.3)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            signals, content_depth, interactivity, visual_appeal
        )

        # Determine level
        level = self._determine_level(engagement_score)

        result = EngagementResult(
            url=url,
            engagement_score=round(engagement_score, 1),
            level=level,
            content_type=content_type,
            signals=signals,
            estimated_time_on_page=round(time_on_page, 1),
            bounce_risk=round(bounce_risk, 2),
            scroll_engagement=round(scroll_engagement, 1),
            content_depth=round(content_depth, 1),
            interactivity=round(interactivity, 1),
            recommendations=recommendations,
        )

        self.logger.info(
            f"Engagement analysis complete: score={engagement_score:.1f}, "
            f"level={level.value}, bounce_risk={bounce_risk:.2f}"
        )

        return result

    def compare_pages(
        self,
        pages: List[Tuple[str, str, str]],  # (url, html, text)
    ) -> Dict[str, Any]:
        """
        Compare engagement across multiple pages.

        Args:
            pages: List of (url, html_content, text_content) tuples

        Returns:
            dict: Comparison results
        """
        results = []
        for url, html, text in pages:
            result = self.analyze_page(url, html, text)
            results.append(result)

        # Sort by engagement score
        results.sort(key=lambda x: x.engagement_score, reverse=True)

        # Calculate averages
        avg_score = sum(r.engagement_score for r in results) / len(results)
        avg_bounce = sum(r.bounce_risk for r in results) / len(results)
        avg_time = sum(r.estimated_time_on_page for r in results) / len(results)

        return {
            "summary": {
                "pages_analyzed": len(results),
                "average_engagement": round(avg_score, 1),
                "average_bounce_risk": round(avg_bounce, 2),
                "average_time_on_page": round(avg_time, 1),
            },
            "rankings": [
                {
                    "rank": i + 1,
                    "url": r.url,
                    "score": r.engagement_score,
                    "level": r.level.value,
                }
                for i, r in enumerate(results)
            ],
            "best_performer": results[0].to_dict() if results else None,
            "worst_performer": results[-1].to_dict() if results else None,
            "improvement_priorities": self._identify_priorities(results),
        }

    def _identify_priorities(
        self,
        results: List[EngagementResult],
    ) -> List[Dict[str, Any]]:
        """
        Identify improvement priorities across pages.

        Args:
            results: List of engagement results

        Returns:
            list: Priority improvements
        """
        priorities = []

        # Find pages with high improvement potential
        for result in results:
            if result.level in (EngagementLevel.POOR, EngagementLevel.VERY_POOR):
                priorities.append({
                    "url": result.url,
                    "current_score": result.engagement_score,
                    "priority": "high",
                    "recommendations": result.recommendations[:3],
                })
            elif result.level == EngagementLevel.AVERAGE:
                priorities.append({
                    "url": result.url,
                    "current_score": result.engagement_score,
                    "priority": "medium",
                    "recommendations": result.recommendations[:2],
                })

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        priorities.sort(key=lambda x: (priority_order[x["priority"]], -x["current_score"]))

        return priorities[:10]

    def save_result(
        self,
        result: EngagementResult,
        competitor_id: Optional[int] = None,
    ):
        """
        Save engagement result to database.

        Args:
            result: Engagement analysis result
            competitor_id: Optional competitor association
        """
        try:
            conn = self.db.engine.connect()

            query = """
                INSERT INTO page_engagement_metrics (
                    url, competitor_id, engagement_score, engagement_level,
                    content_type, word_count, estimated_read_time,
                    bounce_risk, time_on_page, scroll_engagement,
                    content_depth, interactivity, image_count, video_count,
                    cta_count, form_count, analyzed_at
                ) VALUES (
                    %(url)s, %(competitor_id)s, %(engagement_score)s,
                    %(engagement_level)s, %(content_type)s, %(word_count)s,
                    %(estimated_read_time)s, %(bounce_risk)s, %(time_on_page)s,
                    %(scroll_engagement)s, %(content_depth)s, %(interactivity)s,
                    %(image_count)s, %(video_count)s, %(cta_count)s,
                    %(form_count)s, %(analyzed_at)s
                )
                ON CONFLICT (url) DO UPDATE SET
                    engagement_score = EXCLUDED.engagement_score,
                    engagement_level = EXCLUDED.engagement_level,
                    word_count = EXCLUDED.word_count,
                    bounce_risk = EXCLUDED.bounce_risk,
                    time_on_page = EXCLUDED.time_on_page,
                    analyzed_at = EXCLUDED.analyzed_at
            """

            conn.execute(query, {
                "url": result.url,
                "competitor_id": competitor_id,
                "engagement_score": result.engagement_score,
                "engagement_level": result.level.value,
                "content_type": result.content_type.value,
                "word_count": result.signals.word_count,
                "estimated_read_time": result.signals.estimated_read_time,
                "bounce_risk": result.bounce_risk,
                "time_on_page": result.estimated_time_on_page,
                "scroll_engagement": result.scroll_engagement,
                "content_depth": result.content_depth,
                "interactivity": result.interactivity,
                "image_count": result.signals.image_count,
                "video_count": result.signals.video_count,
                "cta_count": result.signals.cta_count,
                "form_count": result.signals.form_count,
                "analyzed_at": result.analyzed_at,
            })

            conn.close()
            self.logger.debug(f"Saved engagement result for {result.url}")

        except Exception as e:
            self.logger.warning(f"Failed to save engagement result: {e}")


# Module-level singleton
_engagement_analyzer_instance = None


def get_engagement_analyzer() -> EngagementAnalyzer:
    """Get or create the singleton EngagementAnalyzer instance."""
    global _engagement_analyzer_instance

    if _engagement_analyzer_instance is None:
        _engagement_analyzer_instance = EngagementAnalyzer()

    return _engagement_analyzer_instance

"""
Content Gap Analyzer Service

Identifies content opportunities by comparing your content with competitors.
Analyzes topic coverage, content depth, and missing keywords.

Analysis Methods:
- Topic coverage comparison
- Keyword presence analysis
- Content depth scoring
- Missing topic identification
- Content freshness comparison

Usage:
    from seo_intelligence.services.content_gap_analyzer import ContentGapAnalyzer

    analyzer = ContentGapAnalyzer()
    gaps = analyzer.analyze_content_gaps(
        your_content=your_pages,
        competitor_content=competitor_pages
    )

Results stored in content_analysis database table.
"""

import re
import json
from collections import Counter, defaultdict
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runner.logging_setup import get_logger


class GapType(Enum):
    """Types of content gaps."""
    MISSING_TOPIC = "MISSING_TOPIC"         # Topic not covered at all
    SHALLOW_COVERAGE = "SHALLOW_COVERAGE"   # Topic covered but shallow
    OUTDATED_CONTENT = "OUTDATED_CONTENT"   # Content needs updating
    MISSING_FORMAT = "MISSING_FORMAT"       # Missing content format (FAQ, video, etc.)
    KEYWORD_GAP = "KEYWORD_GAP"             # Missing keyword variations


class GapPriority(Enum):
    """Content gap priority levels."""
    CRITICAL = "CRITICAL"     # Major competitive disadvantage
    HIGH = "HIGH"             # Important opportunity
    MEDIUM = "MEDIUM"         # Worth addressing
    LOW = "LOW"               # Nice to have


@dataclass
class ContentGap:
    """Represents a content gap opportunity."""
    gap_id: str
    gap_type: GapType
    priority: GapPriority
    topic: str
    description: str
    competitor_coverage: int  # Number of competitors covering this
    your_coverage: int  # Your coverage depth (0-100)
    opportunity_score: float  # 0-100
    keywords: List[str] = field(default_factory=list)
    competitors_with_content: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    identified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "gap_id": self.gap_id,
            "type": self.gap_type.value,
            "priority": self.priority.value,
            "topic": self.topic,
            "description": self.description,
            "competitor_coverage": self.competitor_coverage,
            "your_coverage": self.your_coverage,
            "opportunity_score": self.opportunity_score,
            "keywords": self.keywords[:10],
            "recommendations": self.recommendations,
        }


@dataclass
class ContentPage:
    """Represents a content page for analysis."""
    url: str
    title: str
    content: str  # Main text content
    word_count: int
    headings: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    published_date: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContentGapAnalyzer:
    """
    Analyzes content gaps between your site and competitors.

    Identifies topics, keywords, and formats you're missing.
    """

    # Stop words for topic extraction
    STOP_WORDS = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "it", "its", "this", "that", "these", "those", "i", "you", "he", "she",
        "we", "they", "what", "which", "who", "whom", "all", "each", "every",
        "no", "not", "only", "own", "same", "so", "than", "too", "very",
        "can", "will", "just", "don", "should", "now", "your", "our", "my",
        "their", "his", "her", "have", "has", "had", "do", "does", "did",
    }

    # Content format indicators
    FORMAT_INDICATORS = {
        "faq": ["faq", "frequently asked", "questions and answers", "q&a"],
        "how_to": ["how to", "step by step", "guide", "tutorial", "steps to"],
        "listicle": ["top 10", "top 5", "best", "list of", "ways to"],
        "comparison": ["vs", "versus", "comparison", "compare", "difference"],
        "review": ["review", "reviewed", "rating", "pros and cons"],
        "case_study": ["case study", "success story", "example", "real-world"],
    }

    def __init__(self):
        """Initialize content gap analyzer."""
        self.logger = get_logger("content_gap_analyzer")

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into words.

        Args:
            text: Text to tokenize

        Returns:
            list: Words
        """
        words = re.findall(r'\b[a-z]+\b', text.lower())
        return [w for w in words if w not in self.STOP_WORDS and len(w) > 2]

    def _extract_topics(self, content: str, n_topics: int = 20) -> List[str]:
        """
        Extract main topics from content using TF analysis.

        Args:
            content: Text content
            n_topics: Number of topics to extract

        Returns:
            list: Top topics
        """
        words = self._tokenize(content)

        # Get word frequencies
        word_counts = Counter(words)

        # Also extract 2-grams
        bigrams = []
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            bigrams.append(bigram)

        bigram_counts = Counter(bigrams)

        # Combine with bigrams weighted higher
        all_topics = []

        for word, count in word_counts.most_common(n_topics * 2):
            all_topics.append((word, count))

        for bigram, count in bigram_counts.most_common(n_topics):
            all_topics.append((bigram, count * 1.5))  # Boost bigrams

        # Sort by score and deduplicate
        all_topics.sort(key=lambda x: x[1], reverse=True)

        seen = set()
        topics = []
        for topic, _ in all_topics:
            if topic not in seen:
                # Don't add bigram if both words already in list
                words_in_topic = set(topic.split())
                if not words_in_topic.issubset(seen):
                    topics.append(topic)
                    seen.update(words_in_topic)
                    seen.add(topic)

            if len(topics) >= n_topics:
                break

        return topics

    def _extract_headings(self, content: str) -> List[str]:
        """
        Extract headings from content (H1-H6 patterns).

        Args:
            content: HTML or text content

        Returns:
            list: Heading texts
        """
        headings = []

        # Look for markdown-style headings
        md_headings = re.findall(r'^#{1,6}\s+(.+)$', content, re.MULTILINE)
        headings.extend(md_headings)

        # Look for HTML headings
        html_headings = re.findall(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', content, re.IGNORECASE)
        headings.extend(html_headings)

        # Look for title-case lines that might be headings
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if (10 < len(line) < 100 and
                line[0].isupper() and
                not line.endswith('.') and
                line.count(' ') < 10):
                # Might be a heading
                if not any(h.lower() == line.lower() for h in headings):
                    headings.append(line)

        return headings[:30]  # Limit to top 30

    def _detect_content_formats(self, content: str) -> List[str]:
        """
        Detect content formats present in the content.

        Args:
            content: Text content

        Returns:
            list: Detected formats
        """
        content_lower = content.lower()
        detected_formats = []

        for format_type, indicators in self.FORMAT_INDICATORS.items():
            for indicator in indicators:
                if indicator in content_lower:
                    detected_formats.append(format_type)
                    break

        return detected_formats

    def _calculate_topic_coverage(
        self,
        topics: List[str],
        content: str,
    ) -> Dict[str, float]:
        """
        Calculate how well topics are covered in content.

        Args:
            topics: Topics to check
            content: Content to analyze

        Returns:
            dict: Topic -> coverage score (0-100)
        """
        content_lower = content.lower()
        coverage = {}

        for topic in topics:
            topic_lower = topic.lower()

            # Count occurrences
            count = content_lower.count(topic_lower)

            # Check in headings (weighted higher)
            headings = self._extract_headings(content)
            heading_mentions = sum(
                1 for h in headings if topic_lower in h.lower()
            )

            # Calculate coverage score
            # More mentions and heading presence = higher coverage
            base_score = min(100, count * 10)  # Cap at 100
            heading_bonus = heading_mentions * 20

            coverage[topic] = min(100, base_score + heading_bonus)

        return coverage

    def _identify_missing_topics(
        self,
        your_topics: Set[str],
        competitor_topics: Dict[str, Set[str]],
    ) -> List[Tuple[str, int]]:
        """
        Find topics covered by competitors but not by you.

        Args:
            your_topics: Your covered topics
            competitor_topics: Dict of competitor -> topics

        Returns:
            list: (topic, competitor_count) tuples
        """
        # Count how many competitors cover each topic
        topic_counts = Counter()

        for competitor, topics in competitor_topics.items():
            for topic in topics:
                topic_counts[topic] += 1

        # Find topics you don't cover
        missing = []
        for topic, count in topic_counts.most_common():
            if topic not in your_topics:
                missing.append((topic, count))

        return missing

    def analyze_page(self, url: str, title: str, content: str) -> ContentPage:
        """
        Analyze a single page for content attributes.

        Args:
            url: Page URL
            title: Page title
            content: Page content

        Returns:
            ContentPage: Analyzed page
        """
        topics = self._extract_topics(content)
        headings = self._extract_headings(content)
        keywords = self._tokenize(content)[:50]

        return ContentPage(
            url=url,
            title=title,
            content=content,
            word_count=len(content.split()),
            headings=headings,
            keywords=keywords,
            topics=topics,
        )

    def analyze_content_gaps(
        self,
        your_content: List[ContentPage],
        competitor_content: Dict[str, List[ContentPage]],
        min_competitor_coverage: int = 2,
    ) -> List[ContentGap]:
        """
        Analyze content gaps between you and competitors.

        Args:
            your_content: Your content pages
            competitor_content: Dict of competitor name -> pages
            min_competitor_coverage: Minimum competitors needed to flag gap

        Returns:
            list: ContentGap opportunities
        """
        self.logger.info(
            f"Analyzing gaps: {len(your_content)} your pages vs "
            f"{len(competitor_content)} competitors"
        )

        gaps = []
        gap_num = 0

        # Collect your topics
        your_topics = set()
        your_formats = set()
        your_coverage = defaultdict(float)

        for page in your_content:
            your_topics.update(page.topics)
            your_formats.update(self._detect_content_formats(page.content))
            for topic in page.topics:
                coverage = self._calculate_topic_coverage([topic], page.content)
                your_coverage[topic] = max(your_coverage[topic], coverage.get(topic, 0))

        # Collect competitor topics
        competitor_topics = {}
        competitor_formats = {}
        all_competitor_topics = Counter()

        for comp_name, pages in competitor_content.items():
            comp_topics = set()
            comp_formats = set()

            for page in pages:
                comp_topics.update(page.topics)
                comp_formats.update(self._detect_content_formats(page.content))

            competitor_topics[comp_name] = comp_topics
            competitor_formats[comp_name] = comp_formats

            for topic in comp_topics:
                all_competitor_topics[topic] += 1

        # Find missing topics
        for topic, comp_count in all_competitor_topics.most_common():
            if comp_count < min_competitor_coverage:
                continue

            if topic not in your_topics:
                gap_num += 1

                # Identify which competitors have this topic
                comps_with_topic = [
                    comp for comp, topics in competitor_topics.items()
                    if topic in topics
                ]

                # Calculate opportunity score
                # More competitors + you don't have it = higher opportunity
                opportunity = min(100, comp_count * 25)

                # Determine priority
                if comp_count >= 4:
                    priority = GapPriority.CRITICAL
                elif comp_count >= 3:
                    priority = GapPriority.HIGH
                elif comp_count >= 2:
                    priority = GapPriority.MEDIUM
                else:
                    priority = GapPriority.LOW

                gap = ContentGap(
                    gap_id=f"gap_{gap_num}",
                    gap_type=GapType.MISSING_TOPIC,
                    priority=priority,
                    topic=topic,
                    description=f"Topic '{topic}' covered by {comp_count} competitors but missing from your site",
                    competitor_coverage=comp_count,
                    your_coverage=0,
                    opportunity_score=opportunity,
                    keywords=[topic],
                    competitors_with_content=comps_with_topic,
                    recommendations=[
                        f"Create comprehensive content about '{topic}'",
                        f"Analyze competitor content for structure ideas",
                        f"Target related long-tail keywords",
                    ],
                )
                gaps.append(gap)

            elif your_coverage[topic] < 50:
                # Shallow coverage gap
                gap_num += 1

                comps_with_topic = [
                    comp for comp, topics in competitor_topics.items()
                    if topic in topics
                ]

                opportunity = min(100, (100 - your_coverage[topic]) * 0.5 + comp_count * 15)

                gap = ContentGap(
                    gap_id=f"gap_{gap_num}",
                    gap_type=GapType.SHALLOW_COVERAGE,
                    priority=GapPriority.MEDIUM,
                    topic=topic,
                    description=f"Topic '{topic}' has shallow coverage ({your_coverage[topic]:.0f}%) vs {comp_count} competitors",
                    competitor_coverage=comp_count,
                    your_coverage=int(your_coverage[topic]),
                    opportunity_score=opportunity,
                    keywords=[topic],
                    competitors_with_content=comps_with_topic,
                    recommendations=[
                        f"Expand content depth for '{topic}'",
                        f"Add more detailed sections and examples",
                        f"Include FAQ section if missing",
                    ],
                )
                gaps.append(gap)

        # Check for missing content formats
        all_competitor_formats = set()
        for formats in competitor_formats.values():
            all_competitor_formats.update(formats)

        for format_type in all_competitor_formats:
            if format_type not in your_formats:
                format_count = sum(
                    1 for f in competitor_formats.values() if format_type in f
                )

                if format_count >= min_competitor_coverage:
                    gap_num += 1

                    gap = ContentGap(
                        gap_id=f"gap_{gap_num}",
                        gap_type=GapType.MISSING_FORMAT,
                        priority=GapPriority.MEDIUM,
                        topic=format_type,
                        description=f"Content format '{format_type}' used by {format_count} competitors but missing from your site",
                        competitor_coverage=format_count,
                        your_coverage=0,
                        opportunity_score=min(100, format_count * 20),
                        keywords=[],
                        competitors_with_content=[
                            comp for comp, f in competitor_formats.items()
                            if format_type in f
                        ],
                        recommendations=[
                            f"Create {format_type.replace('_', ' ')} content",
                            f"This format may improve user engagement",
                        ],
                    )
                    gaps.append(gap)

        # Sort by opportunity score
        gaps.sort(key=lambda x: x.opportunity_score, reverse=True)

        self.logger.info(f"Found {len(gaps)} content gaps")

        return gaps

    def analyze_topic_depth(
        self,
        your_page: ContentPage,
        competitor_pages: List[ContentPage],
    ) -> Dict[str, Any]:
        """
        Compare depth of topic coverage for a specific page.

        Args:
            your_page: Your page to analyze
            competitor_pages: Competitor pages on same topic

        Returns:
            dict: Depth analysis with recommendations
        """
        your_word_count = your_page.word_count
        your_heading_count = len(your_page.headings)
        your_topic_count = len(your_page.topics)

        comp_word_counts = [p.word_count for p in competitor_pages]
        comp_heading_counts = [len(p.headings) for p in competitor_pages]
        comp_topic_counts = [len(p.topics) for p in competitor_pages]

        avg_comp_words = sum(comp_word_counts) / len(comp_word_counts) if comp_word_counts else 0
        avg_comp_headings = sum(comp_heading_counts) / len(comp_heading_counts) if comp_heading_counts else 0
        avg_comp_topics = sum(comp_topic_counts) / len(comp_topic_counts) if comp_topic_counts else 0

        recommendations = []

        if your_word_count < avg_comp_words * 0.8:
            recommendations.append(
                f"Consider expanding content (you: {your_word_count} words, "
                f"competitors avg: {int(avg_comp_words)} words)"
            )

        if your_heading_count < avg_comp_headings * 0.8:
            recommendations.append(
                f"Add more sections/headings (you: {your_heading_count}, "
                f"competitors avg: {int(avg_comp_headings)})"
            )

        if your_topic_count < avg_comp_topics * 0.8:
            recommendations.append(
                f"Cover more subtopics (you: {your_topic_count}, "
                f"competitors avg: {int(avg_comp_topics)})"
            )

        # Identify missing subtopics
        your_topic_set = set(your_page.topics)
        competitor_topic_counts = Counter()

        for page in competitor_pages:
            for topic in page.topics:
                competitor_topic_counts[topic] += 1

        missing_topics = [
            topic for topic, count in competitor_topic_counts.most_common(10)
            if topic not in your_topic_set and count >= 2
        ]

        if missing_topics:
            recommendations.append(
                f"Consider adding sections on: {', '.join(missing_topics[:5])}"
            )

        return {
            "your_metrics": {
                "word_count": your_word_count,
                "heading_count": your_heading_count,
                "topic_count": your_topic_count,
            },
            "competitor_avg": {
                "word_count": int(avg_comp_words),
                "heading_count": int(avg_comp_headings),
                "topic_count": int(avg_comp_topics),
            },
            "missing_topics": missing_topics,
            "recommendations": recommendations,
            "depth_score": min(100, (
                (your_word_count / max(1, avg_comp_words)) * 40 +
                (your_heading_count / max(1, avg_comp_headings)) * 30 +
                (your_topic_count / max(1, avg_comp_topics)) * 30
            )),
        }

    def generate_content_plan(
        self,
        gaps: List[ContentGap],
        max_items: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Generate content creation plan from gaps.

        Args:
            gaps: Content gaps to address
            max_items: Maximum plan items

        Returns:
            list: Content plan items
        """
        plan = []

        for gap in gaps[:max_items]:
            item = {
                "priority": gap.priority.value,
                "gap_type": gap.gap_type.value,
                "topic": gap.topic,
                "target_keywords": gap.keywords[:5],
                "opportunity_score": gap.opportunity_score,
                "action": "",
                "content_outline": [],
            }

            # Generate action based on gap type
            if gap.gap_type == GapType.MISSING_TOPIC:
                item["action"] = f"Create new content targeting '{gap.topic}'"
                item["content_outline"] = [
                    f"Introduction to {gap.topic}",
                    "Key concepts and definitions",
                    "How-to guide or practical steps",
                    "Tips and best practices",
                    "FAQ section",
                    "Conclusion and next steps",
                ]

            elif gap.gap_type == GapType.SHALLOW_COVERAGE:
                item["action"] = f"Expand existing content on '{gap.topic}'"
                item["content_outline"] = [
                    "Add more detailed sections",
                    "Include examples and case studies",
                    "Add supporting data/statistics",
                    "Expand FAQ section",
                ]

            elif gap.gap_type == GapType.MISSING_FORMAT:
                item["action"] = f"Create {gap.topic.replace('_', ' ')} content"
                if gap.topic == "faq":
                    item["content_outline"] = [
                        "Compile common questions",
                        "Provide detailed answers",
                        "Add schema markup",
                    ]
                elif gap.topic == "how_to":
                    item["content_outline"] = [
                        "Step-by-step instructions",
                        "Include images/screenshots",
                        "Add tips for each step",
                    ]

            plan.append(item)

        return plan

    def save_gaps(
        self,
        gaps: List[ContentGap],
        competitor_id: Optional[int] = None,
    ):
        """
        Save content gaps to database.

        Args:
            gaps: Gaps to save
            competitor_id: Optional competitor association
        """
        if not gaps:
            return

        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        import os

        load_dotenv()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            self.logger.warning("DATABASE_URL not set, skipping save")
            return

        engine = create_engine(db_url)

        insert_sql = text("""
            INSERT INTO content_analysis (
                topic, gap_type, priority, opportunity_score,
                competitor_coverage, your_coverage,
                keywords, recommendations, competitor_id,
                metadata, created_at
            ) VALUES (
                :topic, :gap_type, :priority, :score,
                :comp_coverage, :your_coverage,
                :keywords, :recommendations, :competitor_id,
                :metadata, :created_at
            )
            ON CONFLICT (topic) DO UPDATE SET
                opportunity_score = GREATEST(content_analysis.opportunity_score, EXCLUDED.opportunity_score),
                competitor_coverage = EXCLUDED.competitor_coverage,
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for gap in gaps:
                try:
                    conn.execute(insert_sql, {
                        "topic": gap.topic,
                        "gap_type": gap.gap_type.value,
                        "priority": gap.priority.value,
                        "score": gap.opportunity_score,
                        "comp_coverage": gap.competitor_coverage,
                        "your_coverage": gap.your_coverage,
                        "keywords": json.dumps(gap.keywords),
                        "recommendations": json.dumps(gap.recommendations),
                        "competitor_id": competitor_id,
                        "metadata": json.dumps(gap.metadata),
                        "created_at": gap.identified_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving gap: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(gaps)} content gaps to database")


# Module-level singleton
_content_gap_analyzer_instance = None


def get_content_gap_analyzer() -> ContentGapAnalyzer:
    """Get or create the singleton ContentGapAnalyzer instance."""
    global _content_gap_analyzer_instance

    if _content_gap_analyzer_instance is None:
        _content_gap_analyzer_instance = ContentGapAnalyzer()

    return _content_gap_analyzer_instance

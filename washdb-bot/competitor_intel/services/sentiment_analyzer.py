"""
Sentiment Analyzer for Competitor Reviews

Analyzes review text for:
- Overall sentiment (positive/negative/neutral)
- Complaint categories (pricing, communication, quality, timing, damage, professionalism)
- Praise categories (quality, professionalism, pricing, communication, timeliness)
- Key phrases and keywords
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from competitor_intel.config import SENTIMENT_CONFIG, REVIEW_CATEGORIES

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """Result of sentiment analysis on a review."""
    score: float  # -1 to 1
    label: str  # positive, negative, neutral, mixed
    confidence: float  # 0 to 1
    complaint_categories: List[str] = field(default_factory=list)
    praise_categories: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


class SentimentAnalyzer:
    """
    Analyzes sentiment of review text using VADER or TextBlob.

    VADER is preferred for social media/review text as it handles:
    - Emoticons and emoji
    - Emphasis (CAPS, punctuation!!!)
    - Slang and abbreviations
    """

    def __init__(self, analyzer_type: str = None):
        """
        Initialize the sentiment analyzer.

        Args:
            analyzer_type: 'vader' or 'textblob'. Defaults to config setting.
        """
        self.analyzer_type = analyzer_type or SENTIMENT_CONFIG.get("analyzer", "vader")
        self.confidence_threshold = SENTIMENT_CONFIG.get("confidence_threshold", 0.6)

        # Initialize the appropriate analyzer
        self._analyzer = None
        self._init_analyzer()

        # Compile category patterns
        self._complaint_patterns = self._compile_patterns(REVIEW_CATEGORIES.get("complaints", {}))
        self._praise_patterns = self._compile_patterns(REVIEW_CATEGORIES.get("praise", {}))

        logger.info(f"SentimentAnalyzer initialized with {self.analyzer_type}")

    def _init_analyzer(self):
        """Initialize the sentiment analysis library."""
        if self.analyzer_type == "vader":
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._analyzer = SentimentIntensityAnalyzer()
                logger.info("VADER sentiment analyzer loaded")
            except ImportError:
                logger.warning("VADER not available, falling back to keyword-based")
                self._analyzer = None
        elif self.analyzer_type == "textblob":
            try:
                from textblob import TextBlob
                self._analyzer = TextBlob
                logger.info("TextBlob sentiment analyzer loaded")
            except ImportError:
                logger.warning("TextBlob not available, falling back to keyword-based")
                self._analyzer = None

    def _compile_patterns(self, categories: Dict[str, List[str]]) -> Dict[str, re.Pattern]:
        """Compile regex patterns for category detection."""
        patterns = {}
        for category, keywords in categories.items():
            # Create pattern that matches any keyword (case insensitive)
            pattern_str = r'\b(' + '|'.join(re.escape(kw) for kw in keywords) + r')\b'
            patterns[category] = re.compile(pattern_str, re.IGNORECASE)
        return patterns

    def analyze(self, text: str) -> SentimentResult:
        """
        Analyze sentiment of a review text.

        Args:
            text: The review text to analyze

        Returns:
            SentimentResult with score, label, categories, and keywords
        """
        if not text or not text.strip():
            return SentimentResult(
                score=0.0,
                label="neutral",
                confidence=0.0,
            )

        # Clean text
        text = self._clean_text(text)

        # Get sentiment score
        score, confidence = self._get_sentiment_score(text)

        # Determine label
        label = self._score_to_label(score, confidence)

        # Extract categories
        complaint_categories = self._detect_categories(text, self._complaint_patterns)
        praise_categories = self._detect_categories(text, self._praise_patterns)

        # Extract keywords
        keywords = self._extract_keywords(text)

        return SentimentResult(
            score=round(score, 3),
            label=label,
            confidence=round(confidence, 3),
            complaint_categories=complaint_categories,
            praise_categories=praise_categories,
            keywords=keywords,
        )

    def _clean_text(self, text: str) -> str:
        """Clean and normalize review text."""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _get_sentiment_score(self, text: str) -> Tuple[float, float]:
        """
        Get sentiment score using configured analyzer.

        Returns:
            Tuple of (score, confidence) where score is -1 to 1
        """
        if self._analyzer is None:
            # Fallback to keyword-based
            return self._keyword_based_sentiment(text)

        if self.analyzer_type == "vader":
            scores = self._analyzer.polarity_scores(text)
            # VADER compound score is -1 to 1
            compound = scores['compound']
            # Confidence based on how extreme the score is
            confidence = abs(compound)
            return compound, confidence

        elif self.analyzer_type == "textblob":
            blob = self._analyzer(text)
            # TextBlob polarity is -1 to 1
            polarity = blob.sentiment.polarity
            # Subjectivity as a proxy for confidence (more subjective = more confident sentiment)
            confidence = blob.sentiment.subjectivity
            return polarity, confidence

        return self._keyword_based_sentiment(text)

    def _keyword_based_sentiment(self, text: str) -> Tuple[float, float]:
        """
        Simple keyword-based sentiment as fallback.

        Returns:
            Tuple of (score, confidence)
        """
        text_lower = text.lower()

        # Positive indicators
        positive_words = [
            'great', 'excellent', 'amazing', 'wonderful', 'fantastic',
            'perfect', 'best', 'love', 'recommend', 'professional',
            'thorough', 'friendly', 'quality', 'satisfied', 'impressed',
            'awesome', 'outstanding', 'exceptional', 'superb', 'terrific',
        ]

        # Negative indicators
        negative_words = [
            'bad', 'terrible', 'awful', 'horrible', 'worst',
            'poor', 'disappointed', 'rude', 'unprofessional', 'late',
            'expensive', 'overpriced', 'damage', 'broken', 'never',
            'waste', 'avoid', 'scam', 'rip', 'incompetent',
        ]

        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)

        total = pos_count + neg_count
        if total == 0:
            return 0.0, 0.3

        # Score from -1 to 1
        score = (pos_count - neg_count) / total
        # Confidence based on how many matches
        confidence = min(total / 5, 1.0)

        return score, confidence

    def _score_to_label(self, score: float, confidence: float) -> str:
        """Convert numeric score to label."""
        if confidence < self.confidence_threshold:
            return "neutral"

        if score >= 0.3:
            return "positive"
        elif score <= -0.3:
            return "negative"
        elif abs(score) < 0.1:
            return "neutral"
        else:
            return "mixed"

    def _detect_categories(self, text: str, patterns: Dict[str, re.Pattern]) -> List[str]:
        """Detect which categories are mentioned in the text."""
        categories = []
        for category, pattern in patterns.items():
            if pattern.search(text):
                categories.append(category)
        return categories

    def _extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """Extract important keywords from the text."""
        # Simple keyword extraction based on word frequency
        # Exclude common stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
            'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
            'very', 'really', 'just', 'also', 'so', 'too', 'much', 'more',
        }

        # Tokenize and clean
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        words = [w for w in words if w not in stop_words]

        # Count frequencies
        freq = {}
        for word in words:
            freq[word] = freq.get(word, 0) + 1

        # Get top keywords
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        keywords = [word for word, count in sorted_words[:max_keywords]]

        return keywords

    def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        """Analyze sentiment for multiple texts."""
        return [self.analyze(text) for text in texts]

    def get_aggregate_sentiment(self, results: List[SentimentResult]) -> Dict:
        """
        Calculate aggregate sentiment metrics from multiple results.

        Returns:
            Dict with average score, label distribution, top categories
        """
        if not results:
            return {}

        scores = [r.score for r in results]
        avg_score = sum(scores) / len(scores)

        # Label distribution
        labels = {}
        for r in results:
            labels[r.label] = labels.get(r.label, 0) + 1

        # Category counts
        complaint_counts = {}
        praise_counts = {}
        for r in results:
            for cat in r.complaint_categories:
                complaint_counts[cat] = complaint_counts.get(cat, 0) + 1
            for cat in r.praise_categories:
                praise_counts[cat] = praise_counts.get(cat, 0) + 1

        return {
            "avg_score": round(avg_score, 3),
            "total_reviews": len(results),
            "label_distribution": labels,
            "pct_positive": round(labels.get("positive", 0) / len(results) * 100, 1),
            "pct_negative": round(labels.get("negative", 0) / len(results) * 100, 1),
            "top_complaints": sorted(complaint_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "top_praise": sorted(praise_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        }


def analyze_review_sentiment(text: str) -> SentimentResult:
    """
    Convenience function to analyze a single review.

    Args:
        text: Review text

    Returns:
        SentimentResult
    """
    analyzer = SentimentAnalyzer()
    return analyzer.analyze(text)

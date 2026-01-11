"""
Content Analyzer for Competitor Intelligence

Analyzes competitor page content for:
- Full text extraction and archiving
- Readability scoring (Flesch-Kincaid)
- Content change detection (diff)
- Keyword density analysis
"""

import re
import json
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from bs4 import BeautifulSoup
from sqlalchemy import text

from competitor_intel.config import CONTENT_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class ContentAnalysis:
    """Result of content analysis."""
    url: str
    full_text: str
    full_text_hash: str
    word_count: int
    paragraph_count: int
    readability_score: float
    reading_time_minutes: int
    primary_keywords: List[Dict]  # [{keyword, count, density}]
    keyword_density_map: Dict[str, float]
    # Change detection
    change_detected: bool = False
    change_percentage: float = 0.0
    diff_summary: str = ""
    previous_hash: str = ""


class ContentAnalyzer:
    """
    Analyzes and archives competitor page content.

    Features:
    - Clean text extraction from HTML
    - Readability scoring
    - Keyword density analysis
    - Change detection between crawls
    """

    def __init__(self):
        self.archive_full_text = CONTENT_CONFIG.get("archive_full_text", True)
        self.compute_readability = CONTENT_CONFIG.get("compute_readability", True)
        self.track_changes = CONTENT_CONFIG.get("track_changes", True)
        self.change_threshold_pct = CONTENT_CONFIG.get("change_threshold_pct", 10)

        logger.info("ContentAnalyzer initialized")

    def analyze(self, url: str, html: str, competitor_id: int = None) -> ContentAnalysis:
        """
        Analyze page content.

        Args:
            url: Page URL
            html: Raw HTML content
            competitor_id: Optional competitor ID for change detection

        Returns:
            ContentAnalysis with extracted data
        """
        # Extract clean text
        full_text = self._extract_text(html)
        full_text_hash = self._hash_content(full_text)

        # Basic metrics
        word_count = len(full_text.split())
        paragraph_count = self._count_paragraphs(full_text)
        reading_time = self._calculate_reading_time(word_count)

        # Readability
        readability_score = 0.0
        if self.compute_readability and word_count > 50:
            readability_score = self._calculate_readability(full_text)

        # Keyword analysis
        primary_keywords, keyword_density = self._analyze_keywords(full_text)

        # Change detection
        change_detected = False
        change_percentage = 0.0
        diff_summary = ""
        previous_hash = ""

        if self.track_changes and competitor_id:
            prev = self._get_previous_content(competitor_id, url)
            if prev:
                previous_hash = prev["hash"]
                if previous_hash != full_text_hash:
                    change_detected = True
                    change_percentage = self._calculate_change_percentage(
                        prev["text"], full_text
                    )
                    diff_summary = self._generate_diff_summary(
                        prev["text"], full_text
                    )

        return ContentAnalysis(
            url=url,
            full_text=full_text if self.archive_full_text else "",
            full_text_hash=full_text_hash,
            word_count=word_count,
            paragraph_count=paragraph_count,
            readability_score=round(readability_score, 2),
            reading_time_minutes=reading_time,
            primary_keywords=primary_keywords,
            keyword_density_map=keyword_density,
            change_detected=change_detected,
            change_percentage=round(change_percentage, 2),
            diff_summary=diff_summary,
            previous_hash=previous_hash,
        )

    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script, style, nav, footer, header
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
            tag.decompose()

        # Get text
        text = soup.get_text(separator=' ', strip=True)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _hash_content(self, text: str) -> str:
        """Generate SHA-256 hash of content."""
        # Normalize before hashing
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _count_paragraphs(self, text: str) -> int:
        """Count paragraphs (sentences separated by periods)."""
        sentences = re.split(r'[.!?]+', text)
        # Group into paragraphs (roughly 3-5 sentences each)
        return max(1, len([s for s in sentences if len(s.strip()) > 20]) // 4)

    def _calculate_reading_time(self, word_count: int, wpm: int = 200) -> int:
        """Calculate estimated reading time in minutes."""
        return max(1, round(word_count / wpm))

    def _calculate_readability(self, text: str) -> float:
        """
        Calculate Flesch-Kincaid readability score.

        Score interpretation:
        - 90-100: Very easy (5th grade)
        - 80-90: Easy (6th grade)
        - 70-80: Fairly easy (7th grade)
        - 60-70: Standard (8th-9th grade)
        - 50-60: Fairly difficult (10th-12th grade)
        - 30-50: Difficult (college)
        - 0-30: Very difficult (college graduate)
        """
        # Count sentences
        sentences = re.split(r'[.!?]+', text)
        sentence_count = len([s for s in sentences if len(s.strip()) > 0])

        if sentence_count == 0:
            return 0.0

        # Count words
        words = text.split()
        word_count = len(words)

        if word_count == 0:
            return 0.0

        # Count syllables (simple approximation)
        syllable_count = self._count_syllables(text)

        # Flesch Reading Ease formula
        # 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
        avg_sentence_length = word_count / sentence_count
        avg_syllables_per_word = syllable_count / word_count

        score = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables_per_word)

        # Clamp to 0-100
        return max(0, min(100, score))

    def _count_syllables(self, text: str) -> int:
        """
        Count syllables in text (approximation).

        Uses vowel groups as proxy for syllables.
        """
        text = text.lower()
        # Remove non-alphabetic
        text = re.sub(r'[^a-z\s]', '', text)

        syllable_count = 0
        words = text.split()

        for word in words:
            if len(word) == 0:
                continue

            # Count vowel groups
            vowels = 'aeiouy'
            count = 0
            prev_was_vowel = False

            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_was_vowel:
                    count += 1
                prev_was_vowel = is_vowel

            # Handle silent e
            if word.endswith('e') and count > 1:
                count -= 1

            # Every word has at least 1 syllable
            syllable_count += max(1, count)

        return syllable_count

    def _analyze_keywords(self, text: str) -> Tuple[List[Dict], Dict[str, float]]:
        """
        Analyze keyword frequency and density.

        Returns:
            Tuple of (primary_keywords list, keyword_density map)
        """
        # Stop words to exclude
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
            'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
            'very', 'really', 'just', 'also', 'so', 'too', 'much', 'more',
            'all', 'any', 'both', 'each', 'few', 'many', 'most', 'other',
            'some', 'such', 'no', 'not', 'only', 'own', 'same', 'than',
        }

        # Tokenize
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        words = [w for w in words if w not in stop_words]

        total_words = len(words)
        if total_words == 0:
            return [], {}

        # Count frequencies
        freq = {}
        for word in words:
            freq[word] = freq.get(word, 0) + 1

        # Calculate density
        keyword_density = {
            word: round(count / total_words * 100, 2)
            for word, count in freq.items()
            if count >= 2  # Only words appearing 2+ times
        }

        # Get top keywords
        sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        primary_keywords = [
            {
                "keyword": word,
                "count": count,
                "density": round(count / total_words * 100, 2),
            }
            for word, count in sorted_keywords[:20]
        ]

        return primary_keywords, keyword_density

    def _get_previous_content(self, competitor_id: int, url: str) -> Optional[Dict]:
        """Get previous content for change detection."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT full_text, full_text_hash
                FROM competitor_content_archive
                WHERE competitor_id = :competitor_id AND url = :url
                ORDER BY captured_at DESC
                LIMIT 1
            """), {
                "competitor_id": competitor_id,
                "url": url,
            }).fetchone()

            if result:
                return {"text": result[0] or "", "hash": result[1]}
            return None
        finally:
            session.close()

    def _calculate_change_percentage(self, old_text: str, new_text: str) -> float:
        """Calculate percentage of content that changed."""
        if not old_text:
            return 100.0

        # Use SequenceMatcher for similarity
        matcher = SequenceMatcher(None, old_text, new_text)
        similarity = matcher.ratio()

        return (1 - similarity) * 100

    def _generate_diff_summary(self, old_text: str, new_text: str, max_length: int = 500) -> str:
        """Generate a human-readable summary of changes."""
        if not old_text:
            return "New content"

        old_words = set(old_text.lower().split())
        new_words = set(new_text.lower().split())

        added = new_words - old_words
        removed = old_words - new_words

        parts = []
        if added:
            sample_added = list(added)[:5]
            parts.append(f"Added words: {', '.join(sample_added)}")
        if removed:
            sample_removed = list(removed)[:5]
            parts.append(f"Removed words: {', '.join(sample_removed)}")

        summary = "; ".join(parts) if parts else "Minor changes"
        return summary[:max_length]

    def save_archive(self, competitor_id: int, analysis: ContentAnalysis, page_type: str = None):
        """Save content analysis to database."""
        session = create_session()
        try:
            session.execute(text("""
                INSERT INTO competitor_content_archive (
                    competitor_id, url, page_type, full_text, full_text_hash,
                    word_count, readability_score, reading_time_minutes,
                    paragraph_count, primary_keywords, keyword_density_map,
                    previous_hash, change_detected, change_percentage, diff_summary
                ) VALUES (
                    :competitor_id, :url, :page_type, :full_text, :full_text_hash,
                    :word_count, :readability_score, :reading_time_minutes,
                    :paragraph_count, :primary_keywords, :keyword_density_map,
                    :previous_hash, :change_detected, :change_percentage, :diff_summary
                )
            """), {
                "competitor_id": competitor_id,
                "url": analysis.url,
                "page_type": page_type,
                "full_text": analysis.full_text,
                "full_text_hash": analysis.full_text_hash,
                "word_count": analysis.word_count,
                "readability_score": analysis.readability_score,
                "reading_time_minutes": analysis.reading_time_minutes,
                "paragraph_count": analysis.paragraph_count,
                "primary_keywords": json.dumps(analysis.primary_keywords),
                "keyword_density_map": json.dumps(analysis.keyword_density_map),
                "previous_hash": analysis.previous_hash,
                "change_detected": analysis.change_detected,
                "change_percentage": analysis.change_percentage,
                "diff_summary": analysis.diff_summary,
            })
            session.commit()
            logger.info(f"Saved content archive for {analysis.url}")
        except Exception as e:
            logger.error(f"Failed to save content archive: {e}")
            session.rollback()
        finally:
            session.close()


def analyze_page_content(url: str, html: str, competitor_id: int = None) -> ContentAnalysis:
    """
    Convenience function to analyze page content.

    Args:
        url: Page URL
        html: Raw HTML content
        competitor_id: Optional competitor ID for change detection

    Returns:
        ContentAnalysis
    """
    analyzer = ContentAnalyzer()
    return analyzer.analyze(url, html, competitor_id)

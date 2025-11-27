"""
Readability Analyzer Service

Calculates readability metrics for text content using pure Python formulas.

Metrics provided:
- Flesch-Kincaid Grade Level: US school grade level required to understand
- Flesch Reading Ease: 0-100 score (higher = easier to read)
- Gunning Fog Index: Years of education needed
- SMOG Index: Simple Measure of Gobbledygook
- Coleman-Liau Index: Character-based readability
- Automated Readability Index (ARI): Character/word based

All formulas are implemented in pure Python with no external API dependencies.

Usage:
    from seo_intelligence.services.readability_analyzer import ReadabilityAnalyzer

    analyzer = ReadabilityAnalyzer()
    result = analyzer.analyze_text(text)

    # Or analyze HTML
    result = analyzer.analyze_html(html)

    # Result contains:
    # {
    #     "flesch_kincaid_grade": 8.5,
    #     "flesch_reading_ease": 65.2,
    #     "gunning_fog_index": 10.3,
    #     "smog_index": 9.1,
    #     "coleman_liau_index": 10.5,
    #     "ari": 9.8,
    #     "word_count": 500,
    #     "sentence_count": 25,
    #     "avg_sentence_length": 20.0,
    #     "complex_word_ratio": 0.15,
    #     "reading_level": "High School",
    #     "reading_time_minutes": 2.5
    # }
"""

import re
import string
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup

from runner.logging_setup import get_logger

logger = get_logger("readability_analyzer")


# Common syllable patterns for syllable counting
# Based on English phonology rules
SYLLABLE_EXCEPTIONS = {
    "area": 3, "idea": 3, "real": 2, "ruin": 2, "science": 2,
    "create": 2, "creature": 2, "feature": 2, "measure": 2,
    "employee": 3, "every": 3, "evening": 3, "everything": 4,
    "business": 2, "different": 3, "family": 3, "interest": 3,
    "favorite": 3, "separate": 3, "chocolate": 3, "comfortable": 4,
    "temperature": 4, "vegetable": 4, "literature": 4, "dictionary": 4,
}

# Prefixes/suffixes that don't add syllables
SILENT_SUFFIXES = ["es", "ed", "e"]
ADD_SYLLABLE_SUFFIXES = ["le", "les", "tion", "sion", "ious", "eous"]


@dataclass
class ReadabilityResult:
    """Container for readability analysis results."""
    # Core metrics
    flesch_kincaid_grade: float
    flesch_reading_ease: float
    gunning_fog_index: float
    smog_index: Optional[float]
    coleman_liau_index: float
    ari: float

    # Text statistics
    word_count: int
    sentence_count: int
    paragraph_count: int
    character_count: int
    syllable_count: int

    # Derived statistics
    avg_sentence_length: float
    avg_word_length: float
    avg_syllables_per_word: float
    complex_word_count: int
    complex_word_ratio: float

    # Interpretation
    reading_level: str
    reading_time_minutes: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self.__dict__.copy()


class ReadabilityAnalyzer:
    """
    Analyzes text readability using standard formulas.

    All calculations are done in pure Python with no external dependencies.
    """

    def __init__(self, words_per_minute: int = 200):
        """
        Initialize readability analyzer.

        Args:
            words_per_minute: Average reading speed for time estimation
        """
        self.words_per_minute = words_per_minute
        logger.info("ReadabilityAnalyzer initialized")

    def _count_syllables(self, word: str) -> int:
        """
        Count syllables in a word using English phonology rules.

        Args:
            word: Word to count syllables for

        Returns:
            int: Number of syllables
        """
        word = word.lower().strip()

        # Remove punctuation
        word = word.strip(string.punctuation)

        if not word:
            return 0

        # Check exception list
        if word in SYLLABLE_EXCEPTIONS:
            return SYLLABLE_EXCEPTIONS[word]

        # Count vowel groups
        vowels = "aeiouy"
        count = 0
        prev_is_vowel = False

        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_is_vowel:
                count += 1
            prev_is_vowel = is_vowel

        # Handle silent e at end
        if word.endswith('e') and count > 1:
            # But not words ending in -le
            if not word.endswith('le'):
                count -= 1

        # Handle -ed endings
        if word.endswith('ed') and count > 1:
            if not word.endswith('ted') and not word.endswith('ded'):
                count -= 1

        # Handle -es endings
        if word.endswith('es') and count > 1:
            if word.endswith('ses') or word.endswith('xes') or word.endswith('zes'):
                pass  # Keep syllable
            elif word.endswith('ches') or word.endswith('shes'):
                pass  # Keep syllable
            else:
                count -= 1

        # Handle special suffixes that add syllables
        for suffix in ['-tion', '-sion', '-cial', '-tial']:
            if word.endswith(suffix.replace('-', '')):
                # These are already counted correctly by vowel groups
                pass

        # Ensure at least one syllable
        return max(1, count)

    def _is_complex_word(self, word: str) -> bool:
        """
        Check if a word is complex (3+ syllables, not proper noun or compound).

        For Gunning Fog Index, complex words have 3+ syllables and:
        - Are not proper nouns (capitalized)
        - Are not combinations of easy words
        - Do not end in -es, -ed, -ing

        Args:
            word: Word to check

        Returns:
            bool: True if word is complex
        """
        syllables = self._count_syllables(word)

        if syllables < 3:
            return False

        # Remove common suffixes that inflate syllable count
        word_lower = word.lower()
        if word_lower.endswith('ing') and syllables >= 3:
            base = word_lower[:-3]
            if self._count_syllables(base) < 3:
                return False

        if word_lower.endswith('ed') and syllables >= 3:
            base = word_lower[:-2]
            if self._count_syllables(base) < 3:
                return False

        if word_lower.endswith('es') and syllables >= 3:
            base = word_lower[:-2]
            if self._count_syllables(base) < 3:
                return False

        return True

    def _tokenize_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences.

        Handles common abbreviations and edge cases.

        Args:
            text: Text to tokenize

        Returns:
            List of sentences
        """
        # Protect common abbreviations
        abbrevs = [
            'Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Jr.', 'Sr.',
            'Inc.', 'Ltd.', 'Corp.', 'Co.',
            'vs.', 'etc.', 'e.g.', 'i.e.',
            'a.m.', 'p.m.', 'A.M.', 'P.M.',
            'U.S.', 'U.K.', 'U.N.',
        ]

        protected_text = text
        for abbrev in abbrevs:
            protected_text = protected_text.replace(abbrev, abbrev.replace('.', '<DOT>'))

        # Split on sentence-ending punctuation
        sentences = re.split(r'[.!?]+\s+', protected_text)

        # Restore dots
        sentences = [s.replace('<DOT>', '.').strip() for s in sentences if s.strip()]

        return sentences

    def _tokenize_words(self, text: str) -> List[str]:
        """
        Split text into words.

        Args:
            text: Text to tokenize

        Returns:
            List of words
        """
        # Remove punctuation except apostrophes and hyphens within words
        text = re.sub(r"[^\w\s'-]", ' ', text)
        text = re.sub(r'\s+', ' ', text)

        words = text.split()

        # Filter out non-words (numbers, single characters)
        words = [w for w in words if len(w) > 1 and not w.isdigit()]

        return words

    def _extract_text_from_html(self, html: str) -> Tuple[str, int]:
        """
        Extract readable text from HTML.

        Args:
            html: HTML content

        Returns:
            Tuple of (text, paragraph_count)
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove scripts and styles
        for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
            element.decompose()

        # Count paragraphs
        paragraphs = soup.find_all(['p', 'li', 'dd', 'blockquote'])
        paragraph_count = len(paragraphs)

        # Get text
        text = soup.get_text(separator=' ')

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text, max(1, paragraph_count)

    def _calculate_flesch_kincaid_grade(
        self,
        words: int,
        sentences: int,
        syllables: int
    ) -> float:
        """
        Calculate Flesch-Kincaid Grade Level.

        Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59

        Returns US school grade level (1-12+)
        """
        if sentences == 0 or words == 0:
            return 0.0

        grade = (
            0.39 * (words / sentences) +
            11.8 * (syllables / words) -
            15.59
        )

        return round(max(0, grade), 1)

    def _calculate_flesch_reading_ease(
        self,
        words: int,
        sentences: int,
        syllables: int
    ) -> float:
        """
        Calculate Flesch Reading Ease score.

        Formula: 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)

        Returns 0-100 score (higher = easier to read)
        - 90-100: Very Easy (5th grade)
        - 80-89: Easy (6th grade)
        - 70-79: Fairly Easy (7th grade)
        - 60-69: Standard (8th-9th grade)
        - 50-59: Fairly Difficult (10th-12th grade)
        - 30-49: Difficult (College)
        - 0-29: Very Confusing (College Graduate)
        """
        if sentences == 0 or words == 0:
            return 0.0

        ease = (
            206.835 -
            1.015 * (words / sentences) -
            84.6 * (syllables / words)
        )

        return round(max(0, min(100, ease)), 1)

    def _calculate_gunning_fog(
        self,
        words: int,
        sentences: int,
        complex_words: int
    ) -> float:
        """
        Calculate Gunning Fog Index.

        Formula: 0.4 * ((words/sentences) + 100 * (complex_words/words))

        Returns years of education needed to understand.
        """
        if sentences == 0 or words == 0:
            return 0.0

        fog = 0.4 * (
            (words / sentences) +
            100 * (complex_words / words)
        )

        return round(max(0, fog), 1)

    def _calculate_smog(
        self,
        sentences: int,
        complex_words: int
    ) -> Optional[float]:
        """
        Calculate SMOG Index (Simple Measure of Gobbledygook).

        Formula: 1.043 * sqrt(complex_words * (30/sentences)) + 3.1291

        Requires at least 30 sentences for accuracy.
        Returns years of education needed.
        """
        if sentences < 30:
            # Not enough sentences for accurate SMOG
            return None

        import math

        smog = 1.043 * math.sqrt(complex_words * (30 / sentences)) + 3.1291

        return round(max(0, smog), 1)

    def _calculate_coleman_liau(
        self,
        words: int,
        sentences: int,
        characters: int
    ) -> float:
        """
        Calculate Coleman-Liau Index.

        Formula: 0.0588 * L - 0.296 * S - 15.8
        Where L = avg letters per 100 words, S = avg sentences per 100 words

        Returns US school grade level.
        """
        if words == 0:
            return 0.0

        L = (characters / words) * 100
        S = (sentences / words) * 100

        cli = 0.0588 * L - 0.296 * S - 15.8

        return round(max(0, cli), 1)

    def _calculate_ari(
        self,
        words: int,
        sentences: int,
        characters: int
    ) -> float:
        """
        Calculate Automated Readability Index.

        Formula: 4.71 * (characters/words) + 0.5 * (words/sentences) - 21.43

        Returns US school grade level.
        """
        if words == 0 or sentences == 0:
            return 0.0

        ari = (
            4.71 * (characters / words) +
            0.5 * (words / sentences) -
            21.43
        )

        return round(max(0, ari), 1)

    def _get_reading_level(self, grade: float) -> str:
        """
        Convert grade level to human-readable label.

        Args:
            grade: Flesch-Kincaid grade level

        Returns:
            str: Reading level description
        """
        if grade <= 5:
            return "Elementary"
        elif grade <= 8:
            return "Middle School"
        elif grade <= 12:
            return "High School"
        elif grade <= 16:
            return "College"
        else:
            return "Graduate"

    def analyze_text(self, text: str) -> ReadabilityResult:
        """
        Analyze readability of plain text.

        Args:
            text: Plain text to analyze

        Returns:
            ReadabilityResult with all metrics
        """
        # Tokenize
        sentences = self._tokenize_sentences(text)
        words = self._tokenize_words(text)

        # Count statistics
        sentence_count = len(sentences)
        word_count = len(words)
        character_count = sum(len(w) for w in words)

        # Count syllables and complex words
        syllable_count = sum(self._count_syllables(w) for w in words)
        complex_words = [w for w in words if self._is_complex_word(w)]
        complex_word_count = len(complex_words)

        # Calculate derived statistics
        avg_sentence_length = word_count / max(1, sentence_count)
        avg_word_length = character_count / max(1, word_count)
        avg_syllables_per_word = syllable_count / max(1, word_count)
        complex_word_ratio = complex_word_count / max(1, word_count)

        # Calculate readability scores
        fk_grade = self._calculate_flesch_kincaid_grade(
            word_count, sentence_count, syllable_count
        )
        fre = self._calculate_flesch_reading_ease(
            word_count, sentence_count, syllable_count
        )
        fog = self._calculate_gunning_fog(
            word_count, sentence_count, complex_word_count
        )
        smog = self._calculate_smog(sentence_count, complex_word_count)
        cli = self._calculate_coleman_liau(
            word_count, sentence_count, character_count
        )
        ari = self._calculate_ari(
            word_count, sentence_count, character_count
        )

        # Estimate reading time
        reading_time = word_count / self.words_per_minute

        # Get reading level interpretation
        reading_level = self._get_reading_level(fk_grade)

        return ReadabilityResult(
            flesch_kincaid_grade=fk_grade,
            flesch_reading_ease=fre,
            gunning_fog_index=fog,
            smog_index=smog,
            coleman_liau_index=cli,
            ari=ari,
            word_count=word_count,
            sentence_count=sentence_count,
            paragraph_count=1,  # Plain text counts as 1 paragraph
            character_count=character_count,
            syllable_count=syllable_count,
            avg_sentence_length=round(avg_sentence_length, 1),
            avg_word_length=round(avg_word_length, 2),
            avg_syllables_per_word=round(avg_syllables_per_word, 2),
            complex_word_count=complex_word_count,
            complex_word_ratio=round(complex_word_ratio, 3),
            reading_level=reading_level,
            reading_time_minutes=round(reading_time, 1),
        )

    def analyze_html(self, html: str) -> ReadabilityResult:
        """
        Analyze readability of HTML content.

        Extracts text from HTML and analyzes it.

        Args:
            html: HTML content

        Returns:
            ReadabilityResult with all metrics
        """
        # Extract text and count paragraphs
        text, paragraph_count = self._extract_text_from_html(html)

        # Analyze the extracted text
        result = self.analyze_text(text)

        # Update paragraph count from HTML structure
        result.paragraph_count = paragraph_count

        return result


# Module-level singleton
_readability_analyzer_instance = None


def get_readability_analyzer(**kwargs) -> ReadabilityAnalyzer:
    """Get or create the singleton ReadabilityAnalyzer instance."""
    global _readability_analyzer_instance

    if _readability_analyzer_instance is None:
        _readability_analyzer_instance = ReadabilityAnalyzer(**kwargs)

    return _readability_analyzer_instance


def main():
    """Demo/CLI interface for readability analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Readability Analyzer")
    parser.add_argument("--text", "-t", help="Text to analyze")
    parser.add_argument("--file", "-f", help="File to analyze (plain text or HTML)")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Readability Analyzer Demo Mode")
        logger.info("=" * 60)

        # Demo text
        demo_text = """
        The quick brown fox jumps over the lazy dog. This is a simple sentence.
        Reading comprehension is important for understanding complex documents.
        Professional writers often aim for a Flesch Reading Ease score above 60.
        Technical documentation sometimes requires more sophisticated vocabulary.
        The Flesch-Kincaid Grade Level indicates the US school grade needed.
        """

        analyzer = ReadabilityAnalyzer()
        result = analyzer.analyze_text(demo_text)

        print("\nDemo Text Analysis:")
        print("-" * 40)
        print(f"Flesch-Kincaid Grade: {result.flesch_kincaid_grade}")
        print(f"Flesch Reading Ease: {result.flesch_reading_ease}")
        print(f"Gunning Fog Index: {result.gunning_fog_index}")
        print(f"Reading Level: {result.reading_level}")
        print(f"Word Count: {result.word_count}")
        print(f"Reading Time: {result.reading_time_minutes} minutes")
        print("=" * 60)
        return

    if args.text:
        analyzer = ReadabilityAnalyzer()
        result = analyzer.analyze_text(args.text)
    elif args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read()

        analyzer = ReadabilityAnalyzer()

        if args.file.endswith('.html') or args.file.endswith('.htm'):
            result = analyzer.analyze_html(content)
        else:
            result = analyzer.analyze_text(content)
    else:
        parser.print_help()
        return

    print("\n" + "=" * 60)
    print("Readability Analysis Results")
    print("=" * 60)
    print(f"Flesch-Kincaid Grade Level: {result.flesch_kincaid_grade}")
    print(f"Flesch Reading Ease: {result.flesch_reading_ease}")
    print(f"Gunning Fog Index: {result.gunning_fog_index}")
    print(f"SMOG Index: {result.smog_index or 'N/A (need 30+ sentences)'}")
    print(f"Coleman-Liau Index: {result.coleman_liau_index}")
    print(f"Automated Readability Index: {result.ari}")
    print("-" * 60)
    print(f"Reading Level: {result.reading_level}")
    print(f"Reading Time: {result.reading_time_minutes} minutes")
    print("-" * 60)
    print(f"Words: {result.word_count}")
    print(f"Sentences: {result.sentence_count}")
    print(f"Paragraphs: {result.paragraph_count}")
    print(f"Average Sentence Length: {result.avg_sentence_length} words")
    print(f"Complex Words: {result.complex_word_count} ({result.complex_word_ratio:.1%})")
    print("=" * 60)


if __name__ == "__main__":
    main()

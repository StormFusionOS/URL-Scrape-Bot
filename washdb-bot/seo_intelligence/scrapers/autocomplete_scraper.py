"""
Google Autocomplete Scraper

Scrapes Google Search autocomplete suggestions for keyword research.
No external APIs required - uses public autocomplete endpoints.

Features:
- Seed keyword expansion with alphabet suffixes
- Question-based keyword discovery (who, what, when, where, why, how)
- Location-based keyword suggestions
- Multi-language support
- Database storage in keyword_suggestions table

Usage:
    from seo_intelligence.scrapers.autocomplete_scraper import AutocompleteScraper

    scraper = AutocompleteScraper()
    suggestions = scraper.get_suggestions("car wash near me")

    # Or expand with prefixes/suffixes
    all_keywords = scraper.expand_keyword("car wash", include_questions=True)

Respects rate limiting and robots.txt compliance.
"""

import re
import json
import time
import random
import hashlib
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.services import get_task_logger
from runner.logging_setup import get_logger


@dataclass
class AutocompleteSuggestion:
    """Represents a single autocomplete suggestion."""
    keyword: str
    seed_keyword: str
    source: str = "google_autocomplete"
    suggestion_type: str = "related"  # related, question, location, alphabet
    relevance_score: float = 1.0
    scraped_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AutocompleteScraper(BaseScraper):
    """
    Scrapes Google Search autocomplete suggestions.

    Uses Google's public suggestion endpoint which returns JSON.
    Implements aggressive rate limiting to avoid detection.
    """

    # Google autocomplete endpoint
    AUTOCOMPLETE_URL = "https://www.google.com/complete/search"

    # Question prefixes for keyword expansion
    QUESTION_PREFIXES = [
        "what is", "what are", "what does",
        "how to", "how do", "how does", "how much", "how long",
        "why is", "why do", "why does", "why are",
        "when to", "when is", "when does",
        "where to", "where is", "where can",
        "who is", "who does", "who can",
        "can you", "can I", "should I",
        "is it", "does it", "will it",
        "best", "top", "cheapest", "fastest",
    ]

    # Alphabet suffixes for a-z expansion
    ALPHABET = list("abcdefghijklmnopqrstuvwxyz")

    # Common comparison modifiers
    COMPARISON_MODIFIERS = [
        "vs", "versus", "or", "compared to",
        "better than", "alternative to",
    ]

    # Intent modifiers
    INTENT_MODIFIERS = [
        "near me", "open now", "reviews", "cost", "price",
        "hours", "phone number", "address", "coupon",
        "discount", "free", "cheap", "best", "top rated",
    ]

    def __init__(
        self,
        tier: str = "D",  # Conservative rate limiting for Google
        country: str = "us",
        language: str = "en",
        max_suggestions_per_query: int = 10,
    ):
        """
        Initialize autocomplete scraper.

        Args:
            tier: Rate limit tier (D recommended for Google)
            country: Country code for localized suggestions
            language: Language code
            max_suggestions_per_query: Max suggestions to keep per query
        """
        super().__init__(
            name="autocomplete_scraper",
            tier=tier,
            headless=True,
            respect_robots=True,
            use_proxy=False,
            max_retries=3,
            page_timeout=15000,
        )

        self.country = country
        self.language = language
        self.max_suggestions = max_suggestions_per_query
        self.logger = get_logger("autocomplete_scraper")

        # Track scraped queries to avoid duplicates
        self._scraped_queries: Set[str] = set()

        # Statistics
        self.keyword_stats = {
            "queries_made": 0,
            "suggestions_found": 0,
            "unique_keywords": 0,
            "rate_limited": 0,
        }

    def _build_autocomplete_url(self, query: str) -> str:
        """
        Build Google autocomplete URL.

        Args:
            query: Search query

        Returns:
            str: Full URL with parameters
        """
        params = {
            "q": query,
            "client": "chrome",  # Returns JSON format
            "hl": self.language,
            "gl": self.country,
        }

        param_str = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        return f"{self.AUTOCOMPLETE_URL}?{param_str}"

    def _parse_suggestions(self, response_text: str) -> List[str]:
        """
        Parse suggestions from Google's JSON response.

        Google returns: ["query", ["suggestion1", "suggestion2", ...], ...]

        Args:
            response_text: Raw response text

        Returns:
            list: Parsed suggestions
        """
        try:
            # Google returns JSONP-like format, extract JSON
            # Response: ["query",["sug1","sug2",...],...]
            data = json.loads(response_text)

            if isinstance(data, list) and len(data) >= 2:
                suggestions = data[1]
                if isinstance(suggestions, list):
                    return [s for s in suggestions if isinstance(s, str)]

            return []

        except json.JSONDecodeError as e:
            self.logger.debug(f"Failed to parse autocomplete JSON: {e}")
            return []
        except Exception as e:
            self.logger.debug(f"Error parsing suggestions: {e}")
            return []

    def get_suggestions(
        self,
        query: str,
        page: Optional[Page] = None,
        suggestion_type: str = "related",
    ) -> List[AutocompleteSuggestion]:
        """
        Get autocomplete suggestions for a query.

        Args:
            query: Search query
            page: Optional Playwright page (creates new session if not provided)
            suggestion_type: Type of suggestion for categorization

        Returns:
            list: AutocompleteSuggestion objects
        """
        query = query.strip().lower()

        if not query:
            return []

        # Check if already scraped
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        if query_hash in self._scraped_queries:
            self.logger.debug(f"Query already scraped: {query}")
            return []

        suggestions = []
        url = self._build_autocomplete_url(query)
        domain = urlparse(url).netloc

        # Use provided page or create new session
        if page:
            suggestions = self._fetch_suggestions(page, url, query, suggestion_type)
        else:
            with self.browser_session(domain=domain) as (browser, context, pg):
                with self._rate_limit_and_concurrency(domain):
                    suggestions = self._fetch_suggestions(pg, url, query, suggestion_type)

        # Mark query as scraped
        self._scraped_queries.add(query_hash)
        self.keyword_stats["queries_made"] += 1
        self.keyword_stats["suggestions_found"] += len(suggestions)

        return suggestions

    def _fetch_suggestions(
        self,
        page: Page,
        url: str,
        seed_query: str,
        suggestion_type: str,
    ) -> List[AutocompleteSuggestion]:
        """
        Fetch suggestions using Playwright.

        Args:
            page: Playwright page
            url: Autocomplete URL
            seed_query: Original query
            suggestion_type: Suggestion categorization

        Returns:
            list: Parsed suggestions
        """
        try:
            # Fetch the autocomplete endpoint
            response = page.goto(url, wait_until="domcontentloaded")

            if response is None:
                self.logger.warning(f"No response for: {seed_query}")
                return []

            if response.status == 429:
                self.logger.warning("Rate limited by Google autocomplete")
                self.keyword_stats["rate_limited"] += 1
                # Add extra delay
                time.sleep(random.uniform(30, 60))
                return []

            if response.status != 200:
                self.logger.warning(f"HTTP {response.status} for: {seed_query}")
                return []

            # Get response text
            content = page.content()

            # Extract text between <pre> tags (Chrome JSON format)
            pre_match = re.search(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
            if pre_match:
                json_text = pre_match.group(1)
            else:
                # Try getting raw text
                json_text = page.evaluate("document.body.innerText")

            # Parse suggestions
            raw_suggestions = self._parse_suggestions(json_text)

            # Convert to AutocompleteSuggestion objects
            suggestions = []
            for i, suggestion in enumerate(raw_suggestions[:self.max_suggestions]):
                # Clean the suggestion
                suggestion = suggestion.strip().lower()

                if suggestion and suggestion != seed_query:
                    # Calculate relevance score based on position
                    relevance = 1.0 - (i * 0.05)  # First = 1.0, decreases by 0.05

                    suggestions.append(AutocompleteSuggestion(
                        keyword=suggestion,
                        seed_keyword=seed_query,
                        source="google_autocomplete",
                        suggestion_type=suggestion_type,
                        relevance_score=max(0.5, relevance),
                        metadata={
                            "position": i + 1,
                            "country": self.country,
                            "language": self.language,
                        }
                    ))

            self.logger.debug(f"Found {len(suggestions)} suggestions for: {seed_query}")
            return suggestions

        except Exception as e:
            self.logger.error(f"Error fetching suggestions for '{seed_query}': {e}")
            return []

    def expand_keyword(
        self,
        seed_keyword: str,
        include_alphabet: bool = True,
        include_questions: bool = True,
        include_modifiers: bool = True,
        max_expansions: int = 100,
    ) -> List[AutocompleteSuggestion]:
        """
        Expand a seed keyword using multiple strategies.

        Strategies:
        - Alphabet expansion: "keyword a", "keyword b", ...
        - Question prefixes: "how to keyword", "what is keyword", ...
        - Intent modifiers: "keyword near me", "keyword reviews", ...

        Args:
            seed_keyword: Base keyword to expand
            include_alphabet: Add a-z suffix expansions
            include_questions: Add question prefix expansions
            include_modifiers: Add intent modifier expansions
            max_expansions: Maximum total suggestions to return

        Returns:
            list: All expanded suggestions (deduplicated)
        """
        seed_keyword = seed_keyword.strip().lower()
        all_suggestions: Dict[str, AutocompleteSuggestion] = {}
        domain = "www.google.com"

        self.logger.info(f"Expanding keyword: {seed_keyword}")

        with self.browser_session(domain=domain) as (browser, context, page):
            # 1. Get base suggestions
            with self._rate_limit_and_concurrency(domain):
                base_suggestions = self.get_suggestions(
                    seed_keyword, page, "related"
                )
                for s in base_suggestions:
                    all_suggestions[s.keyword] = s

            # 2. Alphabet expansion (keyword + a, keyword + b, ...)
            if include_alphabet and len(all_suggestions) < max_expansions:
                for letter in self.ALPHABET:
                    if len(all_suggestions) >= max_expansions:
                        break

                    query = f"{seed_keyword} {letter}"
                    with self._rate_limit_and_concurrency(domain):
                        suggestions = self.get_suggestions(query, page, "alphabet")
                        for s in suggestions:
                            if s.keyword not in all_suggestions:
                                all_suggestions[s.keyword] = s

            # 3. Question prefix expansion
            if include_questions and len(all_suggestions) < max_expansions:
                for prefix in self.QUESTION_PREFIXES[:10]:  # Limit prefixes
                    if len(all_suggestions) >= max_expansions:
                        break

                    query = f"{prefix} {seed_keyword}"
                    with self._rate_limit_and_concurrency(domain):
                        suggestions = self.get_suggestions(query, page, "question")
                        for s in suggestions:
                            if s.keyword not in all_suggestions:
                                all_suggestions[s.keyword] = s

            # 4. Intent modifier expansion
            if include_modifiers and len(all_suggestions) < max_expansions:
                for modifier in self.INTENT_MODIFIERS[:8]:  # Limit modifiers
                    if len(all_suggestions) >= max_expansions:
                        break

                    query = f"{seed_keyword} {modifier}"
                    with self._rate_limit_and_concurrency(domain):
                        suggestions = self.get_suggestions(query, page, "intent")
                        for s in suggestions:
                            if s.keyword not in all_suggestions:
                                all_suggestions[s.keyword] = s

        # Update stats
        self.keyword_stats["unique_keywords"] = len(all_suggestions)

        self.logger.info(
            f"Expanded '{seed_keyword}' to {len(all_suggestions)} unique keywords"
        )

        return list(all_suggestions.values())

    def get_related_questions(
        self,
        keyword: str,
    ) -> List[AutocompleteSuggestion]:
        """
        Get question-based suggestions for a keyword.

        Useful for content ideation and FAQ sections.

        Args:
            keyword: Target keyword

        Returns:
            list: Question-based suggestions
        """
        keyword = keyword.strip().lower()
        questions: Dict[str, AutocompleteSuggestion] = {}
        domain = "www.google.com"

        with self.browser_session(domain=domain) as (browser, context, page):
            for prefix in self.QUESTION_PREFIXES:
                query = f"{prefix} {keyword}"

                with self._rate_limit_and_concurrency(domain):
                    suggestions = self.get_suggestions(query, page, "question")

                    for s in suggestions:
                        # Only keep actual questions
                        if any(s.keyword.startswith(p) for p in ["what", "how", "why", "when", "where", "who", "can", "is", "does", "will", "should"]):
                            questions[s.keyword] = s

        self.logger.info(f"Found {len(questions)} questions for: {keyword}")
        return list(questions.values())

    def save_suggestions(
        self,
        suggestions: List[AutocompleteSuggestion],
        competitor_id: Optional[int] = None,
    ):
        """
        Save suggestions to database.

        Args:
            suggestions: List of suggestions to save
            competitor_id: Optional competitor ID to associate
        """
        if not suggestions:
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
            INSERT INTO keyword_suggestions (
                keyword, seed_keyword, source, suggestion_type,
                relevance_score, competitor_id, metadata, created_at
            ) VALUES (
                :keyword, :seed_keyword, :source, :suggestion_type,
                :relevance_score, :competitor_id, :metadata, :created_at
            )
            ON CONFLICT (keyword, seed_keyword) DO UPDATE SET
                relevance_score = GREATEST(keyword_suggestions.relevance_score, EXCLUDED.relevance_score),
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for suggestion in suggestions:
                try:
                    conn.execute(insert_sql, {
                        "keyword": suggestion.keyword,
                        "seed_keyword": suggestion.seed_keyword,
                        "source": suggestion.source,
                        "suggestion_type": suggestion.suggestion_type,
                        "relevance_score": suggestion.relevance_score,
                        "competitor_id": competitor_id,
                        "metadata": json.dumps(suggestion.metadata),
                        "created_at": suggestion.scraped_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving suggestion: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(suggestions)} suggestions to database")

    def run(
        self,
        seed_keywords: List[str],
        expand: bool = True,
        save_to_db: bool = True,
        competitor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run autocomplete scraper on multiple seed keywords.

        Args:
            seed_keywords: List of seed keywords to process
            expand: Whether to expand keywords with alphabet/questions
            save_to_db: Whether to save results to database
            competitor_id: Optional competitor ID to associate

        Returns:
            dict: Results with all suggestions and statistics
        """
        all_suggestions: List[AutocompleteSuggestion] = []

        for keyword in seed_keywords:
            self.logger.info(f"Processing keyword: {keyword}")

            if expand:
                suggestions = self.expand_keyword(
                    keyword,
                    include_alphabet=True,
                    include_questions=True,
                    include_modifiers=True,
                )
            else:
                suggestions = self.get_suggestions(keyword)

            all_suggestions.extend(suggestions)

        # Deduplicate
        unique_suggestions: Dict[str, AutocompleteSuggestion] = {}
        for s in all_suggestions:
            if s.keyword not in unique_suggestions:
                unique_suggestions[s.keyword] = s

        final_suggestions = list(unique_suggestions.values())

        # Save to database
        if save_to_db:
            self.save_suggestions(final_suggestions, competitor_id)

        return {
            "suggestions": final_suggestions,
            "total_unique": len(final_suggestions),
            "stats": self.keyword_stats,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get scraper statistics."""
        base_stats = super().get_stats()
        return {**base_stats, **self.keyword_stats}


# Module-level singleton
_autocomplete_scraper_instance = None


def get_autocomplete_scraper() -> AutocompleteScraper:
    """Get or create the singleton AutocompleteScraper instance."""
    global _autocomplete_scraper_instance

    if _autocomplete_scraper_instance is None:
        _autocomplete_scraper_instance = AutocompleteScraper()

    return _autocomplete_scraper_instance

"""
Google Autocomplete Scraper (SeleniumBase Version)

Scrapes Google Search autocomplete suggestions for keyword research.
Uses SeleniumBase with undetected Chrome for anti-detection.

Features:
- Seed keyword expansion with alphabet suffixes
- Question-based keyword discovery (who, what, when, where, why, how)
- Location-based keyword suggestions
- Multi-language support
- Database storage in keyword_suggestions table

Usage:
    from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium

    scraper = AutocompleteScraperSelenium()
    suggestions = scraper.get_suggestions("car wash near me")

    # Or expand with prefixes/suffixes
    all_keywords = scraper.expand_keyword("car wash", include_questions=True)

Uses SeleniumBase UC mode for better anti-detection than Playwright.
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

from selenium.webdriver.common.keys import Keys

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.services import get_task_logger, get_google_coordinator
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


class AutocompleteScraperSelenium(BaseSeleniumScraper):
    """
    Scrapes Google Search autocomplete suggestions using SeleniumBase.

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
            name="autocomplete_scraper_selenium",
            tier=tier,
            headless=True,
            use_proxy=False,
            max_retries=3,
            page_timeout=15000,
        )

        self.country = country
        self.language = language
        self.max_suggestions = max_suggestions_per_query
        self.logger = get_logger("autocomplete_scraper_selenium")

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
        driver=None,
        suggestion_type: str = "related",
        use_coordinator: bool = True,
    ) -> List[AutocompleteSuggestion]:
        """
        Get autocomplete suggestions for a query.

        Args:
            query: Search query
            driver: Optional Selenium driver (creates new session if not provided)
            suggestion_type: Type of suggestion for categorization
            use_coordinator: If True, use GoogleCoordinator for rate limiting
                           and SHARED browser session (recommended).
                           If False, use direct scraping (standalone mode).

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

        # If a driver is provided, use it directly (caller is managing coordination)
        if driver:
            suggestions = self._fetch_suggestions(driver, "", query, suggestion_type)
            self._scraped_queries.add(query_hash)
            self.keyword_stats["queries_made"] += 1
            self.keyword_stats["suggestions_found"] += len(suggestions)
            return suggestions

        # Use GoogleCoordinator if enabled (for SHARED browser with other Google modules)
        if use_coordinator:
            try:
                coordinator = get_google_coordinator()
                # Use execute() which provides the SHARED browser (same as SERP)
                suggestions = coordinator.execute(
                    "autocomplete",
                    lambda drv: self._fetch_suggestions(drv, "", query, suggestion_type),
                    priority=5
                )
                if suggestions is None:
                    suggestions = []
                self._scraped_queries.add(query_hash)
                self.keyword_stats["queries_made"] += 1
                self.keyword_stats["suggestions_found"] += len(suggestions)
                return suggestions
            except Exception as e:
                self.logger.warning(f"Coordinator failed, falling back to direct: {e}")

        # Direct scraping (standalone mode or fallback)
        return self._get_suggestions_direct(query, suggestion_type)

    def _get_suggestions_direct(
        self,
        query: str,
        suggestion_type: str = "related",
    ) -> List[AutocompleteSuggestion]:
        """
        Direct scraping implementation without coordinator.

        Args:
            query: Search query
            suggestion_type: Type of suggestion for categorization

        Returns:
            list: AutocompleteSuggestion objects
        """
        suggestions = []
        url = self._build_autocomplete_url(query)
        domain = urlparse(url).netloc

        # Use site="google" for human-like search box interaction (same as SerpScraperSelenium)
        with self.browser_session(site="google") as drv:
            with self._rate_limit_and_concurrency(domain):
                suggestions = self._fetch_suggestions(drv, url, query, suggestion_type)

        # Update stats (only for direct calls, coordinator path handles this above)
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        self._scraped_queries.add(query_hash)
        self.keyword_stats["queries_made"] += 1
        self.keyword_stats["suggestions_found"] += len(suggestions)

        return suggestions

    def _fetch_suggestions(
        self,
        driver,
        url: str,
        seed_query: str,
        suggestion_type: str,
    ) -> List[AutocompleteSuggestion]:
        """
        Fetch suggestions using human-like Google search box interaction.

        Uses the same technique as SerpScraperSelenium:
        1. Navigate to Google homepage
        2. Type query into search box with human-like delays
        3. Wait for autocomplete dropdown to appear
        4. Extract suggestions from the dropdown

        Args:
            driver: Selenium WebDriver
            url: Ignored - we go to Google homepage instead
            seed_query: Original query
            suggestion_type: Suggestion categorization

        Returns:
            list: Parsed suggestions
        """
        try:
            # Navigate to Google homepage (not the API endpoint)
            driver.get("https://www.google.com")
            time.sleep(random.uniform(1.0, 2.0))

            # Check for rate limiting or captcha
            content = driver.page_source.lower()
            if "unusual traffic" in content or "captcha" in content:
                self.logger.warning("Rate limited by Google - CAPTCHA detected")
                self.keyword_stats["rate_limited"] += 1
                time.sleep(random.uniform(30, 60))
                return []

            # Find search input
            search_input = None
            input_selectors = [
                'input[name="q"]',
                'textarea[name="q"]',
                'input[aria-label="Search"]',
            ]

            for selector in input_selectors:
                try:
                    search_input = self.wait_for_element(
                        driver, selector, timeout=10, condition="clickable"
                    )
                    if search_input:
                        break
                except Exception:
                    continue

            if not search_input:
                self.logger.warning("Could not find Google search input")
                return []

            # Click on search box with human-like behavior
            self._human_click(driver, search_input)
            time.sleep(random.uniform(0.3, 0.6))

            # Clear and type query with human-like delays
            search_input.clear()
            self._human_type(driver, search_input, seed_query, clear_first=False)

            # Wait for autocomplete dropdown to appear
            time.sleep(random.uniform(0.8, 1.5))

            # Extract suggestions from dropdown
            raw_suggestions = self._extract_dropdown_suggestions(driver)

            # Convert to AutocompleteSuggestion objects
            suggestions = []
            for i, suggestion_text in enumerate(raw_suggestions[:self.max_suggestions]):
                # Clean the suggestion
                suggestion_text = suggestion_text.strip().lower()

                if suggestion_text and suggestion_text != seed_query.lower():
                    # Calculate relevance score based on position
                    relevance = 1.0 - (i * 0.05)  # First = 1.0, decreases by 0.05

                    suggestions.append(AutocompleteSuggestion(
                        keyword=suggestion_text,
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

    def _extract_dropdown_suggestions(self, driver) -> List[str]:
        """
        Extract autocomplete suggestions from Google's dropdown.

        Args:
            driver: Selenium WebDriver

        Returns:
            list: Raw suggestion strings
        """
        suggestions = []

        # Various selectors for Google autocomplete dropdown
        dropdown_selectors = [
            'div[role="listbox"] li',
            'ul[role="listbox"] li',
            'div.sbct',
            'div.aajZCb div.lnnVSe',
            'div.UUbT9 div.wM6W7d',
            'div[jsname="bN97Pc"] li',
            'div.erkvQe li',
            'div.OBMEnb li',
        ]

        for selector in dropdown_selectors:
            try:
                elements = driver.find_elements("css selector", selector)
                if elements:
                    for elem in elements:
                        try:
                            text = elem.text.strip()
                            if text and len(text) > 1:
                                suggestions.append(text)
                        except Exception:
                            continue
                    if suggestions:
                        break
            except Exception:
                continue

        # Fallback: try to get suggestions from aria-label or data attributes
        if not suggestions:
            try:
                # Try getting elements with suggestion text
                elements = driver.find_elements("css selector", "[role='option']")
                for elem in elements:
                    try:
                        text = elem.text.strip() or elem.get_attribute("aria-label") or ""
                        if text and len(text) > 1:
                            suggestions.append(text)
                    except Exception:
                        continue
            except Exception:
                pass

        return suggestions

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

        # Use site="google" for human-like search box interaction (same as SerpScraperSelenium)
        with self.browser_session(site="google") as driver:
            # 1. Get base suggestions
            with self._rate_limit_and_concurrency(domain):
                base_suggestions = self.get_suggestions(
                    seed_keyword, driver, "related"
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
                        suggestions = self.get_suggestions(query, driver, "alphabet")
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
                        suggestions = self.get_suggestions(query, driver, "question")
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
                        suggestions = self.get_suggestions(query, driver, "intent")
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

        # Use site="google" for human-like search box interaction (same as SerpScraperSelenium)
        with self.browser_session(site="google") as driver:
            for prefix in self.QUESTION_PREFIXES:
                query = f"{prefix} {keyword}"

                with self._rate_limit_and_concurrency(domain):
                    suggestions = self.get_suggestions(query, driver, "question")

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
_autocomplete_scraper_selenium_instance = None


def get_autocomplete_scraper_selenium() -> AutocompleteScraperSelenium:
    """Get or create the singleton AutocompleteScraperSelenium instance."""
    global _autocomplete_scraper_selenium_instance

    if _autocomplete_scraper_selenium_instance is None:
        _autocomplete_scraper_selenium_instance = AutocompleteScraperSelenium()

    return _autocomplete_scraper_selenium_instance

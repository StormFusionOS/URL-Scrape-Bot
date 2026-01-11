"""
Review Aggregator

Aggregates review data from multiple sources for competitors:
- Google Business Profile
- Yelp
- Facebook
- BBB
- Angi/HomeAdvisor
- Thumbtack

Tracks:
- Rating averages
- Review counts and velocity
- Sentiment analysis
- Common complaints/praise
"""

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class ReviewAggregate:
    """Aggregated review data from a single source."""
    source: str
    rating_avg: Optional[float] = None
    review_count: int = 0
    review_count_7d: int = 0
    review_count_30d: int = 0
    sentiment_score: Optional[float] = None  # 0-100
    response_rate: Optional[float] = None  # 0-100
    top_complaints: List[str] = field(default_factory=list)
    top_praise: List[str] = field(default_factory=list)


class ReviewAggregator:
    """
    Aggregates review data from multiple platforms.

    Uses existing scrapers where available, and pattern matching
    for extracting review data from pages.
    """

    # Review source configurations
    SOURCES = {
        'google': {
            'url_pattern': 'google.com/maps|business.google.com',
            'rating_pattern': r'(\d+\.?\d*)\s*(?:stars?|rating)',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:reviews?|ratings?)',
        },
        'yelp': {
            'url_pattern': 'yelp.com/biz/',
            'rating_pattern': r'(\d+\.?\d*)\s*star',
            'count_pattern': r'(\d+(?:,\d+)*)\s*reviews?',
        },
        'facebook': {
            'url_pattern': 'facebook.com/',
            'rating_pattern': r'(\d+\.?\d*)\s*(?:out of 5|stars?)',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:reviews?|recommendations?)',
        },
        'bbb': {
            'url_pattern': 'bbb.org/us/',
            'rating_pattern': r'(\d+\.?\d*)/5|([A-F][+-]?)\s*rating',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:customer\s*)?reviews?',
        },
        'angi': {
            'url_pattern': 'angi.com/|angieslist.com/',
            'rating_pattern': r'(\d+\.?\d*)\s*(?:stars?|rating)',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:reviews?|ratings?)',
        },
        'thumbtack': {
            'url_pattern': 'thumbtack.com/',
            'rating_pattern': r'(\d+\.?\d*)\s*(?:stars?|rating)',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:reviews?|hires?)',
        },
        'homeadvisor': {
            'url_pattern': 'homeadvisor.com/',
            'rating_pattern': r'(\d+\.?\d*)\s*(?:stars?|rating)',
            'count_pattern': r'(\d+(?:,\d+)*)\s*(?:reviews?|ratings?)',
        },
    }

    # Sentiment keywords
    POSITIVE_KEYWORDS = [
        'excellent', 'great', 'amazing', 'wonderful', 'fantastic',
        'professional', 'friendly', 'thorough', 'reliable', 'quality',
        'recommend', 'best', 'perfect', 'impressed', 'outstanding',
        'prompt', 'efficient', 'honest', 'courteous', 'reasonable',
    ]

    NEGATIVE_KEYWORDS = [
        'terrible', 'awful', 'horrible', 'worst', 'bad',
        'unprofessional', 'rude', 'late', 'overpriced', 'poor',
        'avoid', 'never', 'disappointed', 'waste', 'scam',
        'slow', 'messy', 'incomplete', 'damaged', 'ignored',
    ]

    # Common complaint/praise categories
    COMPLAINT_CATEGORIES = {
        'pricing': ['expensive', 'overpriced', 'overcharged', 'hidden fees', 'price'],
        'communication': ['no response', 'didn\'t call', 'never showed', 'ghosted', 'no show'],
        'quality': ['poor quality', 'not clean', 'missed spots', 'incomplete', 'sloppy'],
        'timing': ['late', 'delayed', 'took forever', 'slow', 'behind schedule'],
        'damage': ['damaged', 'broke', 'scratched', 'ruined', 'destroyed'],
    }

    PRAISE_CATEGORIES = {
        'professionalism': ['professional', 'courteous', 'respectful', 'friendly'],
        'quality': ['thorough', 'detailed', 'perfect', 'spotless', 'excellent work'],
        'pricing': ['fair price', 'reasonable', 'good value', 'affordable'],
        'communication': ['responsive', 'great communication', 'kept informed', 'prompt'],
        'timeliness': ['on time', 'punctual', 'quick', 'efficient', 'fast'],
    }

    def __init__(self):
        self.db_manager = get_db_manager()

    def aggregate_reviews(self, competitor_id: int, domain: str) -> Dict[str, Any]:
        """
        Aggregate reviews from all sources for a competitor.

        Args:
            competitor_id: The competitor ID
            domain: Competitor's domain name

        Returns:
            Dict with aggregation results
        """
        results = []
        total_reviews = 0
        weighted_rating_sum = 0

        # Try to get reviews from each source
        for source, config in self.SOURCES.items():
            try:
                aggregate = self._get_source_reviews(competitor_id, domain, source, config)
                if aggregate and aggregate.review_count > 0:
                    results.append(aggregate)
                    total_reviews += aggregate.review_count
                    if aggregate.rating_avg:
                        weighted_rating_sum += aggregate.rating_avg * aggregate.review_count
            except Exception as e:
                logger.debug(f"Failed to get {source} reviews: {e}")

        # Calculate overall metrics
        overall_rating = None
        if total_reviews > 0 and weighted_rating_sum > 0:
            overall_rating = weighted_rating_sum / total_reviews

        # Save to database
        saved = self._save_aggregates(competitor_id, results)

        return {
            'success': True,
            'sources_found': len(results),
            'total_reviews': total_reviews,
            'overall_rating': overall_rating,
            'records_saved': saved,
        }

    def _get_source_reviews(self, competitor_id: int, domain: str,
                            source: str, config: Dict) -> Optional[ReviewAggregate]:
        """Get review data from a specific source."""
        # Try to find existing citation/listing for this source
        listing_url = self._find_listing_url(competitor_id, domain, source)

        if not listing_url:
            logger.debug(f"No {source} listing found for {domain}")
            return None

        # Scrape the listing page
        try:
            html = self._fetch_listing_page(listing_url)
            if not html:
                return None

            # Extract review data
            aggregate = self._parse_review_page(html, source, config)
            aggregate.source = source

            return aggregate

        except Exception as e:
            logger.error(f"Failed to scrape {source} for {domain}: {e}")
            return None

    def _find_listing_url(self, competitor_id: int, domain: str, source: str) -> Optional[str]:
        """Find the listing URL for a source from citations or discovery."""
        # Map source names to directory patterns
        source_patterns = {
            'google': ['google', 'gbp', 'google business'],
            'yelp': ['yelp'],
            'facebook': ['facebook', 'fb'],
            'bbb': ['bbb', 'better business'],
            'angi': ['angi', 'angies', 'angie'],
            'thumbtack': ['thumbtack'],
            'homeadvisor': ['homeadvisor', 'home advisor'],
        }

        patterns = source_patterns.get(source, [source])

        try:
            with self.db_manager.get_session() as session:
                # Check citations table by directory_name
                for pattern in patterns:
                    result = session.execute(text("""
                        SELECT listing_url
                        FROM citations
                        WHERE LOWER(directory_name) LIKE :pattern
                          AND company_id IN (
                              SELECT company_id FROM company_competitors
                              WHERE competitor_id = :competitor_id
                          )
                        ORDER BY last_verified_at DESC NULLS LAST
                        LIMIT 1
                    """), {'pattern': f'%{pattern}%', 'competitor_id': competitor_id})

                    row = result.fetchone()
                    if row and row[0]:
                        return row[0]

                # Check discovery_citations as fallback
                for pattern in patterns:
                    result = session.execute(text("""
                        SELECT source_url
                        FROM discovery_citations
                        WHERE LOWER(source_name) LIKE :pattern
                          AND company_id IN (
                              SELECT company_id FROM company_competitors
                              WHERE competitor_id = :competitor_id
                          )
                        LIMIT 1
                    """), {'pattern': f'%{pattern}%', 'competitor_id': competitor_id})

                    row = result.fetchone()
                    if row and row[0]:
                        return row[0]

        except Exception as e:
            logger.debug(f"Error finding listing URL: {e}")

        return None

    def _fetch_listing_page(self, url: str) -> Optional[str]:
        """Fetch the HTML content of a listing page."""
        try:
            from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper

            scraper = BaseSeleniumScraper()
            result = scraper.fetch_page(url)

            if result and result.get('html'):
                return result['html']

        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")

        return None

    def _parse_review_page(self, html: str, source: str, config: Dict) -> ReviewAggregate:
        """Parse review data from HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        text_content = soup.get_text(separator=' ', strip=True)

        aggregate = ReviewAggregate(source=source)

        # Extract rating
        rating_pattern = config.get('rating_pattern', r'(\d+\.?\d*)\s*stars?')
        rating_match = re.search(rating_pattern, text_content, re.IGNORECASE)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
                if 0 <= rating <= 5:
                    aggregate.rating_avg = rating
            except (ValueError, IndexError):
                pass

        # Extract review count
        count_pattern = config.get('count_pattern', r'(\d+(?:,\d+)*)\s*reviews?')
        count_match = re.search(count_pattern, text_content, re.IGNORECASE)
        if count_match:
            try:
                count_str = count_match.group(1).replace(',', '')
                aggregate.review_count = int(count_str)
            except (ValueError, IndexError):
                pass

        # Calculate sentiment from visible review text
        aggregate.sentiment_score = self._calculate_sentiment(text_content)

        # Extract common themes
        aggregate.top_complaints = self._extract_themes(text_content, self.COMPLAINT_CATEGORIES)
        aggregate.top_praise = self._extract_themes(text_content, self.PRAISE_CATEGORIES)

        return aggregate

    def _calculate_sentiment(self, text: str) -> float:
        """Calculate a simple sentiment score (0-100)."""
        text_lower = text.lower()

        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text_lower)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text_lower)

        total = positive_count + negative_count
        if total == 0:
            return 50.0  # Neutral

        sentiment = (positive_count / total) * 100
        return round(sentiment, 1)

    def _extract_themes(self, text: str, categories: Dict[str, List[str]]) -> List[str]:
        """Extract common themes from review text."""
        text_lower = text.lower()
        found = []

        for category, keywords in categories.items():
            if any(kw in text_lower for kw in keywords):
                found.append(category)

        return found[:5]  # Top 5

    def _save_aggregates(self, competitor_id: int, aggregates: List[ReviewAggregate]) -> int:
        """Save aggregated review data to database."""
        saved = 0

        try:
            with self.db_manager.get_session() as session:
                for agg in aggregates:
                    query = text("""
                        INSERT INTO competitor_reviews_aggregate
                            (competitor_id, source, rating_avg, review_count,
                             review_count_7d, review_count_30d, sentiment_score,
                             response_rate, top_complaints, top_praise, captured_at)
                        VALUES
                            (:competitor_id, :source, :rating_avg, :review_count,
                             :review_count_7d, :review_count_30d, :sentiment_score,
                             :response_rate, :top_complaints, :top_praise, NOW())
                        ON CONFLICT (competitor_id, source, DATE(captured_at))
                        DO UPDATE SET
                            rating_avg = EXCLUDED.rating_avg,
                            review_count = EXCLUDED.review_count,
                            sentiment_score = EXCLUDED.sentiment_score,
                            top_complaints = EXCLUDED.top_complaints,
                            top_praise = EXCLUDED.top_praise
                    """)

                    import json
                    session.execute(query, {
                        'competitor_id': competitor_id,
                        'source': agg.source,
                        'rating_avg': agg.rating_avg,
                        'review_count': agg.review_count,
                        'review_count_7d': agg.review_count_7d,
                        'review_count_30d': agg.review_count_30d,
                        'sentiment_score': agg.sentiment_score,
                        'response_rate': agg.response_rate,
                        'top_complaints': json.dumps(agg.top_complaints),
                        'top_praise': json.dumps(agg.top_praise),
                    })
                    saved += 1

                session.commit()
                logger.info(f"Saved {saved} review aggregates for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Failed to save review aggregates: {e}")

        return saved

    def get_review_summary(self, competitor_id: int) -> Dict[str, Any]:
        """Get the latest review summary for a competitor."""
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text("""
                    SELECT source, rating_avg, review_count, sentiment_score,
                           top_complaints, top_praise, captured_at
                    FROM competitor_reviews_aggregate
                    WHERE competitor_id = :competitor_id
                      AND captured_at > NOW() - INTERVAL '7 days'
                    ORDER BY captured_at DESC
                """), {'competitor_id': competitor_id})

                rows = result.fetchall()

                if not rows:
                    return {'sources': [], 'total_reviews': 0}

                sources = []
                total_reviews = 0
                weighted_sum = 0

                for row in rows:
                    source_data = {
                        'source': row[0],
                        'rating': row[1],
                        'count': row[2],
                        'sentiment': row[3],
                    }
                    sources.append(source_data)
                    total_reviews += row[2] or 0
                    if row[1] and row[2]:
                        weighted_sum += row[1] * row[2]

                overall = weighted_sum / total_reviews if total_reviews > 0 else None

                return {
                    'sources': sources,
                    'total_reviews': total_reviews,
                    'overall_rating': overall,
                }

        except Exception as e:
            logger.error(f"Failed to get review summary: {e}")
            return {'sources': [], 'total_reviews': 0}


def aggregate_reviews_for_competitor(competitor_id: int, domain: str) -> Dict[str, Any]:
    """
    Main entry point for review aggregation.

    Args:
        competitor_id: Competitor to aggregate reviews for
        domain: Competitor's domain

    Returns:
        Dict with success status and aggregation results
    """
    aggregator = ReviewAggregator()
    return aggregator.aggregate_reviews(competitor_id, domain)

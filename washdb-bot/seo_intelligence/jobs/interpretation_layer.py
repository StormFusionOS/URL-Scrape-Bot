#!/usr/bin/env python3
"""
Post-Scrape Interpretation Layer

Generates AI-ready insights from raw scrape data:
- Competitor page diffs with "why it matters" bullets
- SERP changes and intent shifts
- PAA question candidates for FAQ
- Actionable recommendations

Per scraper-fixes.md #10: Create a post-scrape "interpretation layer"
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


class ScrapeInsightGenerator:
    """
    Generates insights from scrape data.

    Transforms raw data into actionable intelligence.
    """

    def __init__(self):
        self.engine = create_engine(os.getenv("DATABASE_URL"))

    def generate_competitor_insights(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Generate insights from recent competitor page changes.

        Args:
            days: Look back period

        Returns:
            List of insight dictionaries
        """
        with self.engine.connect() as conn:
            # Find pages that were updated recently
            result = conn.execute(text("""
                SELECT
                    c.name as competitor_name,
                    c.domain,
                    cp.url,
                    cp.page_type,
                    cp.metadata,
                    cp.last_crawled_at,
                    cp.content_hash
                FROM competitor_pages cp
                JOIN competitors c ON cp.competitor_id = c.competitor_id
                WHERE cp.last_crawled_at >= NOW() - INTERVAL ':days days'
                ORDER BY cp.last_crawled_at DESC
                LIMIT 50
            """).bindparams(days=days))

            insights = []
            for row in result.fetchall():
                metadata = json.loads(row.metadata) if row.metadata else {}

                # Determine insight type and importance
                insight = {
                    "type": "competitor_update",
                    "competitor": row.competitor_name,
                    "domain": row.domain,
                    "url": row.url,
                    "page_type": row.page_type,
                    "detected_at": row.last_crawled_at.isoformat() if row.last_crawled_at else None,
                    "importance": self._calculate_importance(row.page_type, metadata),
                    "summary": self._generate_summary(row.page_type, metadata),
                    "action_items": self._generate_actions(row.page_type, metadata)
                }
                insights.append(insight)

            return insights

    def generate_serp_insights(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Generate insights from SERP changes.

        Returns:
            List of SERP change insights
        """
        with self.engine.connect() as conn:
            # Find recent SERP snapshots
            result = conn.execute(text("""
                SELECT
                    sq.query_text,
                    sq.location,
                    ss.captured_at,
                    ss.result_count,
                    ss.metadata
                FROM serp_snapshots ss
                JOIN search_queries sq ON ss.query_id = sq.query_id
                WHERE ss.captured_at >= NOW() - INTERVAL ':days days'
                ORDER BY ss.captured_at DESC
                LIMIT 30
            """).bindparams(days=days))

            insights = []
            for row in result.fetchall():
                metadata = json.loads(row.metadata) if isinstance(row.metadata, str) else (row.metadata or {})

                insight = {
                    "type": "serp_snapshot",
                    "query": row.query_text,
                    "location": row.location,
                    "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                    "result_count": row.result_count,
                    "features": metadata.get("serp_features", []),
                    "summary": f"SERP for '{row.query_text}' captured with {row.result_count} results"
                }
                insights.append(insight)

            return insights

    def generate_paa_insights(self) -> List[Dict[str, Any]]:
        """
        Generate FAQ candidates from People Also Ask data.

        Returns:
            List of PAA questions suitable for FAQ content
        """
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    paa.question,
                    paa.answer_snippet,
                    sq.query_text,
                    paa.position,
                    COUNT(*) OVER (PARTITION BY paa.question) as frequency
                FROM serp_paa paa
                JOIN serp_snapshots ss ON paa.snapshot_id = ss.snapshot_id
                JOIN search_queries sq ON ss.query_id = sq.query_id
                ORDER BY frequency DESC, paa.position ASC
                LIMIT 50
            """))

            insights = []
            seen_questions = set()
            for row in result.fetchall():
                if row.question in seen_questions:
                    continue
                seen_questions.add(row.question)

                insight = {
                    "type": "faq_candidate",
                    "question": row.question,
                    "answer_snippet": row.answer_snippet,
                    "source_query": row.query_text,
                    "frequency": row.frequency,
                    "priority": "high" if row.frequency >= 3 else "medium" if row.frequency >= 2 else "low",
                    "action": "Consider adding this question to your FAQ page"
                }
                insights.append(insight)

            return insights

    def generate_keyword_gap_insights(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Generate insights from keyword gaps.

        Returns:
            High-opportunity keyword recommendations
        """
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    query_text,
                    our_domain,
                    competitor_count,
                    avg_competitor_position,
                    our_position,
                    opportunity_score
                FROM keyword_gaps
                WHERE opportunity_score >= 80
                ORDER BY opportunity_score DESC
                LIMIT :limit
            """), {"limit": limit})

            insights = []
            for row in result.fetchall():
                insight = {
                    "type": "keyword_opportunity",
                    "keyword": row.query_text,
                    "domain": row.our_domain,
                    "competitors_ranking": row.competitor_count,
                    "avg_competitor_rank": float(row.avg_competitor_position) if row.avg_competitor_position else None,
                    "our_rank": row.our_position,
                    "opportunity_score": float(row.opportunity_score) if row.opportunity_score else None,
                    "action": self._generate_keyword_action(row)
                }
                insights.append(insight)

            return insights

    def _calculate_importance(self, page_type: str, metadata: Dict) -> str:
        """Calculate importance level of a page update."""
        high_value_types = ["services", "homepage", "pricing"]
        if page_type in high_value_types:
            return "high"
        elif page_type in ["blog", "about", "locations"]:
            return "medium"
        return "low"

    def _generate_summary(self, page_type: str, metadata: Dict) -> str:
        """Generate a human-readable summary of page changes."""
        title = metadata.get("title", "Unknown page")
        return f"Competitor updated their {page_type} page: {title}"

    def _generate_actions(self, page_type: str, metadata: Dict) -> List[str]:
        """Generate action items based on page type."""
        actions = []
        if page_type == "services":
            actions.append("Review if competitor added new services")
            actions.append("Check for new pricing information")
        elif page_type == "blog":
            actions.append("Analyze topic for content gap opportunity")
        elif page_type == "locations":
            actions.append("Check for new service areas")
        return actions

    def _generate_keyword_action(self, row) -> str:
        """Generate action for keyword opportunity."""
        if row.our_position is None:
            return f"Create content targeting '{row.query_text}' - {row.competitor_count} competitors rank, you don't"
        elif row.our_position > 10:
            return f"Optimize existing content for '{row.query_text}' - currently rank #{row.our_position}"
        return f"Monitor '{row.query_text}' - good opportunity for improvement"


def generate_all_insights(days: int = 7) -> Dict[str, List[Dict]]:
    """
    Generate all insights from recent scrape data.

    Returns dictionary with all insight types.
    """
    generator = ScrapeInsightGenerator()

    return {
        "generated_at": datetime.now().isoformat(),
        "lookback_days": days,
        "competitor_insights": generator.generate_competitor_insights(days),
        "serp_insights": generator.generate_serp_insights(days),
        "paa_insights": generator.generate_paa_insights(),
        "keyword_opportunities": generator.generate_keyword_gap_insights()
    }


def save_insights_to_file(output_path: str = None, days: int = 7):
    """
    Generate insights and save to JSON file.
    """
    if output_path is None:
        output_path = f"/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/insights_{datetime.now().strftime('%Y%m%d')}.json"

    insights = generate_all_insights(days)

    with open(output_path, 'w') as f:
        json.dump(insights, f, indent=2, default=str)

    print(f"Insights saved to {output_path}")
    print(f"  Competitor updates: {len(insights['competitor_insights'])}")
    print(f"  SERP snapshots: {len(insights['serp_insights'])}")
    print(f"  FAQ candidates: {len(insights['paa_insights'])}")
    print(f"  Keyword opportunities: {len(insights['keyword_opportunities'])}")

    return output_path


if __name__ == "__main__":
    save_insights_to_file()

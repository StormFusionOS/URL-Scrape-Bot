#!/usr/bin/env python3
"""
Analysis Jobs for Derived Intelligence Tables

Populates:
- keyword_metrics: Volume signals, difficulty, opportunity scores
- keyword_gaps: Keywords competitors rank for but we don't
- competitive_analysis: Aggregated gap analysis per company
- topic_clusters: Grouped related keywords

These jobs run after scrape cycles to compute analysis from raw data.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


class KeywordMetricsJob:
    """
    Compute keyword metrics from SERP and research data.

    Populates keyword_metrics table with:
    - volume_tier (1-5 based on signals)
    - keyword_difficulty (0-100)
    - opportunity_score
    - search_intent classification
    """

    INTENT_KEYWORDS = {
        'transactional': ['buy', 'price', 'cost', 'hire', 'service', 'quote', 'near me', 'company', 'contractor'],
        'informational': ['how to', 'what is', 'why', 'guide', 'tips', 'best way', 'diy'],
        'navigational': ['login', 'contact', 'phone', 'address', 'hours'],
        'commercial': ['best', 'top', 'review', 'compare', 'vs', 'alternative']
    }

    def __init__(self):
        self.engine = create_engine(os.getenv("DATABASE_URL"))

    def classify_intent(self, keyword: str) -> str:
        """Classify search intent of a keyword."""
        keyword_lower = keyword.lower()
        for intent, signals in self.INTENT_KEYWORDS.items():
            for signal in signals:
                if signal in keyword_lower:
                    return intent
        return 'informational'  # default

    def estimate_volume_tier(self, keyword: str, serp_data: Dict) -> int:
        """
        Estimate volume tier (1-5) based on available signals.

        Tier 1: Very low volume (long-tail, specific)
        Tier 2: Low volume
        Tier 3: Medium volume
        Tier 4: High volume
        Tier 5: Very high volume (generic terms)
        """
        word_count = len(keyword.split())
        has_local = 'near me' in keyword.lower() or any(c.isupper() for c in keyword.split()[-1] if c.isalpha())

        # Longer keywords = lower volume
        if word_count >= 5:
            base_tier = 1
        elif word_count >= 4:
            base_tier = 2
        elif word_count >= 3:
            base_tier = 3
        elif word_count >= 2:
            base_tier = 4
        else:
            base_tier = 5

        # Local intent reduces apparent volume
        if has_local:
            base_tier = max(1, base_tier - 1)

        return base_tier

    def estimate_difficulty(self, serp_data: Dict) -> int:
        """
        Estimate keyword difficulty (0-100) based on SERP features.

        Factors:
        - Number of ads (more ads = more competitive)
        - Presence of featured snippets, knowledge panels
        - Authority of ranking domains
        """
        difficulty = 30  # base

        # Ads increase difficulty
        ads_count = serp_data.get('ads_count', 0)
        difficulty += min(ads_count * 5, 20)

        # SERP features
        if serp_data.get('featured_snippet'):
            difficulty += 10
        if serp_data.get('knowledge_panel'):
            difficulty += 5
        if serp_data.get('local_pack'):
            difficulty -= 5  # local pack = opportunity

        # PAA presence suggests moderate difficulty
        if serp_data.get('paa_count', 0) > 3:
            difficulty += 5

        return min(100, max(0, difficulty))

    def compute_opportunity(self, volume_tier: int, difficulty: int, our_position: Optional[int]) -> float:
        """
        Compute opportunity score (0-100).

        High opportunity = high volume, low difficulty, not already ranking well.
        """
        volume_factor = volume_tier * 20  # 20-100

        difficulty_factor = 100 - difficulty

        # Position factor: if we're not ranking, high opportunity
        # If ranking well, lower opportunity (already captured)
        if our_position is None:
            position_factor = 100
        elif our_position <= 3:
            position_factor = 20  # already winning
        elif our_position <= 10:
            position_factor = 60  # room to improve
        else:
            position_factor = 80  # good opportunity

        score = (volume_factor * 0.3 + difficulty_factor * 0.3 + position_factor * 0.4)
        return round(score, 2)

    def run(self, limit: int = 500) -> Dict[str, int]:
        """
        Process keywords and populate keyword_metrics.

        Returns counts of processed and inserted rows.
        """
        with self.engine.connect() as conn:
            # Get keywords from search_queries that aren't yet in keyword_metrics
            # Join with serp_snapshots to get SERP feature data
            result = conn.execute(text("""
                SELECT sq.query_text, sq.location, sq.metadata as query_metadata,
                       ss.metadata as serp_metadata, ss.result_count,
                       (SELECT MIN(sr.position) FROM serp_results sr
                        WHERE sr.snapshot_id = ss.snapshot_id AND sr.is_our_company = true) as our_position
                FROM search_queries sq
                LEFT JOIN serp_snapshots ss ON sq.query_id = ss.query_id
                LEFT JOIN keyword_metrics km ON sq.query_text = km.keyword_text
                WHERE km.metric_id IS NULL
                ORDER BY ss.captured_at DESC NULLS LAST
                LIMIT :limit
            """), {"limit": limit})

            keywords = result.fetchall()
            inserted = 0

            for kw in keywords:
                try:
                    # Handle both dict and string metadata
                    if isinstance(kw.serp_metadata, dict):
                        serp_data = kw.serp_metadata
                    elif kw.serp_metadata:
                        serp_data = json.loads(kw.serp_metadata)
                    else:
                        serp_data = {}
                    intent = self.classify_intent(kw.query_text)
                    volume_tier = self.estimate_volume_tier(kw.query_text, serp_data)
                    difficulty = self.estimate_difficulty(serp_data)
                    opportunity = self.compute_opportunity(volume_tier, difficulty, kw.our_position)

                    conn.execute(text("""
                        INSERT INTO keyword_metrics
                        (keyword_text, volume_tier, volume_signals, keyword_difficulty,
                         difficulty_factors, opportunity_score, current_position, search_intent)
                        VALUES (:keyword, :volume_tier, :volume_signals, :difficulty,
                                :difficulty_factors, :opportunity, :position, :intent)
                        ON CONFLICT (keyword_text) DO UPDATE SET
                            opportunity_score = EXCLUDED.opportunity_score,
                            current_position = EXCLUDED.current_position,
                            calculated_at = NOW()
                    """), {
                        "keyword": kw.query_text,
                        "volume_tier": volume_tier,
                        "volume_signals": json.dumps({"location": kw.location, "word_count": len(kw.query_text.split())}),
                        "difficulty": difficulty,
                        "difficulty_factors": json.dumps(serp_data),
                        "opportunity": opportunity,
                        "position": kw.our_position,
                        "intent": intent
                    })
                    inserted += 1

                except Exception as e:
                    print(f"Error processing keyword '{kw.query_text}': {e}")

            conn.commit()
            return {"processed": len(keywords), "inserted": inserted}


class KeywordGapsJob:
    """
    Identify keyword gaps where competitors rank but we don't.

    Populates keyword_gaps table by analyzing SERP results.
    """

    def __init__(self):
        self.engine = create_engine(os.getenv("DATABASE_URL"))

    def run(self, company_domain: str, limit: int = 100) -> Dict[str, int]:
        """
        Find keyword gaps for a specific company domain.

        A gap exists when:
        - Competitors rank in top 20 for a keyword
        - We don't rank or rank worse than competitors
        """
        with self.engine.connect() as conn:
            # Get keywords where competitors rank but we don't
            # Join serp_results with serp_snapshots to get query_text
            result = conn.execute(text("""
                WITH ranked_results AS (
                    SELECT
                        sq.query_text,
                        sr.url,
                        sr.position as rank,
                        sr.domain,
                        sr.is_our_company
                    FROM serp_results sr
                    JOIN serp_snapshots ss ON sr.snapshot_id = ss.snapshot_id
                    JOIN search_queries sq ON ss.query_id = sq.query_id
                    WHERE sr.position <= 20
                ),
                our_rankings AS (
                    SELECT
                        query_text,
                        MIN(rank) as our_position
                    FROM ranked_results
                    WHERE is_our_company = true
                       OR domain = :our_domain
                       OR domain LIKE '%' || :our_domain || '%'
                    GROUP BY query_text
                )
                SELECT
                    rr.query_text,
                    array_agg(DISTINCT rr.domain) as competitor_domains,
                    array_agg(rr.rank) as competitor_ranks,
                    COUNT(DISTINCT rr.domain) as competitor_count,
                    AVG(rr.rank) as avg_position,
                    our.our_position
                FROM ranked_results rr
                LEFT JOIN our_rankings our ON rr.query_text = our.query_text
                WHERE rr.is_our_company = false
                  AND (rr.domain IS NULL OR rr.domain != :our_domain)
                  AND (our.our_position IS NULL OR our.our_position > 10)
                GROUP BY rr.query_text, our.our_position
                HAVING COUNT(DISTINCT rr.domain) >= 1
                ORDER BY COUNT(DISTINCT rr.domain) DESC
                LIMIT :limit
            """), {"our_domain": company_domain, "limit": limit})

            gaps = result.fetchall()
            inserted = 0

            for gap in gaps:
                try:
                    competitor_rankings = {
                        domain: rank
                        for domain, rank in zip(gap.competitor_domains, gap.competitor_ranks)
                    }

                    # Calculate opportunity score
                    opportunity = self._calculate_gap_opportunity(
                        competitor_count=gap.competitor_count,
                        avg_position=float(gap.avg_position) if gap.avg_position else 15,
                        our_position=gap.our_position
                    )

                    conn.execute(text("""
                        INSERT INTO keyword_gaps
                        (our_domain, query_text, competitor_rankings, competitor_count,
                         avg_competitor_position, our_position, opportunity_score, status)
                        VALUES (:domain, :query, CAST(:rankings AS jsonb), :count,
                                :avg_pos, :our_pos, :opportunity, 'identified')
                        ON CONFLICT (our_domain, query_text) DO UPDATE SET
                            competitor_rankings = EXCLUDED.competitor_rankings,
                            competitor_count = EXCLUDED.competitor_count,
                            avg_competitor_position = EXCLUDED.avg_competitor_position,
                            our_position = EXCLUDED.our_position,
                            opportunity_score = EXCLUDED.opportunity_score,
                            updated_at = NOW()
                    """), {
                        "domain": company_domain,
                        "query": gap.query_text,
                        "rankings": json.dumps(competitor_rankings),
                        "count": gap.competitor_count,
                        "avg_pos": gap.avg_position,
                        "our_pos": gap.our_position,
                        "opportunity": opportunity
                    })
                    inserted += 1

                except Exception as e:
                    print(f"Error processing gap '{gap.query_text}': {e}")

            conn.commit()
            return {"processed": len(gaps), "inserted": inserted}

    def _calculate_gap_opportunity(
        self,
        competitor_count: int,
        avg_position: float,
        our_position: Optional[int]
    ) -> float:
        """Calculate opportunity score for a keyword gap."""
        # More competitors = validated keyword
        competitor_factor = min(competitor_count * 10, 40)

        # Higher avg position = easier to outrank
        position_factor = max(0, 40 - avg_position * 2)

        # If we don't rank, high opportunity
        if our_position is None:
            our_factor = 40
        elif our_position > 20:
            our_factor = 30
        else:
            our_factor = 20

        return round(competitor_factor + position_factor + our_factor, 2)


class CompetitiveAnalysisJob:
    """
    Aggregate competitive analysis per company.

    Populates competitive_analysis with gap counts and details.
    """

    def __init__(self):
        self.engine = create_engine(os.getenv("DATABASE_URL"))

    def run(self, company_id: int, company_domain: str) -> Dict[str, Any]:
        """
        Run competitive analysis for a company.

        Aggregates:
        - Keyword gaps count
        - Content gaps (unique page types across all competitors)
        - Backlink gaps (referring domains linking to competitors)
        """
        with self.engine.connect() as conn:
            # Count keyword gaps for this company
            kw_result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM keyword_gaps
                WHERE our_domain = :domain
            """), {"domain": company_domain})
            keyword_gaps = kw_result.scalar() or 0

            # Count unique content types across all competitors
            content_result = conn.execute(text("""
                SELECT COUNT(DISTINCT page_type) as types,
                       COUNT(*) as pages
                FROM competitor_pages
                WHERE page_type IS NOT NULL
                  AND page_type != 'unknown'
                  AND page_type != 'other'
            """))
            content_data = content_result.fetchone()
            content_gaps = content_data.types if content_data else 0

            # Count backlink gaps (domains linking to competitors but not our company)
            backlink_result = conn.execute(text("""
                SELECT COUNT(DISTINCT source_domain) as domains
                FROM backlinks
                WHERE target_domain != :domain
            """), {"domain": company_domain})
            backlink_gaps = backlink_result.scalar() or 0

            # Build details
            details = {
                "keyword_gap_opportunities": keyword_gaps,
                "content_types_missing": content_data.types if content_data else 0,
                "backlink_domains_missing": backlink_gaps,
                "analyzed_at": datetime.now().isoformat()
            }

            # Insert/update
            conn.execute(text("""
                INSERT INTO competitive_analysis
                (company_id, keyword_gaps, content_gaps, backlink_gaps, details)
                VALUES (:company_id, :kw_gaps, :content_gaps, :bl_gaps, CAST(:details AS jsonb))
                ON CONFLICT (company_id) DO UPDATE SET
                    keyword_gaps = EXCLUDED.keyword_gaps,
                    content_gaps = EXCLUDED.content_gaps,
                    backlink_gaps = EXCLUDED.backlink_gaps,
                    details = EXCLUDED.details,
                    analyzed_at = NOW(),
                    updated_at = NOW()
            """), {
                "company_id": company_id,
                "kw_gaps": keyword_gaps,
                "content_gaps": content_gaps,
                "bl_gaps": backlink_gaps,
                "details": json.dumps(details)
            })
            conn.commit()

            return {
                "company_id": company_id,
                "keyword_gaps": keyword_gaps,
                "content_gaps": content_gaps,
                "backlink_gaps": backlink_gaps
            }


def run_all_analysis_jobs(limit: int = 100):
    """
    Run all analysis jobs.

    Called after scrape cycles to update derived tables.
    """
    print("=" * 60)
    print(f"Running Analysis Jobs at {datetime.now()}")
    print("=" * 60)

    # 1. Keyword Metrics
    print("\n1. Keyword Metrics Job")
    kw_job = KeywordMetricsJob()
    kw_result = kw_job.run(limit=limit)
    print(f"   Processed: {kw_result['processed']}, Inserted: {kw_result['inserted']}")

    # 2. Keyword Gaps (for verified companies with domains)
    print("\n2. Keyword Gaps Job")
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        companies = conn.execute(text("""
            SELECT id, domain
            FROM companies
            WHERE verified = true
              AND domain IS NOT NULL
              AND domain != ''
            LIMIT 10
        """)).fetchall()

    gaps_job = KeywordGapsJob()
    total_gaps = 0
    for company in companies:
        result = gaps_job.run(company.domain, limit=50)
        total_gaps += result['inserted']
        print(f"   {company.domain}: {result['inserted']} gaps")
    print(f"   Total gaps identified: {total_gaps}")

    # 3. Competitive Analysis
    print("\n3. Competitive Analysis Job")
    analysis_job = CompetitiveAnalysisJob()
    for company in companies:
        result = analysis_job.run(company.id, company.domain)
        print(f"   {company.domain}: KW={result['keyword_gaps']}, Content={result['content_gaps']}, BL={result['backlink_gaps']}")

    print("\n" + "=" * 60)
    print("Analysis Jobs Complete")
    print("=" * 60)


if __name__ == "__main__":
    run_all_analysis_jobs()

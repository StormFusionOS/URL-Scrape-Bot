"""
Keyword Assigner Module.

Implements 4-tier keyword assignment system for SEO tracking:
- Tier 1: Service-specific seeds from verification_services.json
- Tier 2: Location variants (seed + city)
- Tier 3: Competitor gap keywords
- Tier 4: Long-tail from autocomplete expansion
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database_manager import get_db_manager

logger = logging.getLogger(__name__)


class KeywordAssigner:
    """
    Assigns keywords to companies using 4-tier strategy.
    """

    # Path to verification services JSON
    SERVICES_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "verification_services.json"

    # Maximum keywords per company
    MAX_KEYWORDS_PER_COMPANY = 100

    def __init__(self, db_manager=None, use_autocomplete: bool = False):
        """
        Initialize the keyword assigner.

        Args:
            db_manager: Database manager instance (optional, will get singleton if not provided)
            use_autocomplete: Whether to use AutocompleteScraper for Tier 4 (slow, rate-limited)
        """
        self.db_manager = db_manager or get_db_manager()
        self.use_autocomplete = use_autocomplete
        self._services_data = None

    @property
    def services_data(self) -> Dict:
        """Load services data lazily."""
        if self._services_data is None:
            self._services_data = self._load_services_json()
        return self._services_data

    def _load_services_json(self) -> Dict:
        """Load verification_services.json."""
        try:
            with open(self.SERVICES_JSON_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"verification_services.json not found at {self.SERVICES_JSON_PATH}")
            return {"pressure": {"keywords": []}, "window": {"keywords": []}, "wood": {"keywords": []}}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing verification_services.json: {e}")
            return {"pressure": {"keywords": []}, "window": {"keywords": []}, "wood": {"keywords": []}}

    def assign_keywords_for_company(self, company_id: int) -> Tuple[int, Dict[str, int]]:
        """
        Assign initial keywords to a company using 4-tier strategy.

        Args:
            company_id: The company ID to assign keywords to

        Returns:
            Tuple of (total_inserted, tier_counts_dict)
        """
        with self.db_manager.get_session() as session:
            # Get company data
            company = self._get_company(session, company_id)
            if not company:
                logger.warning(f"Company {company_id} not found")
                return 0, {}

            # Check if company is eligible
            if not company.get('verified') or not company.get('standardized_name'):
                logger.warning(f"Company {company_id} not eligible (verified={company.get('verified')}, standardized_name={company.get('standardized_name')})")
                return 0, {}

            logger.info(f"Assigning keywords for company {company_id}: {company.get('standardized_name')}")

            # Tier 1: Service-specific seeds
            services = self._extract_services(company)
            tier1_keywords = self._get_tier1_keywords(services)
            logger.info(f"  Tier 1: {len(tier1_keywords)} service seed keywords")

            # Tier 2: Location variants
            city = self._extract_city(company)
            tier2_keywords = self._get_tier2_keywords(tier1_keywords, city)
            logger.info(f"  Tier 2: {len(tier2_keywords)} location variant keywords")

            # Tier 3: Competitor gap keywords (if we have competitor data)
            domain = company.get('domain', '')
            tier3_keywords = self._get_tier3_keywords(session, domain)
            logger.info(f"  Tier 3: {len(tier3_keywords)} competitor gap keywords")

            # Tier 4: Autocomplete expansion (optional, slow)
            tier4_keywords = []
            if self.use_autocomplete:
                tier4_keywords = self._get_tier4_keywords(tier1_keywords[:5])
                logger.info(f"  Tier 4: {len(tier4_keywords)} autocomplete keywords")

            # Combine and deduplicate
            all_keywords = self._combine_and_deduplicate(
                tier1_keywords, tier2_keywords, tier3_keywords, tier4_keywords
            )[:self.MAX_KEYWORDS_PER_COMPANY]

            # Build keyword list with tiers and sources
            keyword_entries = []
            for kw in tier1_keywords:
                if kw in all_keywords:
                    keyword_entries.append((kw, 'service_seed', 1))
            for kw in tier2_keywords:
                if kw in all_keywords and kw not in [k[0] for k in keyword_entries]:
                    keyword_entries.append((kw, 'location_variant', 2))
            for kw in tier3_keywords:
                if kw in all_keywords and kw not in [k[0] for k in keyword_entries]:
                    keyword_entries.append((kw, 'competitor_gap', 3))
            for kw in tier4_keywords:
                if kw in all_keywords and kw not in [k[0] for k in keyword_entries]:
                    keyword_entries.append((kw, 'autocomplete', 4))

            # Insert into database
            inserted = self._bulk_insert_keywords(session, company_id, keyword_entries)

            # Count by tier
            tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            for _, _, tier in keyword_entries[:inserted]:
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            logger.info(f"  Total: {inserted} keywords assigned (T1:{tier_counts[1]}, T2:{tier_counts[2]}, T3:{tier_counts[3]}, T4:{tier_counts[4]})")

            return inserted, tier_counts

    def _get_company(self, session: Session, company_id: int) -> Optional[Dict]:
        """Get company data by ID."""
        query = text("""
            SELECT id, name, domain, service_area, verified, standardized_name,
                   city, state, parse_metadata
            FROM companies
            WHERE id = :company_id
        """)
        result = session.execute(query, {"company_id": company_id})
        row = result.fetchone()
        if row:
            return {
                'company_id': row[0],
                'name': row[1],
                'domain': row[2],
                'service_area': row[3],
                'verified': row[4],
                'standardized_name': row[5],
                'city': row[6],
                'state': row[7],
                'parse_metadata': row[8]
            }
        return None

    def _extract_services(self, company: Dict) -> List[str]:
        """
        Extract service types from company metadata.

        Returns list of service categories: ['pressure', 'window', 'wood']
        """
        services = []

        # Try to extract from parse_metadata (LLM classification)
        metadata = company.get('parse_metadata') or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}

        # Check for LLM classification
        llm_classification = metadata.get('llm_classification', {})
        if isinstance(llm_classification, dict):
            classified_services = llm_classification.get('services', [])
            if classified_services:
                for svc in classified_services:
                    svc_lower = svc.lower()
                    if 'pressure' in svc_lower or 'power wash' in svc_lower or 'soft wash' in svc_lower:
                        services.append('pressure')
                    elif 'window' in svc_lower or 'glass' in svc_lower:
                        services.append('window')
                    elif 'deck' in svc_lower or 'fence' in svc_lower or 'wood' in svc_lower:
                        services.append('wood')

        # Fallback: Check company name for service hints
        if not services:
            name = (company.get('name') or company.get('standardized_name') or '').lower()
            if any(kw in name for kw in ['pressure', 'power wash', 'soft wash', 'house wash']):
                services.append('pressure')
            if any(kw in name for kw in ['window', 'glass']):
                services.append('window')
            if any(kw in name for kw in ['deck', 'fence', 'wood', 'stain']):
                services.append('wood')

        # Default to pressure washing (most common)
        if not services:
            services.append('pressure')

        return list(set(services))

    def _extract_city(self, company: Dict) -> Optional[str]:
        """Extract city from company data."""
        # First try direct city field
        city = company.get('city')
        if city:
            return city

        # Try service_area field
        service_area = company.get('service_area')
        if service_area:
            # Try to extract city from "City, State" format
            parts = service_area.split(',')
            if parts:
                return parts[0].strip()

        return None

    def _get_tier1_keywords(self, services: List[str]) -> List[str]:
        """
        Get Tier 1 keywords from verification_services.json.

        These are service-specific seed keywords.
        """
        keywords = []
        for service in services:
            service_data = self.services_data.get(service, {})
            service_keywords = service_data.get('keywords', [])
            keywords.extend(service_keywords)
        return list(set(keywords))

    def _get_tier2_keywords(self, tier1_keywords: List[str], city: Optional[str]) -> List[str]:
        """
        Get Tier 2 keywords by adding location to Tier 1 seeds.

        Format: "[service] [city]" and "[service] near me"
        """
        if not city:
            # Without city, just add "near me" variants
            return [f"{kw} near me" for kw in tier1_keywords[:10]]

        keywords = []
        # Take top 10 service keywords
        for kw in tier1_keywords[:10]:
            keywords.append(f"{kw} {city}")
            keywords.append(f"{kw} in {city}")

        # Add some "near me" variants
        for kw in tier1_keywords[:5]:
            keywords.append(f"{kw} near me")
            keywords.append(f"best {kw} near me")

        return keywords

    def _get_tier3_keywords(self, session: Session, domain: str) -> List[str]:
        """
        Get Tier 3 keywords from competitor gap analysis.

        These are keywords that competitors rank for but we don't.
        """
        if not domain:
            return []

        try:
            # Check if keyword_gaps table exists and has data for this domain
            # Use subquery to allow ORDER BY with DISTINCT
            query = text("""
                SELECT query_text FROM (
                    SELECT DISTINCT ON (query_text) query_text, opportunity_score
                    FROM keyword_gaps
                    WHERE our_domain = :domain
                      AND our_position IS NULL
                      AND opportunity_score > 40
                    ORDER BY query_text, opportunity_score DESC
                ) sub
                ORDER BY opportunity_score DESC
                LIMIT 20
            """)
            result = session.execute(query, {"domain": domain})
            rows = result.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            # Table might not exist or have data - rollback to clear failed transaction
            session.rollback()
            logger.debug(f"Could not get Tier 3 keywords: {e}")
            return []

    def _get_tier4_keywords(self, seed_keywords: List[str]) -> List[str]:
        """
        Get Tier 4 keywords via autocomplete expansion.

        This is slow and rate-limited. Only use when explicitly enabled.
        """
        keywords = []
        try:
            from seo_intelligence.scrapers.autocomplete_scraper_selenium import AutocompleteScraperSelenium

            scraper = AutocompleteScraperSelenium(headless=False, use_proxy=False)
            for seed in seed_keywords:
                try:
                    suggestions = scraper.expand_keyword(seed, max_expansions=10)
                    for suggestion in suggestions:
                        if hasattr(suggestion, 'keyword'):
                            keywords.append(suggestion.keyword)
                        elif isinstance(suggestion, str):
                            keywords.append(suggestion)
                    time.sleep(15)  # Rate limit between keywords
                except Exception as e:
                    logger.warning(f"Autocomplete failed for '{seed}': {e}")

        except ImportError:
            logger.warning("AutocompleteScraperSelenium not available for Tier 4")
        except Exception as e:
            logger.warning(f"Tier 4 autocomplete expansion failed: {e}")

        return keywords

    def _combine_and_deduplicate(self, tier1: List[str], tier2: List[str],
                                  tier3: List[str], tier4: List[str]) -> List[str]:
        """Combine and deduplicate keywords, preserving priority order."""
        seen = set()
        combined = []

        # Priority: Tier 1 > Tier 2 > Tier 3 > Tier 4
        for kw_list in [tier1, tier2, tier3, tier4]:
            for kw in kw_list:
                kw_lower = kw.lower().strip()
                if kw_lower and kw_lower not in seen:
                    seen.add(kw_lower)
                    combined.append(kw)

        return combined

    def _bulk_insert_keywords(self, session: Session, company_id: int,
                               keywords: List[Tuple[str, str, int]]) -> int:
        """
        Bulk insert keywords into keyword_company_tracking table.

        Args:
            session: Database session
            company_id: Company ID
            keywords: List of (keyword_text, source, tier) tuples

        Returns:
            Number of keywords inserted
        """
        inserted = 0
        for keyword_text, source, tier in keywords:
            try:
                query = text("""
                    INSERT INTO keyword_company_tracking
                        (company_id, keyword_text, source, assignment_tier, status, reason)
                    VALUES
                        (:company_id, :keyword_text, :source, :tier, 'tracking', :reason)
                    ON CONFLICT (company_id, keyword_text) DO NOTHING
                """)
                result = session.execute(query, {
                    "company_id": company_id,
                    "keyword_text": keyword_text,
                    "source": source,
                    "tier": tier,
                    "reason": f"Initial assignment: Tier {tier} from {source}"
                })
                if result.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.debug(f"Failed to insert keyword '{keyword_text}': {e}")

        session.commit()
        return inserted

    def get_company_keywords(self, company_id: int) -> List[Dict]:
        """
        Get all keywords assigned to a company.

        Returns list of keyword dicts with tracking info.
        """
        with self.db_manager.get_session() as session:
            query = text("""
                SELECT tracking_id, keyword_text, source, assignment_tier, status,
                       current_position, best_position, opportunity_score,
                       last_checked_at, assigned_at
                FROM keyword_company_tracking
                WHERE company_id = :company_id
                ORDER BY assignment_tier ASC, opportunity_score DESC NULLS LAST
            """)
            result = session.execute(query, {"company_id": company_id})
            rows = result.fetchall()
            return [{
                'tracking_id': row[0],
                'keyword_text': row[1],
                'source': row[2],
                'tier': row[3],
                'status': row[4],
                'position': row[5],
                'best_position': row[6],
                'opportunity_score': row[7],
                'last_checked_at': row[8],
                'assigned_at': row[9]
            } for row in rows]

    def expand_keywords_for_company(self, company_id: int) -> int:
        """
        Expand keywords for a company with Tier 3 + 4 keywords.

        Use this for quarterly refresh to add new keywords.

        Returns number of new keywords added.
        """
        with self.db_manager.get_session() as session:
            company = self._get_company(session, company_id)
            if not company:
                return 0

            domain = company.get('domain', '')
            services = self._extract_services(company)

            # Get existing keywords to avoid duplicates
            existing_query = text("""
                SELECT keyword_text FROM keyword_company_tracking
                WHERE company_id = :company_id
            """)
            result = session.execute(existing_query, {"company_id": company_id})
            existing = {row[0].lower() for row in result.fetchall()}

            # Tier 3: New competitor gaps
            tier3_keywords = self._get_tier3_keywords(session, domain)
            new_tier3 = [(kw, 'competitor_gap', 3) for kw in tier3_keywords
                         if kw.lower() not in existing]

            # Tier 4: Expand with autocomplete if enabled
            new_tier4 = []
            if self.use_autocomplete:
                tier1_keywords = self._get_tier1_keywords(services)
                tier4_keywords = self._get_tier4_keywords(tier1_keywords[:3])
                new_tier4 = [(kw, 'autocomplete', 4) for kw in tier4_keywords
                             if kw.lower() not in existing]

            # Combine and insert
            new_keywords = new_tier3 + new_tier4
            inserted = self._bulk_insert_keywords(session, company_id, new_keywords)

            logger.info(f"Expanded keywords for company {company_id}: {inserted} new keywords")
            return inserted

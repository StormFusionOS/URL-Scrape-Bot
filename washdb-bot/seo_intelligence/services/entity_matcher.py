"""
Entity Matcher Service

Implements entity resolution and deduplication for companies using multiple
matching strategies:

1. Domain-first: Same domain → same company
2. Phone+City: E.164 phone and city match → likely same business
3. Fuzzy name: Similar names at similar locations → potential duplicate
4. Conflict detection: Phone match but name mismatch → shared number/call center

Conflicts are recorded in company_conflicts table for manual review.

Usage:
    from seo_intelligence.services.entity_matcher import get_entity_matcher

    matcher = get_entity_matcher()

    # Find potential duplicates
    conflicts = matcher.find_all_conflicts()

    # Check if two companies match
    is_match, confidence = matcher.companies_match(company1_id, company2_id)
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from difflib import SequenceMatcher

import phonenumbers
from sqlalchemy import select, text, and_, or_
from sqlalchemy.orm import Session

from db.database import get_db_session
from db.models import Company
from runner.logging_setup import get_logger

logger = get_logger("entity_matcher")


@dataclass
class MatchResult:
    """Result of entity matching between two companies."""
    company_id_1: int
    company_id_2: int
    is_match: bool
    match_type: str  # domain_match, phone_match, fuzzy_name_match
    confidence_score: float  # 0-1
    match_score: float  # 0-1 similarity
    matching_fields: Dict[str, Any]
    conflicting_fields: Dict[str, Any]
    evidence: Dict[str, Any]


class EntityMatcher:
    """
    Performs entity resolution and duplicate detection for companies.

    Implements multiple matching strategies with configurable thresholds.
    """

    def __init__(
        self,
        fuzzy_name_threshold: float = 0.85,
        phone_city_match_enabled: bool = True
    ):
        """
        Initialize entity matcher.

        Args:
            fuzzy_name_threshold: Minimum name similarity ratio (0-1) for fuzzy matching
            phone_city_match_enabled: Enable phone+city matching strategy
        """
        self.fuzzy_name_threshold = fuzzy_name_threshold
        self.phone_city_match_enabled = phone_city_match_enabled
        logger.info(
            f"EntityMatcher initialized (fuzzy_threshold={fuzzy_name_threshold}, "
            f"phone_city={phone_city_match_enabled})"
        )

    def _normalize_domain(self, domain: Optional[str]) -> Optional[str]:
        """Normalize domain for comparison."""
        if not domain:
            return None

        domain = domain.lower().strip()

        # Remove www prefix
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove protocol if present
        domain = re.sub(r'^https?://', '', domain)

        # Remove trailing slash
        domain = domain.rstrip('/')

        return domain if domain else None

    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        """Normalize phone to E.164 format."""
        if not phone:
            return None

        try:
            cleaned = re.sub(r'[^\d+]', '', phone)
            parsed = phonenumbers.parse(cleaned, "US")
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass

        return None

    def _normalize_name(self, name: Optional[str]) -> Optional[str]:
        """Normalize business name for comparison."""
        if not name:
            return None

        # Lowercase and strip
        normalized = name.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        # Remove common legal suffixes
        suffixes = [
            r'\s+(llc|inc|corp|corporation|ltd|limited|co|company|enterprises|group)\s*\.?$'
        ]
        for suffix_pattern in suffixes:
            normalized = re.sub(suffix_pattern, '', normalized, flags=re.I)

        # Remove common words that don't affect identity
        common_words = [r'\bthe\b', r'\ba\b', r'\ban\b']
        for word in common_words:
            normalized = re.sub(word, '', normalized)

        # Collapse whitespace again
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized if normalized else None

    def _name_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity ratio between two business names.

        Uses SequenceMatcher for fuzzy string matching.

        Args:
            name1: First name
            name2: Second name

        Returns:
            Similarity ratio (0-1)
        """
        if not name1 or not name2:
            return 0.0

        # Normalize names
        n1 = self._normalize_name(name1)
        n2 = self._normalize_name(name2)

        if not n1 or not n2:
            return 0.0

        return SequenceMatcher(None, n1, n2).ratio()

    def companies_match(
        self,
        company_id_1: int,
        company_id_2: int,
        session: Optional[Session] = None
    ) -> Tuple[bool, MatchResult]:
        """
        Check if two companies are potential duplicates.

        Args:
            company_id_1: First company ID
            company_id_2: Second company ID
            session: Optional database session

        Returns:
            Tuple of (is_match, MatchResult)
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            # Fetch companies
            c1 = session.get(Company, company_id_1)
            c2 = session.get(Company, company_id_2)

            if not c1 or not c2:
                logger.error(f"Company not found: {company_id_1} or {company_id_2}")
                return False, None

            # Initialize result
            matching_fields = {}
            conflicting_fields = {}
            evidence = {}
            is_match = False
            match_type = None
            confidence_score = 0.0
            match_score = 0.0

            # Strategy 1: Domain matching (highest confidence)
            domain1 = self._normalize_domain(c1.domain or c1.website)
            domain2 = self._normalize_domain(c2.domain or c2.website)

            if domain1 and domain2 and domain1 == domain2:
                is_match = True
                match_type = 'domain_match'
                confidence_score = 0.95
                match_score = 1.0
                matching_fields['domain'] = domain1
                evidence['domain_match'] = {
                    'domain': domain1,
                    'reasoning': 'Exact domain match - very likely same business'
                }

            # Strategy 2: Phone + City matching
            if not is_match and self.phone_city_match_enabled:
                phone1 = self._normalize_phone(c1.phone)
                phone2 = self._normalize_phone(c2.phone)
                city1 = c1.city.lower() if c1.city else None
                city2 = c2.city.lower() if c2.city else None

                if phone1 and phone2 and phone1 == phone2:
                    matching_fields['phone'] = phone1

                    if city1 and city2 and city1 == city2:
                        # Same phone AND same city - likely same business
                        is_match = True
                        match_type = 'phone_match'
                        confidence_score = 0.85
                        match_score = 0.9

                        # Check if names are similar
                        name_sim = self._name_similarity(c1.name, c2.name)
                        if name_sim > 0.7:
                            confidence_score = 0.90
                            evidence['phone_city_name_match'] = {
                                'phone': phone1,
                                'city': city1,
                                'name_similarity': name_sim,
                                'reasoning': 'Same phone + city + similar name - very likely duplicate'
                            }
                        else:
                            # Same phone/city but different name - potential conflict
                            confidence_score = 0.70
                            conflicting_fields['name'] = {
                                'company1': c1.name,
                                'company2': c2.name,
                                'similarity': name_sim
                            }
                            evidence['phone_match_name_mismatch'] = {
                                'phone': phone1,
                                'city': city1,
                                'name1': c1.name,
                                'name2': c2.name,
                                'name_similarity': name_sim,
                                'reasoning': 'Same phone/city but different names - may be shared number or call center'
                            }
                    else:
                        # Same phone but different city - lower confidence
                        is_match = False
                        match_type = 'phone_match_name_mismatch'
                        confidence_score = 0.5
                        conflicting_fields['city'] = {
                            'company1': city1,
                            'company2': city2
                        }
                        evidence['phone_match_different_city'] = {
                            'phone': phone1,
                            'city1': city1,
                            'city2': city2,
                            'reasoning': 'Same phone but different cities - likely different locations or franchise'
                        }

            # Strategy 3: Fuzzy name + location matching
            if not is_match:
                name_sim = self._name_similarity(c1.name, c2.name)

                if name_sim >= self.fuzzy_name_threshold:
                    # Very similar names - check location proximity
                    city_match = False
                    if c1.city and c2.city:
                        city_match = c1.city.lower() == c2.city.lower()

                    state_match = False
                    if c1.state and c2.state:
                        state_match = c1.state.upper() == c2.state.upper()

                    if city_match and state_match:
                        # Similar name + same city/state - likely duplicate
                        is_match = True
                        match_type = 'fuzzy_name_match'
                        confidence_score = 0.75 + (name_sim * 0.15)  # 0.75-0.90
                        match_score = name_sim
                        matching_fields['name_similarity'] = name_sim
                        matching_fields['city'] = c1.city
                        matching_fields['state'] = c1.state
                        evidence['fuzzy_name_location_match'] = {
                            'name_similarity': name_sim,
                            'name1': c1.name,
                            'name2': c2.name,
                            'city': c1.city,
                            'state': c1.state,
                            'reasoning': f'Very similar names ({name_sim:.1%}) at same location'
                        }
                    elif state_match:
                        # Similar name + same state but different city - possible franchise/chain
                        is_match = False
                        match_type = 'fuzzy_name_match'
                        confidence_score = 0.5
                        match_score = name_sim
                        matching_fields['name_similarity'] = name_sim
                        matching_fields['state'] = c1.state
                        conflicting_fields['city'] = {
                            'company1': c1.city,
                            'company2': c2.city
                        }
                        evidence['fuzzy_name_different_city'] = {
                            'name_similarity': name_sim,
                            'state': c1.state,
                            'city1': c1.city,
                            'city2': c2.city,
                            'reasoning': 'Similar names but different cities - may be franchise or chain'
                        }

            # Build result
            result = MatchResult(
                company_id_1=company_id_1,
                company_id_2=company_id_2,
                is_match=is_match,
                match_type=match_type or 'no_match',
                confidence_score=confidence_score,
                match_score=match_score,
                matching_fields=matching_fields,
                conflicting_fields=conflicting_fields,
                evidence=evidence
            )

            return is_match, result

        finally:
            if close_session:
                session.close()

    def record_conflict(
        self,
        match_result: MatchResult,
        session: Optional[Session] = None
    ) -> int:
        """
        Record a conflict in the company_conflicts table.

        Args:
            match_result: Match result with conflict details
            session: Optional database session

        Returns:
            Conflict ID
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            # Ensure company_id_1 < company_id_2 for uniqueness constraint
            company_id_1 = min(match_result.company_id_1, match_result.company_id_2)
            company_id_2 = max(match_result.company_id_1, match_result.company_id_2)

            # Check if conflict already exists
            existing = session.execute(
                text("""
                    SELECT conflict_id FROM company_conflicts
                    WHERE company_id_1 = :company_id_1
                    AND company_id_2 = :company_id_2
                """),
                {'company_id_1': company_id_1, 'company_id_2': company_id_2}
            ).fetchone()

            if existing:
                conflict_id = existing[0]
                # Update existing conflict
                session.execute(
                    text("""
                        UPDATE company_conflicts
                        SET
                            last_checked_at = NOW(),
                            confidence_score = :confidence_score,
                            match_score = :match_score,
                            matching_fields = :matching_fields::jsonb,
                            conflicting_fields = :conflicting_fields::jsonb,
                            evidence = :evidence::jsonb
                        WHERE conflict_id = :conflict_id
                    """),
                    {
                        'conflict_id': conflict_id,
                        'confidence_score': match_result.confidence_score,
                        'match_score': match_result.match_score,
                        'matching_fields': __import__('json').dumps(match_result.matching_fields),
                        'conflicting_fields': __import__('json').dumps(match_result.conflicting_fields),
                        'evidence': __import__('json').dumps(match_result.evidence),
                    }
                )
            else:
                # Insert new conflict
                result = session.execute(
                    text("""
                        INSERT INTO company_conflicts (
                            company_id_1, company_id_2, conflict_type,
                            confidence_score, match_score,
                            matching_fields, conflicting_fields, evidence
                        ) VALUES (
                            :company_id_1, :company_id_2, :conflict_type,
                            :confidence_score, :match_score,
                            :matching_fields::jsonb, :conflicting_fields::jsonb, :evidence::jsonb
                        )
                        RETURNING conflict_id
                    """),
                    {
                        'company_id_1': company_id_1,
                        'company_id_2': company_id_2,
                        'conflict_type': match_result.match_type,
                        'confidence_score': match_result.confidence_score,
                        'match_score': match_result.match_score,
                        'matching_fields': __import__('json').dumps(match_result.matching_fields),
                        'conflicting_fields': __import__('json').dumps(match_result.conflicting_fields),
                        'evidence': __import__('json').dumps(match_result.evidence),
                    }
                )
                conflict_id = result.fetchone()[0]

            session.commit()
            logger.info(f"Recorded conflict {conflict_id}: companies {company_id_1} and {company_id_2}")
            return conflict_id

        finally:
            if close_session:
                session.close()

    def find_all_conflicts(
        self,
        batch_size: int = 1000,
        session: Optional[Session] = None
    ) -> Tuple[int, int]:
        """
        Find all potential conflicts across all companies.

        Args:
            batch_size: Number of companies to process per batch
            session: Optional database session

        Returns:
            Tuple of (total_pairs_checked, conflicts_found)
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            pairs_checked = 0
            conflicts_found = 0

            # Strategy 1: Find domain matches
            logger.info("Finding domain conflicts...")
            domain_conflicts = session.execute(
                text("""
                    SELECT c1.id, c2.id
                    FROM companies c1
                    JOIN companies c2 ON c1.domain = c2.domain
                    WHERE c1.id < c2.id
                    AND c1.domain IS NOT NULL
                    AND c1.domain != ''
                """)
            ).fetchall()

            for c1_id, c2_id in domain_conflicts:
                is_match, result = self.companies_match(c1_id, c2_id, session)
                pairs_checked += 1

                if is_match or result.confidence_score > 0.5:
                    self.record_conflict(result, session)
                    conflicts_found += 1

            logger.info(f"Domain conflicts: {len(domain_conflicts)} found")

            # Strategy 2: Find phone matches
            logger.info("Finding phone conflicts...")
            phone_conflicts = session.execute(
                text("""
                    SELECT c1.id, c2.id
                    FROM companies c1
                    JOIN companies c2 ON c1.phone = c2.phone
                    WHERE c1.id < c2.id
                    AND c1.phone IS NOT NULL
                    AND c1.phone != ''
                """)
            ).fetchall()

            for c1_id, c2_id in phone_conflicts:
                is_match, result = self.companies_match(c1_id, c2_id, session)
                pairs_checked += 1

                if is_match or result.confidence_score > 0.5:
                    self.record_conflict(result, session)
                    conflicts_found += 1

            logger.info(f"Phone conflicts: {len(phone_conflicts)} found")

            logger.info(
                f"Conflict detection complete: {pairs_checked} pairs checked, "
                f"{conflicts_found} conflicts recorded"
            )

            return pairs_checked, conflicts_found

        finally:
            if close_session:
                session.close()


# Singleton instance
_entity_matcher_instance: Optional[EntityMatcher] = None


def get_entity_matcher(
    fuzzy_name_threshold: float = 0.85,
    phone_city_match_enabled: bool = True
) -> EntityMatcher:
    """
    Get or create the singleton EntityMatcher instance.

    Args:
        fuzzy_name_threshold: Minimum name similarity for fuzzy matching
        phone_city_match_enabled: Enable phone+city matching

    Returns:
        EntityMatcher instance
    """
    global _entity_matcher_instance

    if _entity_matcher_instance is None:
        _entity_matcher_instance = EntityMatcher(
            fuzzy_name_threshold, phone_city_match_enabled
        )

    return _entity_matcher_instance


def main():
    """Demo: Test entity matching."""
    logger.info("=" * 80)
    logger.info("Entity Matcher Demo")
    logger.info("=" * 80)

    matcher = get_entity_matcher()

    # Find conflicts
    logger.info("\nFinding potential duplicate companies...")
    pairs_checked, conflicts_found = matcher.find_all_conflicts()

    logger.info(f"\nResults:")
    logger.info(f"  Pairs checked: {pairs_checked}")
    logger.info(f"  Conflicts found: {conflicts_found}")

    logger.info("\n" + "=" * 80)
    logger.info("Demo Complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

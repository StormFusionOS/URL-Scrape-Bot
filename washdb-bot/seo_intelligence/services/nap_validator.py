"""
NAP Validator Service

Validates Name-Address-Phone (NAP) consistency across business sources.
Uses source trust weights to identify conflicts and flag companies with
disagreements among high-trust sources.

NAP consistency is critical for:
- Local SEO rankings
- Customer trust
- Data quality assessment
- Identifying data corruption or multiple businesses at same location

Usage:
    from seo_intelligence.services.nap_validator import get_nap_validator

    validator = get_nap_validator()

    # Validate specific company
    result = validator.validate_company(company_id=123)

    # Batch validate all companies
    validator.validate_all_companies()
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

import phonenumbers
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import get_db_session
from db.models import Company, BusinessSource
from seo_intelligence.services.source_trust import get_source_trust
from runner.logging_setup import get_logger

logger = get_logger("nap_validator")


@dataclass
class NAPValidationResult:
    """Result of NAP validation for a company."""
    company_id: int
    has_conflict: bool
    name_conflict: bool = False
    address_conflict: bool = False
    phone_conflict: bool = False
    name_agreement: float = 0.0
    address_agreement: float = 0.0
    phone_agreement: float = 0.0
    canonical_name: Optional[str] = None
    canonical_address: Optional[str] = None
    canonical_phone: Optional[str] = None
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    source_count: int = 0
    high_trust_source_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'company_id': self.company_id,
            'has_conflict': self.has_conflict,
            'name_conflict': self.name_conflict,
            'address_conflict': self.address_conflict,
            'phone_conflict': self.phone_conflict,
            'name_agreement': self.name_agreement,
            'address_agreement': self.address_agreement,
            'phone_agreement': self.phone_agreement,
            'canonical_name': self.canonical_name,
            'canonical_address': self.canonical_address,
            'canonical_phone': self.canonical_phone,
            'conflicts': self.conflicts,
            'source_count': self.source_count,
            'high_trust_source_count': self.high_trust_source_count,
        }


class NAPValidator:
    """
    Validates NAP (Name-Address-Phone) consistency across business sources.

    Uses source trust weights to determine canonical values and identify
    conflicts that matter (disagreements among high-trust sources).
    """

    def __init__(self, conflict_threshold: float = 0.7):
        """
        Initialize NAP validator.

        Args:
            conflict_threshold: Agreement ratio below this is considered a conflict (default: 0.7)
        """
        self.conflict_threshold = conflict_threshold
        self.trust_service = get_source_trust()
        logger.info(f"NAPValidator initialized (conflict_threshold={conflict_threshold})")

    def _normalize_name(self, name: Optional[str]) -> Optional[str]:
        """
        Normalize business name for comparison.

        Args:
            name: Raw business name

        Returns:
            Normalized name (lowercase, stripped, no extra whitespace)
        """
        if not name:
            return None

        # Lowercase and strip
        normalized = name.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        # Remove common legal suffixes for comparison (but keep in display)
        # This helps match "ABC Cleaning" with "ABC Cleaning LLC"
        suffixes = [
            r'\s+(llc|inc|corp|corporation|ltd|limited|co|company|enterprises|group)\s*\.?$'
        ]
        for suffix_pattern in suffixes:
            normalized = re.sub(suffix_pattern, '', normalized, flags=re.I)

        return normalized.strip() if normalized else None

    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        """
        Normalize phone number to E.164 format.

        Args:
            phone: Raw phone number

        Returns:
            E.164 formatted phone or None
        """
        if not phone:
            return None

        try:
            # Remove non-digits except +
            cleaned = re.sub(r'[^\d+]', '', phone)

            # Parse with US as default
            parsed = phonenumbers.parse(cleaned, "US")

            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass

        return None

    def _normalize_address(self, street: Optional[str], city: Optional[str],
                           state: Optional[str], zip_code: Optional[str]) -> Optional[str]:
        """
        Normalize address components into comparable format.

        Args:
            street: Street address
            city: City name
            state: State abbreviation
            zip_code: ZIP code

        Returns:
            Normalized full address string or None
        """
        if not street:
            return None

        # Build full address
        parts = [street]
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        if zip_code:
            parts.append(zip_code[:5])  # Use only 5-digit ZIP

        address = ', '.join(parts).lower().strip()

        # Normalize whitespace
        address = re.sub(r'\s+', ' ', address)

        # Standardize abbreviations
        abbreviations = {
            r'\bstreet\b': 'st',
            r'\bavenue\b': 'ave',
            r'\bboulevard\b': 'blvd',
            r'\bdrive\b': 'dr',
            r'\broad\b': 'rd',
            r'\blane\b': 'ln',
            r'\bcourt\b': 'ct',
            r'\bplace\b': 'pl',
            r'\bsuite\b': 'ste',
            r'\bapartment\b': 'apt',
            r'\bnorth\b': 'n',
            r'\bsouth\b': 's',
            r'\beast\b': 'e',
            r'\bwest\b': 'w',
        }

        for full, abbr in abbreviations.items():
            address = re.sub(full, abbr, address)

        return address if address else None

    def validate_company(self, company_id: int, session: Optional[Session] = None) -> NAPValidationResult:
        """
        Validate NAP consistency for a single company.

        Args:
            company_id: Company ID to validate
            session: Optional database session (creates new if not provided)

        Returns:
            NAPValidationResult with conflict detection and canonical values
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            # Fetch all business_sources for this company
            sources_query = select(BusinessSource).where(
                BusinessSource.company_id == company_id
            )
            sources = session.execute(sources_query).scalars().all()

            if not sources:
                logger.warning(f"Company {company_id}: No business_sources found")
                return NAPValidationResult(
                    company_id=company_id,
                    has_conflict=False,
                    source_count=0
                )

            # Build source dicts with normalized NAP data
            source_dicts = []
            for source in sources:
                # Normalize values
                normalized_name = self._normalize_name(source.name)
                normalized_phone = self._normalize_phone(source.phone)
                normalized_address = self._normalize_address(
                    source.street, source.city, source.state, source.zip_code
                )

                source_dict = {
                    'source_id': source.source_id,
                    'source_type': source.source_type,
                    'source_module': source.source_module,
                    'raw_name': source.name,
                    'raw_phone': source.phone,
                    'raw_address': f"{source.street}, {source.city}, {source.state} {source.zip_code}" if source.street else None,
                    'name': normalized_name,
                    'phone': normalized_phone,
                    'address': normalized_address,
                }
                source_dicts.append(source_dict)

            # Count high-trust sources (trust weight >= 80)
            high_trust_sources = [
                s for s in source_dicts
                if self.trust_service.get_trust_weight(s['source_type']) >= 80
            ]

            # Validate each NAP field using weighted consensus
            name_canonical, name_ratio, name_metadata = self.trust_service.compute_weighted_consensus(
                source_dicts, 'name', threshold=self.conflict_threshold
            )

            phone_canonical, phone_ratio, phone_metadata = self.trust_service.compute_weighted_consensus(
                source_dicts, 'phone', threshold=self.conflict_threshold
            )

            address_canonical, address_ratio, address_metadata = self.trust_service.compute_weighted_consensus(
                source_dicts, 'address', threshold=self.conflict_threshold
            )

            # Determine if conflicts exist
            name_conflict = name_ratio < self.conflict_threshold and len(source_dicts) > 1
            phone_conflict = phone_ratio < self.conflict_threshold and len(source_dicts) > 1
            address_conflict = address_ratio < self.conflict_threshold and len(source_dicts) > 1

            has_conflict = name_conflict or phone_conflict or address_conflict

            # Build detailed conflict list
            conflicts = []
            if name_conflict:
                conflicts.append({
                    'field': 'name',
                    'agreement_ratio': name_ratio,
                    'canonical_value': name_canonical,
                    'competing_values': name_metadata.get('competing_values', {}),
                    'disagreeing_sources': [
                        {'source_type': s['source_type'], 'value': s['raw_name']}
                        for s in source_dicts
                        if s.get('name') != name_canonical and s.get('name')
                    ]
                })

            if phone_conflict:
                conflicts.append({
                    'field': 'phone',
                    'agreement_ratio': phone_ratio,
                    'canonical_value': phone_canonical,
                    'competing_values': phone_metadata.get('competing_values', {}),
                    'disagreeing_sources': [
                        {'source_type': s['source_type'], 'value': s['raw_phone']}
                        for s in source_dicts
                        if s.get('phone') != phone_canonical and s.get('phone')
                    ]
                })

            if address_conflict:
                conflicts.append({
                    'field': 'address',
                    'agreement_ratio': address_ratio,
                    'canonical_value': address_canonical,
                    'competing_values': address_metadata.get('competing_values', {}),
                    'disagreeing_sources': [
                        {'source_type': s['source_type'], 'value': s['raw_address']}
                        for s in source_dicts
                        if s.get('address') != address_canonical and s.get('address')
                    ]
                })

            result = NAPValidationResult(
                company_id=company_id,
                has_conflict=has_conflict,
                name_conflict=name_conflict,
                address_conflict=address_conflict,
                phone_conflict=phone_conflict,
                name_agreement=name_ratio,
                address_agreement=address_ratio,
                phone_agreement=phone_ratio,
                canonical_name=name_canonical,
                canonical_address=address_canonical,
                canonical_phone=phone_canonical,
                conflicts=conflicts,
                source_count=len(source_dicts),
                high_trust_source_count=len(high_trust_sources),
            )

            logger.debug(
                f"Company {company_id} validated: conflict={has_conflict}, "
                f"name={name_ratio:.2f}, phone={phone_ratio:.2f}, address={address_ratio:.2f}"
            )

            return result

        finally:
            if close_session:
                session.close()

    def update_company_nap_flags(self, company_id: int, session: Optional[Session] = None) -> bool:
        """
        Validate company and update nap_conflict flag in database.

        Args:
            company_id: Company ID
            session: Optional database session

        Returns:
            True if successful, False otherwise
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            # Validate NAP
            result = self.validate_company(company_id, session)

            # Update company record
            company = session.get(Company, company_id)
            if not company:
                logger.error(f"Company {company_id} not found")
                return False

            company.nap_conflict = result.has_conflict

            # Update canonical values if high confidence
            if result.name_agreement >= 0.8 and result.canonical_name:
                company.name = result.canonical_name

            if result.phone_agreement >= 0.8 and result.canonical_phone:
                company.phone = result.canonical_phone

            session.commit()

            logger.info(f"Company {company_id} NAP flags updated: conflict={result.has_conflict}")
            return True

        except Exception as e:
            logger.error(f"Failed to update NAP flags for company {company_id}: {e}", exc_info=True)
            session.rollback()
            return False
        finally:
            if close_session:
                session.close()

    def validate_all_companies(self, batch_size: int = 500) -> Tuple[int, int, int]:
        """
        Validate NAP for all companies and update flags.

        Args:
            batch_size: Number of companies to process per batch

        Returns:
            Tuple of (total_processed, conflict_count, success_count)
        """
        session = next(get_db_session())

        try:
            # Get total company count
            total_companies = session.query(Company).count()
            logger.info(f"Validating NAP for {total_companies} companies in batches of {batch_size}")

            processed = 0
            conflict_count = 0
            success_count = 0

            # Process in batches
            offset = 0
            while offset < total_companies:
                company_ids = session.query(Company.id).offset(offset).limit(batch_size).all()
                company_ids = [cid[0] for cid in company_ids]

                for company_id in company_ids:
                    result = self.validate_company(company_id, session)

                    if result.has_conflict:
                        conflict_count += 1

                    # Update database
                    if self.update_company_nap_flags(company_id, session):
                        success_count += 1

                    processed += 1

                offset += batch_size
                logger.info(
                    f"Progress: {processed}/{total_companies} companies validated "
                    f"({conflict_count} conflicts found)"
                )

            logger.info(
                f"NAP validation complete: {processed} companies, "
                f"{conflict_count} with conflicts, {success_count} successfully updated"
            )

            return processed, conflict_count, success_count

        finally:
            session.close()

    def get_companies_with_conflicts(
        self,
        limit: int = 100,
        session: Optional[Session] = None
    ) -> List[NAPValidationResult]:
        """
        Get companies with NAP conflicts.

        Args:
            limit: Maximum number of results
            session: Optional database session

        Returns:
            List of validation results for companies with conflicts
        """
        close_session = False
        if session is None:
            session = next(get_db_session())
            close_session = True

        try:
            # Query companies with nap_conflict flag
            companies_query = select(Company).where(
                Company.nap_conflict == True
            ).limit(limit)
            companies = session.execute(companies_query).scalars().all()

            results = []
            for company in companies:
                result = self.validate_company(company.id, session)
                results.append(result)

            return results

        finally:
            if close_session:
                session.close()


# Singleton instance
_nap_validator_instance: Optional[NAPValidator] = None


def get_nap_validator(conflict_threshold: float = 0.7) -> NAPValidator:
    """
    Get or create the singleton NAPValidator instance.

    Args:
        conflict_threshold: Agreement ratio below this is considered a conflict

    Returns:
        NAPValidator instance
    """
    global _nap_validator_instance

    if _nap_validator_instance is None:
        _nap_validator_instance = NAPValidator(conflict_threshold)

    return _nap_validator_instance


def main():
    """Demo: Test NAP validation."""
    logger.info("=" * 80)
    logger.info("NAP Validator Demo")
    logger.info("=" * 80)

    validator = get_nap_validator()

    # Get companies with conflicts
    logger.info("\nFetching companies with NAP conflicts...")
    conflicts = validator.get_companies_with_conflicts(limit=5)

    if conflicts:
        logger.info(f"\nFound {len(conflicts)} companies with conflicts:\n")
        for result in conflicts:
            logger.info(f"Company ID: {result.company_id}")
            logger.info(f"  Sources: {result.source_count} ({result.high_trust_source_count} high-trust)")
            logger.info(f"  Name: {result.name_agreement:.1%} agreement")
            logger.info(f"  Phone: {result.phone_agreement:.1%} agreement")
            logger.info(f"  Address: {result.address_agreement:.1%} agreement")

            if result.conflicts:
                logger.info("  Conflicts:")
                for conflict in result.conflicts:
                    logger.info(f"    - {conflict['field']}: {len(conflict['disagreeing_sources'])} disagreeing sources")
            logger.info("")
    else:
        logger.info("No companies with NAP conflicts found")

    logger.info("=" * 80)
    logger.info("Demo Complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

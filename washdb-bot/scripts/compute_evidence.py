"""
Compute Evidence Script

Computes field-level evidence and canonical values for all companies by analyzing
business_sources records using weighted consensus based on source trust scores.

For each company:
1. Fetches all business_sources records
2. For each field (name, phone, address, website):
   - Normalizes values
   - Computes canonical_value using weighted consensus
   - Calculates agreement_ratio
   - Identifies disagreeing_sources
   - Determines best_source_id
3. Stores evidence in companies.field_evidence JSONB
4. Updates NAP conflict flags
5. Refreshes quality scores

Usage:
    python scripts/compute_evidence.py [--company-id ID] [--batch-size N] [--verbose]

Examples:
    # Process all companies
    python scripts/compute_evidence.py

    # Process specific company
    python scripts/compute_evidence.py --company-id 123

    # Process in smaller batches with verbose output
    python scripts/compute_evidence.py --batch-size 100 --verbose
"""

import argparse
import sys
import re
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime

import phonenumbers
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

# Add parent directory to path for imports
sys.path.insert(0, '/home/rivercityscrape/URL-Scrape-Bot/washdb-bot')

from db.database import get_db_session
from db.models import Company, BusinessSource
from seo_intelligence.services.source_trust import get_source_trust
from runner.logging_setup import get_logger

logger = get_logger("compute_evidence")


class FieldNormalizer:
    """Handles normalization of field values for comparison."""

    @staticmethod
    def normalize_phone(phone: Optional[str]) -> Optional[str]:
        """
        Normalize phone number to E.164 format.

        Args:
            phone: Raw phone number string

        Returns:
            E.164 formatted phone (e.g., "+15551234567") or None
        """
        if not phone:
            return None

        try:
            # Remove common prefixes and clean
            cleaned = re.sub(r'[^\d+]', '', phone)

            # Try parsing with US as default region
            parsed = phonenumbers.parse(cleaned, "US")

            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass

        return None

    @staticmethod
    def normalize_url(url: Optional[str]) -> Optional[str]:
        """
        Normalize URL to canonical form.

        Args:
            url: Raw URL string

        Returns:
            Canonical URL (lowercase domain, stripped www, no trailing slash) or None
        """
        if not url:
            return None

        try:
            # Add scheme if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Strip www prefix
            if domain.startswith('www.'):
                domain = domain[4:]

            # Reconstruct canonical URL
            path = parsed.path.rstrip('/')
            canonical = f"{parsed.scheme}://{domain}{path}"

            return canonical
        except Exception:
            return None

    @staticmethod
    def normalize_name(name: Optional[str]) -> Optional[str]:
        """
        Normalize business name for comparison.

        Args:
            name: Raw business name

        Returns:
            Normalized name (lowercase, stripped, no extra whitespace) or None
        """
        if not name:
            return None

        # Lowercase and strip
        normalized = name.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        # Remove common suffixes for comparison (but keep in original)
        # We don't actually strip these, just normalize spacing
        return normalized if normalized else None

    @staticmethod
    def normalize_address(address: Optional[str]) -> Optional[str]:
        """
        Normalize address for comparison.

        Args:
            address: Raw address string

        Returns:
            Normalized address (lowercase, stripped, standardized abbreviations) or None
        """
        if not address:
            return None

        # Lowercase and strip
        normalized = address.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        # Standardize common abbreviations
        abbreviations = {
            r'\bstreet\b': 'st',
            r'\bavenue\b': 'ave',
            r'\boulevard\b': 'blvd',
            r'\bdrive\b': 'dr',
            r'\broad\b': 'rd',
            r'\blane\b': 'ln',
            r'\bcourt\b': 'ct',
            r'\bplace\b': 'pl',
            r'\bsuite\b': 'ste',
            r'\bapartment\b': 'apt',
        }

        for full, abbr in abbreviations.items():
            normalized = re.sub(full, abbr, normalized)

        return normalized if normalized else None


class EvidenceComputer:
    """Computes field-level evidence for companies."""

    def __init__(self, session: Session):
        """
        Initialize evidence computer.

        Args:
            session: Database session
        """
        self.session = session
        self.trust_service = get_source_trust()
        self.normalizer = FieldNormalizer()

    def compute_company_evidence(self, company_id: int) -> Dict[str, Any]:
        """
        Compute field-level evidence for a single company.

        Args:
            company_id: Company ID

        Returns:
            Dict with field evidence for name, phone, address, website
        """
        # Fetch all business_sources for this company
        sources_query = select(BusinessSource).where(
            BusinessSource.company_id == company_id
        )
        sources = self.session.execute(sources_query).scalars().all()

        if not sources:
            logger.warning(f"Company {company_id}: No business_sources found")
            return {}

        # Build source dicts for trust service
        source_dicts = []
        for source in sources:
            source_dict = {
                'source_id': source.source_id,
                'source_type': source.source_type,
                'source_module': source.source_module,
                'name': source.name,
                'phone': source.phone,
                'address': f"{source.street}, {source.city}, {source.state} {source.zip_code}" if source.street else None,
                'website': source.website,
                'status': source.status,
            }
            source_dicts.append(source_dict)

        # Compute evidence for each field
        evidence = {}

        # Name evidence
        evidence['name'] = self._compute_field_evidence(
            source_dicts, 'name', self.normalizer.normalize_name
        )

        # Phone evidence
        evidence['phone'] = self._compute_field_evidence(
            source_dicts, 'phone', self.normalizer.normalize_phone
        )

        # Address evidence
        evidence['address'] = self._compute_field_evidence(
            source_dicts, 'address', self.normalizer.normalize_address
        )

        # Website evidence
        evidence['website'] = self._compute_field_evidence(
            source_dicts, 'website', self.normalizer.normalize_url
        )

        return evidence

    def _compute_field_evidence(
        self,
        sources: List[Dict[str, Any]],
        field: str,
        normalizer_func
    ) -> Dict[str, Any]:
        """
        Compute evidence for a single field.

        Args:
            sources: List of source dicts
            field: Field name
            normalizer_func: Function to normalize field values

        Returns:
            Dict with canonical_value, agreement_ratio, metadata
        """
        # Normalize all source values
        normalized_sources = []
        for source in sources:
            raw_value = source.get(field)
            if raw_value:
                normalized_value = normalizer_func(raw_value)
                if normalized_value:
                    normalized_sources.append({
                        'source_id': source['source_id'],
                        'source_type': source['source_type'],
                        'raw_value': raw_value,
                        field: normalized_value  # Use normalized for consensus
                    })

        if not normalized_sources:
            return {
                'canonical_value': None,
                'agreement_ratio': 0.0,
                'source_count': 0,
                'error': 'no_valid_values'
            }

        # Compute weighted consensus
        canonical, ratio, metadata = self.trust_service.compute_weighted_consensus(
            normalized_sources, field, threshold=0.5
        )

        # Find the best source (highest trust with canonical value)
        best_source = self.trust_service.get_best_source(
            [s for s in normalized_sources if s.get(field) == canonical],
            field
        )

        # Identify disagreeing sources (sources with different values)
        disagreeing_sources = []
        if canonical:
            for source in normalized_sources:
                if source.get(field) != canonical:
                    disagreeing_sources.append({
                        'source_id': source['source_id'],
                        'source_type': source['source_type'],
                        'value': source['raw_value']
                    })

        # Build evidence result
        result = {
            'canonical_value': canonical,
            'agreement_ratio': ratio,
            'source_count': len(normalized_sources),
            'best_source_id': best_source['source_id'] if best_source else None,
            'supporting_sources': metadata.get('supporting_sources', []),
            'supporting_weight': metadata.get('supporting_weight', 0),
            'total_weight': metadata.get('total_weight', 0),
            'disagreeing_sources': disagreeing_sources if disagreeing_sources else None,
            'competing_values': metadata.get('competing_values', {})
        }

        return result

    def update_company_evidence(self, company_id: int) -> bool:
        """
        Compute and store evidence for a company.

        Args:
            company_id: Company ID

        Returns:
            True if successful, False otherwise
        """
        try:
            # Compute evidence
            evidence = self.compute_company_evidence(company_id)

            if not evidence:
                logger.warning(f"Company {company_id}: No evidence computed")
                return False

            # Check for NAP conflicts (low agreement on name, phone, or address)
            nap_conflict = (
                evidence.get('name', {}).get('agreement_ratio', 1.0) < 0.7 or
                evidence.get('phone', {}).get('agreement_ratio', 1.0) < 0.7 or
                evidence.get('address', {}).get('agreement_ratio', 1.0) < 0.7
            )

            # Update company record
            company = self.session.get(Company, company_id)
            if not company:
                logger.error(f"Company {company_id} not found")
                return False

            company.field_evidence = evidence
            company.nap_conflict = nap_conflict
            company.last_validated_at = datetime.now(timezone.utc)

            # Update canonical fields if we have high-confidence values
            if evidence.get('phone', {}).get('agreement_ratio', 0) >= 0.7:
                canonical_phone = evidence['phone']['canonical_value']
                if canonical_phone:
                    company.phone = canonical_phone

            if evidence.get('website', {}).get('agreement_ratio', 0) >= 0.7:
                canonical_website = evidence['website']['canonical_value']
                if canonical_website:
                    company.website = canonical_website

            self.session.commit()

            logger.info(
                f"Company {company_id} evidence updated: "
                f"NAP conflict={nap_conflict}, "
                f"name={evidence.get('name', {}).get('agreement_ratio', 0):.1%}, "
                f"phone={evidence.get('phone', {}).get('agreement_ratio', 0):.1%}, "
                f"address={evidence.get('address', {}).get('agreement_ratio', 0):.1%}"
            )

            return True

        except Exception as e:
            logger.error(f"Company {company_id} evidence computation failed: {e}", exc_info=True)
            self.session.rollback()
            return False

    def compute_all_evidence(
        self,
        batch_size: int = 500,
        company_id: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Compute evidence for all companies (or specific company).

        Args:
            batch_size: Number of companies to process per batch
            company_id: Optional specific company ID to process

        Returns:
            Tuple of (success_count, failure_count)
        """
        success_count = 0
        failure_count = 0

        if company_id:
            # Process single company
            logger.info(f"Computing evidence for company {company_id}")
            if self.update_company_evidence(company_id):
                success_count += 1
            else:
                failure_count += 1
        else:
            # Process all companies in batches
            total_companies = self.session.execute(
                select(func.count(Company.id))
            ).scalar()

            logger.info(f"Computing evidence for {total_companies} companies in batches of {batch_size}")

            offset = 0
            while offset < total_companies:
                # Fetch batch of company IDs
                company_ids_query = select(Company.id).offset(offset).limit(batch_size)
                company_ids = self.session.execute(company_ids_query).scalars().all()

                for cid in company_ids:
                    if self.update_company_evidence(cid):
                        success_count += 1
                    else:
                        failure_count += 1

                offset += batch_size
                logger.info(
                    f"Progress: {offset}/{total_companies} companies processed "
                    f"(success={success_count}, failures={failure_count})"
                )

        return success_count, failure_count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Compute field-level evidence for companies'
    )
    parser.add_argument(
        '--company-id',
        type=int,
        help='Process specific company ID only'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Batch size for processing (default: 500)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel('DEBUG')

    logger.info("=" * 80)
    logger.info("Compute Evidence Script")
    logger.info("=" * 80)

    # Create database session
    session = next(get_db_session())

    try:
        # Initialize computer
        computer = EvidenceComputer(session)

        # Compute evidence
        success, failures = computer.compute_all_evidence(
            batch_size=args.batch_size,
            company_id=args.company_id
        )

        logger.info("=" * 80)
        logger.info(f"Evidence Computation Complete")
        logger.info(f"  Success: {success}")
        logger.info(f"  Failures: {failures}")
        logger.info(f"  Total: {success + failures}")
        logger.info("=" * 80)

        # Refresh quality scores for updated companies
        if success > 0:
            logger.info("Refreshing quality scores...")
            if args.company_id:
                session.execute(
                    f"SELECT refresh_company_quality_flags({args.company_id})"
                )
            else:
                # Refresh all companies with updated evidence
                session.execute("""
                    UPDATE companies
                    SET quality_score = compute_company_quality_score(id)
                    WHERE field_evidence IS NOT NULL
                """)
            session.commit()
            logger.info("Quality scores refreshed")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()

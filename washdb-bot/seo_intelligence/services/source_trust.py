"""
Source Trust Scoring Service

Implements trust weights for different business data sources to enable
weighted consensus when determining canonical field values.

Trust Weights:
- 100: Verified business website (highest trust)
- 90: Google/official sources (very high trust)
- 80: Yelp / BBB / Angi (high trust, verified platforms)
- 60: Secondary directories (medium trust)
- 40: SERP-only / aggregators (lower trust)

Usage:
    from seo_intelligence.services.source_trust import get_source_trust

    trust_service = get_source_trust()
    weight = trust_service.get_trust_weight('yelp')
    canonical = trust_service.compute_weighted_consensus(sources, 'phone')
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from runner.logging_setup import get_logger

logger = get_logger("source_trust")


@dataclass
class SourceTrustConfig:
    """Configuration for source trust weights."""

    # Trust weight mapping (source_type -> weight)
    trust_weights: Dict[str, int] = None

    def __post_init__(self):
        """Initialize default trust weights if not provided."""
        if self.trust_weights is None:
            self.trust_weights = {
                # Tier 1: Verified business sources (100)
                'website': 100,
                'verified_website': 100,

                # Tier 2: Official/authoritative sources (90)
                'google': 90,
                'google_business': 90,
                'google_maps': 90,

                # Tier 3: Trusted review platforms (80)
                'yelp': 80,
                'bbb': 80,
                'angi': 80,
                'angies_list': 80,
                'trustpilot': 80,

                # Tier 4: Secondary directories (60)
                'yp': 60,
                'yellowpages': 60,
                'thumbtack': 60,
                'homeadvisor': 60,
                'porch': 60,
                'houzz': 60,

                # Tier 5: Social media (50)
                'facebook': 50,
                'linkedin': 50,
                'instagram': 50,

                # Tier 6: Tertiary directories (40)
                'mapquest': 40,
                'manta': 40,
                'superpages': 40,
                'whitepages': 40,

                # Tier 7: SERP/aggregators (30)
                'serp': 30,
                'aggregator': 30,

                # Default for unknown sources
                'unknown': 20,
            }


class SourceTrustService:
    """
    Service for managing source trust weights and weighted consensus.
    """

    def __init__(self, config: Optional[SourceTrustConfig] = None):
        """
        Initialize source trust service.

        Args:
            config: Optional trust configuration (uses defaults if not provided)
        """
        self.config = config or SourceTrustConfig()
        logger.info(f"SourceTrustService initialized with {len(self.config.trust_weights)} trust tiers")

    def get_trust_weight(self, source_type: str) -> int:
        """
        Get trust weight for a source type.

        Args:
            source_type: Source type key (e.g., 'yelp', 'google', 'yp')

        Returns:
            int: Trust weight (0-100)
        """
        source_type_lower = source_type.lower() if source_type else 'unknown'
        weight = self.config.trust_weights.get(source_type_lower, self.config.trust_weights['unknown'])
        return weight

    def get_trust_tier(self, source_type: str) -> str:
        """
        Get human-readable trust tier for a source.

        Args:
            source_type: Source type key

        Returns:
            str: Trust tier name ('very_high', 'high', 'medium', 'low', 'very_low')
        """
        weight = self.get_trust_weight(source_type)

        if weight >= 90:
            return 'very_high'
        elif weight >= 70:
            return 'high'
        elif weight >= 50:
            return 'medium'
        elif weight >= 30:
            return 'low'
        else:
            return 'very_low'

    def compute_weighted_consensus(
        self,
        sources: List[Dict[str, Any]],
        field: str,
        threshold: float = 0.5
    ) -> Tuple[Optional[Any], float, Dict[str, Any]]:
        """
        Compute weighted consensus for a field across sources.

        Uses trust weights to determine the canonical value. If multiple values exist,
        the value with the highest weighted support wins.

        Args:
            sources: List of source dicts with 'source_type' and field keys
            field: Field name to compute consensus for (e.g., 'phone', 'name')
            threshold: Minimum weighted agreement ratio (0-1) to accept consensus

        Returns:
            Tuple of (canonical_value, agreement_ratio, metadata):
            - canonical_value: The consensus value, or None if no consensus
            - agreement_ratio: Weighted agreement ratio (0-1)
            - metadata: Dict with details about the consensus
        """
        if not sources:
            return None, 0.0, {'error': 'no_sources'}

        # Extract values and weights
        value_weights = {}  # value -> total_weight
        value_sources = {}  # value -> list of source_types
        total_weight = 0

        for source in sources:
            value = source.get(field)
            if value is None or value == '':
                continue

            # Normalize value for comparison (lowercase, strip)
            normalized_value = str(value).lower().strip()
            if not normalized_value:
                continue

            source_type = source.get('source_type', 'unknown')
            weight = self.get_trust_weight(source_type)

            # Accumulate
            if normalized_value not in value_weights:
                value_weights[normalized_value] = 0
                value_sources[normalized_value] = []

            value_weights[normalized_value] += weight
            value_sources[normalized_value].append(source_type)
            total_weight += weight

        if not value_weights:
            return None, 0.0, {'error': 'no_valid_values'}

        # Find value with highest weighted support
        best_value = max(value_weights.keys(), key=lambda v: value_weights[v])
        best_weight = value_weights[best_value]
        agreement_ratio = best_weight / total_weight if total_weight > 0 else 0

        # Check if consensus meets threshold
        if agreement_ratio < threshold:
            return None, agreement_ratio, {
                'error': 'below_threshold',
                'threshold': threshold,
                'agreement_ratio': agreement_ratio,
                'candidate_value': best_value,
                'competing_values': list(value_weights.keys())
            }

        # Build metadata
        metadata = {
            'canonical_value': best_value,
            'agreement_ratio': agreement_ratio,
            'total_weight': total_weight,
            'supporting_weight': best_weight,
            'supporting_sources': value_sources[best_value],
            'unique_value_count': len(value_weights),
            'competing_values': {
                k: {
                    'weight': v,
                    'sources': value_sources[k],
                    'ratio': v / total_weight
                }
                for k, v in value_weights.items()
                if k != best_value
            } if len(value_weights) > 1 else {}
        }

        return best_value, agreement_ratio, metadata

    def rank_sources_by_trust(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank sources by trust weight (highest first).

        Args:
            sources: List of source dicts with 'source_type' key

        Returns:
            List of sources sorted by trust weight descending
        """
        def get_sort_key(source):
            return self.get_trust_weight(source.get('source_type', 'unknown'))

        return sorted(sources, key=get_sort_key, reverse=True)

    def get_best_source(
        self,
        sources: List[Dict[str, Any]],
        field: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the single best (highest trust) source.

        If field is specified, only considers sources that have a non-empty value for that field.

        Args:
            sources: List of source dicts
            field: Optional field name to require

        Returns:
            Best source dict, or None if no sources
        """
        if not sources:
            return None

        # Filter by field if specified
        if field:
            sources = [s for s in sources if s.get(field)]

        if not sources:
            return None

        ranked = self.rank_sources_by_trust(sources)
        return ranked[0] if ranked else None

    def compute_source_quality_multiplier(self, source_type: str) -> float:
        """
        Get quality multiplier for a source (0-1 scale).

        Useful for adjusting quality scores based on source trust.

        Args:
            source_type: Source type key

        Returns:
            float: Quality multiplier (0-1), where 1.0 is highest trust
        """
        weight = self.get_trust_weight(source_type)
        return weight / 100.0

    def explain_trust_decision(
        self,
        sources: List[Dict[str, Any]],
        field: str
    ) -> str:
        """
        Generate human-readable explanation of trust-based consensus decision.

        Args:
            sources: List of source dicts
            field: Field name

        Returns:
            str: Explanation text
        """
        canonical, ratio, metadata = self.compute_weighted_consensus(sources, field)

        if canonical is None:
            if 'error' in metadata:
                if metadata['error'] == 'no_sources':
                    return f"No sources available for field '{field}'"
                elif metadata['error'] == 'no_valid_values':
                    return f"No sources provided valid values for field '{field}'"
                elif metadata['error'] == 'below_threshold':
                    return (
                        f"No consensus reached for field '{field}'. "
                        f"Best candidate '{metadata.get('candidate_value')}' has {ratio:.1%} agreement "
                        f"(threshold: {metadata.get('threshold', 0.5):.1%})"
                    )
            return f"Could not determine consensus for field '{field}'"

        explanation = []
        explanation.append(f"Consensus value for '{field}': {canonical}")
        explanation.append(f"Agreement: {ratio:.1%} ({metadata['supporting_weight']}/{metadata['total_weight']} weighted)")
        explanation.append(f"Supporting sources: {', '.join(metadata['supporting_sources'])}")

        if metadata.get('competing_values'):
            explanation.append("\nCompeting values:")
            for val, info in metadata['competing_values'].items():
                explanation.append(f"  - {val}: {info['ratio']:.1%} ({', '.join(info['sources'])})")

        return "\n".join(explanation)


# Module-level singleton
_source_trust_instance: Optional[SourceTrustService] = None


def get_source_trust(config: Optional[SourceTrustConfig] = None) -> SourceTrustService:
    """
    Get or create the singleton SourceTrustService instance.

    Args:
        config: Optional custom configuration

    Returns:
        SourceTrustService instance
    """
    global _source_trust_instance

    if _source_trust_instance is None or config is not None:
        _source_trust_instance = SourceTrustService(config)

    return _source_trust_instance


def main():
    """Demo: Test source trust scoring."""
    logger.info("=" * 80)
    logger.info("Source Trust Service Demo")
    logger.info("=" * 80)
    logger.info("")

    trust_service = get_source_trust()

    # Demo: Trust weights
    logger.info("Trust Weights by Source Type:")
    for source_type in ['website', 'google', 'yelp', 'yp', 'serp', 'unknown']:
        weight = trust_service.get_trust_weight(source_type)
        tier = trust_service.get_trust_tier(source_type)
        logger.info(f"  {source_type:20s}: {weight:3d} ({tier})")

    logger.info("")

    # Demo: Weighted consensus
    logger.info("Demo: Weighted Consensus for Phone Number")
    sources = [
        {'source_type': 'yelp', 'phone': '(555) 123-4567'},
        {'source_type': 'google', 'phone': '555-123-4567'},
        {'source_type': 'yp', 'phone': '(555) 123-4567'},
        {'source_type': 'serp', 'phone': '555-999-9999'},  # Outlier with low trust
    ]

    canonical, ratio, metadata = trust_service.compute_weighted_consensus(sources, 'phone')

    logger.info(f"\nCanonical phone: {canonical}")
    logger.info(f"Agreement ratio: {ratio:.1%}")
    logger.info(f"Supporting sources: {', '.join(metadata.get('supporting_sources', []))}")

    if metadata.get('competing_values'):
        logger.info("\nCompeting values:")
        for val, info in metadata['competing_values'].items():
            logger.info(f"  {val}: {info['ratio']:.1%} from {', '.join(info['sources'])}")

    logger.info("")
    logger.info("=" * 80)
    logger.info("Demo Complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

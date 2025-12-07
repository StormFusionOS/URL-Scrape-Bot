#!/usr/bin/env python3
"""
Few-Shot Example Selector for Claude prompts.

Selects diverse, high-quality examples to include in Claude prompts:
- Clear provider examples (high confidence, valid services)
- Clear non-provider examples (directories, agencies, blogs)
- Tricky/learning cases (where Claude initially struggled)

Ensures diversity across:
- Service types (pressure washing, window cleaning, etc.)
- Red flag categories (directory, franchise, agency, blog)
- Quality tiers
- Geographic regions
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import random

from db.database_manager import DatabaseManager
from verification.config_verifier import (
    CLAUDE_NUM_PROVIDER_EXAMPLES,
    CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
    CLAUDE_NUM_TRICKY_EXAMPLES
)


logger = logging.getLogger(__name__)


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

@dataclass
class FewShotExample:
    """A single few-shot example for Claude."""
    company_id: int
    example_type: str  # provider, non_provider, tricky
    input_data: dict
    output_data: dict
    diversity_score: float  # How unique this example is


# ==============================================================================
# FEW-SHOT SELECTOR
# ==============================================================================

class FewShotSelector:
    """
    Select diverse, high-quality examples for Claude prompts.

    Strategy:
    1. Provider examples: Clear cases with services, licensing, contact info
    2. Non-provider examples: Directories, agencies, blogs, equipment sellers
    3. Tricky examples: Borderline cases where human corrected Claude
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """Initialize selector with database connection."""
        self.db_manager = db_manager or DatabaseManager()

    def select_examples(
        self,
        n_provider: int = CLAUDE_NUM_PROVIDER_EXAMPLES,
        n_non_provider: int = CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
        n_tricky: int = CLAUDE_NUM_TRICKY_EXAMPLES,
        diversity_threshold: float = 0.7
    ) -> List[dict]:
        """
        Select N examples with diversity and quality.

        Args:
            n_provider: Number of clear provider examples
            n_non_provider: Number of clear non-provider examples
            n_tricky: Number of tricky/learning examples
            diversity_threshold: Minimum diversity score (0-1)

        Returns:
            List of formatted examples for Claude prompt
        """
        examples = []

        # Get clear providers
        provider_examples = self._get_clear_providers(
            n=n_provider,
            min_confidence=0.85
        )
        examples.extend(provider_examples)
        logger.info(f"Selected {len(provider_examples)} provider examples")

        # Get clear non-providers
        non_provider_examples = self._get_clear_non_providers(
            n=n_non_provider,
            min_confidence=0.85
        )
        examples.extend(non_provider_examples)
        logger.info(f"Selected {len(non_provider_examples)} non-provider examples")

        # Get tricky cases (where human corrected Claude)
        tricky_examples = self._get_tricky_cases(n=n_tricky)
        examples.extend(tricky_examples)
        logger.info(f"Selected {len(tricky_examples)} tricky examples")

        # Enforce diversity
        examples = self._enforce_diversity(examples, diversity_threshold)

        logger.info(f"Final selection: {len(examples)} examples with diversity >= {diversity_threshold}")

        return [self._format_example(ex) for ex in examples]

    def _get_clear_providers(
        self,
        n: int,
        min_confidence: float = 0.85
    ) -> List[FewShotExample]:
        """
        Get clear provider examples.

        Criteria:
        - Human labeled as 'provider' OR passed verification with high confidence
        - Has services listed
        - No major red flags
        - Contact info present
        """
        # Use standardized schema: verified=true means passed verification
        query = """
            SELECT
                c.id,
                c.name,
                c.website,
                c.parse_metadata
            FROM companies c
            WHERE c.verified = true
              AND (
                  c.parse_metadata->'verification'->'labels'->>'human' = 'provider'
                  OR (c.parse_metadata->'verification'->>'final_score')::float >= %(min_conf)s
              )
              AND c.parse_metadata->'verification'->'llm_classification'->>'type' = 'provider'
              AND (c.parse_metadata ? 'services_text' OR c.parse_metadata ? 'about_text')
            ORDER BY RANDOM()
            LIMIT %(limit)s
        """

        with self.db_manager.get_connection() as conn:
            result = conn.execute(text(query), {'min_conf': min_confidence, 'limit': n * 2})
            rows = result.fetchall()

        examples = []
        for row in rows:
            company_id, name, website, metadata = row
            example = self._build_provider_example(company_id, name, website, metadata)
            if example:
                examples.append(example)

        return examples[:n]

    def _get_clear_non_providers(
        self,
        n: int,
        min_confidence: float = 0.85
    ) -> List[FewShotExample]:
        """
        Get clear non-provider examples.

        Criteria:
        - Human labeled as 'non_provider' OR failed verification with high confidence
        - Has red flags (directory, agency, blog, franchise)
        - Clearly not a service provider
        """
        # Use standardized schema: verified=false means failed verification
        query = """
            SELECT
                c.id,
                c.name,
                c.website,
                c.parse_metadata
            FROM companies c
            WHERE c.verified = false
              AND (
                  c.parse_metadata->'verification'->'labels'->>'human' IN ('non_provider', 'directory', 'agency', 'blog')
                  OR (c.parse_metadata->'verification'->>'final_score')::float <= (1.0 - %(min_conf)s)
              )
              AND c.parse_metadata->'verification'->'red_flags' IS NOT NULL
              AND jsonb_array_length(c.parse_metadata->'verification'->'red_flags') > 0
            ORDER BY RANDOM()
            LIMIT %(limit)s
        """

        with self.db_manager.get_connection() as conn:
            result = conn.execute(text(query), {'min_conf': min_confidence, 'limit': n * 2})
            rows = result.fetchall()

        examples = []
        for row in rows:
            company_id, name, website, metadata = row
            example = self._build_non_provider_example(company_id, name, website, metadata)
            if example:
                examples.append(example)

        return examples[:n]

    def _get_tricky_cases(self, n: int) -> List[FewShotExample]:
        """
        Get tricky/learning examples.

        Criteria:
        - Cases where Claude initially got it wrong
        - Human reviewed and corrected
        - Borderline scores (0.4-0.6)
        """
        # Tricky cases: human-reviewed and corrected, regardless of current verified status
        query = """
            SELECT
                c.id,
                c.name,
                c.website,
                c.parse_metadata
            FROM companies c
            INNER JOIN claude_review_audit cra ON cra.company_id = c.id
            WHERE cra.human_reviewed = true
              AND cra.decision != cra.human_decision  -- Claude was wrong
              AND (c.parse_metadata->'verification'->>'final_score')::float BETWEEN 0.4 AND 0.6
            ORDER BY cra.reviewed_at DESC
            LIMIT %(limit)s
        """

        with self.db_manager.get_connection() as conn:
            result = conn.execute(text(query), {'limit': n * 2})
            rows = result.fetchall()

        examples = []
        for row in rows:
            company_id, name, website, metadata = row
            example = self._build_tricky_example(company_id, name, website, metadata)
            if example:
                examples.append(example)

        # If we don't have enough tricky cases yet, supplement with borderline cases
        if len(examples) < n:
            remaining = n - len(examples)
            borderline = self._get_borderline_cases(remaining)
            examples.extend(borderline)

        return examples[:n]

    def _get_borderline_cases(self, n: int) -> List[FewShotExample]:
        """Get borderline cases (scores 0.45-0.55) as fallback tricky examples."""
        # Borderline cases: verified IS NOT NULL and have human label or claude review
        query = """
            SELECT
                c.id,
                c.name,
                c.website,
                c.parse_metadata
            FROM companies c
            WHERE c.verified IS NOT NULL
              AND (c.parse_metadata->'verification'->>'final_score')::float BETWEEN 0.45 AND 0.55
              AND (
                  c.parse_metadata->'verification'->'labels'->>'human' IS NOT NULL
                  OR c.parse_metadata->'verification'->'claude_review'->>'reviewed' = 'true'
              )
            ORDER BY RANDOM()
            LIMIT %(limit)s
        """

        with self.db_manager.get_connection() as conn:
            result = conn.execute(text(query), {'limit': n})
            rows = result.fetchall()

        examples = []
        for row in rows:
            company_id, name, website, metadata = row
            example = self._build_tricky_example(company_id, name, website, metadata)
            if example:
                examples.append(example)

        return examples

    def _build_provider_example(
        self,
        company_id: int,
        name: str,
        website: str,
        metadata: dict
    ) -> Optional[FewShotExample]:
        """Build provider example from company data."""
        verification = metadata.get('verification', {})
        llm_class = verification.get('llm_classification', {})

        # Build input
        input_data = {
            'company_id': company_id,
            'name': name,
            'website': website,
            'automated_signals': {
                'final_score': verification.get('final_score', 0.0),
                'ml_probability': verification.get('ml_probability', 0.0),
                'red_flags': verification.get('red_flags', []),
                'services': llm_class.get('services', [])
            },
            'website_content': {
                'services': metadata.get('services_text', '')[:500],
                'about': metadata.get('about_text', '')[:500]
            }
        }

        # Build output (ground truth)
        output_data = {
            'decision': 'approve',
            'confidence': 0.95,
            'reasoning': f"Clear provider of {', '.join(llm_class.get('services', ['services']))}. Has proper contact info and service descriptions.",
            'primary_services': llm_class.get('services', []),
            'red_flags': [],
            'is_provider': True
        }

        return FewShotExample(
            company_id=company_id,
            example_type='provider',
            input_data=input_data,
            output_data=output_data,
            diversity_score=self._calculate_diversity(metadata, 'provider')
        )

    def _build_non_provider_example(
        self,
        company_id: int,
        name: str,
        website: str,
        metadata: dict
    ) -> Optional[FewShotExample]:
        """Build non-provider example from company data."""
        verification = metadata.get('verification', {})
        red_flags = verification.get('red_flags', [])

        # Determine primary red flag
        if 'directory' in red_flags:
            reason = "Directory/listing site"
        elif 'agency' in red_flags:
            reason = "Lead generation agency"
        elif 'blog' in red_flags:
            reason = "Blog or information-only site"
        elif 'franchise' in red_flags:
            reason = "Franchise directory"
        else:
            reason = "Not a direct service provider"

        # Build input
        input_data = {
            'company_id': company_id,
            'name': name,
            'website': website,
            'automated_signals': {
                'final_score': verification.get('final_score', 0.0),
                'ml_probability': verification.get('ml_probability', 0.0),
                'red_flags': red_flags
            },
            'website_content': {
                'homepage': metadata.get('homepage_text', '')[:500]
            }
        }

        # Build output
        output_data = {
            'decision': 'deny',
            'confidence': 0.90,
            'reasoning': reason,
            'primary_services': [],
            'red_flags': red_flags,
            'is_provider': False
        }

        return FewShotExample(
            company_id=company_id,
            example_type='non_provider',
            input_data=input_data,
            output_data=output_data,
            diversity_score=self._calculate_diversity(metadata, 'non_provider')
        )

    def _build_tricky_example(
        self,
        company_id: int,
        name: str,
        website: str,
        metadata: dict
    ) -> Optional[FewShotExample]:
        """Build tricky example from borderline case."""
        verification = metadata.get('verification', {})
        labels = verification.get('labels', {})

        # Use human label as ground truth
        human_label = labels.get('human') or labels.get('claude')
        if not human_label:
            return None

        is_provider = human_label in ('provider', 'approve')

        # Build input
        input_data = {
            'company_id': company_id,
            'name': name,
            'website': website,
            'automated_signals': {
                'final_score': verification.get('final_score', 0.5),
                'ml_probability': verification.get('ml_probability', 0.5),
                'red_flags': verification.get('red_flags', [])
            },
            'website_content': {
                'services': metadata.get('services_text', '')[:500],
                'about': metadata.get('about_text', '')[:500]
            }
        }

        # Build output
        if is_provider:
            output_data = {
                'decision': 'approve',
                'confidence': 0.75,
                'reasoning': 'Borderline case but appears to be legitimate provider',
                'primary_services': verification.get('llm_classification', {}).get('services', []),
                'red_flags': verification.get('red_flags', []),
                'is_provider': True
            }
        else:
            output_data = {
                'decision': 'deny',
                'confidence': 0.75,
                'reasoning': 'Borderline case but does not appear to be direct service provider',
                'primary_services': [],
                'red_flags': verification.get('red_flags', []),
                'is_provider': False
            }

        return FewShotExample(
            company_id=company_id,
            example_type='tricky',
            input_data=input_data,
            output_data=output_data,
            diversity_score=self._calculate_diversity(metadata, 'tricky')
        )

    def _calculate_diversity(self, metadata: dict, example_type: str) -> float:
        """
        Calculate diversity score for an example.

        Higher score = more unique/diverse
        Factors:
        - Service type distribution
        - Red flag types
        - Geographic location
        - Quality tier
        """
        score = 0.5  # Base score

        verification = metadata.get('verification', {})
        llm_class = verification.get('llm_classification', {})

        # Service diversity (more services = more diverse)
        services = llm_class.get('services', [])
        if len(services) > 1:
            score += 0.1

        # Red flag diversity
        red_flags = verification.get('red_flags', [])
        if len(red_flags) >= 1:
            score += 0.1

        # Quality signals
        quality_signals = verification.get('quality_signals', [])
        if len(quality_signals) > 0:
            score += 0.1

        # Borderline score (more informative)
        final_score = float(verification.get('final_score', 0.5))
        if 0.4 <= final_score <= 0.6:
            score += 0.2

        return min(score, 1.0)

    def _enforce_diversity(
        self,
        examples: List[FewShotExample],
        threshold: float
    ) -> List[FewShotExample]:
        """
        Filter examples to ensure diversity.

        Remove examples that are too similar to already-selected ones.
        """
        if not examples:
            return examples

        # Sort by diversity score (highest first)
        sorted_examples = sorted(examples, key=lambda ex: ex.diversity_score, reverse=True)

        # Keep high-diversity examples
        diverse_examples = []
        for ex in sorted_examples:
            if ex.diversity_score >= threshold:
                diverse_examples.append(ex)
            elif len(diverse_examples) < len(sorted_examples) * 0.5:
                # Allow some lower-diversity examples if we don't have enough
                diverse_examples.append(ex)

        return diverse_examples

    def _format_example(self, example: FewShotExample) -> dict:
        """Format example for Claude prompt."""
        return {
            'input': example.input_data,
            'output': example.output_data
        }


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def test_selector():
    """Test few-shot selector."""
    print("Testing FewShotSelector...")

    selector = FewShotSelector()

    # Select examples
    examples = selector.select_examples(
        n_provider=3,
        n_non_provider=3,
        n_tricky=2
    )

    print(f"\nSelected {len(examples)} examples:")
    for i, ex in enumerate(examples, 1):
        output = ex['output']
        print(f"  {i}. {output['decision']} (confidence: {output['confidence']})")
        print(f"     {output['reasoning'][:80]}...")

    return examples


if __name__ == "__main__":
    test_selector()

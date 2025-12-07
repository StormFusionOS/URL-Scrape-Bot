#!/usr/bin/env python3
"""
Claude Prompt Manager with versioning and few-shot selection.

Manages Claude prompts with:
- Version control (load from database)
- Few-shot example selection
- Prompt caching optimization
- Context building from company data
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from db.database_manager import DatabaseManager
from verification.few_shot_selector import FewShotSelector
from verification.config_verifier import (
    CLAUDE_NUM_FEW_SHOT_EXAMPLES,
    CLAUDE_NUM_PROVIDER_EXAMPLES,
    CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
    CLAUDE_NUM_TRICKY_EXAMPLES
)


logger = logging.getLogger(__name__)


# ==============================================================================
# PROMPT MANAGER
# ==============================================================================

class PromptManager:
    """
    Manages Claude prompts with versioning and few-shot selection.

    Features:
    - Load active prompt version from database
    - Select few-shot examples dynamically
    - Build company context from metadata
    - Optimize for prompt caching (static vs dynamic content)
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """Initialize prompt manager."""
        self.db_manager = db_manager or DatabaseManager()
        self.few_shot_selector = FewShotSelector(db_manager=self.db_manager)

        # Cache for current prompt version
        self._cached_version = None
        self._cached_system_prompt = None
        self._cached_examples = None
        self._cache_time = None

    def build_prompt(self, company: dict) -> dict:
        """
        Build optimized prompt with caching.

        Args:
            company: Company data from database

        Returns:
            {
                'system_prompt': str,       # Cached
                'few_shot_examples': list,  # Cached
                'company_context': str,     # Not cached (unique per company)
                'prompt_version': str
            }
        """
        # Get active prompt version (with caching)
        version_data = self._get_active_version()

        # Build company-specific context (not cached)
        company_context = self._build_company_context(company)

        return {
            'system_prompt': version_data['system_prompt'],
            'few_shot_examples': version_data['few_shot_examples'],
            'company_context': company_context,
            'prompt_version': version_data['version']
        }

    def _get_active_version(self) -> dict:
        """
        Get active prompt version from database.

        Returns cached version if available and recent (< 1 hour old).
        """
        # Check cache (refresh every hour)
        if self._cached_version is not None:
            if self._cache_time is not None:
                age_seconds = (datetime.now() - self._cache_time).total_seconds()
                if age_seconds < 3600:  # 1 hour cache
                    return {
                        'version': self._cached_version,
                        'system_prompt': self._cached_system_prompt,
                        'few_shot_examples': self._cached_examples
                    }

        # Load from database
        query = """
            SELECT
                version,
                prompt_text,
                few_shot_examples
            FROM claude_prompt_versions
            WHERE is_active = true
            LIMIT 1
        """

        with self.db_manager.get_connection() as conn:
                        result = conn.execute(text(query))
            row = cursor.fetchone()

            if not row:
                logger.error("No active prompt version found in database!")
                # Return default prompt
                return self._get_default_prompt()

            version, prompt_text, examples_json = row

        # Parse examples
        if examples_json and len(examples_json) > 0:
            # Use examples from database
            few_shot_examples = examples_json
        else:
            # Dynamically select examples
            logger.info("No examples in database, selecting dynamically...")
            few_shot_examples = self.few_shot_selector.select_examples(
                n_provider=CLAUDE_NUM_PROVIDER_EXAMPLES,
                n_non_provider=CLAUDE_NUM_NON_PROVIDER_EXAMPLES,
                n_tricky=CLAUDE_NUM_TRICKY_EXAMPLES
            )

        # Cache
        self._cached_version = version
        self._cached_system_prompt = prompt_text
        self._cached_examples = few_shot_examples
        self._cache_time = datetime.now()

        logger.info(f"Loaded prompt version: {version} with {len(few_shot_examples)} examples")

        return {
            'version': version,
            'system_prompt': prompt_text,
            'few_shot_examples': few_shot_examples
        }

    def _get_default_prompt(self) -> dict:
        """Return default prompt if database is empty."""
        logger.warning("Using default prompt (database had no active version)")

        default_prompt = """You are a business verification specialist. Your task is to determine if a company is a legitimate service provider (e.g., pressure washing, window cleaning) or a non-provider (directory, equipment seller, training course, blog, lead generation agency).

## Context
You have access to:
- Automated verification signals (scores, ML predictions, red flags)
- Website content (services, about, homepage text)
- Business info (name, contact, location)

## Decision Criteria
APPROVE (legitimate provider) if:
- Offers direct services to customers (residential or commercial)
- Has clear contact info (phone, address, or service area)
- No red flags indicating directory/agency/franchise

DENY (non-provider) if:
- Directory or listing site
- Equipment sales only
- Training courses only
- Lead generation agency
- Blog or information-only site
- Franchise directory

UNCLEAR if:
- Insufficient information
- Conflicting signals
- Legitimate provider BUT also sells equipment/training

## Output Format
Respond with JSON:
{
  "decision": "approve" | "deny" | "unclear",
  "confidence": 0.85,  // 0.0-1.0
  "reasoning": "Brief explanation of decision (2-3 sentences)",
  "primary_services": ["pressure washing", "window cleaning"],
  "red_flags": ["franchise"] | [],
  "is_provider": true | false
}"""

        return {
            'version': 'default',
            'system_prompt': default_prompt,
            'few_shot_examples': []
        }

    def _build_company_context(self, company: dict) -> str:
        """
        Build company-specific context for prompt.

        This part is NOT cached (unique per company).

        Args:
            company: Company data from database

        Returns:
            Formatted company context string
        """
        metadata = company.get('parse_metadata', {})
        verification = metadata.get('verification', {})
        llm_class = verification.get('llm_classification', {})

        # Extract company info
        company_id = company.get('id', 0)
        name = company.get('name', 'Unknown')
        website = company.get('website', '')
        domain = website.replace('https://', '').replace('http://', '').split('/')[0] if website else ''

        # Automated signals
        automated_signals = {
            'final_score': float(verification.get('final_score', 0.0)),
            'ml_probability': float(verification.get('ml_probability', 0.0)),
            'llm_classification': {
                'type': llm_class.get('type', 'unknown'),
                'confidence': llm_class.get('confidence', 0.0),
                'services': llm_class.get('services', []),
                'scope': llm_class.get('scope', 'unknown')
            },
            'red_flags': verification.get('red_flags', []),
            'quality_signals': verification.get('quality_signals', [])
        }

        # Website content (truncated)
        website_content = {
            'services': self._truncate_text(metadata.get('services_text', ''), 500),
            'about': self._truncate_text(metadata.get('about_text', ''), 500),
            'homepage': self._truncate_text(metadata.get('homepage_text', ''), 300)
        }

        # Business info
        business_info = {
            'phone': metadata.get('phone', ''),
            'email': metadata.get('email', ''),
            'address': metadata.get('address', ''),
            'service_area': metadata.get('service_area', '')
        }

        # Build JSON context
        context = {
            'company_id': company_id,
            'name': name,
            'website': website,
            'domain': domain,
            'automated_signals': automated_signals,
            'website_content': website_content,
            'business_info': business_info
        }

        # Format as pretty JSON
        return json.dumps(context, indent=2)

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to max length, preferring sentence boundaries."""
        if not text or len(text) <= max_length:
            return text

        # Try to cut at sentence boundary
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')

        cut_point = max(last_period, last_newline)
        if cut_point > max_length * 0.7:  # Only use if we're not cutting too much
            return text[:cut_point + 1].strip()

        # Otherwise just truncate and add ellipsis
        return text[:max_length].strip() + '...'

    def invalidate_cache(self):
        """Invalidate cached prompt version (force reload on next build)."""
        self._cached_version = None
        self._cached_system_prompt = None
        self._cached_examples = None
        self._cache_time = None
        logger.info("Prompt cache invalidated")


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def test_prompt_manager():
    """Test prompt manager."""
    print("Testing PromptManager...")

    pm = PromptManager()

    # Get a sample company
    db_manager = DatabaseManager()
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, website, parse_metadata
            FROM companies
            WHERE active = true
              AND parse_metadata IS NOT NULL
            LIMIT 1
        """)
        row = cursor.fetchone()

    if not row:
        print("ERROR: No companies found in database")
        return

    company_id, name, website, metadata = row
    company = {
        'id': company_id,
        'name': name,
        'website': website,
        'parse_metadata': metadata
    }

    # Build prompt
    prompt_data = pm.build_prompt(company)

    print(f"\n✓ Prompt built successfully")
    print(f"  Version: {prompt_data['prompt_version']}")
    print(f"  System prompt length: {len(prompt_data['system_prompt'])} chars")
    print(f"  Few-shot examples: {len(prompt_data['few_shot_examples'])}")
    print(f"  Company context length: {len(prompt_data['company_context'])} chars")

    print(f"\nSystem prompt preview:")
    print(prompt_data['system_prompt'][:300] + '...')

    print(f"\nCompany context preview:")
    print(prompt_data['company_context'][:500] + '...')

    return prompt_data


if __name__ == "__main__":
    test_prompt_manager()

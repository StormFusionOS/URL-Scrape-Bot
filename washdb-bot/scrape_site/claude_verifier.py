#!/usr/bin/env python3
"""
Claude API-based company verification for high-quality re-verification.

Used for companies that need expert review (status="unknown" from initial pass).
More expensive but more accurate than local LLM.
"""

import logging
import os
from typing import Dict, Optional
import anthropic
from dotenv import load_dotenv

load_dotenv()


class ClaudeVerifier:
    """
    Claude API verifier for high-quality company classification.

    Used selectively for companies that need expert review after
    initial Ollama/Mistral verification.
    """

    def __init__(self):
        """Initialize Claude API verifier."""
        self.logger = logging.getLogger(__name__)
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-3-haiku-20240307')

        if not self.api_key or self.api_key == 'your-api-key-here':
            raise ValueError("ANTHROPIC_API_KEY not set in .env")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.logger.info(f"Claude verifier initialized: {self.model}")

    def classify_company(
        self,
        company_name: str,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        deep_verify: bool = True
    ) -> Optional[Dict]:
        """
        Classify a company using Claude API.

        Args:
            company_name: Company name
            services_text: Services section text
            about_text: About section text
            homepage_text: Homepage text
            deep_verify: If True, run full verification (default)

        Returns:
            Classification dict matching Ollama format for compatibility
        """

        # Build context (same as Ollama verifier)
        context = self._build_context(company_name, services_text, about_text, homepage_text)

        # Use single comprehensive prompt instead of multiple questions
        prompt = self._build_verification_prompt(company_name, context)

        try:
            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                temperature=0.0,  # Deterministic
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            response = message.content[0].text

            # Parse response into structured format
            result = self._parse_response(response)

            # Log usage
            self.logger.info(f"Claude API call: {message.usage.input_tokens} in, {message.usage.output_tokens} out")

            return result

        except Exception as e:
            self.logger.error(f"Claude API error: {e}")
            return None

    def _build_context(self, name: str, services: str, about: str, homepage: str) -> str:
        """Build context from available text."""
        context_parts = [f"Company: {name}"]

        if services:
            context_parts.append(f"\nServices:\n{services[:2000]}")
        if about:
            context_parts.append(f"\nAbout:\n{about[:2000]}")
        if homepage:
            context_parts.append(f"\nHomepage:\n{homepage[:1500]}")

        return "\n".join(context_parts)

    def _build_verification_prompt(self, name: str, context: str) -> str:
        """Build comprehensive verification prompt for Claude."""
        return f"""You are an expert business classifier. Analyze this company and provide a detailed assessment.

{context}

Provide your analysis in this EXACT format (use these exact labels):

TYPE: [Choose ONE: service_provider, equipment_seller, training_company, directory, blog, lead_generation, marketing_agency]

SERVICES:
- Pressure washing: [yes/no]
- Window cleaning: [yes/no]
- Wood restoration: [yes/no]

SCOPE: [Choose ONE: both_residential_and_commercial, residential_only, commercial_only, unclear]

LEGITIMATE: [yes/no - Is this a real operating business that performs services for customers?]

QUALITY_SIGNALS: [List specific positive indicators, one per line]
-

RED_FLAGS: [List specific concerns, one per line]
-

CONFIDENCE: [0.0 to 1.0 - How confident are you in this assessment?]

REASONING: [Brief explanation of your decision]

IMPORTANT DISTINCTIONS:
1. SERVICE PROVIDER = Directly performs services for customers (this is what we want)
2. EQUIPMENT SELLER = Sells pressure washers, cleaning supplies, etc. (NOT what we want)
3. TRAINING = Teaches how to start a business (NOT what we want)
4. DIRECTORY = Lists other companies (NOT what we want)
5. LEAD GEN = Sells leads to contractors (NOT what we want)
6. BLOG = Informational content only (NOT what we want)

Focus on whether they DIRECTLY PROVIDE SERVICES to customers."""

    def _parse_response(self, response: str) -> Dict:
        """Parse Claude's response into structured format matching Ollama output."""
        result = {
            'type': 1,  # Default to service provider
            'pressure_washing': False,
            'window_cleaning': False,
            'wood_restoration': False,
            'scope': 4,  # Unclear
            'is_legitimate': False,
            'quality_signals': [],
            'red_flags': [],
            'confidence': 0.5
        }

        lines = response.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()

            # Parse TYPE
            if line.startswith('TYPE:'):
                type_str = line.split(':', 1)[1].strip().lower()
                type_map = {
                    'service_provider': 1,
                    'equipment_seller': 2,
                    'training_company': 3,
                    'directory': 4,
                    'blog': 5,
                    'lead_generation': 6,
                    'marketing_agency': 6
                }
                result['type'] = type_map.get(type_str, 1)

            # Parse SERVICES
            elif 'pressure washing:' in line.lower():
                result['pressure_washing'] = 'yes' in line.lower()
            elif 'window cleaning:' in line.lower():
                result['window_cleaning'] = 'yes' in line.lower()
            elif 'wood restoration:' in line.lower():
                result['wood_restoration'] = 'yes' in line.lower()

            # Parse SCOPE
            elif line.startswith('SCOPE:'):
                scope_str = line.split(':', 1)[1].strip().lower()
                scope_map = {
                    'both': 1,
                    'both_residential_and_commercial': 1,
                    'residential': 2,
                    'residential_only': 2,
                    'commercial': 3,
                    'commercial_only': 3,
                    'unclear': 4
                }
                result['scope'] = scope_map.get(scope_str, 4)

            # Parse LEGITIMATE
            elif line.startswith('LEGITIMATE:'):
                result['is_legitimate'] = 'yes' in line.lower()

            # Parse CONFIDENCE
            elif line.startswith('CONFIDENCE:'):
                try:
                    conf_str = line.split(':', 1)[1].strip()
                    result['confidence'] = float(conf_str)
                except:
                    result['confidence'] = 0.5

            # Track sections
            elif line.startswith('QUALITY_SIGNALS:'):
                current_section = 'quality'
            elif line.startswith('RED_FLAGS:'):
                current_section = 'red_flags'
            elif line.startswith('REASONING:'):
                current_section = None

            # Parse list items
            elif line.startswith('-') and current_section:
                item = line.lstrip('- ').strip()
                if item and current_section == 'quality':
                    result['quality_signals'].append(item)
                elif item and current_section == 'red_flags':
                    result['red_flags'].append(item)

        return result

#!/usr/bin/env python3
"""
LLM-based company verification using Ollama (Llama 3.2 3B).

Uses Ollama's local API for natural language understanding of company websites to classify:
1. Service type (target service provider vs equipment/blog/directory)
2. Specific services offered (pressure washing, window cleaning, wood restoration)
3. Service scope (residential, commercial, or both)

Designed to augment keyword-based verification for borderline cases.
"""

import logging
import requests
from typing import Dict, Optional, Tuple


class LLMVerifier:
    """
    LLM-based company classifier using Ollama (Llama 3.2 3B).

    Uses Ollama's local API for zero-shot classification with structured prompts.
    Optimized for low latency (~2-4 seconds per classification).
    """

    def __init__(
        self,
        model_name: str = "llama3.2:3b",
        api_url: str = "http://localhost:11434/api/generate"
    ):
        """
        Initialize LLM verifier with Ollama.

        Args:
            model_name: Ollama model name (default: llama3.2:3b)
            api_url: Ollama API endpoint
        """
        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.api_url = api_url

        self.logger.info(f"LLM verifier initialized: {model_name}")

    def classify_company(
        self,
        company_name: str,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        max_length: int = 512
    ) -> Optional[Dict]:
        """
        Classify a company using LLM with separate yes/no questions.

        Args:
            company_name: Company name
            services_text: Services section text
            about_text: About section text
            homepage_text: Homepage text
            max_length: Maximum context length (not used with Ollama but kept for API compatibility)

        Returns:
            Classification dict with keys:
            - type: int (1=service provider, 2=equipment, 3=training, 4=directory, 5=blog)
            - pressure_washing: bool
            - window_cleaning: bool
            - wood_restoration: bool
            - scope: int (1=both, 2=residential, 3=commercial, 4=unclear)
            - confidence: float (0-1)
        """
        try:
            # Build context
            context = self._build_context(company_name, services_text, about_text, homepage_text)

            # Ask each question separately for more reliable answers
            result = {}

            # Question 1: Is this a service provider?
            is_service_provider = self._ask_yesno(context,
                "Is this a company that provides pressure washing, window cleaning, or wood restoration services to customers?")

            if not is_service_provider:
                # Check if it's equipment/blog/directory
                is_equipment = self._ask_yesno(context, "Does this company sell equipment or products?")
                is_blog = self._ask_yesno(context, "Is this a blog, tutorial website, or informational content site?")

                if is_equipment:
                    result['type'] = 2
                elif is_blog:
                    result['type'] = 5
                else:
                    result['type'] = 4  # Directory/other
                result['pressure_washing'] = False
                result['window_cleaning'] = False
                result['wood_restoration'] = False
                result['scope'] = 4
                result['confidence'] = 0.7
                return result

            # It's a service provider - check which services
            result['type'] = 1
            result['pressure_washing'] = self._ask_yesno(context,
                "Does this company offer pressure washing or power washing services?")
            result['window_cleaning'] = self._ask_yesno(context,
                "Does this company offer window cleaning services?")
            result['wood_restoration'] = self._ask_yesno(context,
                "Does this company offer wood restoration, deck staining, or deck sealing services?")

            # Check scope
            serves_residential = self._ask_yesno(context,
                "Does this company serve residential customers or homeowners?")
            serves_commercial = self._ask_yesno(context,
                "Does this company serve commercial customers or businesses?")

            if serves_residential and serves_commercial:
                result['scope'] = 1
            elif serves_residential:
                result['scope'] = 2
            elif serves_commercial:
                result['scope'] = 3
            else:
                result['scope'] = 4

            result['confidence'] = 0.8
            self.logger.debug(f"LLM classified '{company_name}': {result}")
            return result

        except Exception as e:
            self.logger.error(f"LLM classification error for '{company_name}': {e}")
            return None

    def _build_context(
        self,
        company_name: str,
        services_text: str,
        about_text: str,
        homepage_text: str
    ) -> str:
        """
        Build context summary for yes/no questions.
        """
        # Truncate texts to reasonable lengths
        services_text = (services_text or "")[:400]
        about_text = (about_text or "")[:400]
        homepage_text = (homepage_text or "")[:200]

        context = f"Company: {company_name}\n"
        if services_text:
            context += f"Services: {services_text}\n"
        if about_text:
            context += f"About: {about_text}\n"
        if homepage_text:
            context += f"Website: {homepage_text}\n"

        return context.strip()

    def _ask_yesno(self, context: str, question: str) -> bool:
        """
        Ask a yes/no question about the context using Ollama.

        Args:
            context: Company context text
            question: Yes/no question

        Returns:
            True if yes, False if no
        """
        prompt = f"""{context}

Question: {question}

Answer yes or no:"""

        response = self._generate(prompt, max_tokens=10)
        response_lower = response.lower().strip()

        # Parse yes/no
        is_yes = any(word in response_lower for word in ['yes', 'y', 'true', 'correct', 'affirmative'])
        is_no = any(word in response_lower for word in ['no', 'n', 'false', 'incorrect', 'negative', 'not'])

        # Debug logging
        print(f"[DEBUG] Q: {question[:60]}... A: {response} -> {is_yes and not is_no}")

        # Default to no if unclear
        return is_yes and not is_no

    def _generate(self, prompt: str, max_tokens: int = 50) -> str:
        """
        Generate text from prompt using Ollama API.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text
        """
        try:
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temperature for consistent answers
                    "num_predict": max_tokens,
                    "top_p": 0.9,
                    "top_k": 40
                }
            }

            response = requests.post(
                self.api_url,
                json=payload,
                timeout=10.0  # 10 second timeout
            )
            response.raise_for_status()

            result = response.json()
            return result.get("response", "").strip()

        except requests.Timeout:
            self.logger.error("Ollama API timeout")
            return ""
        except requests.RequestException as e:
            self.logger.error(f"Ollama API error: {e}")
            return ""
        except Exception as e:
            self.logger.error(f"Unexpected error calling Ollama: {e}")
            return ""

    def calculate_llm_score(self, classification: Dict, discovery_source: str = "") -> Tuple[float, Dict]:
        """
        Calculate verification score from LLM classification.

        Mirrors the scoring logic from service_verifier.py but uses LLM
        classification results instead of keyword matching.

        Args:
            classification: LLM classification dict
            discovery_source: How company was discovered (for weighting)

        Returns:
            Tuple of (score, details_dict)
        """
        score = 0.0
        details = {
            'type_score': 0,
            'service_score': 0,
            'scope_score': 0,
            'confidence_penalty': 0,
            'total': 0
        }

        # Type scoring
        if classification['type'] == 1:
            # Target service provider
            details['type_score'] = 30
        elif classification['type'] in [2, 3, 4]:
            # Equipment/training/directory - negative signal
            details['type_score'] = -20
        else:
            # Blog/informational
            details['type_score'] = -10

        score += details['type_score']

        # Service scoring (tier-based)
        services_count = sum([
            classification.get('pressure_washing', False),
            classification.get('window_cleaning', False),
            classification.get('wood_restoration', False)
        ])

        if services_count >= 3:
            details['service_score'] = 40  # Tier A
        elif services_count == 2:
            details['service_score'] = 30  # Tier B
        elif services_count == 1:
            details['service_score'] = 20  # Tier C
        else:
            details['service_score'] = 5   # Tier E

        score += details['service_score']

        # Scope scoring
        scope = classification.get('scope', 4)
        if scope == 1:  # Both residential and commercial
            details['scope_score'] = 10
        elif scope in [2, 3]:  # One or the other
            details['scope_score'] = 5
        else:  # Unclear
            details['scope_score'] = 0

        score += details['scope_score']

        # Confidence penalty for low-confidence classifications
        confidence = classification.get('confidence', 0.5)
        if confidence < 0.5:
            details['confidence_penalty'] = -10
            score += details['confidence_penalty']

        # Normalize to 0-100 range
        score = max(0, min(100, score))
        details['total'] = score

        return score, details


# Module-level instance for reuse across workers
_llm_verifier_instance = None


def get_llm_verifier(model_name: str = "llama3.2:3b") -> LLMVerifier:
    """
    Get or create singleton LLM verifier instance.

    Reuses the same instance across calls to avoid reinitializing.
    """
    global _llm_verifier_instance

    if _llm_verifier_instance is None:
        _llm_verifier_instance = LLMVerifier(model_name=model_name)

    return _llm_verifier_instance

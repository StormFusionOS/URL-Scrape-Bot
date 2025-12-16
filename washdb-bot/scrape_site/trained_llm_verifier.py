#!/usr/bin/env python3
"""
Trained LLM verification using the fine-tuned verification-mistral-proper model.

This verifier uses a single-shot prompt approach with actual page content,
letting the trained model make the verification decision directly.

Key differences from the old llm_verifier.py:
- Uses the fine-tuned verification-mistral-proper model (trained on 50k+ samples)
- Single API call per company (vs 15+ yes/no questions)
- Passes actual page content (title, homepage_text, services_text)
- Model returns JSON with legitimate/confidence/services/reasoning

Optimized for RTX 3060 GPU (12GB VRAM) running 24/7.
"""

import json
import logging
import os
import re
import requests
from typing import Dict, List, Optional, Tuple

from verification.config_verifier import (
    LLM_SERVICES_TEXT_LIMIT,
    LLM_ABOUT_TEXT_LIMIT,
    LLM_HOMEPAGE_TEXT_LIMIT,
)


class TrainedLLMVerifier:
    """
    Trained LLM-based company classifier using the fine-tuned Mistral model.

    Uses the verification-mistral-proper model via Ollama for single-shot
    verification based on actual page content.
    """

    # System prompt for the trained model
    SYSTEM_PROMPT = """You are verifying if a business offers exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration/deck cleaning.

Based on the company name and website content, determine if this is a legitimate service provider.

Respond with ONLY a JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}"""

    def __init__(
        self,
        model_name: str = None,
        api_url: str = "http://localhost:11434/api/generate",
        use_queue: bool = None
    ):
        """
        Initialize trained LLM verifier.

        Args:
            model_name: Ollama model name (default: verification-mistral-proper)
            api_url: Ollama API endpoint
            use_queue: If True, use centralized queue (default: from env)
        """
        if model_name is None:
            model_name = os.getenv("OLLAMA_MODEL", "verification-mistral-proper")

        if use_queue is None:
            use_queue = os.getenv("USE_LLM_QUEUE", "true").lower() in ("true", "1", "yes")

        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.api_url = api_url
        self.use_queue = use_queue

        mode_str = "queue" if use_queue else "direct"
        self.logger.info(f"Trained LLM verifier initialized: {model_name} (mode={mode_str})")

    def classify_company(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        deep_verify: bool = True  # Kept for API compatibility
    ) -> Optional[Dict]:
        """
        Classify a company using the trained model in a single call.

        Args:
            company_name: Company name
            website: Website URL
            phone: Phone number
            title: Page title
            services_text: Services section text
            about_text: About section text
            homepage_text: Homepage text

        Returns:
            Classification dict with:
            - legitimate: bool (is this a legitimate exterior cleaning provider)
            - confidence: float (0-1)
            - services: list of detected services
            - reasoning: explanation
            - type: int (1=service provider, for compatibility)
            - pressure_washing, window_cleaning, wood_restoration: bool flags
            - red_flags, quality_signals: lists (for compatibility)
        """
        try:
            # Build the prompt with actual content
            prompt = self._build_prompt(
                company_name=company_name,
                website=website,
                phone=phone,
                title=title,
                services_text=services_text,
                about_text=about_text,
                homepage_text=homepage_text
            )

            # Query the model (single call)
            response = self._query_model(prompt)

            if not response.get('success'):
                self.logger.warning(f"Model query failed for '{company_name}': {response.get('error')}")
                return None

            # Parse the response
            result = self._parse_response(response, company_name)
            return result

        except Exception as e:
            self.logger.error(f"Classification error for '{company_name}': {e}")
            return None

    def _build_prompt(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = ""
    ) -> str:
        """Build the prompt with actual page content."""
        # Truncate long content
        homepage_text = (homepage_text or "")[:LLM_HOMEPAGE_TEXT_LIMIT]
        services_text = (services_text or "")[:LLM_SERVICES_TEXT_LIMIT]
        about_text = (about_text or "")[:LLM_ABOUT_TEXT_LIMIT]

        prompt = f"Company: {company_name}\n"
        prompt += f"Website: {website}\n"

        if phone:
            prompt += f"Phone: {phone}\n"

        if title:
            prompt += f"Page title: {title}\n"

        if homepage_text:
            prompt += f"\nHomepage excerpt:\n{homepage_text}\n"

        if services_text:
            prompt += f"\nServices page excerpt:\n{services_text}\n"
        elif about_text:
            prompt += f"\nAbout page excerpt:\n{about_text}\n"

        prompt += "\nDoes this company provide exterior cleaning services (pressure washing, window cleaning, soft washing, roof/gutter cleaning, wood restoration)? Assess if legitimate."

        return prompt

    def _query_model(self, prompt: str, timeout: float = 30.0) -> Dict:
        """Query the trained model via Ollama API."""
        # Format with Mistral Instruct template
        full_prompt = f"<s>[INST] {self.SYSTEM_PROMPT}\n\n{prompt} [/INST]"

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.85,
                "top_k": 40,
                "num_predict": 400,
                "repeat_penalty": 1.2,
            }
        }

        try:
            if self.use_queue:
                # Use centralized queue for steady GPU usage
                from verification.llm_queue import llm_generate_raw
                response_text = llm_generate_raw(
                    prompt=full_prompt,
                    model=self.model_name,
                    max_tokens=400,
                    timeout=timeout
                )
            else:
                # Direct Ollama call
                response = requests.post(self.api_url, json=payload, timeout=timeout)
                response.raise_for_status()
                result = response.json()
                response_text = result.get("response", "").strip()

            # Try to parse JSON from response
            try:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1

                if json_start >= 0 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    parsed = json.loads(json_str)
                    return {
                        "success": True,
                        "response": parsed,
                        "raw": response_text
                    }
            except json.JSONDecodeError:
                pass

            return {
                "success": False,
                "response": None,
                "raw": response_text,
                "error": "Failed to parse JSON from response"
            }

        except requests.Timeout:
            return {"success": False, "error": "timeout", "raw": ""}
        except Exception as e:
            return {"success": False, "error": str(e), "raw": ""}

    def _parse_response(self, response: Dict, company_name: str) -> Dict:
        """Parse the model response into the expected format."""
        parsed = response.get('response', {})

        # Extract core fields
        legitimate = parsed.get('legitimate', False)
        confidence = parsed.get('confidence', 0.0)
        services = parsed.get('services', [])
        reasoning = parsed.get('reasoning', '')

        # Normalize services list
        if isinstance(services, str):
            services = [s.strip() for s in services.split(',')]

        # Detect specific service types from the services list
        services_lower = ' '.join(services).lower() if services else ''
        reasoning_lower = reasoning.lower()

        pressure_washing = any(kw in services_lower or kw in reasoning_lower
                               for kw in ['pressure wash', 'power wash', 'soft wash'])
        window_cleaning = 'window' in services_lower or 'window' in reasoning_lower
        wood_restoration = any(kw in services_lower or kw in reasoning_lower
                               for kw in ['deck', 'wood', 'fence stain', 'restoration'])

        # Build quality signals and red flags based on legitimacy
        quality_signals = []
        red_flags = []

        if legitimate:
            quality_signals.append("Trained model: Legitimate service provider")
            if services:
                quality_signals.append(f"Services detected: {', '.join(services[:3])}")
        else:
            red_flags.append(f"Trained model: Not a legitimate exterior cleaning provider")
            if reasoning:
                red_flags.append(f"Reason: {reasoning[:100]}")

        # Determine type (for compatibility with old system)
        # type 1 = service provider, type 4 = other/unknown
        company_type = 1 if legitimate else 4

        # Determine scope (1=both, 2=residential, 3=commercial, 4=unclear)
        scope = 4
        if legitimate:
            scope = 1  # Assume both if legitimate

        result = {
            # Core classification
            'legitimate': legitimate,
            'is_legitimate': legitimate,
            'confidence': confidence,
            'services': services,
            'reasoning': reasoning,

            # Service flags (compatibility)
            'pressure_washing': pressure_washing,
            'window_cleaning': window_cleaning,
            'wood_restoration': wood_restoration,

            # Type and scope (compatibility)
            'type': company_type,
            'scope': scope,

            # Signals (compatibility)
            'quality_signals': quality_signals,
            'red_flags': red_flags,

            # Raw for debugging
            'raw_response': response.get('raw', '')[:500]
        }

        self.logger.debug(
            f"Trained model classified '{company_name}': "
            f"legitimate={legitimate}, confidence={confidence:.2f}, "
            f"services={services}"
        )

        return result

    def calculate_llm_score(self, classification: Dict, discovery_source: str = "") -> Tuple[float, Dict]:
        """
        Calculate verification score from trained model classification.

        Simpler scoring since the trained model gives us direct legitimacy.

        Args:
            classification: Classification dict from classify_company
            discovery_source: How company was discovered (for weighting)

        Returns:
            Tuple of (score 0-100, details_dict)
        """
        score = 0.0
        details = {
            'legitimacy_score': 0,
            'confidence_score': 0,
            'service_score': 0,
            'total': 0
        }

        # Core legitimacy (60 points max)
        if classification.get('legitimate', False):
            details['legitimacy_score'] = 60
        else:
            details['legitimacy_score'] = 0

        score += details['legitimacy_score']

        # Confidence boost (20 points max)
        confidence = classification.get('confidence', 0.0)
        details['confidence_score'] = int(confidence * 20)
        score += details['confidence_score']

        # Service detection bonus (20 points max)
        services_count = sum([
            classification.get('pressure_washing', False),
            classification.get('window_cleaning', False),
            classification.get('wood_restoration', False)
        ])
        details['service_score'] = min(services_count * 7, 20)
        score += details['service_score']

        # Normalize to 0-100
        score = max(0, min(100, score))
        details['total'] = score

        return score, details

    def quick_classify(
        self,
        company_name: str,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = ""
    ) -> Optional[Dict]:
        """
        Quick classification (same as full for trained model).

        API compatibility with old LLMVerifier.
        """
        return self.classify_company(
            company_name=company_name,
            services_text=services_text,
            about_text=about_text,
            homepage_text=homepage_text
        )


# Module-level instance for reuse
_trained_verifier_instance = None


def get_trained_llm_verifier(model_name: str = None) -> TrainedLLMVerifier:
    """
    Get or create singleton trained LLM verifier instance.

    Default model: verification-mistral-proper (configurable via OLLAMA_MODEL env var)
    """
    global _trained_verifier_instance

    if _trained_verifier_instance is None:
        _trained_verifier_instance = TrainedLLMVerifier(model_name=model_name)

    return _trained_verifier_instance


# Alias for drop-in replacement
def get_llm_verifier(model_name: str = None) -> TrainedLLMVerifier:
    """Alias for get_trained_llm_verifier for drop-in compatibility."""
    return get_trained_llm_verifier(model_name=model_name)

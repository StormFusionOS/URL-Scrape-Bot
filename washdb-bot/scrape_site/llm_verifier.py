#!/usr/bin/env python3
"""
LLM-based company verification using Ollama (Mistral 7B).

Enhanced verification system with:
1. Service detection (pressure washing, window cleaning, wood restoration)
2. Company type classification (service provider vs equipment/blog/directory)
3. Legitimacy assessment (real business vs spam/fake)
4. Content quality scoring
5. Red flag detection (training sites, lead gen, marketing agencies)

Optimized for RTX 3060 GPU (12GB VRAM) running 24/7.

Supports two modes:
- Direct: Each worker calls Ollama directly (original behavior)
- Queue: Requests go through centralized queue for steady GPU usage
  Set USE_LLM_QUEUE=true to enable queue mode (recommended for 5+ workers)
"""

import logging
import os
import requests
from typing import Dict, List, Optional, Tuple


class LLMVerifier:
    """
    Enhanced LLM-based company classifier using Ollama (Mistral 7B).

    Uses Ollama's local API for comprehensive business verification.
    GPU-accelerated for fast 24/7 operation (~1-2s per question).

    Supports two modes:
    - Direct: Each call goes directly to Ollama (original)
    - Queue: Requests go through centralized queue for steady GPU usage
    """

    def __init__(
        self,
        model_name: str = None,
        api_url: str = "http://localhost:11434/api/generate",
        use_queue: bool = None
    ):
        """
        Initialize LLM verifier with Ollama.

        Args:
            model_name: Ollama model name (default: mistral:7b via OLLAMA_MODEL env var)
            api_url: Ollama API endpoint
            use_queue: If True, use centralized queue for steady GPU usage.
                       Default: True if USE_LLM_QUEUE env var is set to 'true'
        """
        if model_name is None:
            model_name = os.getenv("OLLAMA_MODEL", "mistral:7b")

        if use_queue is None:
            use_queue = os.getenv("USE_LLM_QUEUE", "true").lower() in ("true", "1", "yes")

        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.api_url = api_url
        self.use_queue = use_queue

        mode_str = "queue" if use_queue else "direct"
        self.logger.info(f"LLM verifier initialized: {model_name} (mode={mode_str})")

    def classify_company(
        self,
        company_name: str,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        deep_verify: bool = True
    ) -> Optional[Dict]:
        """
        Classify a company using comprehensive LLM analysis.

        Args:
            company_name: Company name
            services_text: Services section text
            about_text: About section text
            homepage_text: Homepage text
            deep_verify: If True, run full verification (default). If False, quick mode.

        Returns:
            Classification dict with:
            - type: int (1=service provider, 2=equipment, 3=training, 4=directory, 5=blog, 6=lead_gen)
            - pressure_washing: bool
            - window_cleaning: bool
            - wood_restoration: bool
            - scope: int (1=both, 2=residential, 3=commercial, 4=unclear)
            - is_legitimate: bool (real operating business)
            - red_flags: list of detected issues
            - quality_signals: list of positive indicators
            - confidence: float (0-1)
        """
        try:
            context = self._build_context(company_name, services_text, about_text, homepage_text)

            result = {
                'red_flags': [],
                'quality_signals': []
            }

            # === PHASE 1: Service Detection ===
            result['pressure_washing'] = self._ask_yesno(context,
                "Does this company offer pressure washing or power washing services?")
            result['window_cleaning'] = self._ask_yesno(context,
                "Does this company offer window cleaning services?")
            result['wood_restoration'] = self._ask_yesno(context,
                "Does this company offer deck staining, deck sealing, or wood restoration services?")

            has_target_services = any([
                result['pressure_washing'],
                result['window_cleaning'],
                result['wood_restoration']
            ])

            # === PHASE 2: Business Type Classification ===
            if has_target_services:
                result['type'] = 1  # Service provider

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
                    result['scope'] = 1  # Default to both if unclear

                result['quality_signals'].append("Offers target services")
            else:
                # Determine non-service type
                result['type'], type_flag = self._classify_non_service_type(context)
                if type_flag:
                    result['red_flags'].append(type_flag)
                result['scope'] = 4

            # === PHASE 3: Deep Verification (if enabled) ===
            if deep_verify:
                self._run_deep_verification(context, result, has_target_services)

            # === PHASE 4: Calculate Confidence ===
            result['confidence'] = self._calculate_confidence(result)
            result['is_legitimate'] = self._assess_legitimacy(result)

            self.logger.debug(f"LLM classified '{company_name}': type={result['type']}, "
                            f"legitimate={result['is_legitimate']}, confidence={result['confidence']:.2f}")
            return result

        except Exception as e:
            self.logger.error(f"LLM classification error for '{company_name}': {e}")
            return None

    def _classify_non_service_type(self, context: str) -> Tuple[int, Optional[str]]:
        """Classify what type of non-service site this is."""
        # Check for equipment seller
        if self._ask_yesno(context,
            "Does this company primarily sell equipment, machines, or products?"):
            return 2, "Equipment seller, not service provider"

        # Check for training/course site
        if self._ask_yesno(context,
            "Does this website offer training courses, coaching, or business education?"):
            return 3, "Training/course site"

        # Check for lead generation / marketing
        if self._ask_yesno(context,
            "Is this a marketing agency, lead generation service, or advertising company?"):
            return 6, "Lead generation or marketing agency"

        # Check for blog/informational
        if self._ask_yesno(context,
            "Is this primarily a blog, tutorial site, or informational website?"):
            return 5, "Blog or informational site"

        # Check for directory listing
        if self._ask_yesno(context,
            "Is this a directory, listing site, or aggregator of multiple businesses?"):
            return 4, "Directory or listing site"

        return 4, None  # Default to directory/other

    def _run_deep_verification(self, context: str, result: Dict, has_services: bool):
        """Run comprehensive verification checks."""

        # === Legitimacy Checks ===

        # Check for local business indicators
        has_service_area = self._ask_yesno(context,
            "Does this company mention a specific city, state, or service area?")
        if has_service_area:
            result['quality_signals'].append("Mentions specific service area")
        else:
            result['red_flags'].append("No specific service area mentioned")

        # Check for contact information presence
        has_contact = self._ask_yesno(context,
            "Does this website show contact information like a phone number or email?")
        if has_contact:
            result['quality_signals'].append("Contact information present")
        else:
            result['red_flags'].append("No contact information visible")

        # Check for company history/experience
        has_experience = self._ask_yesno(context,
            "Does this company mention years in business, experience, or established date?")
        if has_experience:
            result['quality_signals'].append("Business experience mentioned")

        # === Red Flag Detection ===

        # Check for "how to start" content (not a real service company)
        is_howto = self._ask_yesno(context,
            "Does this content teach how to start a pressure washing or cleaning business?")
        if is_howto:
            result['red_flags'].append("Teaching how to start business (not a service provider)")
            result['type'] = 3  # Override to training

        # Check for franchise/opportunity selling
        is_franchise = self._ask_yesno(context,
            "Is this company selling franchises, business opportunities, or coaching programs?")
        if is_franchise:
            result['red_flags'].append("Selling franchises or business opportunities")
            result['type'] = 3

        # Check for thin/template content
        is_thin = self._ask_yesno(context,
            "Does this website have very generic content that could apply to any cleaning company?")
        if is_thin:
            result['red_flags'].append("Generic/template content detected")

        # === Service Provider Quality Checks (only if has services) ===
        if has_services and result['type'] == 1:
            # Check for real project examples
            has_examples = self._ask_yesno(context,
                "Does this company mention specific projects, before/after results, or case studies?")
            if has_examples:
                result['quality_signals'].append("Specific project examples mentioned")

            # Check for team/owner information
            has_team = self._ask_yesno(context,
                "Does this company mention the owner's name, team members, or staff?")
            if has_team:
                result['quality_signals'].append("Owner/team information present")

            # Check for insurance/licensing
            is_insured = self._ask_yesno(context,
                "Does this company mention being licensed, insured, or bonded?")
            if is_insured:
                result['quality_signals'].append("Licensed/insured mentioned")

            # Check for pricing transparency
            has_pricing = self._ask_yesno(context,
                "Does this company offer free quotes, estimates, or mention pricing?")
            if has_pricing:
                result['quality_signals'].append("Pricing/quotes offered")

    def _calculate_confidence(self, result: Dict) -> float:
        """Calculate confidence score based on signals."""
        base_confidence = 0.5

        # Boost for quality signals
        quality_boost = len(result.get('quality_signals', [])) * 0.08
        base_confidence += min(quality_boost, 0.35)  # Cap at 0.35 boost

        # Penalty for red flags
        red_flag_penalty = len(result.get('red_flags', [])) * 0.12
        base_confidence -= min(red_flag_penalty, 0.40)  # Cap penalty at 0.40

        # Boost for service providers with services
        if result.get('type') == 1:
            service_count = sum([
                result.get('pressure_washing', False),
                result.get('window_cleaning', False),
                result.get('wood_restoration', False)
            ])
            base_confidence += service_count * 0.05

        return max(0.1, min(0.95, base_confidence))

    def _assess_legitimacy(self, result: Dict) -> bool:
        """Determine if this appears to be a legitimate operating business."""
        # Must be a service provider
        if result.get('type') != 1:
            return False

        # Must have at least one target service
        has_services = any([
            result.get('pressure_washing'),
            result.get('window_cleaning'),
            result.get('wood_restoration')
        ])
        if not has_services:
            return False

        # Check red flags vs quality signals
        red_flag_count = len(result.get('red_flags', []))
        quality_signal_count = len(result.get('quality_signals', []))

        # Fail if too many red flags
        if red_flag_count >= 3:
            return False

        # Pass if quality signals outweigh red flags
        if quality_signal_count >= red_flag_count + 2:
            return True

        # Pass if confidence is high enough
        if result.get('confidence', 0) >= 0.65:
            return True

        return False

    def _build_context(
        self,
        company_name: str,
        services_text: str,
        about_text: str,
        homepage_text: str
    ) -> str:
        """Build context summary for LLM questions."""
        # Larger context for better analysis (GPU can handle it)
        services_text = (services_text or "")[:600]
        about_text = (about_text or "")[:600]
        homepage_text = (homepage_text or "")[:400]

        context = f"Company: {company_name}\n"
        if services_text:
            context += f"Services: {services_text}\n"
        if about_text:
            context += f"About: {about_text}\n"
        if homepage_text:
            context += f"Website: {homepage_text}\n"

        return context.strip()

    def _ask_yesno(self, context: str, question: str) -> bool:
        """Ask a yes/no question about the context using Ollama."""
        prompt = f"""You are a classifier. Read the company info and answer with ONLY "Yes" or "No".

{context}

Question: {question}
Answer (Yes/No):"""

        response = self._generate(prompt, max_tokens=5)
        response_lower = response.lower().strip()

        # Get first word for cleaner parsing
        first_word = response_lower.split()[0].rstrip('.,!') if response_lower.split() else ""

        if first_word == 'yes':
            return True
        if first_word == 'no':
            return False

        # Fallback
        return response_lower.startswith('yes')

    def _generate(self, prompt: str, max_tokens: int = 50) -> str:
        """Generate text from prompt using Ollama API or queue."""
        try:
            if self.use_queue:
                # Use centralized queue for steady GPU usage
                from verification.llm_queue import llm_generate
                return llm_generate(prompt, max_tokens, timeout=30.0)
            else:
                # Direct Ollama call (original behavior)
                return self._generate_direct(prompt, max_tokens)

        except Exception as e:
            self.logger.error(f"LLM generation error: {e}")
            return ""

    def _generate_direct(self, prompt: str, max_tokens: int = 50) -> str:
        """Generate text from prompt using direct Ollama API call."""
        try:
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,  # Deterministic for consistency
                    "num_predict": max_tokens,
                    "top_p": 0.9,
                    "top_k": 40
                }
            }

            response = requests.post(
                self.api_url,
                json=payload,
                timeout=15.0  # Slightly longer timeout for deep verification
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

        Enhanced scoring that incorporates:
        - Service detection (40 points max)
        - Business type (30 points max)
        - Scope coverage (15 points max)
        - Quality signals (20 points max)
        - Red flag penalties (-40 points max)

        Args:
            classification: LLM classification dict
            discovery_source: How company was discovered (for weighting)

        Returns:
            Tuple of (score 0-100, details_dict)
        """
        score = 0.0
        details = {
            'type_score': 0,
            'service_score': 0,
            'scope_score': 0,
            'quality_score': 0,
            'red_flag_penalty': 0,
            'legitimacy_bonus': 0,
            'total': 0
        }

        # === Type Scoring (up to 30 points) ===
        company_type = classification.get('type', 4)
        type_scores = {
            1: 30,   # Service provider
            2: -15,  # Equipment seller
            3: -20,  # Training site
            4: -10,  # Directory
            5: -10,  # Blog
            6: -25   # Lead gen / marketing
        }
        details['type_score'] = type_scores.get(company_type, 0)
        score += details['type_score']

        # === Service Scoring (up to 40 points) ===
        services_count = sum([
            classification.get('pressure_washing', False),
            classification.get('window_cleaning', False),
            classification.get('wood_restoration', False)
        ])

        if services_count >= 3:
            details['service_score'] = 40  # All three services
        elif services_count == 2:
            details['service_score'] = 30  # Two services
        elif services_count == 1:
            details['service_score'] = 20  # One service
        else:
            details['service_score'] = 0

        score += details['service_score']

        # === Scope Scoring (up to 15 points) ===
        scope = classification.get('scope', 4)
        scope_scores = {
            1: 15,  # Both residential and commercial
            2: 10,  # Residential only
            3: 10,  # Commercial only
            4: 0    # Unclear
        }
        details['scope_score'] = scope_scores.get(scope, 0)
        score += details['scope_score']

        # === Quality Signal Bonus (up to 20 points) ===
        quality_signals = classification.get('quality_signals', [])
        details['quality_score'] = min(len(quality_signals) * 4, 20)
        score += details['quality_score']

        # === Red Flag Penalties (up to -40 points) ===
        red_flags = classification.get('red_flags', [])
        details['red_flag_penalty'] = min(len(red_flags) * 10, 40)
        score -= details['red_flag_penalty']

        # === Legitimacy Bonus (15 points) ===
        if classification.get('is_legitimate', False):
            details['legitimacy_bonus'] = 15
            score += details['legitimacy_bonus']

        # Normalize to 0-100 range
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
        Quick classification without deep verification.

        Useful for high-volume initial screening.
        Only checks services and basic type classification.
        """
        return self.classify_company(
            company_name=company_name,
            services_text=services_text,
            about_text=about_text,
            homepage_text=homepage_text,
            deep_verify=False
        )


# Module-level instance for reuse across workers
_llm_verifier_instance = None


def get_llm_verifier(model_name: str = None) -> LLMVerifier:
    """
    Get or create singleton LLM verifier instance.

    Reuses the same instance across calls to avoid reinitializing.
    Default model: mistral:7b (configurable via OLLAMA_MODEL env var)
    """
    global _llm_verifier_instance

    if _llm_verifier_instance is None:
        _llm_verifier_instance = LLMVerifier(model_name=model_name)

    return _llm_verifier_instance

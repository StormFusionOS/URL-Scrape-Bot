#!/usr/bin/env python3
"""
Unified LLM - Single model for verification and name standardization.

This module provides a unified interface to the fine-tuned Mistral model that
handles both:
1. Business verification (is this a legitimate exterior cleaning provider?)
2. Name standardization (extract the proper business name from website data)

The unified model (unified-washdb) was trained on 60k+ examples combining:
- 50k+ verification examples with actual page content
- 10k+ name standardization examples

This replaces the previous approach of separate models:
- verification-mistral-proper (verification only)
- standardization-mistral7b (name extraction only)
"""

import json
import logging
import os
import re
import requests
from typing import Dict, List, Optional, Tuple
from enum import Enum

from verification.config_verifier import (
    LLM_SERVICES_TEXT_LIMIT,
    LLM_ABOUT_TEXT_LIMIT,
    LLM_HOMEPAGE_TEXT_LIMIT,
)


class TaskType(Enum):
    """Type of LLM task to perform."""
    VERIFICATION = "verification"
    STANDARDIZATION = "standardization"


class UnifiedLLM:
    """
    Unified LLM for business verification and name standardization.

    Uses the unified-washdb model via Ollama for both tasks.
    The model distinguishes tasks via system prompts.
    """

    # System prompt for verification task - matches training data format
    VERIFICATION_PROMPT = """You are a business verification assistant. Your task is to determine if a company is a legitimate service provider that offers exterior building and property cleaning services.

Target services include:
- Pressure washing / power washing
- Window cleaning
- Soft washing / house washing
- Roof cleaning
- Gutter cleaning
- Solar panel cleaning
- Fleet washing / truck washing
- Wood restoration / deck staining

Respond with a JSON object containing:
- "legitimate": true if offering target services, false otherwise
- "confidence": 0.0 to 1.0 based on evidence strength
- "services": object with service types as keys and boolean values
- "reasoning": brief explanation of your decision"""

    # System prompt for name standardization task - matches training format
    STANDARDIZATION_PROMPT = """You are a business name standardization assistant. Extract and standardize the official business name from the provided website information.

Rules:
- Extract the actual business name, not page titles or taglines
- Remove legal suffixes (LLC, Inc, Corp) unless they're part of the brand identity
- Preserve proper capitalization and spacing
- If the business name is already correct, return it unchanged

Respond with ONLY the standardized business name, nothing else."""

    def __init__(
        self,
        model_name: str = None,
        api_url: str = "http://localhost:11434/api/generate",
        use_queue: bool = None
    ):
        """
        Initialize unified LLM.

        Args:
            model_name: Ollama model name (default: unified-washdb)
            api_url: Ollama API endpoint
            use_queue: If True, use centralized queue (default: from env)
        """
        if model_name is None:
            model_name = os.getenv("OLLAMA_MODEL", "unified-washdb-v2")

        if use_queue is None:
            use_queue = os.getenv("USE_LLM_QUEUE", "true").lower() in ("true", "1", "yes")

        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.api_url = api_url
        self.use_queue = use_queue

        mode_str = "queue" if use_queue else "direct"
        self.logger.info(f"Unified LLM initialized: {model_name} (mode={mode_str})")

    # =========================================================================
    # VERIFICATION METHODS
    # =========================================================================

    def verify_company(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
    ) -> Optional[Dict]:
        """
        Verify if a company is a legitimate exterior cleaning service provider.

        Args:
            company_name: Company name
            website: Website URL
            phone: Phone number
            title: Page title
            services_text: Services section text
            about_text: About section text
            homepage_text: Homepage text

        Returns:
            Classification dict with legitimate, confidence, services, reasoning
        """
        try:
            prompt = self._build_verification_prompt(
                company_name=company_name,
                website=website,
                phone=phone,
                title=title,
                services_text=services_text,
                about_text=about_text,
                homepage_text=homepage_text
            )

            response = self._query_model(prompt, TaskType.VERIFICATION)

            if not response.get('success'):
                self.logger.warning(f"Verification failed for '{company_name}': {response.get('error')}")
                return None

            return self._parse_verification_response(response, company_name)

        except Exception as e:
            self.logger.error(f"Verification error for '{company_name}': {e}")
            return None

    def verify_company_rich(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        meta_description: str = "",
        h1_text: str = "",
        og_site_name: str = "",
        json_ld: List[Dict] = None,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        address: str = "",
        emails: List[str] = None,
    ) -> Optional[Dict]:
        """
        Verify company with rich browser-extracted content.

        This method accepts comprehensive data extracted from browser-rendered pages
        for maximum LLM accuracy.

        Args:
            company_name: Company name
            website: Website URL
            phone: Phone number
            title: Page title
            h1_text: H1 heading text
            og_site_name: Open Graph site name
            json_ld: List of JSON-LD structured data objects
            services_text: Services section text (up to 4000 chars)
            about_text: About section text (up to 4000 chars)
            homepage_text: Homepage text (up to 8000 chars)
            address: Physical address
            emails: List of email addresses

        Returns:
            Classification dict with legitimate, confidence, services, reasoning
        """
        try:
            prompt = self._build_verification_prompt_rich(
                company_name=company_name,
                website=website,
                phone=phone,
                title=title,
                meta_description=meta_description,
                h1_text=h1_text,
                og_site_name=og_site_name,
                json_ld=json_ld or [],
                services_text=services_text,
                about_text=about_text,
                homepage_text=homepage_text,
                address=address,
                emails=emails or [],
            )

            response = self._query_model(prompt, TaskType.VERIFICATION)

            if not response.get('success'):
                self.logger.warning(f"Rich verification failed for '{company_name}': {response.get('error')}")
                return None

            return self._parse_verification_response(response, company_name)

        except Exception as e:
            self.logger.error(f"Rich verification error for '{company_name}': {e}")
            return None

    def _build_verification_prompt_rich(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        meta_description: str = "",
        h1_text: str = "",
        og_site_name: str = "",
        json_ld: List[Dict] = None,
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = "",
        address: str = "",
        emails: List[str] = None,
    ) -> str:
        """Build verification prompt with rich browser-extracted content."""
        # Increased limits for browser-extracted content
        services_text = (services_text or "")[:4000]
        about_text = (about_text or "")[:4000]
        homepage_text = (homepage_text or "")[:8000]

        prompt = f"Company: {company_name}\n"
        prompt += f"Website: {website}\n"

        if phone:
            prompt += f"Phone: {phone}\n"
        if address:
            prompt += f"Address: {address}\n"
        if emails:
            prompt += f"Email: {', '.join(emails[:2])}\n"

        # Structured data section (JSON-LD is most reliable)
        if json_ld:
            for item in json_ld[:2]:
                item_type = item.get('@type', '')
                if any(t in str(item_type) for t in ['LocalBusiness', 'Organization', 'Service']):
                    prompt += "\nJSON-LD Business Data:\n"
                    if item.get('name'):
                        prompt += f"  Name: {item.get('name')}\n"
                    if item.get('description'):
                        prompt += f"  Description: {str(item.get('description'))[:300]}\n"
                    if item.get('serviceType'):
                        prompt += f"  Service Type: {item.get('serviceType')}\n"
                    if item.get('areaServed'):
                        prompt += f"  Area Served: {item.get('areaServed')}\n"
                    break

        # Title and headings (strong signals)
        if title:
            prompt += f"\nPage Title: {title}\n"
        if meta_description:
            prompt += f"Meta Description: {meta_description[:500]}\n"
        if h1_text and h1_text != title:
            prompt += f"Main Heading: {h1_text}\n"
        if og_site_name and og_site_name != title:
            prompt += f"Site Name: {og_site_name}\n"

        # Content sections with smart truncation
        current_len = len(prompt)
        max_total = 12000

        if services_text:
            remaining = max_total - current_len - 500
            prompt += f"\nServices Page Content:\n{services_text[:min(3000, remaining)]}\n"
            current_len = len(prompt)

        if about_text and current_len < max_total - 500:
            remaining = max_total - current_len - 200
            prompt += f"\nAbout Page Content:\n{about_text[:min(2000, remaining)]}\n"
            current_len = len(prompt)

        if homepage_text and current_len < max_total - 200:
            remaining = max_total - current_len - 100
            prompt += f"\nHomepage Content:\n{homepage_text[:remaining]}\n"

        # Auto-detect quality signals and red flags (matches training format)
        all_text = f"{title} {meta_description} {h1_text} {services_text} {about_text} {homepage_text}".lower()
        quality_signals = []
        red_flags = []

        # Check for target service mentions
        service_keywords = [
            'pressure wash', 'power wash', 'soft wash', 'window clean',
            'roof clean', 'gutter clean', 'solar panel', 'fleet wash',
            'deck stain', 'wood restoration', 'house wash'
        ]
        found_services = [kw for kw in service_keywords if kw in all_text]
        if found_services:
            quality_signals.append(f"Offers target services: {', '.join(found_services[:3])}")

        # Check for business legitimacy indicators
        if phone:
            quality_signals.append("Has phone number")
        if address:
            quality_signals.append("Has physical address")
        if json_ld:
            quality_signals.append("Has structured data (JSON-LD)")
        if 'free quote' in all_text or 'free estimate' in all_text:
            quality_signals.append("Offers free estimates")
        if 'licensed' in all_text or 'insured' in all_text:
            quality_signals.append("Licensed/insured")

        # Check for red flags
        if not found_services:
            red_flags.append("No target services mentioned")
        if 'template' in all_text or 'lorem ipsum' in all_text:
            red_flags.append("Generic/template content detected")
        if len(all_text.strip()) < 100:
            red_flags.append("Minimal page content")

        # Format signals
        quality_str = "; ".join(quality_signals) if quality_signals else "None detected"
        red_flags_str = "; ".join(red_flags) if red_flags else "None detected"

        prompt += f"\nQuality signals detected: {quality_str}\n"
        prompt += f"Red flags detected: {red_flags_str}\n"
        prompt += "\nIs this a legitimate exterior cleaning service provider? Provide your detailed assessment."
        return prompt

    def _build_verification_prompt(
        self,
        company_name: str,
        website: str = "",
        phone: str = "",
        title: str = "",
        services_text: str = "",
        about_text: str = "",
        homepage_text: str = ""
    ) -> str:
        """Build verification prompt with page content - matches training format."""
        homepage_text = (homepage_text or "")[:LLM_HOMEPAGE_TEXT_LIMIT]
        services_text = (services_text or "")[:LLM_SERVICES_TEXT_LIMIT]
        about_text = (about_text or "")[:LLM_ABOUT_TEXT_LIMIT]

        # Combine all text for signal detection
        all_text = f"{title} {homepage_text} {services_text} {about_text}".lower()

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

        # Auto-detect quality signals and red flags (matches training format)
        quality_signals = []
        red_flags = []

        # Check for target service mentions
        service_keywords = [
            'pressure wash', 'power wash', 'soft wash', 'window clean',
            'roof clean', 'gutter clean', 'solar panel', 'fleet wash',
            'deck stain', 'wood restoration', 'house wash'
        ]
        found_services = [kw for kw in service_keywords if kw in all_text]
        if found_services:
            quality_signals.append(f"Offers target services: {', '.join(found_services[:3])}")

        # Check for business legitimacy indicators
        if phone:
            quality_signals.append("Has phone number")
        if 'free quote' in all_text or 'free estimate' in all_text:
            quality_signals.append("Offers free estimates")
        if 'licensed' in all_text or 'insured' in all_text:
            quality_signals.append("Licensed/insured")
        if 'years' in all_text and ('experience' in all_text or 'business' in all_text):
            quality_signals.append("Established business")

        # Check for red flags
        if not found_services:
            red_flags.append("No target services mentioned")
        if 'template' in all_text or 'lorem ipsum' in all_text:
            red_flags.append("Generic/template content detected")
        if len(all_text.strip()) < 100:
            red_flags.append("Minimal page content")
        if 'directory' in all_text or 'listing' in all_text:
            red_flags.append("May be directory listing")

        # Format signals
        quality_str = "; ".join(quality_signals) if quality_signals else "None detected"
        red_flags_str = "; ".join(red_flags) if red_flags else "None detected"

        prompt += f"\nQuality signals detected: {quality_str}\n"
        prompt += f"Red flags detected: {red_flags_str}\n"
        prompt += "\nIs this a legitimate exterior cleaning service provider? Provide your detailed assessment."
        return prompt

    # Strong indicators of target exterior cleaning services
    TARGET_SERVICE_KEYWORDS = [
        'pressure wash', 'power wash', 'powerwash', 'pressurewash',
        'soft wash', 'softwash', 'house wash', 'housewash',
        'window clean', 'window wash',
        'roof clean', 'roof wash',
        'gutter clean', 'gutter wash',
        'deck clean', 'deck wash', 'deck stain',
        'exterior clean', 'building wash',
        'solar panel clean', 'fleet wash', 'truck wash',
    ]

    # Non-target services (should NOT be marked legitimate)
    NON_TARGET_KEYWORDS = [
        'car wash', 'auto detail', 'laundry', 'dry clean',
        'carpet clean', 'maid service', 'janitorial',
        'plumbing', 'plumber', 'electrician', 'electric',
        'hvac', 'roofing contractor', 'roofer',
        'landscaping', 'lawn care', 'tree service',
        'pest control', 'painting contractor', 'painter',
    ]

    def _apply_post_processing_rules(
        self,
        legitimate: bool,
        confidence: float,
        company_name: str,
        page_content: str = ""
    ) -> tuple:
        """
        Apply post-processing rules to fix obvious LLM mislabels.

        This corrects known issues with the current model:
        - Companies with target service in name marked as not legitimate
        - Low confidence on obvious matches

        Returns:
            (corrected_legitimate, corrected_confidence, was_corrected)
        """
        name_lower = company_name.lower()
        content_lower = (page_content or "").lower()
        combined = name_lower + " " + content_lower

        # Check for strong target service indicators in name
        has_target_in_name = any(kw in name_lower for kw in self.TARGET_SERVICE_KEYWORDS)
        has_target_in_content = any(kw in content_lower for kw in self.TARGET_SERVICE_KEYWORDS)
        has_non_target = any(kw in name_lower for kw in self.NON_TARGET_KEYWORDS)

        was_corrected = False

        # Rule 1: If target service in company NAME, should be legitimate
        if has_target_in_name and not has_non_target:
            if not legitimate:
                legitimate = True
                was_corrected = True
            # Boost confidence for clear matches
            confidence = max(confidence, 0.80)

        # Rule 2: If target service in content but not name, moderate confidence
        elif has_target_in_content and not has_non_target:
            if not legitimate:
                legitimate = True
                was_corrected = True
            confidence = max(confidence, 0.65)

        # Rule 3: If only non-target service, should NOT be legitimate
        elif has_non_target and not has_target_in_name and not has_target_in_content:
            if legitimate:
                legitimate = False
                was_corrected = True
            confidence = max(confidence, 0.70)

        # Rule 4: Ensure minimum confidence thresholds
        if legitimate and confidence < 0.50:
            confidence = 0.55  # Don't let legitimate have very low confidence

        return legitimate, confidence, was_corrected

    def _parse_verification_response(self, response: Dict, company_name: str) -> Dict:
        """Parse verification response into standard format with post-processing fixes."""
        parsed = response.get('response', {})

        legitimate = parsed.get('legitimate', False)
        confidence = parsed.get('confidence', 0.0)
        services = parsed.get('services', [])
        reasoning = parsed.get('reasoning', '')

        # Apply post-processing rules to fix LLM mislabels
        original_legitimate = legitimate
        legitimate, confidence, was_corrected = self._apply_post_processing_rules(
            legitimate, confidence, company_name
        )

        if was_corrected:
            if legitimate and not original_legitimate:
                reasoning = f"[Auto-corrected] {reasoning}" if reasoning else "Target service detected in company name"

        # Handle services as dict (model returns {"pressure_washing": true, ...})
        if isinstance(services, dict):
            # Extract service names where value is True
            services_list = [k.replace('_', ' ').title() for k, v in services.items() if v]
            services = services_list if services_list else []
        elif isinstance(services, str):
            services = [s.strip() for s in services.split(',')]
        elif not isinstance(services, list):
            services = []

        services_lower = ' '.join(str(s) for s in services).lower() if services else ''
        reasoning_lower = reasoning.lower()

        pressure_washing = any(kw in services_lower or kw in reasoning_lower
                               for kw in ['pressure wash', 'power wash', 'soft wash'])
        window_cleaning = 'window' in services_lower or 'window' in reasoning_lower
        wood_restoration = any(kw in services_lower or kw in reasoning_lower
                               for kw in ['deck', 'wood', 'fence stain', 'restoration'])

        quality_signals = []
        red_flags = []

        if legitimate:
            quality_signals.append("Unified LLM: Legitimate service provider")
            if services:
                quality_signals.append(f"Services: {', '.join(str(s) for s in services[:3])}")
        else:
            red_flags.append("Unified LLM: Not a legitimate exterior cleaning provider")
            if reasoning:
                red_flags.append(f"Reason: {reasoning[:100]}")

        company_type = 1 if legitimate else 4
        scope = 1 if legitimate else 4

        return {
            'legitimate': legitimate,
            'is_legitimate': legitimate,
            'confidence': confidence,
            'services': services,
            'reasoning': reasoning,
            'pressure_washing': pressure_washing,
            'window_cleaning': window_cleaning,
            'wood_restoration': wood_restoration,
            'type': company_type,
            'scope': scope,
            'quality_signals': quality_signals,
            'red_flags': red_flags,
            'raw_response': response.get('raw', '')[:500]
        }

    def calculate_llm_score(self, classification: Dict, discovery_source: str = "") -> Tuple[float, Dict]:
        """Calculate verification score from classification."""
        score = 0.0
        details = {
            'legitimacy_score': 0,
            'confidence_score': 0,
            'service_score': 0,
            'total': 0
        }

        if classification.get('legitimate', False):
            details['legitimacy_score'] = 60
        score += details['legitimacy_score']

        confidence = classification.get('confidence', 0.0)
        details['confidence_score'] = int(confidence * 20)
        score += details['confidence_score']

        services_count = sum([
            classification.get('pressure_washing', False),
            classification.get('window_cleaning', False),
            classification.get('wood_restoration', False)
        ])
        details['service_score'] = min(services_count * 7, 20)
        score += details['service_score']

        score = max(0, min(100, score))
        details['total'] = score

        return score, details

    # =========================================================================
    # STANDARDIZATION METHODS
    # =========================================================================

    def standardize_name(
        self,
        current_name: str,
        website: str = "",
        page_title: str = "",
        meta_description: str = "",
        og_site_name: str = "",
        json_ld_name: str = "",
        h1_text: str = "",
        copyright_text: str = ""
    ) -> Optional[Dict]:
        """
        Extract the proper business name from website data.

        Args:
            current_name: Current (possibly truncated) name
            website: Website URL
            page_title: Page title
            meta_description: Meta description
            og_site_name: Open Graph site name
            json_ld_name: JSON-LD schema name
            h1_text: H1 heading text
            copyright_text: Copyright notice text

        Returns:
            Dict with name, confidence, source, or None on failure
        """
        try:
            prompt = self._build_standardization_prompt(
                current_name=current_name,
                website=website,
                page_title=page_title,
                meta_description=meta_description,
                og_site_name=og_site_name,
                json_ld_name=json_ld_name,
                h1_text=h1_text,
                copyright_text=copyright_text
            )

            response = self._query_model(prompt, TaskType.STANDARDIZATION)

            if not response.get('success'):
                self.logger.warning(f"Standardization failed for '{current_name}': {response.get('error')}")
                return None

            return self._parse_standardization_response(response, current_name)

        except Exception as e:
            self.logger.error(f"Standardization error for '{current_name}': {e}")
            return None

    def standardize_name_rich(
        self,
        current_name: str,
        website: str = "",
        page_title: str = "",
        meta_description: str = "",
        og_site_name: str = "",
        json_ld: List[Dict] = None,
        h1_text: str = "",
        copyright_text: str = "",
    ) -> Optional[Dict]:
        """
        Extract the proper business name from rich browser-extracted content.

        This method accepts comprehensive data for maximum name extraction accuracy.

        Args:
            current_name: Current (possibly truncated) name
            website: Website URL
            page_title: Page title
            meta_description: Meta description
            og_site_name: Open Graph site name
            json_ld: List of JSON-LD structured data objects
            h1_text: H1 heading text
            copyright_text: Copyright notice text

        Returns:
            Dict with name, confidence, source, or None on failure
        """
        # Extract name from JSON-LD if available
        json_ld_name = None
        if json_ld:
            for item in json_ld:
                name = item.get('name')
                if name and isinstance(name, str) and len(name) > 2:
                    json_ld_name = name.strip()
                    break

        try:
            prompt = self._build_standardization_prompt(
                current_name=current_name,
                website=website,
                page_title=page_title,
                meta_description=meta_description,
                og_site_name=og_site_name,
                json_ld_name=json_ld_name or "",
                h1_text=h1_text,
                copyright_text=copyright_text
            )

            response = self._query_model(prompt, TaskType.STANDARDIZATION)

            if not response.get('success'):
                self.logger.warning(f"Rich standardization failed for '{current_name}': {response.get('error')}")
                return None

            return self._parse_standardization_response(response, current_name)

        except Exception as e:
            self.logger.error(f"Rich standardization error for '{current_name}': {e}")
            return None

    def _build_standardization_prompt(
        self,
        current_name: str,
        website: str = "",
        page_title: str = "",
        meta_description: str = "",
        og_site_name: str = "",
        json_ld_name: str = "",
        h1_text: str = "",
        copyright_text: str = ""
    ) -> str:
        """Build standardization prompt - matches training format."""
        # Extract domain from website
        domain = ""
        if website:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(website)
                domain = parsed.netloc or parsed.path.split('/')[0]
            except:
                domain = website.replace('https://', '').replace('http://', '').split('/')[0]

        # Training format: simple 3-line prompt
        prompt = "Extract business name:\n"
        prompt += f"Original: {current_name}\n"
        if domain:
            prompt += f"Domain: {domain}\n"
        prompt += f"Website: {website}"

        # Add additional context if available (training also included some examples with more data)
        extra_context = []
        if json_ld_name and json_ld_name != current_name:
            extra_context.append(f"JSON-LD name: {json_ld_name}")
        if og_site_name and og_site_name != current_name:
            extra_context.append(f"Site name: {og_site_name}")
        if page_title and page_title != current_name:
            extra_context.append(f"Title: {page_title}")

        if extra_context:
            prompt += "\n" + "\n".join(extra_context)

        return prompt

    def _parse_standardization_response(self, response: Dict, original_name: str) -> Dict:
        """Parse standardization response."""
        parsed = response.get('response', {})

        name = parsed.get('name', 'UNKNOWN')
        confidence = parsed.get('confidence', 0.0)
        source = parsed.get('source', 'unknown')

        # Clean up the name
        name = name.strip()
        if name.upper() == 'UNKNOWN' or not name:
            return {
                'name': original_name,
                'confidence': 0.0,
                'source': 'failed',
                'success': False
            }

        return {
            'name': name,
            'confidence': confidence,
            'source': source,
            'success': True,
            'original_name': original_name
        }

    # =========================================================================
    # SHARED METHODS
    # =========================================================================

    def _extract_business_name(self, response_text: str) -> str:
        """
        Extract just the business name from model response.

        The model sometimes continues generating after the name (address, phone, etc.)
        This method extracts just the business name portion.
        """
        import re
        text = response_text.strip()

        # If it's just the name (common case), return it
        if '\n' in text:
            text = text.split('\n')[0].strip()

        # Handle pipe separator (common in titles: "Name | Tagline")
        if ' | ' in text:
            text = text.split(' | ')[0].strip()

        # Handle dash separator (common: "Name - Services")
        if ' - ' in text and len(text.split(' - ')[0]) >= 3:
            first_part = text.split(' - ')[0].strip()
            # Only use if it looks like a business name
            if not first_part.lower().startswith(('the ', 'a ', 'an ')):
                text = first_part

        # Stop at common patterns that indicate extra content
        stop_patterns = [
            r'\s+\d{3,5}\s+[NSEW]?\s*\w',  # Address pattern (number + street)
            r'\s*\(\d{3}\)',     # Phone pattern (xxx)
            r'\s+\d{3}[-.\s]\d{3}',  # Phone pattern xxx-xxx
            r'\s+Get\s+',       # "Get a Free Quote" etc
            r'\s+Home\s+About',  # Navigation text
            r'\s+Contact\s+Us',  # Contact text
            r'\s+Our\s+Work',    # Portfolio text
            r'\s+We\s+(are|provide|offer|specialize)',  # Description start
            r'\s+is\s+a\s+(family|professional|full)',     # Description start
            r',\s*(Suite|Ste|#)\s*\w',  # Suite/unit number
        ]

        for pattern in stop_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                text = text[:match.start()].strip()
                break

        # Clean up trailing punctuation and quotes
        text = text.strip('"\'.,;:!?')

        # Remove trailing LLC, Inc if followed by garbage
        # But keep it if it's at the end
        text = re.sub(r'(LLC|Inc|Corp|Co\.?)\s+\d.*$', r'\1', text)

        # If we ended up with something too long, likely has extra content
        words = text.split()
        if len(words) > 8:
            # Take first 6 words max for a business name
            text = ' '.join(words[:6])

        return text.strip()

    def _query_model(self, prompt: str, task_type: TaskType, timeout: float = 30.0) -> Dict:
        """Query the unified model via Ollama API using ChatML format."""
        system_prompt = (
            self.VERIFICATION_PROMPT if task_type == TaskType.VERIFICATION
            else self.STANDARDIZATION_PROMPT
        )

        # Use ChatML format matching training data
        full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        full_prompt += f"<|im_start|>user\n{prompt}<|im_end|>\n"
        full_prompt += "<|im_start|>assistant\n"

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "raw": True,  # CRITICAL: bypass Ollama template to use our ChatML format
            "options": {
                "temperature": 0.1,
                "top_p": 0.85,
                "top_k": 40,
                "num_predict": 400,
                "repeat_penalty": 1.2,
            }
        }

        try:
            if self.use_queue:
                from verification.llm_queue import llm_generate_raw
                response_text = llm_generate_raw(
                    prompt=full_prompt,
                    model=self.model_name,
                    max_tokens=400,
                    timeout=timeout
                )
            else:
                response = requests.post(self.api_url, json=payload, timeout=timeout)
                response.raise_for_status()
                result = response.json()
                response_text = result.get("response", "").strip()

            # Parse JSON from response - find first complete JSON object
            try:
                json_start = response_text.find('{')
                if json_start >= 0:
                    # Find matching closing brace by counting braces
                    brace_count = 0
                    json_end = -1
                    for i, char in enumerate(response_text[json_start:], json_start):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = i + 1
                                break

                    if json_end > json_start:
                        json_str = response_text[json_start:json_end]
                        parsed = json.loads(json_str)
                        return {
                            "success": True,
                            "response": parsed,
                            "raw": response_text
                        }
            except json.JSONDecodeError:
                pass

            # For standardization tasks, the model returns plain text (the name)
            # but may continue generating extra content - extract just the name
            if task_type == TaskType.STANDARDIZATION and response_text.strip():
                clean_name = self._extract_business_name(response_text)
                if clean_name and len(clean_name) >= 2 and len(clean_name) <= 100:
                    return {
                        "success": True,
                        "response": {
                            "name": clean_name,
                            "confidence": 0.85,
                            "source": "llm_text"
                        },
                        "raw": response_text
                    }

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

    # =========================================================================
    # COMPATIBILITY ALIASES
    # =========================================================================

    def classify_company(self, *args, **kwargs) -> Optional[Dict]:
        """Alias for verify_company (backwards compatibility)."""
        return self.verify_company(*args, **kwargs)

    def quick_classify(self, *args, **kwargs) -> Optional[Dict]:
        """Alias for verify_company (backwards compatibility)."""
        return self.verify_company(*args, **kwargs)


# Module-level singleton
_unified_llm_instance = None


def get_unified_llm(model_name: str = None) -> UnifiedLLM:
    """Get or create singleton unified LLM instance."""
    global _unified_llm_instance

    if _unified_llm_instance is None:
        _unified_llm_instance = UnifiedLLM(model_name=model_name)

    return _unified_llm_instance


# Backwards compatibility aliases
def get_llm_verifier(model_name: str = None) -> UnifiedLLM:
    """Alias for get_unified_llm (drop-in replacement for old verifier)."""
    return get_unified_llm(model_name=model_name)


def get_trained_llm_verifier(model_name: str = None) -> UnifiedLLM:
    """Alias for get_unified_llm (drop-in replacement for trained verifier)."""
    return get_unified_llm(model_name=model_name)

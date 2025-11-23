#!/usr/bin/env python3
"""
Service verification module for filtering and classifying businesses.

This module implements multi-phase verification:
- Phase 1: Rule-based service detection (pressure/window/wood)
- Phase 2: Site structure analysis (navigation, headings, schema.org)
- Phase 3: Combined scoring with discovery signals
- Phase 5: ML classifier integration (optional)

Target services:
- Residential & commercial pressure washing
- Residential & commercial window cleaning
- Residential & commercial wood restoration (deck/fence/log home)

Filters out:
- Directories (Yelp, HomeAdvisor, etc.)
- Equipment sellers
- Training sites / courses
- Marketing agencies
- Blogs / informational content only
- Auto detailing services
"""

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from runner.logging_setup import get_logger

logger = get_logger("service_verifier")


class ServiceVerifier:
    """
    Verify that a company website offers target services (pressure/window/wood).

    Uses multi-tier classification:
    - Tier A: All 3 services with both residential & commercial
    - Tier B: ≥ 2 services with both residential & commercial
    - Tier C: ≥ 1 service with both residential & commercial
    - Tier D: Only partial / no clear residential + commercial
    """

    def __init__(
        self,
        config_file: str = 'data/verification_services.json',
        ml_model_path: Optional[str] = None,
        use_llm: bool = False
    ):
        """
        Initialize verifier with configuration.

        Args:
            config_file: Path to verification services config JSON
            ml_model_path: Optional path to trained ML model (Phase 5)
            use_llm: Whether to use LLM for uncertain cases (hybrid mode)
        """
        self.config = self._load_config(config_file)
        self.ml_model = self._load_ml_model(ml_model_path) if ml_model_path else None
        self.use_llm = use_llm
        self.llm_verifier = None

        # Initialize LLM if requested
        if use_llm:
            try:
                from scrape_site.llm_verifier import get_llm_verifier
                self.llm_verifier = get_llm_verifier()
                logger.info("✓ LLM verifier loaded (Llama 3.2 3B)")
            except Exception as e:
                logger.warning(f"Failed to load LLM verifier: {e}")
                self.use_llm = False

        # Extract service definitions
        self.services = {
            'pressure': self.config['pressure'],
            'window': self.config['window'],
            'wood': self.config['wood']
        }

        # Extract negative filters
        self.neg_filters = self.config['negative_filters']
        self.blocked_domains = (
            set(self.neg_filters['directories']) |
            set(self.neg_filters['ecommerce']) |
            set(self.neg_filters['social_media'])
        )

        # Provider vs informational language
        self.provider_phrases = set(p.lower() for p in self.config['provider_phrases'])
        self.informational_phrases = set(p.lower() for p in self.config['informational_phrases'])
        self.cta_phrases = set(p.lower() for p in self.config['cta_phrases'])

        logger.info(f"✓ ServiceVerifier initialized")
        logger.info(f"  Services tracked: {list(self.services.keys())}")
        logger.info(f"  Blocked domains: {len(self.blocked_domains)}")
        logger.info(f"  Provider phrases: {len(self.provider_phrases)}")
        logger.info(f"  ML model: {'loaded' if self.ml_model else 'not loaded'}")
        logger.info(f"  LLM mode: {'enabled' if self.use_llm else 'disabled'}")

    def _load_config(self, config_file: str) -> dict:
        """Load verification services configuration from JSON."""
        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_ml_model(self, model_path: str):
        """Load trained ML model (Phase 5 implementation)."""
        try:
            import joblib
            model = joblib.load(model_path)
            logger.info(f"✓ Loaded ML model from {model_path}")
            return model
        except Exception as e:
            logger.warning(f"Failed to load ML model: {e}")
            return None

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison (lowercase, strip)."""
        if not text:
            return ""
        return text.lower().strip()

    def verify_company(
        self,
        company_data: Dict,
        website_html: Optional[str] = None,
        website_metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Verify a company and return structured verification result.

        Args:
            company_data: Company record from database (must include 'website', 'parse_metadata')
            website_html: Optional website HTML content for analysis
            website_metadata: Optional pre-parsed website metadata (from site_parse.py)

        Returns:
            Verification result dict with:
                - status: 'passed', 'failed', 'unknown'
                - score: 0.0-1.0 confidence score
                - tier: 'A', 'B', 'C', 'D' (service coverage)
                - services_detected: {service: {any, residential, commercial}}
                - positive_signals: [list of reasons]
                - negative_signals: [list of reasons]
                - reason: Human-readable explanation
        """
        result = {
            'status': 'unknown',
            'score': 0.0,
            'tier': 'D',
            'services_detected': {},
            'positive_signals': [],
            'negative_signals': [],
            'reason': '',
            'needs_review': False
        }

        website = company_data.get('website', '')
        if not website:
            result['status'] = 'failed'
            result['reason'] = 'No website URL provided'
            result['negative_signals'].append('No website URL')
            return result

        # Phase 1: Check hard negative filters
        domain = self._extract_domain(website)
        if self._check_blocked_domain(domain, result):
            return result

        # If we have website_metadata, use it for deep analysis
        if website_metadata:
            # Phase 1: Multi-label service detection (include company name!)
            company_name = company_data.get('name', '')
            self._detect_services(website_metadata, result, company_name)

            # Phase 1: Provider vs informational language
            self._analyze_language(website_metadata, result)

            # Phase 1: Local business artifacts
            self._validate_local_business(website_metadata, result)

            # Phase 2: Site structure analysis
            if website_html:
                self._analyze_site_structure(website_html, result, company_name)
                self._analyze_schema_org(website_metadata.get('json_ld', []), result)

        # Phase 1: Classify into tiers
        self._assign_tier(result)

        # Calculate rule-based score
        rule_score = self._calculate_rule_score(result)

        # Hybrid LLM Enhancement for uncertain cases (0.30-0.80 rule score)
        if self.use_llm and self.llm_verifier and website_metadata and 0.30 <= rule_score <= 0.80:
            llm_result = self._get_llm_classification(company_data, website_metadata)
            if llm_result:
                llm_score, llm_details = self.llm_verifier.calculate_llm_score(llm_result)
                # Blend rule score and LLM score for uncertain cases
                result['score'] = (0.5 * rule_score + 0.5 * (llm_score / 100.0))  # Normalize LLM score to 0-1
                result['llm_classification'] = llm_result
                result['llm_score'] = llm_score
                result['llm_details'] = llm_details
                logger.debug(f"LLM enhanced score: rule={rule_score:.2f}, llm={llm_score:.0f}/100, final={result['score']:.2f}")
            else:
                # LLM failed, fall back to rule score
                result['score'] = rule_score
                logger.debug(f"LLM unavailable, using rule score: {rule_score:.2f}")
        # Phase 5: Optionally enhance with ML score (if not using LLM)
        elif self.ml_model:
            ml_score = self._get_ml_score(company_data, result)
            # Weighted average: 60% rules, 40% ML
            result['score'] = 0.6 * rule_score + 0.4 * ml_score
            result['ml_score'] = ml_score
        else:
            # Fast path: use rule score only
            result['score'] = rule_score

        # Determine status based on score
        if result['score'] >= 0.75:
            result['status'] = 'passed'
            result['reason'] = f'Verified target service company (Tier {result["tier"]})'
        elif result['score'] <= 0.35:
            result['status'] = 'failed'
            result['reason'] = 'Does not meet target service criteria'
        else:
            result['status'] = 'unknown'
            result['needs_review'] = True
            result['reason'] = 'Requires manual review (ambiguous signals)'

        return result

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ''

    def _check_blocked_domain(self, domain: str, result: Dict) -> bool:
        """Check if domain is in blocklist. Returns True if blocked."""
        if domain in self.blocked_domains:
            result['status'] = 'failed'
            result['score'] = 0.0
            result['reason'] = f'Blocked domain: {domain}'
            result['negative_signals'].append(f'Domain is a directory/marketplace: {domain}')
            return True

        # Check for ecommerce indicators in domain
        for indicator in ['shop', 'store', 'cart', 'ecommerce', 'online-store']:
            if indicator in domain:
                result['negative_signals'].append(f'Ecommerce indicator in domain: {indicator}')

        return False

    def _detect_services(self, metadata: Dict, result: Dict, company_name: str = ''):
        """
        Detect which services are offered (pressure/window/wood).

        Sets result['services_detected'] with structure:
        {
            'pressure': {'any': bool, 'residential': bool, 'commercial': bool},
            'window': {'any': bool, 'residential': bool, 'commercial': bool},
            'wood': {'any': bool, 'residential': bool, 'commercial': bool}
        }
        """
        # Combine all text content INCLUDING COMPANY NAME (handle None values)
        all_text = ' '.join([
            company_name or '',  # IMPORTANT: Include company name for detection
            metadata.get('services') or '',
            metadata.get('about') or '',
            metadata.get('homepage_text') or ''
        ]).lower()

        for service_name, service_config in self.services.items():
            detected = {
                'any': False,
                'residential': False,
                'commercial': False
            }

            # Check if service keywords are present
            for keyword in service_config['keywords']:
                if keyword.lower() in all_text:
                    detected['any'] = True
                    result['positive_signals'].append(f'{service_name.title()} service keyword: {keyword}')
                    break

            if detected['any']:
                # Check for residential context
                for res_word in service_config['res_words']:
                    if res_word.lower() in all_text:
                        detected['residential'] = True
                        result['positive_signals'].append(f'{service_name.title()} residential context: {res_word}')
                        break

                # Check for commercial context
                for com_word in service_config['com_words']:
                    if com_word.lower() in all_text:
                        detected['commercial'] = True
                        result['positive_signals'].append(f'{service_name.title()} commercial context: {com_word}')
                        break

            result['services_detected'][service_name] = detected

    def _analyze_language(self, metadata: Dict, result: Dict):
        """Analyze provider vs informational language."""
        all_text = ' '.join([
            metadata.get('services') or '',
            metadata.get('about') or '',
            metadata.get('homepage_text') or ''
        ]).lower()

        provider_count = sum(1 for phrase in self.provider_phrases if phrase in all_text)
        informational_count = sum(1 for phrase in self.informational_phrases if phrase in all_text)
        cta_count = sum(1 for phrase in self.cta_phrases if phrase in all_text)

        # Positive signals
        if provider_count > 0:
            result['positive_signals'].append(f'Provider language detected ({provider_count} phrases)')
        if cta_count > 0:
            result['positive_signals'].append(f'Call-to-action phrases detected ({cta_count})')

        # Negative signals
        if informational_count > provider_count and provider_count == 0:
            result['negative_signals'].append(f'Informational content dominates (no provider language)')
        elif informational_count > 3:
            result['negative_signals'].append(f'Heavy informational content ({informational_count} phrases)')

        # Store counts for scoring
        result['provider_phrase_count'] = provider_count
        result['informational_phrase_count'] = informational_count
        result['cta_phrase_count'] = cta_count

    def _validate_local_business(self, metadata: Dict, result: Dict):
        """Validate local business artifacts (phone, email, address)."""
        has_phone = bool(metadata.get('phones'))
        has_email = bool(metadata.get('emails'))
        has_address = bool(metadata.get('address'))
        has_service_area = bool(metadata.get('service_area'))

        # At least one contact method required
        if has_phone:
            result['positive_signals'].append('US phone number present')
        if has_email:
            result['positive_signals'].append('Email address present')
        if has_address:
            result['positive_signals'].append('Physical address present')
        if has_service_area:
            result['positive_signals'].append('Service area specified')

        if not has_phone and not has_email:
            result['negative_signals'].append('No contact information (no phone or email)')

        # Store flags for scoring
        result['has_phone'] = has_phone
        result['has_email'] = has_email
        result['has_address'] = has_address

    def _analyze_site_structure(self, html: str, result: Dict, company_name: str = ''):
        """Analyze site structure (navigation, headings) - Phase 2."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Extract navigation text
            nav_elements = soup.find_all(['nav', 'header'])
            nav_text = ' '.join(nav.get_text(' ', strip=True).lower() for nav in nav_elements)

            # Extract heading text
            headings = soup.find_all(['h1', 'h2', 'h3'])
            headings_text = ' '.join(h.get_text(' ', strip=True).lower() for h in headings)

            # Include company name in analysis (strong signal!)
            company_name_lower = (company_name or '').lower()

            # Check for service keywords in navigation/headings/company name
            for service_name, service_config in self.services.items():
                for keyword in service_config['keywords']:
                    if keyword.lower() in nav_text:
                        result['positive_signals'].append(f'{service_name.title()} in navigation: {keyword}')
                    if keyword.lower() in headings_text:
                        result['positive_signals'].append(f'{service_name.title()} in headings: {keyword}')
                    # NEW: Check company name for service keywords
                    if keyword.lower() in company_name_lower:
                        result['positive_signals'].append(f'{service_name.title()} in company name: {keyword}')

            # Store for scoring
            result['has_service_nav'] = any(
                keyword.lower() in nav_text
                for service_config in self.services.values()
                for keyword in service_config['keywords']
            )

        except Exception as e:
            logger.warning(f"Error analyzing site structure: {e}")

    def _analyze_schema_org(self, json_ld_items: List[Dict], result: Dict):
        """Analyze JSON-LD schema.org structured data - Phase 2."""
        local_business_types = [
            'LocalBusiness',
            'HomeAndConstructionBusiness',
            'CleaningService',
            'ProfessionalService',
            'Service'
        ]

        for item in json_ld_items:
            item_type = item.get('@type', '')
            if isinstance(item_type, list):
                item_type = item_type[0] if item_type else ''

            # Check if it's a local business
            if item_type in local_business_types:
                result['positive_signals'].append(f'LocalBusiness schema detected: {item_type}')
                result['has_local_business_schema'] = True

                # Check serviceType field
                service_type = item.get('serviceType', '')
                if service_type:
                    result['positive_signals'].append(f'Service type in schema: {service_type}')

    def _assign_tier(self, result: Dict):
        """
        Assign tier based on service coverage.

        Tier A: All 3 services with both residential & commercial
        Tier B: ≥ 2 services with both residential & commercial
        Tier C: ≥ 1 service with both residential & commercial
        Tier D: Services detected but missing res/com context
        Tier E: No services detected or minimal signals
        """
        services = result['services_detected']

        # Count services with both residential and commercial
        full_coverage_count = sum(
            1 for svc in services.values()
            if svc.get('residential', False) and svc.get('commercial', False)
        )

        # Count services with ANY detection (relaxed requirement)
        any_service_count = sum(
            1 for svc in services.values()
            if svc.get('any', False)
        )

        if full_coverage_count >= 3:
            result['tier'] = 'A'
        elif full_coverage_count >= 2:
            result['tier'] = 'B'
        elif full_coverage_count >= 1:
            result['tier'] = 'C'
        elif any_service_count >= 1:
            # New Tier D: Has services but not both res+com
            result['tier'] = 'D'
        else:
            # New Tier E: No clear services detected
            result['tier'] = 'E'

    def _calculate_rule_score(self, result: Dict) -> float:
        """Calculate confidence score based on rule-based signals."""
        score = 0.0

        # Tier scoring (0-40 points) - Updated with more generous D/E tiers
        tier_scores = {'A': 40, 'B': 30, 'C': 20, 'D': 15, 'E': 5}
        score += tier_scores.get(result['tier'], 0)

        # Provider language (0-20 points)
        provider_count = result.get('provider_phrase_count', 0)
        score += min(provider_count * 4, 20)  # Max 20 points

        # CTA phrases (0-10 points)
        cta_count = result.get('cta_phrase_count', 0)
        score += min(cta_count * 3, 10)  # Max 10 points

        # Local business artifacts (0-15 points)
        if result.get('has_phone'):
            score += 5
        if result.get('has_email'):
            score += 5
        if result.get('has_address'):
            score += 5

        # Site structure (0-10 points)
        if result.get('has_service_nav'):
            score += 5
        if result.get('has_local_business_schema'):
            score += 5

        # Negative penalties
        informational_count = result.get('informational_phrase_count', 0)
        provider_count = result.get('provider_phrase_count', 0)

        # Reduced penalty: only if heavy informational AND low provider content
        # Don't penalize if provider signals balance out informational content
        if informational_count > 5 and provider_count < informational_count / 2:
            score -= 5  # Reduced penalty (was -10 at threshold 3)

        if len(result['negative_signals']) > 0:
            score -= len(result['negative_signals']) * 5  # 5 points per negative signal

        # Normalize to 0.0-1.0
        normalized_score = max(0.0, min(score / 100.0, 1.0))
        return normalized_score

    def _get_llm_classification(self, company_data: Dict, website_metadata: Dict) -> Optional[Dict]:
        """
        Get LLM classification for uncertain cases.

        Args:
            company_data: Company data dict
            website_metadata: Parsed website metadata

        Returns:
            LLM classification dict or None if failed
        """
        if not self.llm_verifier:
            return None

        try:
            company_name = company_data.get('name', '')
            services_text = website_metadata.get('services', '')
            about_text = website_metadata.get('about', '')
            homepage_text = website_metadata.get('homepage_text', '')

            # Call LLM classifier
            classification = self.llm_verifier.classify_company(
                company_name=company_name,
                services_text=services_text,
                about_text=about_text,
                homepage_text=homepage_text
            )

            return classification

        except Exception as e:
            logger.warning(f"Error getting LLM classification: {e}")
            return None

    def _get_ml_score(self, company_data: Dict, result: Dict) -> float:
        """Get ML model prediction (Phase 5 implementation)."""
        if not self.ml_model:
            return 0.5  # Neutral score if no model

        try:
            # Extract features (Phase 5.2 feature engineering)
            features = self._extract_ml_features(company_data, result)

            # Predict probability of being a target
            # Assumes model.predict_proba returns [P(non-target), P(target)]
            prob = self.ml_model.predict_proba([features])[0][1]
            return float(prob)

        except Exception as e:
            logger.warning(f"Error getting ML score: {e}")
            return 0.5  # Fallback to neutral

    def _extract_ml_features(self, company_data: Dict, result: Dict) -> List[float]:
        """Extract features for ML model (Phase 5.2)."""
        # Placeholder for Phase 5 implementation
        # Returns a feature vector for the ML model
        features = [
            # Service counts
            len([s for s in result['services_detected'].values() if s.get('any', False)]),
            len([s for s in result['services_detected'].values() if s.get('residential', False)]),
            len([s for s in result['services_detected'].values() if s.get('commercial', False)]),

            # Language features
            result.get('provider_phrase_count', 0),
            result.get('informational_phrase_count', 0),
            result.get('cta_phrase_count', 0),

            # Boolean features (converted to 0/1)
            int(result.get('has_phone', False)),
            int(result.get('has_email', False)),
            int(result.get('has_address', False)),
            int(result.get('has_service_nav', False)),
            int(result.get('has_local_business_schema', False)),

            # Discovery signals (if present)
            company_data.get('parse_metadata', {}).get('google_filter', {}).get('confidence', 0.0),
            company_data.get('parse_metadata', {}).get('yp_filter', {}).get('confidence', 0.0),

            # Reviews
            self._log_scale(company_data.get('reviews_google', 0) + company_data.get('reviews_yp', 0))
        ]

        return features

    def _log_scale(self, value: int) -> float:
        """Log-scale a count value."""
        return math.log1p(value)  # log(1 + value)


def create_verifier(
    config_file: str = 'data/verification_services.json',
    use_llm: bool = False
) -> ServiceVerifier:
    """
    Factory function to create a ServiceVerifier instance.

    Args:
        config_file: Path to verification services config JSON
        use_llm: Whether to use LLM for uncertain cases (hybrid mode)

    Returns:
        Configured ServiceVerifier instance
    """
    return ServiceVerifier(config_file=config_file, use_llm=use_llm)

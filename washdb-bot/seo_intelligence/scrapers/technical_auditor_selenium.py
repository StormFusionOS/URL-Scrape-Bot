"""
Technical Auditor Module (Selenium Version)

Uses SeleniumBase Undetected Chrome for better anti-detection.
Falls back to HTTP requests when browser fails.

This is the SeleniumBase equivalent of technical_auditor.py.
"""

import os
import re
import json
import time
import ssl
import socket
import requests
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field, asdict
from enum import Enum

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_selenium_scraper import BaseSeleniumScraper
from seo_intelligence.services import get_task_logger
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("technical_auditor_selenium")


class IssueSeverity(Enum):
    """Severity levels for audit issues."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IssueCategory(Enum):
    """Categories for audit issues."""
    SECURITY = "security"
    PERFORMANCE = "performance"
    SEO = "seo"
    ACCESSIBILITY = "accessibility"
    MOBILE = "mobile"
    CONTENT = "content"
    TECHNICAL = "technical"


@dataclass
class AuditIssue:
    """Represents a single audit issue."""
    category: str
    severity: str
    issue_type: str
    description: str
    affected_element: str = ""
    recommendation: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditResult:
    """Complete audit result for a page."""
    url: str
    audit_date: datetime
    overall_score: float
    performance_score: float
    seo_score: float
    accessibility_score: float
    security_score: float
    issues: List[AuditIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    passed_checks: List[str] = field(default_factory=list)

    @property
    def critical_issues(self) -> List[AuditIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.CRITICAL.value]

    @property
    def high_issues(self) -> List[AuditIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.HIGH.value]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "audit_date": self.audit_date.isoformat(),
            "overall_score": self.overall_score,
            "performance_score": self.performance_score,
            "seo_score": self.seo_score,
            "accessibility_score": self.accessibility_score,
            "security_score": self.security_score,
            "issues": [i.to_dict() for i in self.issues],
            "metrics": self.metrics,
            "passed_checks": self.passed_checks,
            "critical_count": len(self.critical_issues),
            "high_count": len(self.high_issues),
        }


class TechnicalAuditorSelenium(BaseSeleniumScraper):
    """
    Technical SEO auditor using SeleniumBase Undetected Chrome.

    Better anti-detection than Playwright version.
    """

    def __init__(
        self,
        headless: bool = False,  # Non-headless by default for better stealth
        use_proxy: bool = True,
        tier: str = "C",
        mobile_mode: bool = False,
    ):
        super().__init__(
            name="technical_auditor_selenium",
            tier=tier,
            headless=headless,
            respect_robots=False,
            use_proxy=use_proxy,
            max_retries=2,
            page_timeout=30,
            mobile_mode=mobile_mode,
        )

        self._tier = tier
        self._mobile_mode = mobile_mode

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set")

        logger.info(f"TechnicalAuditorSelenium initialized (tier={tier}, UC mode)")

    def _http_fallback_audit(self, url: str) -> Optional[Tuple[str, Dict[str, Any], List[AuditIssue]]]:
        """Simple HTTP fallback when browser fails."""
        issues = []
        metrics = {"fallback_mode": True}

        try:
            start_time = time.time()
            response = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                verify=True,
                allow_redirects=True,
            )
            load_time = time.time() - start_time

            metrics["http_status"] = response.status_code
            metrics["load_time_seconds"] = round(load_time, 2)

            if load_time > 5:
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.HIGH.value,
                    issue_type="slow_response",
                    description=f"Slow response time: {load_time:.1f}s",
                    recommendation="Optimize server response time"
                ))

            logger.info(f"HTTP fallback succeeded for {url}")
            return response.text, metrics, issues

        except Exception as e:
            logger.warning(f"HTTP fallback failed for {url}: {e}")
            return None, metrics, issues

    def _check_ssl(self, url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check SSL/HTTPS configuration."""
        issues = []
        metrics = {"has_ssl": False}

        parsed = urlparse(url)

        if parsed.scheme == "https":
            metrics["has_ssl"] = True
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SECURITY.value,
                severity=IssueSeverity.CRITICAL.value,
                issue_type="no_ssl",
                description="Site not using HTTPS",
                recommendation="Install SSL certificate and redirect HTTP to HTTPS"
            ))

        return issues, metrics

    def _check_response_headers(self, url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check HTTP response headers."""
        issues = []
        metrics = {"headers_checked": True, "headers": {}}

        try:
            response = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, allow_redirects=True, verify=True)

            headers = response.headers
            metrics["final_status_code"] = response.status_code

            # Cache-Control
            cache_control = headers.get("Cache-Control", "")
            if not cache_control:
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_cache_control",
                    description="Missing Cache-Control header",
                    recommendation="Add Cache-Control header",
                ))

            # Compression
            content_encoding = headers.get("Content-Encoding", "")
            if content_encoding:
                metrics["compression_enabled"] = True
            else:
                content_type = headers.get("Content-Type", "")
                if "text/html" in content_type.lower():
                    issues.append(AuditIssue(
                        category=IssueCategory.PERFORMANCE.value,
                        severity=IssueSeverity.MEDIUM.value,
                        issue_type="missing_compression",
                        description="No compression enabled (gzip/br)",
                        recommendation="Enable gzip or Brotli compression",
                    ))

            # HSTS
            hsts = headers.get("Strict-Transport-Security", "")
            if response.url.startswith("https://"):
                if hsts:
                    metrics["hsts_enabled"] = True
                else:
                    issues.append(AuditIssue(
                        category=IssueCategory.SECURITY.value,
                        severity=IssueSeverity.MEDIUM.value,
                        issue_type="missing_hsts",
                        description="Missing HSTS header on HTTPS site",
                        recommendation="Add Strict-Transport-Security header",
                    ))

            # CSP
            if not headers.get("Content-Security-Policy", ""):
                issues.append(AuditIssue(
                    category=IssueCategory.SECURITY.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_csp",
                    description="Missing Content-Security-Policy header",
                    recommendation="Add CSP header",
                ))

            # X-Frame-Options
            if not headers.get("X-Frame-Options", ""):
                issues.append(AuditIssue(
                    category=IssueCategory.SECURITY.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_x_frame_options",
                    description="Missing X-Frame-Options header",
                    recommendation="Add X-Frame-Options",
                ))

        except Exception as e:
            logger.warning(f"Error checking headers for {url}: {e}")
            metrics["headers_error"] = str(e)[:100]

        return issues, metrics

    def _check_meta_tags(self, soup, url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check meta tags for SEO."""
        issues = []
        metrics = {}

        # Title
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            metrics["title"] = title_text
            metrics["title_length"] = len(title_text)

            if len(title_text) < 30:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="title_too_short",
                    description=f"Title tag too short ({len(title_text)} chars)",
                    recommendation="Title should be 50-60 characters"
                ))
            elif len(title_text) > 60:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="title_too_long",
                    description=f"Title tag too long ({len(title_text)} chars)",
                    recommendation="Title should be 50-60 characters"
                ))
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.CRITICAL.value,
                issue_type="missing_title",
                description="Missing title tag",
                recommendation="Add a descriptive title tag"
            ))

        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            desc_text = meta_desc.get('content', '')
            metrics["meta_description_length"] = len(desc_text)

            if len(desc_text) < 120:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="meta_desc_too_short",
                    description=f"Meta description too short ({len(desc_text)} chars)",
                    recommendation="Meta description should be 150-160 characters"
                ))
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_meta_description",
                description="Missing meta description",
                recommendation="Add a meta description"
            ))

        # Viewport
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        if viewport:
            metrics["has_viewport"] = True
        else:
            issues.append(AuditIssue(
                category=IssueCategory.MOBILE.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_viewport",
                description="Missing viewport meta tag",
                recommendation="Add viewport meta tag"
            ))

        return issues, metrics

    def _check_headings(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check heading structure."""
        issues = []
        metrics = {}

        h1_tags = soup.find_all('h1')
        metrics["h1_count"] = len(h1_tags)

        if len(h1_tags) == 0:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_h1",
                description="Page has no H1 tag",
                recommendation="Add one H1 tag"
            ))
        elif len(h1_tags) > 1:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.LOW.value,
                issue_type="multiple_h1",
                description=f"Page has {len(h1_tags)} H1 tags",
                recommendation="Use only one H1 tag"
            ))

        return issues, metrics

    def _check_images(self, soup, base_url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check images for alt text."""
        issues = []
        metrics = {}

        images = soup.find_all('img')
        metrics["total_images"] = len(images)

        missing_alt = sum(1 for img in images if img.get('alt') is None)
        metrics["images_missing_alt"] = missing_alt

        if missing_alt > 0:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="images_missing_alt",
                description=f"{missing_alt} images missing alt attribute",
                recommendation="Add alt text to all images"
            ))

        return issues, metrics

    def _check_schema(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check schema.org structured data.

        Uses get_text() instead of string property to handle multi-node scripts.
        Supports @graph arrays commonly used in modern schema markup.
        """
        issues = []
        metrics = {}

        schemas = []
        schema_types = set()

        def extract_types(data):
            """Recursively extract @type values from schema data."""
            if isinstance(data, dict):
                if '@type' in data:
                    t = data['@type']
                    if isinstance(t, list):
                        schema_types.update(t)
                    else:
                        schema_types.add(t)
                # Check nested objects
                for v in data.values():
                    extract_types(v)
            elif isinstance(data, list):
                for item in data:
                    extract_types(item)

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                # Use get_text() instead of .string - handles multi-node scripts
                content = script.get_text(strip=True)
                if content:
                    data = json.loads(content)
                    # Handle @graph arrays (common in Google-style schema)
                    if isinstance(data, dict) and '@graph' in data:
                        graph_items = data['@graph']
                        if isinstance(graph_items, list):
                            schemas.extend(graph_items)
                            for item in graph_items:
                                extract_types(item)
                        else:
                            schemas.append(graph_items)
                            extract_types(graph_items)
                    elif isinstance(data, list):
                        schemas.extend(data)
                        for item in data:
                            extract_types(item)
                    else:
                        schemas.append(data)
                        extract_types(data)
            except json.JSONDecodeError:
                issues.append(AuditIssue(
                    category=IssueCategory.TECHNICAL.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="invalid_schema_json",
                    description="Invalid JSON-LD schema",
                    recommendation="Fix JSON syntax"
                ))

        metrics["schema_count"] = len(schemas)
        metrics["schema_types"] = list(schema_types)

        if not schemas:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="missing_schema",
                description="No schema.org structured data",
                recommendation="Add LocalBusiness schema"
            ))

        return issues, metrics

    def _check_social_meta(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check Open Graph and Twitter Card meta tags for completeness."""
        issues = []
        metrics = {}

        # ===== Open Graph Analysis =====
        og_tags = {
            'og:title': None,
            'og:description': None,
            'og:image': None,
            'og:url': None,
            'og:type': None,
            'og:site_name': None,
            'og:locale': None,
        }

        # Required OG tags for good sharing
        og_required = ['og:title', 'og:description', 'og:image', 'og:url']
        # Optional but recommended
        og_recommended = ['og:type', 'og:site_name']

        for meta in soup.find_all('meta', property=True):
            prop = meta.get('property', '')
            content = meta.get('content', '')
            if prop in og_tags:
                og_tags[prop] = content

        og_present = [k for k, v in og_tags.items() if v]
        og_missing_required = [t for t in og_required if not og_tags.get(t)]
        og_missing_recommended = [t for t in og_recommended if not og_tags.get(t)]

        metrics['og_tags_present'] = og_present
        metrics['og_tags_count'] = len(og_present)

        # Calculate OG completeness score (0-100)
        og_score = 0
        # Required tags worth 20 points each (80 total)
        for tag in og_required:
            if og_tags.get(tag):
                og_score += 20
        # Recommended tags worth 10 points each (20 total)
        for tag in og_recommended:
            if og_tags.get(tag):
                og_score += 10

        metrics['og_completeness_score'] = og_score
        metrics['og_title'] = og_tags.get('og:title', '')
        metrics['og_description'] = og_tags.get('og:description', '')
        metrics['og_image'] = og_tags.get('og:image', '')

        # Issues for OG
        if not any(og_tags.values()):
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="missing_open_graph",
                description="No Open Graph meta tags found",
                recommendation="Add og:title, og:description, og:image, og:url meta tags for social sharing",
                metadata={"missing_tags": og_required}
            ))
        elif og_missing_required:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.LOW.value,
                issue_type="incomplete_open_graph",
                description=f"Missing required OG tags: {', '.join(og_missing_required)}",
                recommendation=f"Add missing Open Graph tags for better social sharing",
                metadata={"missing_tags": og_missing_required, "score": og_score}
            ))

        # Check OG image dimensions hint (can't check actual dimensions without fetching)
        if og_tags.get('og:image'):
            # Check for og:image:width and og:image:height
            og_width = soup.find('meta', property='og:image:width')
            og_height = soup.find('meta', property='og:image:height')
            if og_width and og_height:
                metrics['og_image_dimensions_specified'] = True
            else:
                metrics['og_image_dimensions_specified'] = False

        # ===== Twitter Card Analysis =====
        twitter_tags = {
            'twitter:card': None,
            'twitter:title': None,
            'twitter:description': None,
            'twitter:image': None,
            'twitter:site': None,
            'twitter:creator': None,
        }

        # Required for proper Twitter cards
        twitter_required = ['twitter:card', 'twitter:title', 'twitter:description']
        # Recommended
        twitter_recommended = ['twitter:image', 'twitter:site']

        for meta in soup.find_all('meta', attrs={'name': True}):
            name = meta.get('name', '')
            content = meta.get('content', '')
            if name in twitter_tags:
                twitter_tags[name] = content

        twitter_present = [k for k, v in twitter_tags.items() if v]
        twitter_missing_required = [t for t in twitter_required if not twitter_tags.get(t)]

        metrics['twitter_tags_present'] = twitter_present
        metrics['twitter_tags_count'] = len(twitter_present)
        metrics['twitter_card_type'] = twitter_tags.get('twitter:card', '')

        # Calculate Twitter completeness score (0-100)
        twitter_score = 0
        # Required tags worth 25 points each (75 total)
        for tag in twitter_required:
            if twitter_tags.get(tag):
                twitter_score += 25
        # Recommended tags worth 12.5 points each (25 total)
        for tag in twitter_recommended:
            if twitter_tags.get(tag):
                twitter_score += 12.5

        metrics['twitter_completeness_score'] = twitter_score
        metrics['twitter_title'] = twitter_tags.get('twitter:title', '')
        metrics['twitter_description'] = twitter_tags.get('twitter:description', '')
        metrics['twitter_image'] = twitter_tags.get('twitter:image', '')

        # Issues for Twitter Cards
        if not any(twitter_tags.values()):
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.LOW.value,
                issue_type="missing_twitter_cards",
                description="No Twitter Card meta tags found",
                recommendation="Add twitter:card, twitter:title, twitter:description meta tags",
                metadata={"missing_tags": twitter_required}
            ))
        elif twitter_missing_required:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.INFO.value,
                issue_type="incomplete_twitter_cards",
                description=f"Missing Twitter Card tags: {', '.join(twitter_missing_required)}",
                recommendation="Add missing Twitter Card tags",
                metadata={"missing_tags": twitter_missing_required, "score": twitter_score}
            ))

        # ===== Combined Social Meta Score =====
        # Average of OG and Twitter scores
        social_meta_score = (og_score + twitter_score) / 2
        metrics['social_meta_score'] = social_meta_score

        # Grade the social meta implementation
        if social_meta_score >= 90:
            metrics['social_meta_grade'] = 'A'
        elif social_meta_score >= 75:
            metrics['social_meta_grade'] = 'B'
        elif social_meta_score >= 60:
            metrics['social_meta_grade'] = 'C'
        elif social_meta_score >= 40:
            metrics['social_meta_grade'] = 'D'
        else:
            metrics['social_meta_grade'] = 'F'

        return issues, metrics

    def _check_accessibility(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check WCAG 2.1 Level A accessibility requirements."""
        issues = []
        metrics = {}

        # Track accessibility score components
        a11y_checks = {
            'lang_attribute': False,
            'skip_links': False,
            'form_labels': False,
            'aria_landmarks': False,
            'link_text_quality': False,
            'button_text': False,
            'tabindex_valid': False,
            'focus_indicators': False,
        }

        # ===== 1. Language Attribute (WCAG 3.1.1) =====
        html_tag = soup.find('html')
        if html_tag:
            lang = html_tag.get('lang', '')
            if lang:
                a11y_checks['lang_attribute'] = True
                metrics['html_lang'] = lang
            else:
                issues.append(AuditIssue(
                    category=IssueCategory.ACCESSIBILITY.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="missing_lang_attribute",
                    description="Missing lang attribute on <html> element",
                    recommendation="Add lang attribute (e.g., lang='en') for screen readers",
                    metadata={"wcag": "3.1.1"}
                ))

        # ===== 2. Skip Links (WCAG 2.4.1) =====
        skip_link = soup.find('a', href='#main') or soup.find('a', href='#content') or \
                    soup.find('a', class_=re.compile(r'skip', re.I)) or \
                    soup.find('a', string=re.compile(r'skip to (main|content)', re.I))
        if skip_link:
            a11y_checks['skip_links'] = True
            metrics['has_skip_links'] = True
        else:
            metrics['has_skip_links'] = False
            # Only flag as low severity since many modern sites use other nav patterns
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.LOW.value,
                issue_type="missing_skip_links",
                description="No skip navigation links found",
                recommendation="Add 'Skip to main content' link for keyboard users",
                metadata={"wcag": "2.4.1"}
            ))

        # ===== 3. Form Labels (WCAG 1.3.1, 4.1.2) =====
        forms = soup.find_all('form')
        inputs = soup.find_all(['input', 'select', 'textarea'])
        labeled_inputs = 0
        unlabeled_inputs = []

        for inp in inputs:
            input_type = inp.get('type', 'text')
            # Skip hidden, submit, button, reset inputs
            if input_type in ['hidden', 'submit', 'button', 'reset', 'image']:
                continue

            input_id = inp.get('id', '')
            input_name = inp.get('name', '')

            # Check for associated label
            has_label = False

            # Check for <label for="id">
            if input_id:
                label = soup.find('label', attrs={'for': input_id})
                if label:
                    has_label = True

            # Check for aria-label or aria-labelledby
            if inp.get('aria-label') or inp.get('aria-labelledby'):
                has_label = True

            # Check for placeholder (not a proper label but counts as fallback)
            if inp.get('placeholder') and not has_label:
                has_label = True  # Acceptable fallback

            # Check for wrapped in label
            parent = inp.parent
            if parent and parent.name == 'label':
                has_label = True

            if has_label:
                labeled_inputs += 1
            else:
                unlabeled_inputs.append(input_name or input_id or input_type)

        total_form_inputs = len([i for i in inputs if i.get('type', 'text') not in ['hidden', 'submit', 'button', 'reset', 'image']])
        metrics['form_inputs_total'] = total_form_inputs
        metrics['form_inputs_labeled'] = labeled_inputs
        metrics['form_inputs_unlabeled'] = len(unlabeled_inputs)

        if total_form_inputs > 0:
            label_ratio = labeled_inputs / total_form_inputs
            metrics['form_label_ratio'] = round(label_ratio, 2)

            if label_ratio >= 0.9:
                a11y_checks['form_labels'] = True
            elif unlabeled_inputs:
                issues.append(AuditIssue(
                    category=IssueCategory.ACCESSIBILITY.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="unlabeled_form_inputs",
                    description=f"{len(unlabeled_inputs)} form inputs missing labels",
                    recommendation="Add <label> elements or aria-label attributes",
                    metadata={"wcag": "1.3.1", "unlabeled": unlabeled_inputs[:5]}
                ))
        else:
            a11y_checks['form_labels'] = True  # No forms to check

        # ===== 4. ARIA Landmarks (WCAG 1.3.1) =====
        landmarks = {
            'main': soup.find('main') or soup.find(attrs={'role': 'main'}),
            'nav': soup.find('nav') or soup.find(attrs={'role': 'navigation'}),
            'header': soup.find('header') or soup.find(attrs={'role': 'banner'}),
            'footer': soup.find('footer') or soup.find(attrs={'role': 'contentinfo'}),
        }

        found_landmarks = [k for k, v in landmarks.items() if v]
        metrics['aria_landmarks'] = found_landmarks
        metrics['aria_landmarks_count'] = len(found_landmarks)

        if 'main' in found_landmarks:
            a11y_checks['aria_landmarks'] = True
        else:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.LOW.value,
                issue_type="missing_main_landmark",
                description="Missing <main> element or role='main'",
                recommendation="Add <main> element to identify primary content",
                metadata={"wcag": "1.3.1", "found_landmarks": found_landmarks}
            ))

        # ===== 5. Link Text Quality (WCAG 2.4.4) =====
        links = soup.find_all('a', href=True)
        vague_links = []
        empty_links = []

        vague_text_patterns = ['click here', 'read more', 'learn more', 'here', 'more', 'link']

        for link in links:
            link_text = link.get_text(strip=True).lower()
            aria_label = link.get('aria-label', '').strip()

            # Check for empty links
            if not link_text and not aria_label and not link.find('img'):
                empty_links.append(link.get('href', '')[:50])
            # Check for vague link text
            elif link_text in vague_text_patterns and not aria_label:
                vague_links.append(link_text)

        metrics['links_total'] = len(links)
        metrics['links_empty'] = len(empty_links)
        metrics['links_vague'] = len(vague_links)

        if len(links) > 0:
            good_links_ratio = (len(links) - len(empty_links) - len(vague_links)) / len(links)
            metrics['link_text_quality_ratio'] = round(good_links_ratio, 2)

            if good_links_ratio >= 0.9:
                a11y_checks['link_text_quality'] = True

            if empty_links:
                issues.append(AuditIssue(
                    category=IssueCategory.ACCESSIBILITY.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="empty_links",
                    description=f"{len(empty_links)} links have no accessible text",
                    recommendation="Add descriptive text or aria-label to links",
                    metadata={"wcag": "2.4.4", "examples": empty_links[:3]}
                ))

            if len(vague_links) > 3:
                issues.append(AuditIssue(
                    category=IssueCategory.ACCESSIBILITY.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="vague_link_text",
                    description=f"{len(vague_links)} links use vague text like 'click here'",
                    recommendation="Use descriptive link text that makes sense out of context",
                    metadata={"wcag": "2.4.4", "vague_count": len(vague_links)}
                ))
        else:
            a11y_checks['link_text_quality'] = True

        # ===== 6. Button Accessibility (WCAG 4.1.2) =====
        buttons = soup.find_all(['button', 'input'])
        buttons = [b for b in buttons if b.name == 'button' or b.get('type') in ['button', 'submit', 'reset']]
        unlabeled_buttons = []

        for button in buttons:
            button_text = button.get_text(strip=True)
            aria_label = button.get('aria-label', '')
            value = button.get('value', '')
            title = button.get('title', '')

            if not (button_text or aria_label or value or title):
                unlabeled_buttons.append(str(button)[:50])

        metrics['buttons_total'] = len(buttons)
        metrics['buttons_unlabeled'] = len(unlabeled_buttons)

        if unlabeled_buttons:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="unlabeled_buttons",
                description=f"{len(unlabeled_buttons)} buttons missing accessible names",
                recommendation="Add text content, aria-label, or value attribute",
                metadata={"wcag": "4.1.2", "count": len(unlabeled_buttons)}
            ))
        else:
            a11y_checks['button_text'] = True

        # ===== 7. Tabindex Validation (WCAG 2.4.3) =====
        positive_tabindex = soup.find_all(attrs={'tabindex': True})
        bad_tabindex = [el for el in positive_tabindex if el.get('tabindex', '0').lstrip('-').isdigit() and int(el.get('tabindex', '0')) > 0]

        metrics['tabindex_positive_count'] = len(bad_tabindex)

        if bad_tabindex:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.LOW.value,
                issue_type="positive_tabindex",
                description=f"{len(bad_tabindex)} elements use positive tabindex values",
                recommendation="Avoid tabindex > 0; use natural DOM order or tabindex='0'",
                metadata={"wcag": "2.4.3", "count": len(bad_tabindex)}
            ))
        else:
            a11y_checks['tabindex_valid'] = True

        # ===== 8. Focus Indicators (WCAG 2.4.7) - Basic check =====
        # Check for outline: none or outline: 0 in inline styles (basic heuristic)
        elements_with_no_outline = soup.find_all(style=re.compile(r'outline:\s*(none|0)', re.I))
        metrics['elements_outline_none'] = len(elements_with_no_outline)

        if len(elements_with_no_outline) > 5:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="focus_indicators_removed",
                description=f"{len(elements_with_no_outline)} elements have outline:none in styles",
                recommendation="Ensure focus indicators are visible or provide custom focus styles",
                metadata={"wcag": "2.4.7", "count": len(elements_with_no_outline)}
            ))
        else:
            a11y_checks['focus_indicators'] = True

        # ===== Calculate Accessibility Score =====
        checks_passed = sum(1 for v in a11y_checks.values() if v)
        total_checks = len(a11y_checks)
        a11y_score = round((checks_passed / total_checks) * 100, 1)

        metrics['a11y_checks'] = a11y_checks
        metrics['a11y_checks_passed'] = checks_passed
        metrics['a11y_checks_total'] = total_checks
        metrics['a11y_score'] = a11y_score

        # Grade the accessibility
        if a11y_score >= 90:
            metrics['a11y_grade'] = 'A'
        elif a11y_score >= 75:
            metrics['a11y_grade'] = 'B'
        elif a11y_score >= 60:
            metrics['a11y_grade'] = 'C'
        elif a11y_score >= 40:
            metrics['a11y_grade'] = 'D'
        else:
            metrics['a11y_grade'] = 'F'

        return issues, metrics

    def _calculate_scores(self, issues: List[AuditIssue], metrics: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
        """Calculate audit scores from issues."""
        security_score = 100.0
        seo_score = 100.0
        accessibility_score = 100.0
        performance_score = 100.0

        deductions = {
            IssueSeverity.CRITICAL.value: 25,
            IssueSeverity.HIGH.value: 15,
            IssueSeverity.MEDIUM.value: 8,
            IssueSeverity.LOW.value: 3,
            IssueSeverity.INFO.value: 0,
        }

        for issue in issues:
            deduction = deductions.get(issue.severity, 0)

            if issue.category == IssueCategory.SECURITY.value:
                security_score = max(0, security_score - deduction)
            elif issue.category == IssueCategory.SEO.value:
                seo_score = max(0, seo_score - deduction)
            elif issue.category == IssueCategory.ACCESSIBILITY.value:
                accessibility_score = max(0, accessibility_score - deduction)
            elif issue.category == IssueCategory.PERFORMANCE.value:
                performance_score = max(0, performance_score - deduction)
            elif issue.category == IssueCategory.MOBILE.value:
                seo_score = max(0, seo_score - deduction / 2)
                accessibility_score = max(0, accessibility_score - deduction / 2)

        overall = (security_score * 0.15 + seo_score * 0.40 + accessibility_score * 0.20 + performance_score * 0.25)

        return overall, performance_score, seo_score, accessibility_score, security_score

    def audit_page_with_artifact(
        self,
        url: str,
        save_artifact: bool = True,
        quality_profile: Optional['ScrapeQualityProfile'] = None,
    ) -> Tuple[AuditResult, Optional['PageArtifact']]:
        """
        Perform technical audit and capture comprehensive artifacts.

        This method captures raw HTML, screenshots, console logs, and metadata
        so the audit can be re-run offline without re-scraping.

        Args:
            url: URL to audit
            save_artifact: Whether to persist artifact to disk
            quality_profile: Quality settings (defaults to HIGH_QUALITY_PROFILE for better data)

        Returns:
            Tuple of (AuditResult, PageArtifact) - PageArtifact may be None if fetch failed
        """
        from seo_intelligence.models.artifacts import (
            PageArtifact,
            ScrapeQualityProfile,
            ArtifactStorage,
            HIGH_QUALITY_PROFILE,
        )

        profile = quality_profile or HIGH_QUALITY_PROFILE
        logger.info(f"Auditing {url} with artifact capture (quality={profile.wait_strategy})")

        all_issues = []
        all_metrics = {}
        passed_checks = []
        artifact = None

        try:
            # SSL check (doesn't need browser)
            ssl_issues, ssl_metrics = self._check_ssl(url)
            all_issues.extend(ssl_issues)
            all_metrics.update(ssl_metrics)
            if not ssl_issues:
                passed_checks.append("SSL/HTTPS configured")

            # HTTP headers check (doesn't need browser)
            header_issues, header_metrics = self._check_response_headers(url)
            all_issues.extend(header_issues)
            all_metrics.update(header_metrics)
            if header_metrics.get("compression_enabled"):
                passed_checks.append("Compression enabled")
            if header_metrics.get("hsts_enabled"):
                passed_checks.append("HSTS configured")

            # Fetch page with artifact capture
            html = None

            try:
                with self.browser_session("generic") as driver:
                    artifact = self.fetch_page_with_artifact(
                        driver=driver,
                        url=url,
                        quality_profile=profile,
                        save_artifact=save_artifact,
                        wait_for_selector="body",
                    )

                    if artifact and artifact.html_raw:
                        html = artifact.html_raw
                        all_metrics["load_time_seconds"] = round(
                            (artifact.fetch_duration_ms or 0) / 1000, 2
                        )
                        all_metrics["artifact_captured"] = True
                        all_metrics["artifact_completeness"] = artifact.completeness_score

                        # Add artifact metadata to metrics
                        if artifact.console_errors:
                            all_metrics["console_errors_count"] = len(artifact.console_errors)
                            all_metrics["console_errors"] = artifact.console_errors[:5]
                        if artifact.console_warnings:
                            all_metrics["console_warnings_count"] = len(artifact.console_warnings)

                        if artifact.detected_captcha:
                            all_issues.append(AuditIssue(
                                category=IssueCategory.TECHNICAL.value,
                                severity=IssueSeverity.HIGH.value,
                                issue_type="captcha_detected",
                                description="CAPTCHA detected during page load",
                                recommendation="Site may be blocking automated access"
                            ))

                        if artifact.detected_consent_overlay:
                            all_metrics["has_consent_overlay"] = True

                        load_time = all_metrics.get("load_time_seconds", 0)
                        if load_time > 5:
                            all_issues.append(AuditIssue(
                                category=IssueCategory.PERFORMANCE.value,
                                severity=IssueSeverity.HIGH.value,
                                issue_type="slow_page_load",
                                description=f"Page load time: {load_time:.1f}s",
                                recommendation="Optimize page load time"
                            ))
                        elif load_time < 3 and load_time > 0:
                            passed_checks.append(f"Fast page load ({load_time:.1f}s)")

            except Exception as e:
                logger.warning(f"SeleniumBase UC error for {url}: {e}")
                # Try HTTP fallback
                fallback_result = self._http_fallback_audit(url)
                if fallback_result and fallback_result[0]:
                    html, fb_metrics, fb_issues = fallback_result
                    all_metrics.update(fb_metrics)
                    all_issues.extend(fb_issues)
                    all_metrics["artifact_captured"] = False

            if not html:
                return AuditResult(
                    url=url,
                    audit_date=datetime.now(),
                    overall_score=0,
                    performance_score=0,
                    seo_score=0,
                    accessibility_score=0,
                    security_score=0,
                    issues=all_issues + [AuditIssue(
                        category=IssueCategory.TECHNICAL.value,
                        severity=IssueSeverity.CRITICAL.value,
                        issue_type="page_unreachable",
                        description="Could not load page",
                        recommendation="Check if URL is accessible"
                    )],
                    metrics=all_metrics,
                ), artifact

            # Parse and analyze HTML
            soup = BeautifulSoup(html, 'html.parser')

            checks = [
                self._check_meta_tags(soup, url),
                self._check_headings(soup),
                self._check_images(soup, url),
                self._check_schema(soup),
                self._check_social_meta(soup),
                self._check_accessibility(soup),
            ]

            for issues, metrics in checks:
                all_issues.extend(issues)
                all_metrics.update(metrics)

            # Calculate scores
            overall, perf, seo, access, security = self._calculate_scores(all_issues, all_metrics)

            result = AuditResult(
                url=url,
                audit_date=datetime.now(),
                overall_score=overall,
                performance_score=perf,
                seo_score=seo,
                accessibility_score=access,
                security_score=security,
                issues=all_issues,
                metrics=all_metrics,
                passed_checks=passed_checks,
            )

            logger.info(
                f"Audit with artifact complete: {url} - Score: {overall:.0f} "
                f"({len(all_issues)} issues, artifact={artifact is not None})"
            )

            return result, artifact

        except Exception as e:
            logger.error(f"Error auditing {url} with artifact: {e}", exc_info=True)
            return AuditResult(
                url=url,
                audit_date=datetime.now(),
                overall_score=0,
                performance_score=0,
                seo_score=0,
                accessibility_score=0,
                security_score=0,
                issues=[AuditIssue(
                    category=IssueCategory.TECHNICAL.value,
                    severity=IssueSeverity.CRITICAL.value,
                    issue_type="audit_error",
                    description=str(e),
                    recommendation="Check URL and try again"
                )],
                metrics=all_metrics,
            ), artifact

    def audit_page(self, url: str, measure_cwv: bool = False) -> AuditResult:
        """Perform technical audit using SeleniumBase UC."""
        logger.info(f"Auditing {url} with SeleniumBase UC")

        all_issues = []
        all_metrics = {}
        passed_checks = []

        try:
            # SSL check
            ssl_issues, ssl_metrics = self._check_ssl(url)
            all_issues.extend(ssl_issues)
            all_metrics.update(ssl_metrics)
            if not ssl_issues:
                passed_checks.append("SSL/HTTPS configured")

            # HTTP headers check
            header_issues, header_metrics = self._check_response_headers(url)
            all_issues.extend(header_issues)
            all_metrics.update(header_metrics)
            if header_metrics.get("compression_enabled"):
                passed_checks.append("Compression enabled")
            if header_metrics.get("hsts_enabled"):
                passed_checks.append("HSTS configured")

            # Fetch page with SeleniumBase UC
            html = None
            use_http_fallback = False

            try:
                with self.browser_session("generic") as driver:
                    start_time = time.time()

                    html = self.fetch_page(
                        driver=driver,
                        url=url,
                        wait_for_selector="body",
                        wait_timeout=20,
                        extra_wait=1.0,
                    )

                    load_time = time.time() - start_time
                    all_metrics["load_time_seconds"] = round(load_time, 2)

                    if load_time > 5:
                        all_issues.append(AuditIssue(
                            category=IssueCategory.PERFORMANCE.value,
                            severity=IssueSeverity.HIGH.value,
                            issue_type="slow_page_load",
                            description=f"Page load time: {load_time:.1f}s",
                            recommendation="Optimize page load time"
                        ))
                    elif load_time < 3:
                        passed_checks.append(f"Fast page load ({load_time:.1f}s)")

            except Exception as e:
                logger.warning(f"SeleniumBase UC error for {url}: {e}")
                use_http_fallback = True

            if use_http_fallback or not html:
                logger.info(f"Using HTTP fallback for {url}")
                fallback_result = self._http_fallback_audit(url)
                if fallback_result and fallback_result[0]:
                    html, fb_metrics, fb_issues = fallback_result
                    all_metrics.update(fb_metrics)
                    all_issues.extend(fb_issues)
                else:
                    return AuditResult(
                        url=url,
                        audit_date=datetime.now(),
                        overall_score=0,
                        performance_score=0,
                        seo_score=0,
                        accessibility_score=0,
                        security_score=0,
                        issues=all_issues + [AuditIssue(
                            category=IssueCategory.TECHNICAL.value,
                            severity=IssueSeverity.CRITICAL.value,
                            issue_type="page_unreachable",
                            description="Could not load page",
                            recommendation="Check if URL is accessible"
                        )],
                        metrics=all_metrics,
                    )

            # Parse and analyze HTML
            soup = BeautifulSoup(html, 'html.parser')

            checks = [
                self._check_meta_tags(soup, url),
                self._check_headings(soup),
                self._check_images(soup, url),
                self._check_schema(soup),
                self._check_social_meta(soup),  # Open Graph + Twitter Cards
                self._check_accessibility(soup),  # WCAG 2.1 accessibility checks
            ]

            for issues, metrics in checks:
                all_issues.extend(issues)
                all_metrics.update(metrics)

            # Calculate scores
            overall, perf, seo, access, security = self._calculate_scores(all_issues, all_metrics)

            result = AuditResult(
                url=url,
                audit_date=datetime.now(),
                overall_score=overall,
                performance_score=perf,
                seo_score=seo,
                accessibility_score=access,
                security_score=security,
                issues=all_issues,
                metrics=all_metrics,
                passed_checks=passed_checks,
            )

            logger.info(f"Audit complete: {url} - Score: {overall:.0f} ({len(all_issues)} issues)")

            return result

        except Exception as e:
            logger.error(f"Error auditing {url}: {e}", exc_info=True)
            return AuditResult(
                url=url,
                audit_date=datetime.now(),
                overall_score=0,
                performance_score=0,
                seo_score=0,
                accessibility_score=0,
                security_score=0,
                issues=[AuditIssue(
                    category=IssueCategory.TECHNICAL.value,
                    severity=IssueSeverity.CRITICAL.value,
                    issue_type="audit_error",
                    description=str(e),
                    recommendation="Check URL and try again"
                )],
                metrics=all_metrics,
            )

    def run(self, urls: List[str]) -> Dict[str, Any]:
        """Run technical audit for multiple URLs."""
        results = {
            "total_urls": len(urls),
            "successful": 0,
            "failed": 0,
            "average_score": 0.0,
        }

        scores = []

        for url in urls:
            result = self.audit_page(url)
            if result.overall_score > 0:
                results["successful"] += 1
                scores.append(result.overall_score)
            else:
                results["failed"] += 1

        if scores:
            results["average_score"] = sum(scores) / len(scores)

        return results

    def save_audit_to_db(
        self,
        result: AuditResult,
        company_id: Optional[int] = None,
    ) -> Optional[int]:
        """Save audit result to database.

        Args:
            result: The AuditResult from audit_page()
            company_id: Optional company ID to associate with the audit

        Returns:
            The audit_id if saved successfully, None otherwise
        """
        if not self.engine:
            logger.warning("No database engine configured, skipping DB save")
            return None

        try:
            with Session(self.engine) as session:
                # Insert main audit record
                insert_result = session.execute(
                    text("""
                        INSERT INTO technical_audits (
                            url, company_id, overall_score, audit_type,
                            lcp_ms, fid_ms, cls_value, fcp_ms, ttfb_ms, tti_ms,
                            cwv_score, lcp_rating, cls_rating, fid_rating,
                            page_load_time_ms, page_size_kb, total_requests,
                            metadata, audited_at
                        ) VALUES (
                            :url, :company_id, :overall_score, :audit_type,
                            :lcp_ms, :fid_ms, :cls_value, :fcp_ms, :ttfb_ms, :tti_ms,
                            :cwv_score, :lcp_rating, :cls_rating, :fid_rating,
                            :page_load_time_ms, :page_size_kb, :total_requests,
                            :metadata, :audited_at
                        ) RETURNING audit_id
                    """),
                    {
                        "url": result.url,
                        "company_id": company_id,
                        "overall_score": int(result.overall_score),
                        "audit_type": "technical",
                        "lcp_ms": result.metrics.get("lcp_ms"),
                        "fid_ms": result.metrics.get("fid_ms"),
                        "cls_value": result.metrics.get("cls_value"),
                        "fcp_ms": result.metrics.get("fcp_ms"),
                        "ttfb_ms": result.metrics.get("ttfb_ms"),
                        "tti_ms": result.metrics.get("tti_ms"),
                        "cwv_score": result.metrics.get("cwv_score"),
                        "lcp_rating": result.metrics.get("lcp_rating"),
                        "cls_rating": result.metrics.get("cls_rating"),
                        "fid_rating": result.metrics.get("fid_rating"),
                        "page_load_time_ms": result.metrics.get("page_load_time_ms"),
                        "page_size_kb": result.metrics.get("page_size_kb"),
                        "total_requests": result.metrics.get("total_requests"),
                        "metadata": json.dumps(result.metrics),
                        "audited_at": result.audit_date,
                    }
                )

                audit_id = insert_result.fetchone()[0]

                # Insert individual issues
                for issue in result.issues:
                    session.execute(
                        text("""
                            INSERT INTO technical_audit_issues (
                                audit_id, category, issue_type, severity,
                                description, element, recommendation, metadata
                            ) VALUES (
                                :audit_id, :category, :issue_type, :severity,
                                :description, :element, :recommendation, :metadata
                            )
                        """),
                        {
                            "audit_id": audit_id,
                            "category": issue.category,
                            "issue_type": issue.issue_type,
                            "severity": issue.severity,
                            "description": issue.description,
                            "element": issue.affected_element,
                            "recommendation": issue.recommendation,
                            "metadata": json.dumps(issue.metadata) if issue.metadata else None,
                        }
                    )

                session.commit()
                logger.info(f"Saved audit {audit_id} for {result.url} with {len(result.issues)} issues")
                return audit_id

        except Exception as e:
            logger.error(f"Failed to save audit to DB: {e}")
            return None


# Singleton
_auditor_instance = None

def get_technical_auditor_selenium(**kwargs) -> TechnicalAuditorSelenium:
    """Get singleton TechnicalAuditorSelenium instance."""
    global _auditor_instance
    if _auditor_instance is None:
        _auditor_instance = TechnicalAuditorSelenium(**kwargs)
    return _auditor_instance


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        auditor = get_technical_auditor_selenium()
        result = auditor.audit_page(sys.argv[1])
        print(f"\nAudit: {sys.argv[1]}")
        print(f"Score: {result.overall_score:.0f}/100")
        print(f"Issues: {len(result.issues)}")
    else:
        print("Usage: python technical_auditor_selenium.py <url>")

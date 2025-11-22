"""
Technical Auditor Module

Performs technical SEO audits on websites.

Features:
- SSL/HTTPS verification
- Page load performance metrics
- Mobile-friendliness checks
- SEO basics (title, meta, headings)
- Accessibility issues detection
- Broken link checking
- Schema.org validation
- Core Web Vitals estimation

Stores results in page_audits and audit_issues tables.
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

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.scrapers.base_scraper import BaseScraper
from seo_intelligence.services import get_task_logger, get_change_manager
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("technical_auditor")


class IssueSeverity(Enum):
    """Severity levels for audit issues."""
    CRITICAL = "critical"    # Blocks SEO completely
    HIGH = "high"            # Significant SEO impact
    MEDIUM = "medium"        # Moderate impact
    LOW = "low"              # Minor improvement opportunity
    INFO = "info"            # Informational only


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
    overall_score: float  # 0-100
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


class TechnicalAuditor(BaseScraper):
    """
    Technical SEO auditor for websites.

    Performs comprehensive audits covering security, performance,
    SEO, accessibility, and mobile-friendliness.
    """

    def __init__(
        self,
        headless: bool = True,
        use_proxy: bool = False,  # Don't use proxy for own site audits
    ):
        """
        Initialize technical auditor.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool (typically False for own sites)
        """
        super().__init__(
            name="technical_auditor",
            tier="D",  # Faster rate limits for own properties
            headless=headless,
            respect_robots=False,  # Can audit own sites regardless
            use_proxy=use_proxy,
            max_retries=2,
            page_timeout=20000,  # Reduced from 45s to 20s
        )

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info("TechnicalAuditor initialized (tier=D)")

    def _http_fallback_audit(self, url: str) -> Optional[Tuple[str, Dict[str, Any], List[AuditIssue]]]:
        """
        Simple HTTP fallback when Playwright fails.
        Returns (html_content, metrics, issues) or None if also fails.
        """
        issues = []
        metrics = {"fallback_mode": True}

        try:
            start_time = time.time()
            response = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                verify=True,
                allow_redirects=True,
            )
            load_time = time.time() - start_time

            metrics["http_status"] = response.status_code
            metrics["load_time_seconds"] = round(load_time, 2)
            metrics["content_length"] = len(response.text)
            metrics["redirect_count"] = len(response.history)

            # Check response time
            if load_time > 5:
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.HIGH.value,
                    issue_type="slow_response",
                    description=f"Slow response time: {load_time:.1f}s",
                    recommendation="Optimize server response time"
                ))

            # Check HTTP status
            if response.status_code >= 400:
                issues.append(AuditIssue(
                    category=IssueCategory.TECHNICAL.value,
                    severity=IssueSeverity.CRITICAL.value,
                    issue_type="http_error",
                    description=f"HTTP {response.status_code} error",
                    recommendation="Fix server error"
                ))

            # Check for redirect chains
            if len(response.history) > 2:
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="redirect_chain",
                    description=f"Redirect chain of {len(response.history)} hops",
                    recommendation="Minimize redirect chains"
                ))

            logger.info(f"HTTP fallback succeeded for {url} (status={response.status_code})")
            return response.text, metrics, issues

        except requests.exceptions.SSLError as e:
            issues.append(AuditIssue(
                category=IssueCategory.SECURITY.value,
                severity=IssueSeverity.CRITICAL.value,
                issue_type="ssl_error",
                description=f"SSL certificate error: {str(e)[:100]}",
                recommendation="Fix SSL certificate configuration"
            ))
            logger.warning(f"SSL error for {url}: {e}")
            return None, metrics, issues

        except requests.exceptions.Timeout:
            logger.warning(f"HTTP fallback timeout for {url}")
            return None, metrics, issues

        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP fallback failed for {url}: {e}")
            return None, metrics, issues

    def _check_ssl(self, url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check SSL/HTTPS configuration."""
        issues = []
        metrics = {"has_ssl": False, "redirects_to_https": False}

        parsed = urlparse(url)

        # Check if using HTTPS
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

    def _check_meta_tags(
        self,
        soup,
        url: str,
    ) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check meta tags for SEO."""
        from bs4 import BeautifulSoup

        issues = []
        metrics = {}

        # Check title
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
                    affected_element=title_text[:50],
                    recommendation="Title should be 50-60 characters"
                ))
            elif len(title_text) > 60:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="title_too_long",
                    description=f"Title tag too long ({len(title_text)} chars)",
                    affected_element=title_text[:50] + "...",
                    recommendation="Title should be 50-60 characters"
                ))
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.CRITICAL.value,
                issue_type="missing_title",
                description="Missing title tag",
                recommendation="Add a unique, descriptive title tag"
            ))

        # Check meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            desc_text = meta_desc.get('content', '')
            metrics["meta_description"] = desc_text
            metrics["meta_description_length"] = len(desc_text)

            if len(desc_text) < 120:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="meta_desc_too_short",
                    description=f"Meta description too short ({len(desc_text)} chars)",
                    recommendation="Meta description should be 150-160 characters"
                ))
            elif len(desc_text) > 160:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="meta_desc_too_long",
                    description=f"Meta description too long ({len(desc_text)} chars)",
                    recommendation="Meta description should be 150-160 characters"
                ))
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_meta_description",
                description="Missing meta description",
                recommendation="Add a compelling meta description"
            ))

        # Check canonical
        canonical = soup.find('link', rel='canonical')
        if canonical:
            metrics["canonical_url"] = canonical.get('href', '')
        else:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="missing_canonical",
                description="Missing canonical tag",
                recommendation="Add canonical tag to prevent duplicate content"
            ))

        # Check viewport
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        if viewport:
            metrics["has_viewport"] = True
        else:
            issues.append(AuditIssue(
                category=IssueCategory.MOBILE.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_viewport",
                description="Missing viewport meta tag",
                recommendation="Add viewport meta tag for mobile responsiveness"
            ))

        return issues, metrics

    def _check_headings(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check heading structure."""
        issues = []
        metrics = {}

        # Find all H1s
        h1_tags = soup.find_all('h1')
        metrics["h1_count"] = len(h1_tags)
        metrics["h1_tags"] = [h.get_text(strip=True)[:100] for h in h1_tags[:5]]

        if len(h1_tags) == 0:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.HIGH.value,
                issue_type="missing_h1",
                description="Page has no H1 tag",
                recommendation="Add one H1 tag containing primary keyword"
            ))
        elif len(h1_tags) > 1:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.LOW.value,
                issue_type="multiple_h1",
                description=f"Page has {len(h1_tags)} H1 tags",
                recommendation="Use only one H1 tag per page"
            ))

        # Check H2s
        h2_tags = soup.find_all('h2')
        metrics["h2_count"] = len(h2_tags)

        if len(h2_tags) == 0:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.LOW.value,
                issue_type="missing_h2",
                description="Page has no H2 tags",
                recommendation="Add H2 tags to structure content"
            ))

        return issues, metrics

    def _check_images(self, soup, base_url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check images for alt text and optimization."""
        issues = []
        metrics = {}

        images = soup.find_all('img')
        metrics["total_images"] = len(images)

        missing_alt = []
        empty_alt = []

        for img in images:
            src = img.get('src', '')
            alt = img.get('alt')

            if alt is None:
                missing_alt.append(src[:50])
            elif alt.strip() == '':
                empty_alt.append(src[:50])

        metrics["images_missing_alt"] = len(missing_alt)
        metrics["images_empty_alt"] = len(empty_alt)
        metrics["images_with_alt"] = len(images) - len(missing_alt) - len(empty_alt)

        if missing_alt:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="images_missing_alt",
                description=f"{len(missing_alt)} images missing alt attribute",
                affected_element=", ".join(missing_alt[:3]),
                recommendation="Add descriptive alt text to all images"
            ))

        return issues, metrics

    def _check_links(self, soup, base_url: str) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check internal and external links."""
        issues = []
        metrics = {}

        base_domain = urlparse(base_url).netloc
        links = soup.find_all('a', href=True)

        internal = 0
        external = 0
        nofollow = 0
        empty_links = 0

        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)

            if not href or href.startswith('#'):
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            if parsed.netloc == base_domain or not parsed.netloc:
                internal += 1
            else:
                external += 1

            rel = link.get('rel', [])
            if 'nofollow' in rel:
                nofollow += 1

            if not text.strip():
                empty_links += 1

        metrics["internal_links"] = internal
        metrics["external_links"] = external
        metrics["nofollow_links"] = nofollow
        metrics["empty_links"] = empty_links

        if empty_links > 0:
            issues.append(AuditIssue(
                category=IssueCategory.ACCESSIBILITY.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="empty_link_text",
                description=f"{empty_links} links have empty or missing text",
                recommendation="Add descriptive text to all links"
            ))

        return issues, metrics

    def _check_schema(self, soup) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Check schema.org structured data."""
        issues = []
        metrics = {}

        schemas = []
        schema_types = set()

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                content = script.string
                if content:
                    data = json.loads(content)
                    schemas.append(data)

                    def extract_types(obj):
                        if isinstance(obj, dict):
                            if '@type' in obj:
                                t = obj['@type']
                                if isinstance(t, list):
                                    schema_types.update(t)
                                else:
                                    schema_types.add(t)
                            for v in obj.values():
                                extract_types(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                extract_types(item)

                    extract_types(data)
            except json.JSONDecodeError:
                issues.append(AuditIssue(
                    category=IssueCategory.TECHNICAL.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="invalid_schema_json",
                    description="Invalid JSON-LD schema markup",
                    recommendation="Fix JSON syntax in structured data"
                ))

        metrics["schema_count"] = len(schemas)
        metrics["schema_types"] = list(schema_types)

        if not schemas:
            issues.append(AuditIssue(
                category=IssueCategory.SEO.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="missing_schema",
                description="No schema.org structured data found",
                recommendation="Add LocalBusiness schema for better search visibility"
            ))
        else:
            # Check for recommended schema types for local business
            recommended = {'LocalBusiness', 'Organization', 'WebSite'}
            if not schema_types & recommended:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_business_schema",
                    description="Missing LocalBusiness or Organization schema",
                    recommendation="Add LocalBusiness schema with NAP information"
                ))

        return issues, metrics

    def _check_performance(
        self,
        page,
        soup,
    ) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """Estimate performance metrics."""
        issues = []
        metrics = {}

        # Count resources
        scripts = soup.find_all('script', src=True)
        stylesheets = soup.find_all('link', rel='stylesheet')
        images = soup.find_all('img')

        metrics["script_count"] = len(scripts)
        metrics["stylesheet_count"] = len(stylesheets)
        metrics["image_count"] = len(images)

        # Check for render-blocking resources
        render_blocking = 0
        for script in scripts:
            if not script.get('async') and not script.get('defer'):
                render_blocking += 1

        metrics["render_blocking_scripts"] = render_blocking

        if render_blocking > 3:
            issues.append(AuditIssue(
                category=IssueCategory.PERFORMANCE.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="render_blocking_scripts",
                description=f"{render_blocking} render-blocking scripts",
                recommendation="Add async or defer to non-critical scripts"
            ))

        # Check for large page (basic heuristic)
        page_size = len(str(soup))
        metrics["html_size"] = page_size

        if page_size > 500000:  # 500KB
            issues.append(AuditIssue(
                category=IssueCategory.PERFORMANCE.value,
                severity=IssueSeverity.MEDIUM.value,
                issue_type="large_html",
                description=f"Large HTML size ({page_size // 1000}KB)",
                recommendation="Optimize and minify HTML content"
            ))

        return issues, metrics

    def _calculate_scores(
        self,
        issues: List[AuditIssue],
        metrics: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float]:
        """Calculate audit scores from issues."""
        # Start with perfect scores
        security_score = 100.0
        seo_score = 100.0
        accessibility_score = 100.0
        performance_score = 100.0

        # Deductions by severity
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
                # Mobile affects both SEO and accessibility
                seo_score = max(0, seo_score - deduction / 2)
                accessibility_score = max(0, accessibility_score - deduction / 2)

        # Overall weighted score
        overall = (
            security_score * 0.15 +
            seo_score * 0.40 +
            accessibility_score * 0.20 +
            performance_score * 0.25
        )

        return overall, performance_score, seo_score, accessibility_score, security_score

    def _save_audit(
        self,
        session: Session,
        result: AuditResult,
    ) -> int:
        """Save audit result to database."""
        # Prepare extended metadata with all scores
        extended_metadata = {
            **result.metrics,
            "performance_score": result.performance_score,
            "seo_score": result.seo_score,
            "accessibility_score": result.accessibility_score,
            "security_score": result.security_score,
            "issues_count": len(result.issues),
            "critical_count": len(result.critical_issues),
            "high_count": len(result.high_issues),
        }

        # Insert page audit - using actual table schema
        audit_result = session.execute(
            text("""
                INSERT INTO page_audits (
                    url, audit_type, overall_score, page_load_time_ms,
                    page_size_kb, total_requests, metadata
                ) VALUES (
                    :url, 'technical', :overall_score, :page_load_time_ms,
                    :page_size_kb, :total_requests, CAST(:audit_metadata AS jsonb)
                )
                RETURNING audit_id
            """),
            {
                "url": result.url,
                "overall_score": result.overall_score,
                "page_load_time_ms": int(result.metrics.get("load_time_seconds", 0) * 1000),
                "page_size_kb": result.metrics.get("html_size", 0) // 1024,
                "total_requests": result.metrics.get("script_count", 0) + result.metrics.get("stylesheet_count", 0),
                "audit_metadata": json.dumps(extended_metadata),
            }
        )
        audit_id = audit_result.fetchone()[0]

        # Insert individual issues
        for issue in result.issues:
            session.execute(
                text("""
                    INSERT INTO audit_issues (
                        audit_id, category, severity, issue_type,
                        description, element, recommendation, metadata
                    ) VALUES (
                        :audit_id, :category, :severity, :issue_type,
                        :description, :element, :recommendation, CAST(:issue_metadata AS jsonb)
                    )
                """),
                {
                    "audit_id": audit_id,
                    "category": issue.category,
                    "severity": issue.severity,
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                    "element": issue.affected_element[:500] if issue.affected_element else "",
                    "recommendation": issue.recommendation,
                    "issue_metadata": json.dumps(issue.metadata),
                }
            )

        # Propose fixes for critical/high severity actionable issues
        # Define issue types that can be automatically fixed or flagged for review
        actionable_issue_types = [
            'http_only',                # HTTP → HTTPS redirect
            'missing_canonical',         # Add canonical tag
            'missing_meta_description',  # Generate meta description
            'missing_alt_text',          # Flag for content team
            'broken_link',               # Update or remove link
            'missing_viewport',          # Add viewport meta tag
            'missing_h1',                # Add H1 tag
            'duplicate_h1',              # Fix duplicate H1s
        ]

        critical_high_issues = [
            issue for issue in result.issues
            if issue.severity in ['critical', 'high'] and issue.issue_type in actionable_issue_types
        ]

        if critical_high_issues:
            try:
                change_manager = get_change_manager()
                for issue in critical_high_issues:
                    # Propose change for each actionable issue
                    change_manager.propose_change(
                        change_type='audit_fix',
                        entity_type='page',
                        entity_id=result.url,
                        proposed_value={
                            'fix': issue.issue_type,
                            'element': issue.affected_element[:200] if issue.affected_element else None,
                            'recommendation': issue.recommendation
                        },
                        current_value={
                            'issue': issue.description,
                            'severity': issue.severity,
                            'category': issue.category
                        },
                        reason=f"{issue.severity.upper()}: {issue.description}",
                        priority='high' if issue.severity == 'critical' else 'medium',
                        source='technical_auditor',
                        metadata={
                            'audit_id': audit_id,
                            'issue_type': issue.issue_type,
                            'category': issue.category,
                            'url': result.url
                        }
                    )
                    logger.info(f"Proposed change for {issue.issue_type} on {result.url}")
            except Exception as e:
                logger.error(f"Error proposing changes for audit {audit_id}: {e}")

        session.commit()
        return audit_id

    def audit_page(self, url: str) -> AuditResult:
        """
        Perform technical audit on a single page.

        Args:
            url: URL to audit

        Returns:
            AuditResult with findings
        """
        from bs4 import BeautifulSoup

        logger.info(f"Auditing {url}")

        all_issues = []
        all_metrics = {}
        passed_checks = []

        try:
            # SSL check first
            ssl_issues, ssl_metrics = self._check_ssl(url)
            all_issues.extend(ssl_issues)
            all_metrics.update(ssl_metrics)
            if not ssl_issues:
                passed_checks.append("SSL/HTTPS configured")

            # Fetch page - try Playwright first, fall back to HTTP if in asyncio loop
            html = None
            page = None
            use_http_fallback = False

            try:
                with self.browser_session() as (browser, context, page):
                    start_time = time.time()

                    html = self.fetch_page(
                        url=url,
                        page=page,
                        wait_for="domcontentloaded",  # Changed from networkidle - faster
                        extra_wait=0.5,
                    )

                    load_time = time.time() - start_time
                    all_metrics["load_time_seconds"] = round(load_time, 2)

                    if load_time > 5:
                        all_issues.append(AuditIssue(
                            category=IssueCategory.PERFORMANCE.value,
                            severity=IssueSeverity.HIGH.value,
                            issue_type="slow_page_load",
                            description=f"Page load time: {load_time:.1f}s",
                            recommendation="Optimize page load time to under 3 seconds"
                        ))
                    elif load_time < 3:
                        passed_checks.append(f"Fast page load ({load_time:.1f}s)")
            except Exception as pw_error:
                # Playwright can't run in asyncio loop (NiceGUI dashboard)
                if "asyncio" in str(pw_error).lower():
                    logger.info(f"Playwright unavailable in async context, using HTTP for {url}")
                    use_http_fallback = True
                else:
                    logger.warning(f"Playwright error for {url}: {pw_error}")
                    use_http_fallback = True

            if use_http_fallback or not html:
                # Use HTTP fallback
                logger.info(f"Using HTTP fallback for {url}")
                fallback_result = self._http_fallback_audit(url)
                if fallback_result and fallback_result[0]:
                    html, fb_metrics, fb_issues = fallback_result
                    all_metrics.update(fb_metrics)
                    all_issues.extend(fb_issues)
                else:
                    # HTTP fallback failed
                    if fallback_result:
                        _, fb_metrics, fb_issues = fallback_result
                        all_metrics.update(fb_metrics)
                        all_issues.extend(fb_issues)
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
                            description="Could not load page (HTTP fallback failed)",
                            recommendation="Check if URL is accessible"
                        )],
                        metrics=all_metrics,
                    )

            soup = BeautifulSoup(html, 'html.parser')

            # Run all checks (skip page-dependent checks if using HTTP fallback)
            checks = [
                self._check_meta_tags(soup, url),
                self._check_headings(soup),
                self._check_images(soup, url),
                self._check_links(soup, url),
                self._check_schema(soup),
            ]

            # Only run performance check if we have a Playwright page
            if page and not use_http_fallback:
                checks.append(self._check_performance(page, soup))

            for issues, metrics in checks:
                all_issues.extend(issues)
                all_metrics.update(metrics)

            # Calculate scores
            overall, perf, seo, access, security = self._calculate_scores(
                all_issues, all_metrics
            )

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

            # Save to database
            if self.engine:
                with Session(self.engine) as session:
                    self._save_audit(session, result)

            logger.info(
                f"Audit complete: {url} - Score: {overall:.0f} "
                f"({len(all_issues)} issues found)"
            )

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
        """
        Run technical audit for multiple URLs.

        Args:
            urls: List of URLs to audit

        Returns:
            dict: Results summary
        """
        task_logger = get_task_logger()

        results = {
            "total_urls": len(urls),
            "successful": 0,
            "failed": 0,
            "average_score": 0.0,
            "critical_issues": 0,
            "high_issues": 0,
        }

        scores = []

        with task_logger.log_task("technical_auditor", "audit", {"url_count": len(urls)}) as task:
            for url in urls:
                task.increment_processed()

                result = self.audit_page(url)

                if result.overall_score > 0:
                    results["successful"] += 1
                    scores.append(result.overall_score)
                    results["critical_issues"] += len(result.critical_issues)
                    results["high_issues"] += len(result.high_issues)
                    task.increment_created()
                else:
                    results["failed"] += 1

        if scores:
            results["average_score"] = sum(scores) / len(scores)

        logger.info(
            f"Audit run complete: {results['successful']}/{results['total_urls']} "
            f"pages, avg score: {results['average_score']:.0f}"
        )

        return results


# Module-level singleton
_technical_auditor_instance = None


def get_technical_auditor(**kwargs) -> TechnicalAuditor:
    """Get or create the singleton TechnicalAuditor instance."""
    global _technical_auditor_instance

    if _technical_auditor_instance is None:
        _technical_auditor_instance = TechnicalAuditor(**kwargs)

    return _technical_auditor_instance


def main():
    """Demo/CLI interface for technical auditor."""
    import argparse

    parser = argparse.ArgumentParser(description="Technical SEO Auditor")
    parser.add_argument("url", nargs="?", help="URL to audit")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")

    args = parser.parse_args()

    if args.demo:
        logger.info("=" * 60)
        logger.info("Technical SEO Auditor Demo")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Checks performed:")
        logger.info("  - SSL/HTTPS configuration")
        logger.info("  - Meta tags (title, description, canonical)")
        logger.info("  - Heading structure (H1, H2)")
        logger.info("  - Image optimization (alt text)")
        logger.info("  - Link analysis")
        logger.info("  - Schema.org markup")
        logger.info("  - Performance indicators")
        logger.info("")
        logger.info("Example usage:")
        logger.info("  python technical_auditor.py 'https://example.com'")
        logger.info("")
        logger.info("=" * 60)
        return

    if not args.url:
        parser.print_help()
        return

    auditor = get_technical_auditor()
    result = auditor.audit_page(args.url)

    logger.info("")
    logger.info(f"Audit Results for {args.url}")
    logger.info("=" * 60)
    logger.info(f"Overall Score: {result.overall_score:.0f}/100")
    logger.info(f"  Performance: {result.performance_score:.0f}")
    logger.info(f"  SEO: {result.seo_score:.0f}")
    logger.info(f"  Accessibility: {result.accessibility_score:.0f}")
    logger.info(f"  Security: {result.security_score:.0f}")
    logger.info("")
    logger.info(f"Issues Found: {len(result.issues)}")
    logger.info(f"  Critical: {len(result.critical_issues)}")
    logger.info(f"  High: {len(result.high_issues)}")
    logger.info("")

    if result.issues:
        logger.info("Top Issues:")
        for issue in result.issues[:5]:
            logger.info(f"  [{issue.severity.upper()}] {issue.description}")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()

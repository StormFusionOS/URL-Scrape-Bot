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
- HTTP Response Header Analysis:
  - Cache-Control, ETag, Content-Encoding
  - X-Robots-Tag, HSTS, Content-Security-Policy
  - Redirect chain analysis
  - Security headers audit

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
from seo_intelligence.services import get_task_logger, get_change_manager, get_cwv_metrics_service
from seo_intelligence.scrapers.core_web_vitals import CoreWebVitalsCollector, get_cwv_collector
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
        headless: bool = True,  # Hybrid mode: starts headless, upgrades to headed on detection
        use_proxy: bool = False,  # Don't use proxy for own site audits
        tier: str = "C",  # Tier C for external sites (moderate delays), D for own sites
    ):
        """
        Initialize technical auditor with stealth features.

        Args:
            headless: Run browser in headless mode
            use_proxy: Use proxy pool (typically False for own sites)
            tier: Rate limiting tier (A=slowest/safest, D=fastest). Use C for external sites.
        """
        super().__init__(
            name="technical_auditor",
            tier=tier,  # Configurable tier - use C for external sites to avoid detection
            headless=headless,
            respect_robots=False,  # Can audit own sites regardless
            use_proxy=use_proxy,
            max_retries=2,
            page_timeout=25000,  # Slightly longer timeout for external sites
        )

        # Store tier for logging
        self._tier = tier

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database storage disabled")

        logger.info(f"TechnicalAuditor initialized (tier={tier}, stealth features enabled via BaseScraper)")

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

    def _check_response_headers(
        self,
        url: str,
        timeout: int = 15,
    ) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """
        Check HTTP response headers for SEO and security best practices.

        Analyzes:
        - Cache-Control, ETag, Content-Encoding (performance)
        - X-Robots-Tag (SEO directives)
        - HSTS, CSP, X-Frame-Options (security)
        - Redirect chains (performance/SEO)

        Args:
            url: URL to check
            timeout: Request timeout in seconds

        Returns:
            Tuple of (issues, metrics) with header analysis
        """
        issues = []
        metrics = {
            "headers_checked": True,
            "headers": {},
        }

        try:
            # Make request with redirects tracked
            response = requests.get(
                url,
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                allow_redirects=True,
                verify=True,
            )

            headers = response.headers
            metrics["final_status_code"] = response.status_code

            # ============================================
            # 1. REDIRECT CHAIN ANALYSIS
            # ============================================
            redirect_chain = []
            for resp in response.history:
                redirect_chain.append({
                    "url": resp.url,
                    "status": resp.status_code,
                    "location": resp.headers.get("Location", ""),
                })

            metrics["redirect_count"] = len(redirect_chain)
            metrics["redirect_chain"] = redirect_chain

            if len(redirect_chain) > 2:
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="long_redirect_chain",
                    description=f"Long redirect chain ({len(redirect_chain)} hops)",
                    affected_element=" -> ".join(r["url"][:50] for r in redirect_chain[:3]),
                    recommendation="Minimize redirect chains to 1-2 hops maximum",
                    metadata={"redirect_count": len(redirect_chain)}
                ))
            elif len(redirect_chain) == 0:
                metrics["no_redirects"] = True

            # Check for HTTP->HTTPS redirect
            if redirect_chain:
                first_url = redirect_chain[0]["url"]
                if first_url.startswith("http://") and response.url.startswith("https://"):
                    metrics["http_to_https_redirect"] = True

            # ============================================
            # 2. CACHE-CONTROL ANALYSIS
            # ============================================
            cache_control = headers.get("Cache-Control", "")
            metrics["headers"]["cache_control"] = cache_control

            if cache_control:
                # Parse directives
                directives = [d.strip().lower() for d in cache_control.split(",")]
                metrics["cache_directives"] = directives

                # Check for no-cache/no-store on cacheable pages
                if "no-store" in directives or "no-cache" in directives:
                    issues.append(AuditIssue(
                        category=IssueCategory.PERFORMANCE.value,
                        severity=IssueSeverity.LOW.value,
                        issue_type="no_cache_header",
                        description="Cache-Control prevents caching (no-store/no-cache)",
                        affected_element=cache_control[:100],
                        recommendation="Enable caching for static resources to improve performance",
                        metadata={"cache_control": cache_control}
                    ))

                # Check max-age
                for directive in directives:
                    if directive.startswith("max-age="):
                        try:
                            max_age = int(directive.split("=")[1])
                            metrics["cache_max_age_seconds"] = max_age
                            if max_age < 3600:  # Less than 1 hour
                                issues.append(AuditIssue(
                                    category=IssueCategory.PERFORMANCE.value,
                                    severity=IssueSeverity.INFO.value,
                                    issue_type="short_cache_duration",
                                    description=f"Short cache duration ({max_age}s)",
                                    recommendation="Consider longer cache durations for static content",
                                ))
                        except ValueError:
                            pass
            else:
                # No cache-control header
                issues.append(AuditIssue(
                    category=IssueCategory.PERFORMANCE.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_cache_control",
                    description="Missing Cache-Control header",
                    recommendation="Add Cache-Control header to optimize repeat visits",
                ))

            # ============================================
            # 3. ETAG ANALYSIS
            # ============================================
            etag = headers.get("ETag", "")
            metrics["headers"]["etag"] = etag if etag else None
            metrics["has_etag"] = bool(etag)

            # ============================================
            # 4. CONTENT-ENCODING (COMPRESSION)
            # ============================================
            content_encoding = headers.get("Content-Encoding", "")
            metrics["headers"]["content_encoding"] = content_encoding if content_encoding else None

            if content_encoding:
                metrics["compression_enabled"] = True
                metrics["compression_type"] = content_encoding
            else:
                # Check content type - only flag for text-based content
                content_type = headers.get("Content-Type", "")
                if any(t in content_type.lower() for t in ["text/html", "text/css", "text/javascript", "application/javascript", "application/json"]):
                    issues.append(AuditIssue(
                        category=IssueCategory.PERFORMANCE.value,
                        severity=IssueSeverity.MEDIUM.value,
                        issue_type="missing_compression",
                        description="No compression enabled (gzip/br)",
                        affected_element=f"Content-Type: {content_type[:50]}",
                        recommendation="Enable gzip or Brotli compression to reduce transfer size",
                    ))

            # ============================================
            # 5. X-ROBOTS-TAG (SEO)
            # ============================================
            x_robots = headers.get("X-Robots-Tag", "")
            metrics["headers"]["x_robots_tag"] = x_robots if x_robots else None

            if x_robots:
                x_robots_lower = x_robots.lower()
                metrics["x_robots_directives"] = x_robots

                # Check for blocking directives
                if "noindex" in x_robots_lower:
                    issues.append(AuditIssue(
                        category=IssueCategory.SEO.value,
                        severity=IssueSeverity.HIGH.value,
                        issue_type="x_robots_noindex",
                        description="X-Robots-Tag: noindex blocks indexing",
                        affected_element=x_robots,
                        recommendation="Remove noindex from X-Robots-Tag if page should be indexed",
                        metadata={"x_robots_tag": x_robots}
                    ))

                if "nofollow" in x_robots_lower:
                    issues.append(AuditIssue(
                        category=IssueCategory.SEO.value,
                        severity=IssueSeverity.MEDIUM.value,
                        issue_type="x_robots_nofollow",
                        description="X-Robots-Tag: nofollow prevents link following",
                        affected_element=x_robots,
                        recommendation="Remove nofollow if links should pass PageRank",
                    ))

                if "none" in x_robots_lower:
                    issues.append(AuditIssue(
                        category=IssueCategory.SEO.value,
                        severity=IssueSeverity.CRITICAL.value,
                        issue_type="x_robots_none",
                        description="X-Robots-Tag: none blocks all crawling",
                        affected_element=x_robots,
                        recommendation="Remove 'none' directive to allow indexing and crawling",
                    ))

            # ============================================
            # 6. HSTS (HTTP Strict Transport Security)
            # ============================================
            hsts = headers.get("Strict-Transport-Security", "")
            metrics["headers"]["hsts"] = hsts if hsts else None

            if response.url.startswith("https://"):
                if hsts:
                    metrics["hsts_enabled"] = True
                    # Parse max-age
                    if "max-age=" in hsts.lower():
                        try:
                            max_age_match = re.search(r'max-age=(\d+)', hsts, re.IGNORECASE)
                            if max_age_match:
                                hsts_max_age = int(max_age_match.group(1))
                                metrics["hsts_max_age"] = hsts_max_age
                                # Recommended: at least 1 year (31536000)
                                if hsts_max_age < 31536000:
                                    issues.append(AuditIssue(
                                        category=IssueCategory.SECURITY.value,
                                        severity=IssueSeverity.LOW.value,
                                        issue_type="hsts_short_duration",
                                        description=f"HSTS max-age is short ({hsts_max_age}s)",
                                        recommendation="Set HSTS max-age to at least 31536000 (1 year)",
                                    ))
                        except ValueError:
                            pass

                    # Check for includeSubDomains and preload
                    metrics["hsts_include_subdomains"] = "includesubdomains" in hsts.lower()
                    metrics["hsts_preload"] = "preload" in hsts.lower()
                else:
                    issues.append(AuditIssue(
                        category=IssueCategory.SECURITY.value,
                        severity=IssueSeverity.MEDIUM.value,
                        issue_type="missing_hsts",
                        description="Missing HSTS header on HTTPS site",
                        recommendation="Add Strict-Transport-Security header to enforce HTTPS",
                    ))

            # ============================================
            # 7. CONTENT-SECURITY-POLICY (CSP)
            # ============================================
            csp = headers.get("Content-Security-Policy", "")
            csp_report = headers.get("Content-Security-Policy-Report-Only", "")
            metrics["headers"]["csp"] = csp if csp else None
            metrics["headers"]["csp_report_only"] = csp_report if csp_report else None

            if csp or csp_report:
                metrics["csp_enabled"] = True
            else:
                issues.append(AuditIssue(
                    category=IssueCategory.SECURITY.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_csp",
                    description="Missing Content-Security-Policy header",
                    recommendation="Add CSP header to prevent XSS and injection attacks",
                ))

            # ============================================
            # 8. X-FRAME-OPTIONS
            # ============================================
            x_frame = headers.get("X-Frame-Options", "")
            metrics["headers"]["x_frame_options"] = x_frame if x_frame else None

            if x_frame:
                metrics["clickjacking_protection"] = True
            else:
                # CSP frame-ancestors can also provide this protection
                if not (csp and "frame-ancestors" in csp.lower()):
                    issues.append(AuditIssue(
                        category=IssueCategory.SECURITY.value,
                        severity=IssueSeverity.LOW.value,
                        issue_type="missing_x_frame_options",
                        description="Missing X-Frame-Options header",
                        recommendation="Add X-Frame-Options: DENY or SAMEORIGIN to prevent clickjacking",
                    ))

            # ============================================
            # 9. X-CONTENT-TYPE-OPTIONS
            # ============================================
            x_content_type = headers.get("X-Content-Type-Options", "")
            metrics["headers"]["x_content_type_options"] = x_content_type if x_content_type else None

            if x_content_type and "nosniff" in x_content_type.lower():
                metrics["mime_sniffing_protection"] = True
            else:
                issues.append(AuditIssue(
                    category=IssueCategory.SECURITY.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="missing_x_content_type_options",
                    description="Missing X-Content-Type-Options: nosniff",
                    recommendation="Add X-Content-Type-Options: nosniff to prevent MIME sniffing",
                ))

            # ============================================
            # 10. REFERRER-POLICY
            # ============================================
            referrer_policy = headers.get("Referrer-Policy", "")
            metrics["headers"]["referrer_policy"] = referrer_policy if referrer_policy else None

            # ============================================
            # 11. PERMISSIONS-POLICY (formerly Feature-Policy)
            # ============================================
            permissions_policy = headers.get("Permissions-Policy", "")
            feature_policy = headers.get("Feature-Policy", "")
            metrics["headers"]["permissions_policy"] = permissions_policy if permissions_policy else None
            metrics["headers"]["feature_policy"] = feature_policy if feature_policy else None

            # ============================================
            # 12. SERVER HEADER (info leak check)
            # ============================================
            server_header = headers.get("Server", "")
            metrics["headers"]["server"] = server_header if server_header else None

            if server_header:
                # Check for version disclosure
                version_pattern = re.search(r'[\d]+\.[\d]+', server_header)
                if version_pattern:
                    issues.append(AuditIssue(
                        category=IssueCategory.SECURITY.value,
                        severity=IssueSeverity.INFO.value,
                        issue_type="server_version_disclosure",
                        description=f"Server header reveals version: {server_header}",
                        recommendation="Consider hiding server version information",
                    ))

            # ============================================
            # SUMMARY METRICS
            # ============================================
            # Count security headers present
            security_headers = [
                bool(hsts),
                bool(csp) or bool(csp_report),
                bool(x_frame),
                bool(x_content_type and "nosniff" in x_content_type.lower()),
                bool(referrer_policy),
            ]
            metrics["security_headers_count"] = sum(security_headers)
            metrics["security_headers_max"] = len(security_headers)
            metrics["security_score_headers"] = round(sum(security_headers) / len(security_headers) * 100)

            logger.debug(
                f"Header analysis for {url}: "
                f"redirects={len(redirect_chain)}, "
                f"cache={bool(cache_control)}, "
                f"compression={bool(content_encoding)}, "
                f"security={metrics['security_headers_count']}/{metrics['security_headers_max']}"
            )

        except requests.exceptions.Timeout:
            logger.warning(f"Header check timeout for {url}")
            metrics["headers_error"] = "timeout"
        except requests.exceptions.SSLError as e:
            logger.warning(f"SSL error checking headers for {url}: {e}")
            metrics["headers_error"] = "ssl_error"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error checking headers for {url}: {e}")
            metrics["headers_error"] = str(e)[:100]

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

    def _check_js_rendering(
        self,
        raw_html: str,
        rendered_html: str,
    ) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """
        Analyze JavaScript rendering by comparing raw HTML vs rendered HTML.

        Detects how much content is JavaScript-dependent by measuring:
        - Content change percentage between raw and rendered
        - Ratio of text content (rendered/raw)
        - Number of links added by JavaScript
        - Whether the page is JS-dependent (>50% change)

        Args:
            raw_html: HTML content before JavaScript execution
            rendered_html: HTML content after JavaScript execution

        Returns:
            Tuple of (issues, metrics) with JS rendering analysis
        """
        from bs4 import BeautifulSoup

        issues = []
        metrics = {}

        try:
            # Parse both versions
            raw_soup = BeautifulSoup(raw_html, 'html.parser')
            rendered_soup = BeautifulSoup(rendered_html, 'html.parser')

            # Remove script/style tags for text comparison
            for soup in [raw_soup, rendered_soup]:
                for elem in soup(['script', 'style', 'noscript']):
                    elem.decompose()

            # Extract text content
            raw_text = raw_soup.get_text(separator=' ', strip=True)
            rendered_text = rendered_soup.get_text(separator=' ', strip=True)

            raw_word_count = len(raw_text.split())
            rendered_word_count = len(rendered_text.split())

            # Calculate content ratio (rendered / raw)
            if raw_word_count > 0:
                js_content_ratio = round(rendered_word_count / raw_word_count, 2)
            else:
                js_content_ratio = float('inf') if rendered_word_count > 0 else 1.0

            metrics["js_dependent_content_ratio"] = js_content_ratio
            metrics["raw_word_count"] = raw_word_count
            metrics["rendered_word_count"] = rendered_word_count

            # Calculate content change percentage
            if raw_word_count > 0:
                content_change = abs(rendered_word_count - raw_word_count) / raw_word_count * 100
            else:
                content_change = 100.0 if rendered_word_count > 0 else 0.0

            metrics["content_change_percent"] = round(content_change, 1)

            # Count links in both versions (re-parse since we decomposed elements)
            raw_soup_links = BeautifulSoup(raw_html, 'html.parser')
            rendered_soup_links = BeautifulSoup(rendered_html, 'html.parser')

            raw_links = len(raw_soup_links.find_all('a', href=True))
            rendered_links = len(rendered_soup_links.find_all('a', href=True))
            js_added_links = max(0, rendered_links - raw_links)

            metrics["raw_links"] = raw_links
            metrics["rendered_links"] = rendered_links
            metrics["js_added_links"] = js_added_links

            # Determine if page is JS-dependent
            is_js_dependent = content_change > 50 or js_content_ratio > 1.5
            metrics["is_js_dependent"] = is_js_dependent

            # Generate issues based on findings
            if is_js_dependent:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.MEDIUM.value,
                    issue_type="js_dependent_content",
                    description=f"Page is JavaScript-dependent ({content_change:.0f}% content change)",
                    recommendation="Ensure critical content is in initial HTML for SEO. Consider server-side rendering.",
                    metadata={
                        "content_change_percent": content_change,
                        "js_content_ratio": js_content_ratio,
                    }
                ))

            if js_added_links > 20:
                issues.append(AuditIssue(
                    category=IssueCategory.SEO.value,
                    severity=IssueSeverity.LOW.value,
                    issue_type="js_loaded_links",
                    description=f"{js_added_links} links loaded via JavaScript",
                    recommendation="Important navigation links should be in initial HTML",
                    metadata={"js_added_links": js_added_links}
                ))

            logger.debug(
                f"JS rendering analysis: ratio={js_content_ratio}, "
                f"change={content_change:.1f}%, js_links={js_added_links}, "
                f"dependent={is_js_dependent}"
            )

        except Exception as e:
            logger.warning(f"Error in JS rendering analysis: {e}")
            metrics["js_analysis_error"] = str(e)

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

    def _measure_core_web_vitals(
        self,
        url: str,
        measure_cwv: bool = True,
    ) -> Tuple[List[AuditIssue], Dict[str, Any]]:
        """
        Measure Core Web Vitals using Playwright Performance APIs.

        Args:
            url: URL to measure
            measure_cwv: Whether to actually measure CWV (can be disabled)

        Returns:
            Tuple of (issues, metrics) with CWV data
        """
        issues = []
        metrics = {}

        if not measure_cwv:
            return issues, metrics

        try:
            # Use dedicated CWV collector
            cwv_collector = CoreWebVitalsCollector(
                headless=self.headless,
                page_timeout=self.page_timeout,
                cwv_wait_time=5.0,
            )

            result = cwv_collector.measure_url(url)

            if result.error:
                logger.warning(f"CWV measurement error for {url}: {result.error}")
                return issues, metrics

            # Store metrics
            if result.lcp_ms is not None:
                metrics["lcp_ms"] = round(result.lcp_ms, 2)
                metrics["lcp_rating"] = result.lcp_rating

            if result.cls_value is not None:
                metrics["cls_value"] = round(result.cls_value, 4)
                metrics["cls_rating"] = result.cls_rating

            if result.fid_ms is not None:
                metrics["fid_ms"] = round(result.fid_ms, 2)
                metrics["fid_rating"] = result.fid_rating

            if result.fcp_ms is not None:
                metrics["fcp_ms"] = round(result.fcp_ms, 2)

            if result.tti_ms is not None:
                metrics["tti_ms"] = round(result.tti_ms, 2)

            if result.ttfb_ms is not None:
                metrics["ttfb_ms"] = round(result.ttfb_ms, 2)

            if result.lcp_element:
                metrics["lcp_element"] = result.lcp_element

            if result.cwv_score is not None:
                metrics["cwv_score"] = result.cwv_score

            if result.cwv_assessment:
                metrics["cwv_assessment"] = result.cwv_assessment

            # Generate issues from CWV metrics service
            cwv_service = get_cwv_metrics_service()
            cwv_issues = cwv_service.generate_issues(
                lcp_ms=result.lcp_ms,
                cls_value=result.cls_value,
                fid_ms=result.fid_ms,
                fcp_ms=result.fcp_ms,
                tti_ms=result.tti_ms,
                ttfb_ms=result.ttfb_ms,
                lcp_element=result.lcp_element,
            )

            # Convert CWV issues to AuditIssue format
            for cwv_issue in cwv_issues:
                issues.append(AuditIssue(
                    category=cwv_issue["category"],
                    severity=cwv_issue["severity"],
                    issue_type=cwv_issue["issue_type"],
                    description=cwv_issue["description"],
                    affected_element=cwv_issue.get("element", ""),
                    recommendation=cwv_issue["recommendation"],
                    metadata=cwv_issue.get("metadata", {}),
                ))

            logger.info(
                f"CWV measured for {url}: "
                f"LCP={result.lcp_ms}ms ({result.lcp_rating}), "
                f"CLS={result.cls_value} ({result.cls_rating}), "
                f"Score={result.cwv_score}"
            )

        except Exception as e:
            logger.error(f"CWV measurement failed for {url}: {e}")

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

        # Insert page audit - using actual table schema with CWV columns
        audit_result = session.execute(
            text("""
                INSERT INTO page_audits (
                    url, audit_type, overall_score, page_load_time_ms,
                    page_size_kb, total_requests,
                    lcp_ms, cls_value, fid_ms, tti_ms, fcp_ms, ttfb_ms,
                    cwv_score, lcp_rating, cls_rating, fid_rating, cwv_element,
                    metadata
                ) VALUES (
                    :url, 'technical', :overall_score, :page_load_time_ms,
                    :page_size_kb, :total_requests,
                    :lcp_ms, :cls_value, :fid_ms, :tti_ms, :fcp_ms, :ttfb_ms,
                    :cwv_score, :lcp_rating, :cls_rating, :fid_rating, :cwv_element,
                    CAST(:audit_metadata AS jsonb)
                )
                RETURNING audit_id
            """),
            {
                "url": result.url,
                "overall_score": result.overall_score,
                "page_load_time_ms": int(result.metrics.get("load_time_seconds", 0) * 1000),
                "page_size_kb": result.metrics.get("html_size", 0) // 1024,
                "total_requests": result.metrics.get("script_count", 0) + result.metrics.get("stylesheet_count", 0),
                # CWV metrics
                "lcp_ms": result.metrics.get("lcp_ms"),
                "cls_value": result.metrics.get("cls_value"),
                "fid_ms": result.metrics.get("fid_ms"),
                "tti_ms": result.metrics.get("tti_ms"),
                "fcp_ms": result.metrics.get("fcp_ms"),
                "ttfb_ms": result.metrics.get("ttfb_ms"),
                "cwv_score": result.metrics.get("cwv_score"),
                "lcp_rating": result.metrics.get("lcp_rating"),
                "cls_rating": result.metrics.get("cls_rating"),
                "fid_rating": result.metrics.get("fid_rating"),
                "cwv_element": result.metrics.get("lcp_element"),
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

    def audit_page(self, url: str, measure_cwv: bool = True) -> AuditResult:
        """
        Perform technical audit on a single page.

        Args:
            url: URL to audit
            measure_cwv: Whether to measure Core Web Vitals (adds ~5s to audit)

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

            # HTTP Response Headers check (cache, compression, security headers)
            header_issues, header_metrics = self._check_response_headers(url)
            all_issues.extend(header_issues)
            all_metrics.update(header_metrics)
            if header_metrics.get("compression_enabled"):
                passed_checks.append("Compression enabled")
            if header_metrics.get("hsts_enabled"):
                passed_checks.append("HSTS configured")
            if header_metrics.get("security_headers_count", 0) >= 4:
                passed_checks.append("Security headers configured")

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

            # Measure Core Web Vitals (separate browser session)
            if measure_cwv and not use_http_fallback:
                cwv_issues, cwv_metrics = self._measure_core_web_vitals(url, measure_cwv=True)
                all_issues.extend(cwv_issues)
                all_metrics.update(cwv_metrics)

            # JS Rendering Analysis: Compare raw HTML vs rendered HTML
            # Only run if we have rendered HTML from Playwright (not HTTP fallback)
            if not use_http_fallback and html:
                try:
                    # Fetch raw HTML without JavaScript execution
                    raw_response = requests.get(
                        url,
                        timeout=10,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        },
                        verify=True,
                        allow_redirects=True,
                    )
                    if raw_response.status_code == 200:
                        raw_html = raw_response.text
                        js_issues, js_metrics = self._check_js_rendering(raw_html, html)
                        all_issues.extend(js_issues)
                        all_metrics.update(js_metrics)
                except Exception as js_err:
                    logger.debug(f"JS rendering analysis skipped for {url}: {js_err}")

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
        logger.info("  - HTTP Response Headers:")
        logger.info("    - Cache-Control, ETag, Content-Encoding")
        logger.info("    - X-Robots-Tag (SEO directives)")
        logger.info("    - HSTS, CSP, X-Frame-Options (security)")
        logger.info("    - Redirect chain analysis")
        logger.info("  - Meta tags (title, description, canonical)")
        logger.info("  - Heading structure (H1, H2)")
        logger.info("  - Image optimization (alt text)")
        logger.info("  - Link analysis")
        logger.info("  - Schema.org markup")
        logger.info("  - Performance indicators")
        logger.info("  - Core Web Vitals (LCP, CLS, INP)")
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

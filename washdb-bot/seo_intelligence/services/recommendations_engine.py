"""
SEO Recommendations Engine

Generates prioritized, actionable SEO recommendations based on audit results
from TechnicalAuditor, CoreWebVitals, BacklinkCrawler, and CompetitorCrawler.

Key features:
- Priority scoring (1-5, 1 = highest)
- Effort estimation (quick-win, medium, large)
- Impact estimation (high, medium, low)
- Category classification (technical, content, ux, conversion, security, performance)
- Affected URLs tracking
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class RecommendationCategory(Enum):
    """Categories for SEO recommendations."""
    TECHNICAL = "technical"
    CONTENT = "content"
    UX = "ux"
    CONVERSION = "conversion"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    MOBILE = "mobile"
    BACKLINKS = "backlinks"


class EffortLevel(Enum):
    """Effort required to implement the recommendation."""
    QUICK_WIN = "quick-win"  # < 1 hour
    MEDIUM = "medium"        # 1-8 hours
    LARGE = "large"          # > 8 hours


class ImpactLevel(Enum):
    """Expected SEO impact of the recommendation."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SEORecommendation:
    """
    A single SEO recommendation with prioritization metadata.
    """
    category: RecommendationCategory
    priority: int  # 1-5 (1 = highest priority)
    issue: str  # What's wrong
    recommendation: str  # What to do
    effort: EffortLevel
    expected_impact: ImpactLevel
    affected_urls: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'category': self.category.value,
            'priority': self.priority,
            'issue': self.issue,
            'recommendation': self.recommendation,
            'effort': self.effort.value,
            'expected_impact': self.expected_impact.value,
            'affected_urls': self.affected_urls,
            'details': self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SEORecommendation':
        """Create from dictionary."""
        return cls(
            category=RecommendationCategory(data['category']),
            priority=data['priority'],
            issue=data['issue'],
            recommendation=data['recommendation'],
            effort=EffortLevel(data['effort']),
            expected_impact=ImpactLevel(data['expected_impact']),
            affected_urls=data.get('affected_urls', []),
            details=data.get('details', {}),
        )


class RecommendationsEngine:
    """
    Generates SEO recommendations from audit data.

    Usage:
        engine = RecommendationsEngine()

        # Add audit results
        engine.add_technical_audit(audit_result)
        engine.add_cwv_results(cwv_result)
        engine.add_backlink_data(backlinks)
        engine.add_competitor_data(competitor)

        # Get prioritized recommendations
        recommendations = engine.generate_recommendations()
    """

    def __init__(self):
        self.technical_audits: List[Dict[str, Any]] = []
        self.cwv_results: List[Dict[str, Any]] = []
        self.backlink_data: List[Dict[str, Any]] = []
        self.competitor_data: List[Dict[str, Any]] = []
        self.recommendations: List[SEORecommendation] = []

    def add_technical_audit(self, audit: Dict[str, Any]) -> None:
        """Add technical audit results."""
        self.technical_audits.append(audit)

    def add_cwv_results(self, cwv: Dict[str, Any]) -> None:
        """Add Core Web Vitals results."""
        self.cwv_results.append(cwv)

    def add_backlink_data(self, backlinks: List[Dict[str, Any]]) -> None:
        """Add backlink crawl data."""
        self.backlink_data.extend(backlinks)

    def add_competitor_data(self, competitor: Dict[str, Any]) -> None:
        """Add competitor analysis data."""
        self.competitor_data.append(competitor)

    def clear(self) -> None:
        """Clear all data and recommendations."""
        self.technical_audits.clear()
        self.cwv_results.clear()
        self.backlink_data.clear()
        self.competitor_data.clear()
        self.recommendations.clear()

    def generate_recommendations(self) -> List[SEORecommendation]:
        """
        Generate all recommendations from loaded audit data.
        Returns sorted list by priority (1 = highest).
        """
        self.recommendations.clear()

        # Process each data source
        self._process_technical_audits()
        self._process_cwv_results()
        self._process_backlink_data()
        self._process_competitor_data()

        # Sort by priority (1 first), then by impact (high first)
        impact_order = {ImpactLevel.HIGH: 0, ImpactLevel.MEDIUM: 1, ImpactLevel.LOW: 2}
        self.recommendations.sort(
            key=lambda r: (r.priority, impact_order.get(r.expected_impact, 2))
        )

        return self.recommendations

    def _add_recommendation(
        self,
        category: RecommendationCategory,
        priority: int,
        issue: str,
        recommendation: str,
        effort: EffortLevel,
        impact: ImpactLevel,
        urls: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Helper to add a recommendation."""
        self.recommendations.append(SEORecommendation(
            category=category,
            priority=max(1, min(5, priority)),  # Clamp to 1-5
            issue=issue,
            recommendation=recommendation,
            effort=effort,
            expected_impact=impact,
            affected_urls=urls or [],
            details=details or {},
        ))

    # =========================================================================
    # Technical Audit Processing
    # =========================================================================

    def _process_technical_audits(self) -> None:
        """Process technical audit results and generate recommendations."""
        for audit in self.technical_audits:
            url = audit.get('url', 'Unknown URL')

            # Meta tags
            self._check_meta_issues(audit, url)

            # Security
            self._check_security_issues(audit, url)

            # Performance
            self._check_performance_issues(audit, url)

            # Accessibility
            self._check_accessibility_issues(audit, url)

            # Mobile
            self._check_mobile_issues(audit, url)

            # Structured data
            self._check_structured_data_issues(audit, url)

            # Social/OG tags
            self._check_social_meta_issues(audit, url)

    def _check_meta_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for meta tag issues."""
        meta = audit.get('meta_tags', {})

        # Missing or bad title
        title = meta.get('title', '')
        if not title:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=1,
                issue="Missing page title",
                recommendation="Add a unique, descriptive <title> tag (50-60 characters)",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )
        elif len(title) < 30:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=3,
                issue=f"Title too short ({len(title)} chars)",
                recommendation="Expand title to 50-60 characters with target keywords",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'current_title': title},
            )
        elif len(title) > 60:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=4,
                issue=f"Title too long ({len(title)} chars)",
                recommendation="Shorten title to 50-60 characters to prevent truncation in SERPs",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.LOW,
                urls=[url],
                details={'current_title': title},
            )

        # Missing or bad meta description
        description = meta.get('description', '')
        if not description:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=2,
                issue="Missing meta description",
                recommendation="Add a compelling meta description (150-160 characters) with call-to-action",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )
        elif len(description) < 120:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=4,
                issue=f"Meta description too short ({len(description)} chars)",
                recommendation="Expand meta description to 150-160 characters",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.LOW,
                urls=[url],
            )
        elif len(description) > 160:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=5,
                issue=f"Meta description too long ({len(description)} chars)",
                recommendation="Shorten meta description to 150-160 characters",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.LOW,
                urls=[url],
            )

        # Missing canonical
        canonical = meta.get('canonical')
        if not canonical:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=2,
                issue="Missing canonical tag",
                recommendation="Add <link rel='canonical'> to prevent duplicate content issues",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

        # Missing viewport
        viewport = meta.get('viewport')
        if not viewport:
            self._add_recommendation(
                RecommendationCategory.MOBILE,
                priority=1,
                issue="Missing viewport meta tag",
                recommendation="Add <meta name='viewport' content='width=device-width, initial-scale=1'>",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

    def _check_security_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for security issues."""
        security = audit.get('security', {})

        # HTTPS
        if not security.get('is_https', True):
            self._add_recommendation(
                RecommendationCategory.SECURITY,
                priority=1,
                issue="Site not using HTTPS",
                recommendation="Install SSL certificate and redirect all HTTP traffic to HTTPS",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

        # HSTS
        if not security.get('hsts_enabled', False):
            self._add_recommendation(
                RecommendationCategory.SECURITY,
                priority=3,
                issue="HSTS not enabled",
                recommendation="Add Strict-Transport-Security header to enforce HTTPS",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
            )

        # Content Security Policy
        if not security.get('csp_present', False):
            self._add_recommendation(
                RecommendationCategory.SECURITY,
                priority=4,
                issue="Missing Content-Security-Policy header",
                recommendation="Implement CSP header to prevent XSS attacks",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.LOW,
                urls=[url],
            )

        # X-Frame-Options
        if not security.get('x_frame_options', False):
            self._add_recommendation(
                RecommendationCategory.SECURITY,
                priority=4,
                issue="Missing X-Frame-Options header",
                recommendation="Add X-Frame-Options: DENY or SAMEORIGIN to prevent clickjacking",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.LOW,
                urls=[url],
            )

        # Mixed content
        mixed_content = security.get('mixed_content', [])
        if mixed_content:
            self._add_recommendation(
                RecommendationCategory.SECURITY,
                priority=2,
                issue=f"Mixed content detected ({len(mixed_content)} resources)",
                recommendation="Update all HTTP resources to HTTPS to avoid browser warnings",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
                details={'mixed_content_urls': mixed_content[:10]},
            )

    def _check_performance_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for performance issues from technical audit."""
        performance = audit.get('performance', {})
        resources = audit.get('resource_analysis', {})

        # Large page size
        page_weight = resources.get('total_page_weight_kb', 0)
        if page_weight > 5000:  # > 5MB
            self._add_recommendation(
                RecommendationCategory.PERFORMANCE,
                priority=2,
                issue=f"Very large page size ({page_weight/1000:.1f}MB)",
                recommendation="Optimize images, minify CSS/JS, and remove unused code",
                effort=EffortLevel.LARGE,
                impact=ImpactLevel.HIGH,
                urls=[url],
                details={'page_weight_kb': page_weight},
            )
        elif page_weight > 3000:  # > 3MB
            self._add_recommendation(
                RecommendationCategory.PERFORMANCE,
                priority=3,
                issue=f"Large page size ({page_weight/1000:.1f}MB)",
                recommendation="Consider optimizing images and deferring non-critical resources",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'page_weight_kb': page_weight},
            )

        # Render-blocking resources
        render_blocking = resources.get('render_blocking_count', 0)
        if render_blocking > 5:
            self._add_recommendation(
                RecommendationCategory.PERFORMANCE,
                priority=2,
                issue=f"{render_blocking} render-blocking resources",
                recommendation="Defer non-critical CSS/JS or inline critical styles",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
                details={'render_blocking_resources': resources.get('render_blocking_resources', [])[:5]},
            )

        # Too many third-party scripts
        third_party = resources.get('third_party_count', 0)
        if third_party > 10:
            self._add_recommendation(
                RecommendationCategory.PERFORMANCE,
                priority=3,
                issue=f"{third_party} third-party scripts detected",
                recommendation="Audit third-party scripts and remove unnecessary ones",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'third_party_domains': resources.get('third_party_domains', [])},
            )

        # No compression
        if not performance.get('compression_enabled', True):
            self._add_recommendation(
                RecommendationCategory.PERFORMANCE,
                priority=2,
                issue="Gzip/Brotli compression not enabled",
                recommendation="Enable compression on the server to reduce transfer size",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

    def _check_accessibility_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for accessibility issues."""
        a11y = audit.get('accessibility', {})

        # Images without alt text
        images_without_alt = a11y.get('images_without_alt', 0)
        if images_without_alt > 0:
            self._add_recommendation(
                RecommendationCategory.ACCESSIBILITY,
                priority=2,
                issue=f"{images_without_alt} images missing alt text",
                recommendation="Add descriptive alt attributes to all images",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
                details={'count': images_without_alt},
            )

        # Missing lang attribute
        if not a11y.get('html_lang_present', True):
            self._add_recommendation(
                RecommendationCategory.ACCESSIBILITY,
                priority=2,
                issue="Missing lang attribute on <html>",
                recommendation="Add lang='en' (or appropriate language) to the <html> tag",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

        # Poor color contrast
        contrast_issues = a11y.get('color_contrast_issues', 0)
        if contrast_issues > 0:
            self._add_recommendation(
                RecommendationCategory.ACCESSIBILITY,
                priority=3,
                issue=f"{contrast_issues} color contrast issues",
                recommendation="Ensure text has at least 4.5:1 contrast ratio against background",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'contrast_issues': a11y.get('contrast_issue_details', [])[:5]},
            )

        # Missing skip link
        if not a11y.get('skip_link_present', True):
            self._add_recommendation(
                RecommendationCategory.ACCESSIBILITY,
                priority=4,
                issue="No skip-to-content link",
                recommendation="Add a 'Skip to main content' link for keyboard navigation",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
            )

        # Missing form labels
        unlabeled_inputs = a11y.get('inputs_without_labels', 0)
        if unlabeled_inputs > 0:
            self._add_recommendation(
                RecommendationCategory.ACCESSIBILITY,
                priority=2,
                issue=f"{unlabeled_inputs} form inputs without labels",
                recommendation="Associate all form inputs with <label> elements",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

    def _check_mobile_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for mobile-specific issues."""
        mobile = audit.get('mobile', {})

        # Small touch targets
        small_targets = mobile.get('small_touch_targets', 0)
        if small_targets > 0:
            self._add_recommendation(
                RecommendationCategory.MOBILE,
                priority=3,
                issue=f"{small_targets} touch targets too small (<44x44px)",
                recommendation="Increase button/link sizes to at least 44x44 pixels",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
            )

        # Small font sizes
        if mobile.get('small_font_detected', False):
            self._add_recommendation(
                RecommendationCategory.MOBILE,
                priority=3,
                issue="Text smaller than 16px detected",
                recommendation="Use minimum 16px font size for mobile readability",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
            )

        # Horizontal scroll
        if mobile.get('horizontal_scroll_detected', False):
            self._add_recommendation(
                RecommendationCategory.MOBILE,
                priority=2,
                issue="Horizontal scrolling detected on mobile",
                recommendation="Fix layout to prevent horizontal overflow (check fixed widths)",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

        # Not mobile-friendly
        if not mobile.get('is_mobile_friendly', True):
            self._add_recommendation(
                RecommendationCategory.MOBILE,
                priority=1,
                issue="Page not mobile-friendly",
                recommendation="Implement responsive design with proper viewport and flexible layouts",
                effort=EffortLevel.LARGE,
                impact=ImpactLevel.HIGH,
                urls=[url],
            )

    def _check_structured_data_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for structured data issues."""
        schema = audit.get('structured_data', {})

        # No structured data
        if not schema.get('has_schema', False):
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=3,
                issue="No structured data (Schema.org) found",
                recommendation="Add relevant Schema.org markup (LocalBusiness, Organization, etc.)",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
            )

        # Schema validation errors
        errors = schema.get('validation_errors', [])
        if errors:
            self._add_recommendation(
                RecommendationCategory.TECHNICAL,
                priority=3,
                issue=f"Structured data has {len(errors)} validation errors",
                recommendation="Fix Schema.org markup errors to enable rich snippets",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'errors': errors[:5]},
            )

    def _check_social_meta_issues(self, audit: Dict[str, Any], url: str) -> None:
        """Check for Open Graph and Twitter Card issues."""
        og = audit.get('open_graph', {})
        twitter = audit.get('twitter_card', {})

        # Open Graph completeness
        og_score = og.get('completeness_score', 1.0)
        if og_score < 0.5:
            self._add_recommendation(
                RecommendationCategory.CONTENT,
                priority=4,
                issue=f"Open Graph tags incomplete ({og_score*100:.0f}%)",
                recommendation="Add og:title, og:description, og:image, and og:url tags",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'missing': og.get('missing_tags', [])},
            )
        elif og_score < 0.8:
            self._add_recommendation(
                RecommendationCategory.CONTENT,
                priority=5,
                issue=f"Open Graph tags partially complete ({og_score*100:.0f}%)",
                recommendation="Add missing Open Graph tags for better social sharing",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.LOW,
                urls=[url],
                details={'missing': og.get('missing_tags', [])},
            )

        # Twitter Card completeness
        twitter_score = twitter.get('completeness_score', 1.0)
        if twitter_score < 0.5:
            self._add_recommendation(
                RecommendationCategory.CONTENT,
                priority=4,
                issue=f"Twitter Card tags incomplete ({twitter_score*100:.0f}%)",
                recommendation="Add twitter:card, twitter:title, twitter:description tags",
                effort=EffortLevel.QUICK_WIN,
                impact=ImpactLevel.MEDIUM,
                urls=[url],
                details={'missing': twitter.get('missing_tags', [])},
            )

    # =========================================================================
    # Core Web Vitals Processing
    # =========================================================================

    def _process_cwv_results(self) -> None:
        """Process Core Web Vitals results."""
        for cwv in self.cwv_results:
            url = cwv.get('url', 'Unknown URL')

            # LCP (Largest Contentful Paint)
            lcp = cwv.get('lcp_ms', 0)
            if lcp > 4000:  # Poor
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=1,
                    issue=f"Poor LCP ({lcp/1000:.1f}s) - should be under 2.5s",
                    recommendation="Optimize images, reduce server response time, remove render-blocking resources",
                    effort=EffortLevel.LARGE,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'lcp_ms': lcp, 'lcp_element': cwv.get('lcp_element')},
                )
            elif lcp > 2500:  # Needs improvement
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=2,
                    issue=f"LCP needs improvement ({lcp/1000:.1f}s) - target under 2.5s",
                    recommendation="Optimize the LCP element, consider preloading hero images",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'lcp_ms': lcp, 'lcp_element': cwv.get('lcp_element')},
                )

            # CLS (Cumulative Layout Shift)
            cls = cwv.get('cls', 0)
            if cls > 0.25:  # Poor
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=1,
                    issue=f"Poor CLS ({cls:.3f}) - should be under 0.1",
                    recommendation="Add size attributes to images/videos, reserve space for ads/embeds",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'cls': cls, 'shift_sources': cwv.get('shift_sources', [])},
                )
            elif cls > 0.1:  # Needs improvement
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=2,
                    issue=f"CLS needs improvement ({cls:.3f}) - target under 0.1",
                    recommendation="Identify and fix elements causing layout shifts",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'cls': cls, 'shift_sources': cwv.get('shift_sources', [])},
                )

            # INP (Interaction to Next Paint) - replaces FID
            inp = cwv.get('inp_ms', 0)
            if inp > 500:  # Poor
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=1,
                    issue=f"Poor INP ({inp}ms) - should be under 200ms",
                    recommendation="Optimize JavaScript, break up long tasks, reduce main thread work",
                    effort=EffortLevel.LARGE,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'inp_ms': inp},
                )
            elif inp > 200:  # Needs improvement
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=2,
                    issue=f"INP needs improvement ({inp}ms) - target under 200ms",
                    recommendation="Optimize event handlers and reduce JavaScript blocking time",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'inp_ms': inp},
                )

            # TBT (Total Blocking Time)
            tbt = cwv.get('tbt_ms', 0)
            if tbt > 600:  # Poor
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=2,
                    issue=f"High TBT ({tbt}ms) - should be under 300ms",
                    recommendation="Break up long JavaScript tasks, defer non-critical scripts",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'tbt_ms': tbt, 'long_tasks': cwv.get('long_tasks', [])[:5]},
                )
            elif tbt > 300:  # Needs improvement
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=3,
                    issue=f"TBT needs improvement ({tbt}ms) - target under 300ms",
                    recommendation="Identify and optimize long JavaScript tasks",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    urls=[url],
                    details={'tbt_ms': tbt},
                )

            # TTFB (Time to First Byte)
            ttfb = cwv.get('ttfb_ms', 0)
            if ttfb > 1800:  # Poor
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=2,
                    issue=f"Poor TTFB ({ttfb}ms) - should be under 800ms",
                    recommendation="Optimize server response time, use CDN, implement caching",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.HIGH,
                    urls=[url],
                    details={'ttfb_ms': ttfb},
                )
            elif ttfb > 800:  # Needs improvement
                self._add_recommendation(
                    RecommendationCategory.PERFORMANCE,
                    priority=3,
                    issue=f"TTFB needs improvement ({ttfb}ms) - target under 800ms",
                    recommendation="Consider server-side caching or CDN implementation",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    urls=[url],
                    details={'ttfb_ms': ttfb},
                )

    # =========================================================================
    # Backlink Data Processing
    # =========================================================================

    def _process_backlink_data(self) -> None:
        """Process backlink data and generate recommendations."""
        if not self.backlink_data:
            return

        # Count total and quality metrics
        total_backlinks = len(self.backlink_data)
        dofollow_count = sum(1 for bl in self.backlink_data if not bl.get('nofollow', True))
        nofollow_count = total_backlinks - dofollow_count

        unique_domains = len(set(bl.get('source_domain', '') for bl in self.backlink_data))

        # Very few backlinks
        if total_backlinks < 10:
            self._add_recommendation(
                RecommendationCategory.BACKLINKS,
                priority=2,
                issue=f"Very few backlinks detected ({total_backlinks})",
                recommendation="Build backlinks through guest posting, local directories, and industry partnerships",
                effort=EffortLevel.LARGE,
                impact=ImpactLevel.HIGH,
                details={'total_backlinks': total_backlinks, 'unique_domains': unique_domains},
            )
        elif total_backlinks < 50:
            self._add_recommendation(
                RecommendationCategory.BACKLINKS,
                priority=3,
                issue=f"Limited backlink profile ({total_backlinks} links)",
                recommendation="Focus on acquiring quality backlinks from relevant industry sites",
                effort=EffortLevel.LARGE,
                impact=ImpactLevel.MEDIUM,
                details={'total_backlinks': total_backlinks, 'unique_domains': unique_domains},
            )

        # High nofollow ratio
        if total_backlinks > 10:
            nofollow_ratio = nofollow_count / total_backlinks
            if nofollow_ratio > 0.8:
                self._add_recommendation(
                    RecommendationCategory.BACKLINKS,
                    priority=3,
                    issue=f"High nofollow ratio ({nofollow_ratio*100:.0f}%)",
                    recommendation="Focus on acquiring more dofollow backlinks from authoritative sources",
                    effort=EffortLevel.LARGE,
                    impact=ImpactLevel.MEDIUM,
                    details={'dofollow': dofollow_count, 'nofollow': nofollow_count},
                )

        # Low domain diversity
        if unique_domains > 0 and total_backlinks > 10:
            diversity_ratio = unique_domains / total_backlinks
            if diversity_ratio < 0.3:
                self._add_recommendation(
                    RecommendationCategory.BACKLINKS,
                    priority=3,
                    issue=f"Low domain diversity ({unique_domains} domains for {total_backlinks} links)",
                    recommendation="Diversify backlink sources to reduce over-reliance on few domains",
                    effort=EffortLevel.LARGE,
                    impact=ImpactLevel.MEDIUM,
                    details={'unique_domains': unique_domains, 'total_backlinks': total_backlinks},
                )

        # Check for potentially toxic backlinks
        low_quality_count = sum(
            1 for bl in self.backlink_data
            if bl.get('quality_score', 50) < 20
        )
        if low_quality_count > 5:
            self._add_recommendation(
                RecommendationCategory.BACKLINKS,
                priority=2,
                issue=f"{low_quality_count} potentially low-quality backlinks detected",
                recommendation="Audit backlinks and consider disavowing toxic links",
                effort=EffortLevel.MEDIUM,
                impact=ImpactLevel.HIGH,
                details={'low_quality_count': low_quality_count},
            )

    # =========================================================================
    # Competitor Data Processing
    # =========================================================================

    def _process_competitor_data(self) -> None:
        """Process competitor data and generate recommendations."""
        if not self.competitor_data:
            return

        for competitor in self.competitor_data:
            name = competitor.get('name', 'Competitor')

            # Trust signals comparison
            trust = competitor.get('trust_signals', {})
            if trust.get('certifications_count', 0) > 3:
                self._add_recommendation(
                    RecommendationCategory.CONVERSION,
                    priority=4,
                    issue=f"{name} displays {trust.get('certifications_count')} certifications",
                    recommendation="Add industry certifications, awards, and trust badges to your site",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    details={'competitor': name, 'trust_signals': trust},
                )

            # Testimonials comparison
            if trust.get('testimonials_count', 0) > 10:
                self._add_recommendation(
                    RecommendationCategory.CONVERSION,
                    priority=4,
                    issue=f"{name} has {trust.get('testimonials_count')} testimonials",
                    recommendation="Collect and display more customer testimonials and reviews",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    details={'competitor': name},
                )

            # Content analysis
            content = competitor.get('content_analysis', {})
            word_count = content.get('word_count', 0)
            if word_count > 2000:
                self._add_recommendation(
                    RecommendationCategory.CONTENT,
                    priority=3,
                    issue=f"{name} has comprehensive content ({word_count} words)",
                    recommendation="Create more in-depth content to compete for topical authority",
                    effort=EffortLevel.LARGE,
                    impact=ImpactLevel.HIGH,
                    details={'competitor': name, 'word_count': word_count},
                )

            # FAQ/structured content
            if content.get('has_faq', False):
                self._add_recommendation(
                    RecommendationCategory.CONTENT,
                    priority=4,
                    issue=f"{name} has FAQ section",
                    recommendation="Add FAQ section with structured data for featured snippet opportunities",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    details={'competitor': name},
                )

            # Tech stack insights
            tech = competitor.get('tech_stack', {})
            if tech.get('has_live_chat', False):
                self._add_recommendation(
                    RecommendationCategory.CONVERSION,
                    priority=4,
                    issue=f"{name} uses live chat for lead capture",
                    recommendation="Consider adding live chat or chatbot for immediate visitor engagement",
                    effort=EffortLevel.MEDIUM,
                    impact=ImpactLevel.MEDIUM,
                    details={'competitor': name, 'tech_stack': tech},
                )

    # =========================================================================
    # Output Methods
    # =========================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of recommendations by category and priority."""
        if not self.recommendations:
            return {'total': 0, 'by_category': {}, 'by_priority': {}, 'quick_wins': []}

        by_category: Dict[str, int] = {}
        by_priority: Dict[int, int] = {}
        quick_wins: List[Dict[str, Any]] = []

        for rec in self.recommendations:
            cat = rec.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
            by_priority[rec.priority] = by_priority.get(rec.priority, 0) + 1

            if rec.effort == EffortLevel.QUICK_WIN and rec.priority <= 3:
                quick_wins.append(rec.to_dict())

        return {
            'total': len(self.recommendations),
            'by_category': by_category,
            'by_priority': by_priority,
            'quick_wins': quick_wins[:10],  # Top 10 quick wins
        }

    def get_top_recommendations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the top N prioritized recommendations."""
        return [r.to_dict() for r in self.recommendations[:limit]]

    def get_by_category(self, category: RecommendationCategory) -> List[Dict[str, Any]]:
        """Get all recommendations for a specific category."""
        return [
            r.to_dict() for r in self.recommendations
            if r.category == category
        ]

    def get_quick_wins(self) -> List[Dict[str, Any]]:
        """Get all quick-win recommendations sorted by impact."""
        impact_order = {ImpactLevel.HIGH: 0, ImpactLevel.MEDIUM: 1, ImpactLevel.LOW: 2}
        quick_wins = [r for r in self.recommendations if r.effort == EffortLevel.QUICK_WIN]
        quick_wins.sort(key=lambda r: (r.priority, impact_order.get(r.expected_impact, 2)))
        return [r.to_dict() for r in quick_wins]

    def to_dict(self) -> Dict[str, Any]:
        """Convert all recommendations to dictionary."""
        return {
            'summary': self.get_summary(),
            'recommendations': [r.to_dict() for r in self.recommendations],
        }


def generate_recommendations_from_audit(
    technical_audit: Optional[Dict[str, Any]] = None,
    cwv_results: Optional[Dict[str, Any]] = None,
    backlinks: Optional[List[Dict[str, Any]]] = None,
    competitor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to generate recommendations from audit data.

    Args:
        technical_audit: Result from TechnicalAuditorSelenium.audit_page()
        cwv_results: Result from CoreWebVitalsSelenium.measure_url()
        backlinks: List of backlinks from BacklinkCrawlerSelenium
        competitor: Result from CompetitorCrawlerSelenium.crawl_competitor()

    Returns:
        Dictionary with summary and prioritized recommendations
    """
    engine = RecommendationsEngine()

    if technical_audit:
        engine.add_technical_audit(technical_audit)

    if cwv_results:
        engine.add_cwv_results(cwv_results)

    if backlinks:
        engine.add_backlink_data(backlinks)

    if competitor:
        engine.add_competitor_data(competitor)

    engine.generate_recommendations()

    return engine.to_dict()

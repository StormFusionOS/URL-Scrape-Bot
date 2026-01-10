"""
Browser Drivers for SEO Intelligence.

This module provides undetected browser drivers for various SEO scraping tasks.

Includes:
- SeleniumBase UC (Undetected Chrome) drivers
- Camoufox (Firefox-based) drivers
- Browser escalation manager for CAPTCHA handling
- Enterprise Browser Pool for session management
"""

from .seleniumbase_drivers import (
    get_uc_driver,
    get_google_serp_driver,
    get_yelp_driver,
    get_bbb_driver,
    get_yellowpages_driver,
    get_gbp_driver,
    get_driver_for_site,
    click_element_human_like,
)

from .camoufox_drivers import (
    CamoufoxDriver,
    CamoufoxGoogleDriver,
    CamoufoxPageArtifact,
    get_camoufox_driver,
)

from .browser_escalation import (
    BrowserTier,
    BrowserEscalationManager,
    BrowserProfileManager,
    EscalationState,
    get_escalation_manager,
    should_use_camoufox,
    report_captcha,
    report_success,
)

from .pool_models import (
    BrowserSession,
    BrowserType,
    SessionLease,
    SessionState,
    RecycleAction,
    TargetGroupConfig,
    PoolStats,
    TARGET_GROUP_CONFIGS,
    SITE_TO_DOMAIN,
    get_target_group_for_domain,
)

from .browser_pool import (
    EnterpriseBrowserPool,
    get_browser_pool,
)

from .pool_metrics import (
    PoolMetricsCollector,
    LeaseMetrics,
    DomainMetrics,
    get_pool_metrics,
    reset_pool_metrics,
)

from .human_behavior import (
    generate_bezier_path,
    move_mouse_naturally_selenium,
    move_mouse_naturally_playwright,
    scroll_naturally_selenium,
    scroll_naturally_playwright,
    click_safe_element_selenium,
    click_safe_element_playwright,
    type_naturally_selenium,
    type_naturally_playwright,
    simulate_reading_selenium,
    simulate_reading_playwright,
)

from .warmup_reputation import (
    WarmupReputationTracker,
    URLReputationEntry,
    get_warmup_reputation_tracker,
)

__all__ = [
    # SeleniumBase UC drivers
    "get_uc_driver",
    "get_google_serp_driver",
    "get_yelp_driver",
    "get_bbb_driver",
    "get_yellowpages_driver",
    "get_gbp_driver",
    "get_driver_for_site",
    "click_element_human_like",
    # Camoufox drivers
    "CamoufoxDriver",
    "CamoufoxGoogleDriver",
    "CamoufoxPageArtifact",
    "get_camoufox_driver",
    # Browser escalation
    "BrowserTier",
    "BrowserEscalationManager",
    "BrowserProfileManager",
    "EscalationState",
    "get_escalation_manager",
    "should_use_camoufox",
    "report_captcha",
    "report_success",
    # Browser pool
    "BrowserSession",
    "BrowserType",
    "SessionLease",
    "SessionState",
    "RecycleAction",
    "TargetGroupConfig",
    "PoolStats",
    "TARGET_GROUP_CONFIGS",
    "SITE_TO_DOMAIN",
    "get_target_group_for_domain",
    "EnterpriseBrowserPool",
    "get_browser_pool",
    # Pool metrics
    "PoolMetricsCollector",
    "LeaseMetrics",
    "DomainMetrics",
    "get_pool_metrics",
    "reset_pool_metrics",
    # Human behavior simulation
    "generate_bezier_path",
    "move_mouse_naturally_selenium",
    "move_mouse_naturally_playwright",
    "scroll_naturally_selenium",
    "scroll_naturally_playwright",
    "click_safe_element_selenium",
    "click_safe_element_playwright",
    "type_naturally_selenium",
    "type_naturally_playwright",
    "simulate_reading_selenium",
    "simulate_reading_playwright",
    # Warmup reputation tracking
    "WarmupReputationTracker",
    "URLReputationEntry",
    "get_warmup_reputation_tracker",
]

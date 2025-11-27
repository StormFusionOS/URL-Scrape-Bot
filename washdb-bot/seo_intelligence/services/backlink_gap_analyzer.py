"""
Backlink Gap Analyzer Service

Identifies backlink opportunities by comparing your backlink profile
with competitors. Finds domains linking to competitors but not to you.

Analysis Methods:
- Domain comparison across competitors
- Link type categorization
- Opportunity scoring
- Outreach priority ranking

Usage:
    from seo_intelligence.services.backlink_gap_analyzer import BacklinkGapAnalyzer

    analyzer = BacklinkGapAnalyzer()
    gaps = analyzer.analyze_backlink_gaps(
        your_backlinks=your_domains,
        competitor_backlinks=competitor_domains
    )

Results stored in backlink_gaps database table.
"""

import json
from collections import Counter, defaultdict
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from enum import Enum

from runner.logging_setup import get_logger


class LinkType(Enum):
    """Types of backlink sources."""
    DIRECTORY = "DIRECTORY"           # Business directories
    BLOG = "BLOG"                     # Blog mentions
    NEWS = "NEWS"                     # News/press coverage
    FORUM = "FORUM"                   # Forum discussions
    SOCIAL = "SOCIAL"                 # Social platforms
    RESOURCE = "RESOURCE"             # Resource pages
    GUEST_POST = "GUEST_POST"         # Guest posting opportunities
    CITATION = "CITATION"             # Citation/NAP listings
    COMPETITOR = "COMPETITOR"         # Competitor mentions
    GENERAL = "GENERAL"               # Other


class OutreachPriority(Enum):
    """Outreach priority levels."""
    HIGH = "HIGH"             # Easy win, high value
    MEDIUM = "MEDIUM"         # Worth pursuing
    LOW = "LOW"               # If resources available
    SKIP = "SKIP"             # Not worth effort


@dataclass
class BacklinkOpportunity:
    """Represents a backlink gap opportunity."""
    domain: str
    link_type: LinkType
    priority: OutreachPriority
    competitor_count: int  # How many competitors have this link
    competitors_with_link: List[str]
    opportunity_score: float  # 0-100
    estimated_da: int  # Estimated domain authority
    is_dofollow: bool
    contact_likelihood: float  # 0-1 probability of getting link
    outreach_notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    identified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "link_type": self.link_type.value,
            "priority": self.priority.value,
            "competitor_count": self.competitor_count,
            "competitors": self.competitors_with_link[:5],
            "opportunity_score": self.opportunity_score,
            "estimated_da": self.estimated_da,
            "outreach_notes": self.outreach_notes,
        }


@dataclass
class BacklinkProfile:
    """Represents a site's backlink profile."""
    domain: str
    referring_domains: List[str]
    total_backlinks: int = 0
    dofollow_count: int = 0
    nofollow_count: int = 0
    link_types: Dict[str, int] = field(default_factory=dict)
    top_anchors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BacklinkGapAnalyzer:
    """
    Analyzes backlink gaps between you and competitors.

    Identifies link building opportunities based on competitor backlinks.
    """

    # Domain patterns for categorization
    DOMAIN_PATTERNS = {
        LinkType.DIRECTORY: [
            "yelp", "yellowpages", "manta", "bbb", "foursquare",
            "mapquest", "superpages", "whitepages", "citysearch",
            "local", "directory", "listings", "bizjournals",
        ],
        LinkType.NEWS: [
            "news", "times", "post", "herald", "tribune", "journal",
            "gazette", "daily", "press", "cnn", "bbc", "npr",
            "forbes", "bloomberg", "reuters", "ap", "techcrunch",
        ],
        LinkType.BLOG: [
            "blog", "wordpress", "medium", "blogger", "tumblr",
            "substack", "ghost", "hashnode", "dev.to",
        ],
        LinkType.FORUM: [
            "forum", "reddit", "quora", "stackexchange", "stackoverflow",
            "community", "discuss", "boards", "answers",
        ],
        LinkType.SOCIAL: [
            "facebook", "twitter", "linkedin", "instagram", "pinterest",
            "youtube", "tiktok", "snapchat",
        ],
        LinkType.RESOURCE: [
            "resources", "tools", "guide", "wiki", "edu", "gov",
            "library", "reference", "links",
        ],
    }

    # High-authority TLDs
    HIGH_AUTHORITY_TLDS = {".gov", ".edu", ".org"}

    # Known high-DA domains
    HIGH_DA_DOMAINS = {
        "wikipedia.org": 95, "forbes.com": 94, "nytimes.com": 95,
        "bbc.com": 95, "cnn.com": 94, "linkedin.com": 98,
        "facebook.com": 96, "twitter.com": 94, "youtube.com": 98,
        "reddit.com": 91, "quora.com": 93, "medium.com": 95,
        "github.com": 96, "yelp.com": 93, "tripadvisor.com": 90,
    }

    def __init__(self):
        """Initialize backlink gap analyzer."""
        self.logger = get_logger("backlink_gap_analyzer")

    def _classify_link_type(self, domain: str) -> LinkType:
        """
        Classify a domain by link type.

        Args:
            domain: Domain to classify

        Returns:
            LinkType: Classified type
        """
        domain_lower = domain.lower()

        for link_type, patterns in self.DOMAIN_PATTERNS.items():
            for pattern in patterns:
                if pattern in domain_lower:
                    return link_type

        return LinkType.GENERAL

    def _estimate_domain_authority(self, domain: str) -> int:
        """
        Estimate domain authority for a domain.

        Args:
            domain: Domain to estimate

        Returns:
            int: Estimated DA (0-100)
        """
        domain_lower = domain.lower()

        # Check known domains
        for known_domain, da in self.HIGH_DA_DOMAINS.items():
            if known_domain in domain_lower:
                return da

        # Check TLD
        for tld in self.HIGH_AUTHORITY_TLDS:
            if domain_lower.endswith(tld):
                return 70  # Government/education sites are typically high DA

        # Estimate based on patterns
        base_da = 30

        # Shorter domains often have higher authority
        if len(domain.replace("www.", "").split(".")[0]) <= 6:
            base_da += 10

        # News/media patterns suggest higher DA
        if any(p in domain_lower for p in ["news", "media", "press"]):
            base_da += 15

        # Directory patterns
        if any(p in domain_lower for p in ["directory", "listings"]):
            base_da += 10

        return min(100, base_da)

    def _calculate_opportunity_score(
        self,
        domain: str,
        competitor_count: int,
        total_competitors: int,
        estimated_da: int,
    ) -> float:
        """
        Calculate opportunity score for a backlink.

        Higher score = better opportunity.

        Args:
            domain: Linking domain
            competitor_count: Number of competitors with this link
            total_competitors: Total competitors analyzed
            estimated_da: Estimated domain authority

        Returns:
            float: Opportunity score (0-100)
        """
        # More competitors with link = easier to get
        competitor_ratio = competitor_count / max(1, total_competitors)
        competitor_score = competitor_ratio * 40

        # Higher DA = more valuable
        da_score = (estimated_da / 100) * 40

        # Link type bonus
        link_type = self._classify_link_type(domain)
        type_bonus = 0
        if link_type in (LinkType.RESOURCE, LinkType.DIRECTORY):
            type_bonus = 15  # Easier to get
        elif link_type == LinkType.BLOG:
            type_bonus = 10
        elif link_type == LinkType.NEWS:
            type_bonus = 5  # Harder but valuable

        return min(100, competitor_score + da_score + type_bonus)

    def _calculate_contact_likelihood(
        self,
        domain: str,
        link_type: LinkType,
    ) -> float:
        """
        Estimate likelihood of getting a link from this domain.

        Args:
            domain: Target domain
            link_type: Type of link source

        Returns:
            float: Likelihood (0-1)
        """
        # Base likelihood by type
        base_likelihood = {
            LinkType.DIRECTORY: 0.8,    # High - usually just submit
            LinkType.CITATION: 0.9,      # Very high - business listings
            LinkType.RESOURCE: 0.5,      # Medium - depends on content quality
            LinkType.BLOG: 0.4,          # Medium - need good pitch
            LinkType.GUEST_POST: 0.3,    # Lower - competitive
            LinkType.NEWS: 0.2,          # Low - need newsworthy angle
            LinkType.FORUM: 0.6,         # Medium - community dependent
            LinkType.SOCIAL: 0.7,        # High - just create profile
            LinkType.GENERAL: 0.3,       # Low - unknown
            LinkType.COMPETITOR: 0.1,    # Very low
        }

        likelihood = base_likelihood.get(link_type, 0.3)

        # Adjust for known domains
        domain_lower = domain.lower()

        # Easy directory submissions
        if any(d in domain_lower for d in ["yelp", "yellowpages", "foursquare"]):
            likelihood = 0.9

        # Hard to get news coverage
        if any(d in domain_lower for d in ["nytimes", "forbes", "bbc"]):
            likelihood = 0.1

        return likelihood

    def _generate_outreach_notes(
        self,
        domain: str,
        link_type: LinkType,
        competitors_with_link: List[str],
    ) -> List[str]:
        """
        Generate outreach notes for a backlink opportunity.

        Args:
            domain: Target domain
            link_type: Type of link source
            competitors_with_link: Competitors who have this link

        Returns:
            list: Outreach suggestions
        """
        notes = []

        if link_type == LinkType.DIRECTORY:
            notes.append("Submit business listing with complete NAP information")
            notes.append("Ensure consistent business details across all directories")

        elif link_type == LinkType.RESOURCE:
            notes.append("Create valuable resource content to pitch for inclusion")
            notes.append("Look for broken links on this resource page to suggest replacement")

        elif link_type == LinkType.BLOG:
            notes.append("Research recent articles for relevant guest post opportunities")
            notes.append("Consider pitching unique data or case studies")

        elif link_type == LinkType.NEWS:
            notes.append("Build relationship with journalists in your niche")
            notes.append("Prepare newsworthy angles (data, trends, local impact)")
            notes.append("Use HARO for media inquiry opportunities")

        elif link_type == LinkType.FORUM:
            notes.append("Participate authentically in community discussions")
            notes.append("Provide value before including any links")

        elif link_type == LinkType.CITATION:
            notes.append("Claim and complete business profile")
            notes.append("Add photos, hours, and service details")

        # Add competitor context
        if len(competitors_with_link) >= 2:
            notes.append(
                f"Multiple competitors ({len(competitors_with_link)}) have this link - "
                "likely achievable"
            )

        return notes

    def _determine_priority(
        self,
        opportunity_score: float,
        contact_likelihood: float,
        estimated_da: int,
    ) -> OutreachPriority:
        """
        Determine outreach priority for an opportunity.

        Args:
            opportunity_score: Overall opportunity score
            contact_likelihood: Likelihood of getting link
            estimated_da: Domain authority

        Returns:
            OutreachPriority: Priority level
        """
        # Combined score
        combined = (
            opportunity_score * 0.4 +
            contact_likelihood * 100 * 0.3 +
            estimated_da * 0.3
        )

        if combined >= 70:
            return OutreachPriority.HIGH
        elif combined >= 50:
            return OutreachPriority.MEDIUM
        elif combined >= 30:
            return OutreachPriority.LOW
        return OutreachPriority.SKIP

    def analyze_backlink_gaps(
        self,
        your_backlinks: List[str],
        competitor_backlinks: Dict[str, List[str]],
        min_competitor_coverage: int = 1,
    ) -> List[BacklinkOpportunity]:
        """
        Find backlink opportunities from competitor analysis.

        Args:
            your_backlinks: List of domains linking to you
            competitor_backlinks: Dict of competitor name -> linking domains
            min_competitor_coverage: Minimum competitors needed for opportunity

        Returns:
            list: BacklinkOpportunity objects
        """
        self.logger.info(
            f"Analyzing gaps: {len(your_backlinks)} your links vs "
            f"{len(competitor_backlinks)} competitors"
        )

        opportunities = []
        your_domains = set(d.lower() for d in your_backlinks)

        # Count competitor coverage per domain
        domain_coverage = Counter()
        domain_competitors = defaultdict(list)

        for competitor, domains in competitor_backlinks.items():
            for domain in domains:
                domain_lower = domain.lower()
                if domain_lower not in your_domains:
                    domain_coverage[domain_lower] += 1
                    domain_competitors[domain_lower].append(competitor)

        # Analyze gaps
        total_competitors = len(competitor_backlinks)

        for domain, count in domain_coverage.most_common():
            if count < min_competitor_coverage:
                continue

            # Skip common spam/low-value domains
            if any(skip in domain for skip in ["spam", "xxx", "adult", "casino"]):
                continue

            link_type = self._classify_link_type(domain)
            estimated_da = self._estimate_domain_authority(domain)

            opportunity_score = self._calculate_opportunity_score(
                domain, count, total_competitors, estimated_da
            )

            contact_likelihood = self._calculate_contact_likelihood(
                domain, link_type
            )

            priority = self._determine_priority(
                opportunity_score, contact_likelihood, estimated_da
            )

            outreach_notes = self._generate_outreach_notes(
                domain, link_type, domain_competitors[domain]
            )

            opportunity = BacklinkOpportunity(
                domain=domain,
                link_type=link_type,
                priority=priority,
                competitor_count=count,
                competitors_with_link=domain_competitors[domain],
                opportunity_score=round(opportunity_score, 2),
                estimated_da=estimated_da,
                is_dofollow=True,  # Assume dofollow, would need to verify
                contact_likelihood=round(contact_likelihood, 2),
                outreach_notes=outreach_notes,
            )

            opportunities.append(opportunity)

        # Sort by opportunity score
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

        self.logger.info(f"Found {len(opportunities)} backlink opportunities")

        return opportunities

    def get_quick_wins(
        self,
        opportunities: List[BacklinkOpportunity],
        limit: int = 20,
    ) -> List[BacklinkOpportunity]:
        """
        Get easiest backlink wins.

        Prioritizes high likelihood + good DA.

        Args:
            opportunities: All opportunities
            limit: Maximum to return

        Returns:
            list: Top quick win opportunities
        """
        # Filter for high likelihood, decent DA
        quick_wins = [
            opp for opp in opportunities
            if opp.contact_likelihood >= 0.5 and opp.estimated_da >= 30
        ]

        # Sort by likelihood * DA
        quick_wins.sort(
            key=lambda x: x.contact_likelihood * x.estimated_da,
            reverse=True
        )

        return quick_wins[:limit]

    def get_by_type(
        self,
        opportunities: List[BacklinkOpportunity],
        link_type: LinkType,
    ) -> List[BacklinkOpportunity]:
        """
        Filter opportunities by link type.

        Args:
            opportunities: All opportunities
            link_type: Desired type

        Returns:
            list: Filtered opportunities
        """
        return [opp for opp in opportunities if opp.link_type == link_type]

    def generate_outreach_plan(
        self,
        opportunities: List[BacklinkOpportunity],
        max_items: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Generate prioritized outreach plan.

        Args:
            opportunities: Opportunities to plan
            max_items: Maximum plan items

        Returns:
            list: Outreach plan items
        """
        # Filter to actionable items
        actionable = [
            opp for opp in opportunities
            if opp.priority != OutreachPriority.SKIP
        ][:max_items]

        plan = []
        for opp in actionable:
            item = {
                "domain": opp.domain,
                "priority": opp.priority.value,
                "type": opp.link_type.value,
                "estimated_da": opp.estimated_da,
                "competitor_coverage": opp.competitor_count,
                "likelihood": f"{opp.contact_likelihood * 100:.0f}%",
                "steps": opp.outreach_notes,
            }

            # Add specific action
            if opp.link_type == LinkType.DIRECTORY:
                item["action"] = "Submit business listing"
            elif opp.link_type == LinkType.CITATION:
                item["action"] = "Claim and complete profile"
            elif opp.link_type == LinkType.RESOURCE:
                item["action"] = "Pitch for resource inclusion"
            elif opp.link_type == LinkType.BLOG:
                item["action"] = "Pitch guest post or content"
            else:
                item["action"] = "Research and outreach"

            plan.append(item)

        return plan

    def save_opportunities(
        self,
        opportunities: List[BacklinkOpportunity],
        competitor_id: Optional[int] = None,
    ):
        """
        Save backlink opportunities to database.

        Args:
            opportunities: Opportunities to save
            competitor_id: Optional competitor association
        """
        if not opportunities:
            return

        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        import os

        load_dotenv()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            self.logger.warning("DATABASE_URL not set, skipping save")
            return

        engine = create_engine(db_url)

        insert_sql = text("""
            INSERT INTO backlink_gaps (
                domain, link_type, priority, opportunity_score,
                competitor_count, estimated_da, contact_likelihood,
                competitors_with_link, outreach_notes,
                competitor_id, metadata, created_at
            ) VALUES (
                :domain, :link_type, :priority, :score,
                :comp_count, :da, :likelihood,
                :competitors, :notes,
                :competitor_id, :metadata, :created_at
            )
            ON CONFLICT (domain) DO UPDATE SET
                opportunity_score = GREATEST(backlink_gaps.opportunity_score, EXCLUDED.opportunity_score),
                competitor_count = EXCLUDED.competitor_count,
                updated_at = NOW()
        """)

        with engine.connect() as conn:
            for opp in opportunities:
                try:
                    conn.execute(insert_sql, {
                        "domain": opp.domain,
                        "link_type": opp.link_type.value,
                        "priority": opp.priority.value,
                        "score": opp.opportunity_score,
                        "comp_count": opp.competitor_count,
                        "da": opp.estimated_da,
                        "likelihood": opp.contact_likelihood,
                        "competitors": json.dumps(opp.competitors_with_link),
                        "notes": json.dumps(opp.outreach_notes),
                        "competitor_id": competitor_id,
                        "metadata": json.dumps(opp.metadata),
                        "created_at": opp.identified_at,
                    })
                except Exception as e:
                    self.logger.debug(f"Error saving opportunity: {e}")

            conn.commit()

        self.logger.info(f"Saved {len(opportunities)} backlink opportunities to database")


# Module-level singleton
_backlink_gap_analyzer_instance = None


def get_backlink_gap_analyzer() -> BacklinkGapAnalyzer:
    """Get or create the singleton BacklinkGapAnalyzer instance."""
    global _backlink_gap_analyzer_instance

    if _backlink_gap_analyzer_instance is None:
        _backlink_gap_analyzer_instance = BacklinkGapAnalyzer()

    return _backlink_gap_analyzer_instance

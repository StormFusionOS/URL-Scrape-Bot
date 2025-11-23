"""
Unlinked Mentions Finder

Scans competitor pages and external content for brand mentions that don't include
backlinks. These represent link-building opportunities.

Usage:
    from seo_intelligence.scrapers.unlinked_mentions import UnlinkedMentionsFinder

    finder = UnlinkedMentionsFinder()
    mentions = finder.find_mentions(company_id=123)
"""

import os
import re
import json
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seo_intelligence.services import get_task_logger
from seo_intelligence.services.governance import propose_change, ChangeType
from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("unlinked_mentions")


@dataclass
class BrandConfig:
    """Brand terms configuration for a company."""
    company_id: int
    company_name: str
    brand_terms: List[str]  # Full names, abbreviations, domain variants
    domains: List[str]  # Company's domains to check for links


@dataclass
class UnlinkedMention:
    """Represents an unlinked brand mention."""
    company_id: int
    page_url: str
    source_domain: str
    brand_term: str
    context_snippet: str  # Surrounding text
    mention_count: int  # Number of times mentioned on page
    has_link_to_domain: bool
    discovered_at: datetime
    page_id: Optional[int] = None  # FK to competitor_pages if applicable

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        result = asdict(self)
        result['discovered_at'] = self.discovered_at.isoformat()
        return result


class UnlinkedMentionsFinder:
    """
    Finds unlinked brand mentions in competitor pages and external content.

    Features:
    - Case-insensitive brand term matching
    - Context extraction around mentions
    - Link presence detection
    - Deduplication and scoring
    """

    def __init__(
        self,
        max_pages_per_run: int = 100,
        context_chars: int = 200,
        min_word_count: int = 100,
        exclude_domains: Optional[List[str]] = None
    ):
        """
        Initialize mentions finder.

        Args:
            max_pages_per_run: Maximum pages to scan per run
            context_chars: Characters to extract around each mention
            min_word_count: Minimum page word count to scan
            exclude_domains: Domains to skip (e.g., social media)
        """
        self.max_pages_per_run = max_pages_per_run
        self.context_chars = context_chars
        self.min_word_count = min_word_count
        self.exclude_domains = exclude_domains or [
            'facebook.com', 'twitter.com', 'linkedin.com',
            'instagram.com', 'youtube.com', 'reddit.com'
        ]

        # Database connection
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            self.engine = create_engine(database_url, echo=False)
        else:
            self.engine = None
            logger.warning("DATABASE_URL not set - database operations disabled")

        # Task logger
        self.task_logger = get_task_logger()

        logger.info(f"UnlinkedMentionsFinder initialized (max_pages={max_pages_per_run})")

    def _load_brand_config(self, company_id: int, session: Session) -> Optional[BrandConfig]:
        """
        Load brand configuration for a company.

        Args:
            company_id: Company ID
            session: Database session

        Returns:
            BrandConfig or None if not found
        """
        # Query company info
        result = session.execute(
            text("""
                SELECT name, website, domain
                FROM companies
                WHERE id = :company_id
                LIMIT 1
            """),
            {"company_id": company_id}
        )
        row = result.fetchone()

        if not row:
            logger.warning(f"Company {company_id} not found")
            return None

        company_name, website, domain = row

        # Generate brand terms
        brand_terms = [
            company_name,  # Full name
            company_name.lower(),  # Lowercase
            company_name.replace(' ', ''),  # No spaces
        ]

        # Add domain-based variants
        if domain:
            brand_terms.append(domain)
            brand_terms.append(domain.replace('.com', ''))
            brand_terms.append(domain.replace('www.', ''))

        # Add common abbreviations (first letters)
        words = company_name.split()
        if len(words) > 1:
            abbreviation = ''.join([w[0].upper() for w in words])
            brand_terms.append(abbreviation)

        # Deduplicate
        brand_terms = list(set([term.strip() for term in brand_terms if term]))

        domains = [domain] if domain else []
        if website:
            from urllib.parse import urlparse
            parsed = urlparse(website)
            if parsed.netloc:
                domains.append(parsed.netloc)

        config = BrandConfig(
            company_id=company_id,
            company_name=company_name,
            brand_terms=brand_terms,
            domains=list(set(domains))
        )

        logger.info(f"Loaded brand config: {len(brand_terms)} terms, {len(domains)} domains")
        logger.debug(f"Brand terms: {brand_terms}")

        return config

    def _get_competitor_pages_to_scan(
        self,
        session: Session,
        limit: int
    ) -> List[Dict]:
        """
        Get competitor pages to scan for mentions.

        Args:
            session: Database session
            limit: Maximum pages to return

        Returns:
            List of page dictionaries
        """
        # Get recent competitor pages with content
        result = session.execute(
            text("""
                SELECT
                    page_id,
                    competitor_id,
                    url,
                    word_count,
                    metadata
                FROM competitor_pages
                WHERE
                    word_count >= :min_words
                    AND crawled_at > NOW() - INTERVAL '90 days'
                ORDER BY crawled_at DESC
                LIMIT :limit
            """),
            {
                "min_words": self.min_word_count,
                "limit": limit
            }
        )

        pages = []
        for row in result:
            pages.append({
                'page_id': row[0],
                'competitor_id': row[1],
                'url': row[2],
                'word_count': row[3],
                'metadata': row[4] or {}
            })

        logger.info(f"Found {len(pages)} competitor pages to scan")
        return pages

    def _extract_text_from_metadata(self, metadata: Dict) -> str:
        """
        Extract text content from page metadata.

        Args:
            metadata: Page metadata JSONB

        Returns:
            Extracted text
        """
        text_parts = []

        # Extract from common metadata fields
        if 'content_text' in metadata:
            text_parts.append(metadata['content_text'])

        if 'body_text' in metadata:
            text_parts.append(metadata['body_text'])

        if 'paragraphs' in metadata:
            if isinstance(metadata['paragraphs'], list):
                text_parts.extend(metadata['paragraphs'])

        return ' '.join(text_parts)

    def _check_for_brand_mentions(
        self,
        text: str,
        brand_config: BrandConfig,
        page_url: str
    ) -> List[Tuple[str, List[str]]]:
        """
        Check if text contains brand mentions.

        Args:
            text: Page text content
            brand_config: Brand configuration
            page_url: Page URL (for link checking)

        Returns:
            List of (brand_term, context_snippets) tuples
        """
        mentions = []
        text_lower = text.lower()

        for brand_term in brand_config.brand_terms:
            if len(brand_term) < 3:  # Skip very short terms
                continue

            # Case-insensitive search
            pattern = re.compile(re.escape(brand_term), re.IGNORECASE)
            matches = list(pattern.finditer(text))

            if matches:
                # Extract context around each mention
                contexts = []
                for match in matches[:3]:  # Max 3 contexts per term
                    start = max(0, match.start() - self.context_chars // 2)
                    end = min(len(text), match.end() + self.context_chars // 2)
                    snippet = text[start:end].strip()
                    contexts.append(snippet)

                mentions.append((brand_term, contexts))

        return mentions

    def _has_link_to_domains(self, metadata: Dict, domains: List[str]) -> bool:
        """
        Check if page has links to any of the target domains.

        Args:
            metadata: Page metadata with links
            domains: Target domains to check for

        Returns:
            True if any link found
        """
        if not domains or 'links' not in metadata:
            return False

        links = metadata.get('links', {})
        external_links = links.get('external', [])

        for link_url in external_links:
            for domain in domains:
                if domain.lower() in link_url.lower():
                    return True

        return False

    def _save_mention(
        self,
        session: Session,
        mention: UnlinkedMention
    ) -> Optional[int]:
        """
        Propose unlinked mention for governance review.

        Uses change_log governance workflow instead of direct insertion.

        Args:
            session: Database session
            mention: Unlinked mention data

        Returns:
            change_id if proposed successfully
        """
        # First, ensure page_audits entry exists
        audit_result = session.execute(
            text("""
                INSERT INTO page_audits (
                    url,
                    audit_type,
                    overall_score,
                    audited_at,
                    metadata
                ) VALUES (
                    :url,
                    'seo_opportunities',
                    NULL,
                    NOW(),
                    :metadata::jsonb
                )
                ON CONFLICT DO NOTHING
                RETURNING audit_id
            """),
            {
                "url": mention.page_url,
                "metadata": "{}"
            }
        )

        audit_row = audit_result.fetchone()
        if audit_row:
            audit_id = audit_row[0]
        else:
            # Get existing audit_id
            audit_result = session.execute(
                text("""
                    SELECT audit_id
                    FROM page_audits
                    WHERE url = :url
                    AND audit_type = 'seo_opportunities'
                    ORDER BY audited_at DESC
                    LIMIT 1
                """),
                {"url": mention.page_url}
            )
            audit_id = audit_result.scalar()

        session.commit()

        # Build proposed data for audit_issue insertion
        issue_metadata = {
            'company_id': mention.company_id,
            'brand_term': mention.brand_term,
            'context_snippet': mention.context_snippet,
            'mention_count': mention.mention_count,
            'has_link': mention.has_link_to_domain,
            'source_domain': mention.source_domain,
            'page_id': mention.page_id,
            'discovered_at': mention.discovered_at.isoformat()
        }

        proposed_data = {
            'audit_id': audit_id,
            'severity': 'medium',
            'category': 'seo',
            'issue_type': 'unlinked_mention',
            'description': f"Brand mention '{mention.brand_term}' found {mention.mention_count} times without backlink",
            'recommendation': f"Reach out to {mention.source_domain} to request a link to your website",
            'metadata': issue_metadata
        }

        # Propose change through governance
        change_id = propose_change(
            table_name='audit_issues',
            operation='insert',
            proposed_data=proposed_data,
            change_type=ChangeType.UNLINKED_MENTIONS,
            source='unlinked_mentions_finder',
            reason=f"Unlinked mention discovered: '{mention.brand_term}' on {mention.source_domain}",
            metadata={
                'page_url': mention.page_url,
                'mention_count': mention.mention_count
            }
        )

        logger.debug(f"Proposed mention: {mention.brand_term} on {mention.source_domain} (change_id={change_id})")
        return change_id

    def find_mentions(
        self,
        company_id: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[UnlinkedMention]:
        """
        Find unlinked brand mentions.

        Args:
            company_id: Specific company to scan for (None = all companies)
            limit: Maximum pages to scan (None = use default)

        Returns:
            List of unlinked mentions found
        """
        if not self.engine:
            logger.error("Cannot find mentions - database not configured")
            return []

        limit = limit or self.max_pages_per_run
        all_mentions = []

        # Start task logging
        task_id = None
        if self.task_logger:
            task_id = self.task_logger.start_task(
                task_name="unlinked_mentions_finder",
                task_type="analyzer",
                metadata={"company_id": company_id, "limit": limit}
            )

        try:
            with Session(self.engine) as session:
                # Load brand configuration
                if not company_id:
                    logger.warning("No company_id specified - skipping")
                    return []

                brand_config = self._load_brand_config(company_id, session)
                if not brand_config:
                    return []

                # Get pages to scan
                pages = self._get_competitor_pages_to_scan(session, limit)

                logger.info(f"Scanning {len(pages)} pages for mentions of {brand_config.company_name}")

                # Scan each page
                for page in pages:
                    # Skip excluded domains
                    from urllib.parse import urlparse
                    parsed = urlparse(page['url'])
                    page_domain = parsed.netloc.replace('www.', '')

                    if any(excluded in page_domain for excluded in self.exclude_domains):
                        logger.debug(f"Skipping excluded domain: {page_domain}")
                        continue

                    # Extract text
                    text = self._extract_text_from_metadata(page['metadata'])
                    if not text or len(text) < 100:
                        continue

                    # Check for brand mentions
                    mentions_found = self._check_for_brand_mentions(
                        text,
                        brand_config,
                        page['url']
                    )

                    if mentions_found:
                        # Check if page has links to our domains
                        has_link = self._has_link_to_domains(
                            page['metadata'],
                            brand_config.domains
                        )

                        if not has_link:
                            # This is an unlinked mention!
                            for brand_term, contexts in mentions_found:
                                mention = UnlinkedMention(
                                    company_id=company_id,
                                    page_url=page['url'],
                                    source_domain=page_domain,
                                    brand_term=brand_term,
                                    context_snippet=contexts[0] if contexts else "",
                                    mention_count=len(contexts),
                                    has_link_to_domain=False,
                                    discovered_at=datetime.now(),
                                    page_id=page.get('page_id')
                                )

                                # Save to database
                                self._save_mention(session, mention)
                                all_mentions.append(mention)

                                logger.info(
                                    f"Found unlinked mention: '{brand_term}' on {page_domain} "
                                    f"({mention.mention_count} times)"
                                )

                # Complete task logging
                if self.task_logger and task_id:
                    self.task_logger.complete_task(
                        task_id=task_id,
                        status="success",
                        records_processed=len(pages),
                        records_created=len(all_mentions),
                        metadata={
                            "mentions_found": len(all_mentions),
                            "brand_terms": brand_config.brand_terms
                        }
                    )

                logger.info(
                    f"Scan complete: Found {len(all_mentions)} unlinked mentions "
                    f"across {len(pages)} pages"
                )

        except Exception as e:
            logger.error(f"Error finding mentions: {e}", exc_info=True)

            if self.task_logger and task_id:
                self.task_logger.complete_task(
                    task_id=task_id,
                    status="failed",
                    error_message=str(e)
                )

            raise

        return all_mentions


def get_mentions_finder(**kwargs) -> UnlinkedMentionsFinder:
    """
    Factory function to get mentions finder instance.

    Args:
        **kwargs: Arguments to pass to UnlinkedMentionsFinder

    Returns:
        UnlinkedMentionsFinder instance
    """
    return UnlinkedMentionsFinder(**kwargs)


# CLI interface
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Find unlinked brand mentions")
    parser.add_argument("--company-id", type=int, required=True, help="Company ID to scan for")
    parser.add_argument("--limit", type=int, default=100, help="Max pages to scan")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    finder = UnlinkedMentionsFinder(max_pages_per_run=args.limit)
    mentions = finder.find_mentions(company_id=args.company_id)

    print(f"\nFound {len(mentions)} unlinked mentions:")
    for mention in mentions:
        print(f"  - {mention.brand_term} on {mention.source_domain} ({mention.mention_count}x)")
        print(f"    {mention.context_snippet[:100]}...")

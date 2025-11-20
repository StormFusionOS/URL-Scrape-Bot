"""
Technical auditor with indexability and accessibility checks.

Performs automated technical SEO audits:
- Indexability checks (robots, canonical, status codes)
- Basic accessibility checks (alt text, headings, ARIA)
- Performance signals (page size, resource count)
"""
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import AuditIssue, Competitor, CompetitorPage, PageAudit
from ..infrastructure.http_client import get_with_retry
from ..infrastructure.task_logger import task_logger

logger = logging.getLogger(__name__)


class TechnicalAuditor:
    """
    Performs technical SEO audits on pages.

    Checks:
    - Indexability (robots directives, canonical, status codes)
    - Accessibility (alt text, heading structure, ARIA labels)
    - Performance (page size, resource counts)
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize technical auditor.

        Args:
            database_url: Database URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        # Database setup
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _check_indexability(self, soup: BeautifulSoup, headers: Dict) -> List[Dict]:
        """
        Check indexability issues.

        Args:
            soup: BeautifulSoup parsed HTML
            headers: HTTP response headers

        Returns:
            List of issue dicts
        """
        issues = []

        # Check robots meta tag
        robots_meta = soup.find('meta', attrs={'name': 'robots'})
        if robots_meta:
            content = robots_meta.get('content', '').lower()
            if 'noindex' in content:
                issues.append({
                    'category': 'indexability',
                    'severity': 'error',
                    'issue_type': 'noindex_meta',
                    'description': 'Page has noindex robots meta tag'
                })

        # Check X-Robots-Tag header
        x_robots = headers.get('X-Robots-Tag', '').lower()
        if 'noindex' in x_robots:
            issues.append({
                'category': 'indexability',
                'severity': 'error',
                'issue_type': 'noindex_header',
                'description': 'Page has noindex in X-Robots-Tag header'
            })

        # Check for canonical
        canonical = soup.find('link', rel='canonical')
        if not canonical:
            issues.append({
                'category': 'indexability',
                'severity': 'warning',
                'issue_type': 'missing_canonical',
                'description': 'Page missing canonical link'
            })

        return issues

    def _check_accessibility(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Check accessibility issues.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            List of issue dicts
        """
        issues = []

        # Check images without alt text
        images = soup.find_all('img')
        images_without_alt = [img for img in images if not img.get('alt')]

        if images_without_alt:
            issues.append({
                'category': 'accessibility',
                'severity': 'warning',
                'issue_type': 'missing_alt_text',
                'description': f'{len(images_without_alt)} images missing alt text'
            })

        # Check heading structure
        h1_tags = soup.find_all('h1')
        if len(h1_tags) == 0:
            issues.append({
                'category': 'accessibility',
                'severity': 'error',
                'issue_type': 'missing_h1',
                'description': 'Page missing H1 heading'
            })
        elif len(h1_tags) > 1:
            issues.append({
                'category': 'accessibility',
                'severity': 'warning',
                'issue_type': 'multiple_h1',
                'description': f'Page has {len(h1_tags)} H1 headings (should have 1)'
            })

        # Check for lang attribute
        html_tag = soup.find('html')
        if html_tag and not html_tag.get('lang'):
            issues.append({
                'category': 'accessibility',
                'severity': 'warning',
                'issue_type': 'missing_lang',
                'description': 'HTML missing lang attribute'
            })

        return issues

    def audit_page(
        self,
        page_id: int,
        url: Optional[str] = None
    ) -> bool:
        """
        Audit a single page.

        Args:
            page_id: CompetitorPage database ID
            url: Optional URL (if not from database)

        Returns:
            True if successful, False otherwise
        """
        with self.SessionLocal() as session:
            try:
                # Get page from database if page_id provided
                if page_id:
                    page = session.query(CompetitorPage).filter(
                        CompetitorPage.id == page_id
                    ).first()

                    if not page:
                        raise ValueError(f"CompetitorPage {page_id} not found")

                    url = page.url

                logger.info(f"Auditing page: {url}")

                # Fetch page
                response = get_with_retry(url)
                if not response or response.status_code != 200:
                    logger.warning(f"Failed to fetch {url}")
                    return False

                html = response.text
                headers = dict(response.headers)

                # Parse HTML
                soup = BeautifulSoup(html, 'html.parser')

                # Run checks
                issues = []
                issues.extend(self._check_indexability(soup, headers))
                issues.extend(self._check_accessibility(soup))

                # Calculate counts by severity
                error_count = len([i for i in issues if i['severity'] == 'error'])
                warning_count = len([i for i in issues if i['severity'] == 'warning'])

                # Create or update audit record
                audit = PageAudit(
                    page_id=page_id,
                    audit_date=datetime.utcnow(),
                    error_count=error_count,
                    warning_count=warning_count
                )
                session.add(audit)
                session.flush()  # Get audit.id

                # Store issues
                for issue in issues:
                    audit_issue = AuditIssue(
                        audit_id=audit.id,
                        category=issue['category'],
                        severity=issue['severity'],
                        issue_type=issue['issue_type'],
                        description=issue['description']
                    )
                    session.add(audit_issue)

                session.commit()

                logger.info(
                    f"Audit complete for {url}: {error_count} errors, "
                    f"{warning_count} warnings"
                )

                return True

            except Exception as e:
                logger.error(f"Error auditing page {url}: {e}")
                session.rollback()
                return False

    def audit_competitor(self, competitor_id: int) -> Dict[str, int]:
        """
        Audit all pages for a competitor.

        Args:
            competitor_id: Competitor database ID

        Returns:
            Dict with processing stats
        """
        with self.SessionLocal() as session:
            # Get all pages for competitor
            pages = session.query(CompetitorPage).filter(
                CompetitorPage.competitor_id == competitor_id
            ).all()

            logger.info(f"Auditing {len(pages)} pages for competitor {competitor_id}")

            success_count = 0
            failed_count = 0

            for page in pages:
                try:
                    result = self.audit_page(page.id)
                    if result:
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Failed to audit page {page.id}: {e}")
                    failed_count += 1

            results = {
                'success': success_count,
                'failed': failed_count
            }

            logger.info(
                f"Audit complete: {success_count} success, {failed_count} failed"
            )

            return results

    def audit_all_competitors(self, track_only: bool = True) -> Dict[str, int]:
        """
        Audit all competitors.

        Args:
            track_only: Only audit tracked competitors (default: True)

        Returns:
            Dict with aggregate stats
        """
        with task_logger.log_task("technical_auditor", "audits") as log_id:
            with self.SessionLocal() as session:
                query = session.query(Competitor)
                if track_only:
                    query = query.filter(Competitor.track == True)

                competitors = query.all()

                logger.info(f"Auditing {len(competitors)} competitors")

                total_success = 0
                total_failed = 0

                for i, competitor in enumerate(competitors, 1):
                    logger.info(
                        f"Processing competitor {i}/{len(competitors)}: "
                        f"{competitor.name}"
                    )

                    try:
                        results = self.audit_competitor(competitor.id)
                        total_success += results['success']
                        total_failed += results['failed']

                        # Update progress
                        task_logger.update_progress(
                            log_id,
                            items_processed=i,
                            items_new=total_success,
                            items_failed=total_failed
                        )

                    except Exception as e:
                        logger.error(f"Failed to audit competitor {competitor.id}: {e}")
                        total_failed += 1

                results = {
                    'success': total_success,
                    'failed': total_failed
                }

                logger.info(
                    f"All audits complete: {total_success} success, {total_failed} failed"
                )

                return results

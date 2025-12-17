"""
Standardization Service - Database operations for company standardization

Handles:
- Statistics retrieval
- Pending company queries
- Company updates
- Batch processing via title fetching
"""

import os
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


def get_engine():
    """Get database engine"""
    return create_engine(os.getenv('DATABASE_URL'))


class StandardizationService:
    """Service for managing company data standardization"""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    @staticmethod
    def get_statistics() -> Dict[str, Any]:
        """Get standardization statistics"""
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    standardization_status,
                    COUNT(*) as count
                FROM companies
                WHERE verified = TRUE
                GROUP BY standardization_status
            """))

            stats = {
                'pending': 0,
                'in_progress': 0,
                'completed': 0,
                'failed': 0,
                'skipped': 0,
                'total': 0
            }

            for row in result:
                status = row[0] or 'pending'
                count = row[1]
                if status in stats:
                    stats[status] = count
                stats['total'] += count

            # Calculate percentages
            if stats['total'] > 0:
                stats['completion_percent'] = round(
                    (stats['completed'] / stats['total']) * 100, 1
                )
            else:
                stats['completion_percent'] = 0

            # Get name quality distribution
            quality_result = conn.execute(text("""
                SELECT
                    CASE
                        WHEN name_quality_score < 30 THEN 'poor'
                        WHEN name_quality_score < 60 THEN 'fair'
                        WHEN name_quality_score < 80 THEN 'good'
                        ELSE 'excellent'
                    END as quality,
                    COUNT(*) as count
                FROM companies
                WHERE verified = TRUE
                GROUP BY quality
            """))

            stats['quality_distribution'] = {}
            for row in quality_result:
                stats['quality_distribution'][row[0]] = row[1]

            return stats

    @staticmethod
    def get_pending_companies(
        limit: int = 100,
        priority: str = 'poor_names'
    ) -> List[Dict[str, Any]]:
        """Get companies pending standardization"""
        order_by = {
            'poor_names': 'name_quality_score ASC, id',
            'newest': 'verified_at DESC NULLS LAST, id',
            'oldest': 'verified_at ASC NULLS LAST, id'
        }.get(priority, 'name_quality_score ASC, id')

        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT
                    id, name, domain, address, phone, email,
                    name_quality_score, standardization_status,
                    verified_at
                FROM companies
                WHERE verified = TRUE
                AND standardization_status = 'pending'
                ORDER BY {order_by}
                LIMIT :limit
            """), {'limit': limit})

            return [dict(row._mapping) for row in result]

    @staticmethod
    def get_company_details(company_id: int) -> Optional[Dict[str, Any]]:
        """Get full details for a company"""
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    id, name, domain, address, phone, email,
                    city, state, zip_code,
                    standardized_name, standardized_name_source,
                    standardized_name_confidence,
                    name_quality_score, name_length_flag,
                    standardization_status, standardized_at,
                    verified, verified_at
                FROM companies
                WHERE id = :id
            """), {'id': company_id})

            row = result.fetchone()
            return dict(row._mapping) if row else None

    @staticmethod
    def update_standardization(
        company_id: int,
        standardized_name: Optional[str] = None,
        source: str = 'manual',
        confidence: float = 1.0,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        status: str = 'completed'
    ) -> bool:
        """Update standardization data for a company"""
        engine = get_engine()
        with engine.connect() as conn:
            try:
                conn.execute(text("""
                    UPDATE companies
                    SET
                        standardized_name = COALESCE(:std_name, standardized_name),
                        standardized_name_source = CASE
                            WHEN :std_name IS NOT NULL THEN :source
                            ELSE standardized_name_source
                        END,
                        standardized_name_confidence = CASE
                            WHEN :std_name IS NOT NULL THEN :confidence
                            ELSE standardized_name_confidence
                        END,
                        city = COALESCE(:city, city),
                        state = COALESCE(:state, state),
                        zip_code = COALESCE(:zip_code, zip_code),
                        standardization_status = :status,
                        standardized_at = NOW()
                    WHERE id = :id
                """), {
                    'id': company_id,
                    'std_name': standardized_name,
                    'source': source,
                    'confidence': confidence,
                    'city': city,
                    'state': state,
                    'zip_code': zip_code,
                    'status': status
                })
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                return False

    @staticmethod
    def mark_status(company_id: int, status: str) -> bool:
        """Update just the status for a company"""
        engine = get_engine()
        with engine.connect() as conn:
            try:
                conn.execute(text("""
                    UPDATE companies
                    SET standardization_status = :status,
                        standardized_at = NOW()
                    WHERE id = :id
                """), {'id': company_id, 'status': status})
                conn.commit()
                return True
            except Exception:
                return False

    @staticmethod
    def bulk_mark_good_names(min_score: int = 80) -> int:
        """Mark companies with good name quality as completed"""
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                UPDATE companies
                SET standardization_status = 'completed',
                    standardized_at = NOW()
                WHERE verified = TRUE
                AND standardization_status = 'pending'
                AND name_quality_score >= :min_score
            """), {'min_score': min_score})
            conn.commit()
            return result.rowcount

    @staticmethod
    def get_recent_activity(limit: int = 20) -> List[Dict[str, Any]]:
        """Get recently standardized companies"""
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    id, name, standardized_name,
                    standardized_name_source, standardization_status,
                    standardized_at, name_quality_score
                FROM companies
                WHERE standardized_at IS NOT NULL
                ORDER BY standardized_at DESC
                LIMIT :limit
            """), {'limit': limit})

            return [dict(row._mapping) for row in result]


class StandardizationWorker:
    """Worker that processes companies and standardizes their data"""

    def __init__(self, batch_size: int = 50, headless: bool = True):
        self.batch_size = batch_size
        self.headless = headless
        self.running = False
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.current_company = None
        self.log_messages = []

    def log(self, message: str):
        """Add a log message"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_messages.append(f"[{timestamp}] {message}")
        # Keep only last 100 messages
        if len(self.log_messages) > 100:
            self.log_messages = self.log_messages[-100:]

    @staticmethod
    def clean_title(title: str) -> str:
        """Clean website title to extract business name"""
        if not title:
            return ""

        cleaned = title.strip()

        # Skip generic titles
        generic_titles = ['home', 'welcome', 'homepage', 'official site', 'official website']
        if cleaned.lower() in generic_titles:
            return ""

        # Remove common suffixes
        patterns = [
            r'\s*[\|\-\u2013\u2014]\s*Home\s*$',
            r'\s*[\|\-\u2013\u2014]\s*Welcome\s*$',
            r'\s*[\|\-\u2013\u2014]\s*Official Site\s*$',
            r'\s*[\|\-\u2013\u2014]\s*Homepage\s*$',
            r'\s*-\s*$',
            r'\s*\|\s*$',
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        # Split on separators and take best part
        separators = [' | ', ' - ', ' \u2013 ', ' \u2014 ', ' :: ']
        for sep in separators:
            if sep in cleaned:
                parts = cleaned.split(sep)
                valid_parts = [
                    p.strip() for p in parts
                    if p.strip().lower() not in generic_titles
                    and len(p.strip()) >= 3
                ]
                if valid_parts:
                    cleaned = valid_parts[0]
                break

        # Skip if too long
        if len(cleaned) > 60:
            return ""

        return cleaned.strip()

    @staticmethod
    def score_name_quality(name: str) -> int:
        """Calculate name quality score (0-100)"""
        if not name:
            return 0

        score = 50  # Base score

        # Length scoring
        length = len(name)
        if length < 3:
            score -= 50
        elif length < 5:
            score -= 30
        elif length < 8:
            score -= 10
        elif length >= 15:
            score += 20
        elif length >= 10:
            score += 10

        # Word count
        words = name.split()
        if len(words) >= 3:
            score += 15
        elif len(words) >= 2:
            score += 5

        # Has proper capitalization
        if any(c.isupper() for c in name):
            score += 5

        # Penalty for all caps
        if name.isupper() and len(name) > 3:
            score -= 10

        return max(0, min(100, score))

    @staticmethod
    def parse_location_from_address(address: str) -> Dict[str, str]:
        """Parse city, state, zip from address string"""
        result = {'city': None, 'state': None, 'zip_code': None}

        if not address:
            return result

        patterns = [
            r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)',
            r'([A-Za-z\s]+),\s*([A-Za-z]+)\s*(\d{5}(?:-\d{4})?)',
            r'([A-Za-z\s]+),\s*([A-Z]{2})\s*$',
        ]

        for pattern in patterns:
            match = re.search(pattern, address)
            if match:
                result['city'] = match.group(1).strip()
                result['state'] = match.group(2).strip()
                if len(match.groups()) > 2:
                    result['zip_code'] = match.group(3)
                break

        return result

    async def fetch_title(self, page, url: str, timeout: int = 10000) -> str:
        """Fetch title from a URL"""
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            return await page.title()
        except Exception:
            return ""

    async def process_company(self, page, company: Dict[str, Any]) -> Tuple[bool, str]:
        """Process a single company"""
        company_id = company['id']
        name = company['name']
        domain = company['domain']
        address = company.get('address')
        current_score = company.get('name_quality_score', 50)

        self.current_company = name
        self.log(f"Processing: {name}")

        # Mark as in progress
        StandardizationService.mark_status(company_id, 'in_progress')

        # Parse location from address
        location = self.parse_location_from_address(address) if address else {}
        city = location.get('city')
        state = location.get('state')
        zip_code = location.get('zip_code')

        # If name is already good quality, we're done
        if current_score >= 80:
            StandardizationService.update_standardization(
                company_id,
                city=city,
                state=state,
                zip_code=zip_code,
                status='completed'
            )
            self.log(f"  Good name quality ({current_score}), marked complete")
            return True, f"Good name quality ({current_score})"

        # Try to fetch title from website
        new_name = None
        source = None
        confidence = 0.0

        if domain:
            url = f"https://{domain}" if not domain.startswith('http') else domain
            self.log(f"  Fetching: {url}")
            title = await self.fetch_title(page, url)

            if title:
                cleaned = self.clean_title(title)
                new_score = self.score_name_quality(cleaned)
                self.log(f"  Title: '{title[:50]}...' -> '{cleaned}' (score: {new_score})")

                if cleaned and new_score > current_score:
                    new_name = cleaned
                    source = 'title_fetch'
                    confidence = 0.85

        # Update the company
        StandardizationService.update_standardization(
            company_id,
            standardized_name=new_name,
            source=source or 'none',
            confidence=confidence,
            city=city,
            state=state,
            zip_code=zip_code,
            status='completed'
        )

        if new_name:
            self.log(f"  Updated name: '{new_name}'")
            return True, f"Updated name to '{new_name}'"
        else:
            self.log(f"  No improvement found")
            return True, "Location parsed, name unchanged"

    async def run_batch(self, limit: int = None, progress_callback=None) -> Dict[str, int]:
        """Process a batch of pending companies"""
        from playwright.async_api import async_playwright

        limit = limit or self.batch_size
        companies = StandardizationService.get_pending_companies(limit=limit)

        if not companies:
            return {'processed': 0, 'success': 0, 'failed': 0}

        self.running = True
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.log_messages = []

        self.log(f"Starting batch of {len(companies)} companies")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()

            for company in companies:
                if not self.running:
                    self.log("Batch stopped by user")
                    break

                try:
                    success, msg = await self.process_company(page, company)
                    self.processed += 1
                    if success:
                        self.success += 1
                    else:
                        self.failed += 1
                except Exception as e:
                    StandardizationService.mark_status(company['id'], 'failed')
                    self.processed += 1
                    self.failed += 1
                    self.log(f"  Error: {str(e)[:50]}")

                # Notify progress
                if progress_callback:
                    await progress_callback({
                        'processed': self.processed,
                        'success': self.success,
                        'failed': self.failed,
                        'total': len(companies),
                        'current': self.current_company
                    })

                # Small delay between requests
                await asyncio.sleep(0.3)

            await browser.close()

        self.running = False
        self.current_company = None
        self.log(f"Batch complete: {self.processed} processed, {self.success} success, {self.failed} failed")

        return {
            'processed': self.processed,
            'success': self.success,
            'failed': self.failed
        }

    def stop(self):
        """Stop the current batch"""
        self.running = False

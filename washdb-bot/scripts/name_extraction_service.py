#!/usr/bin/env python3
"""
Name Extraction Service - Extract real business names from websites

Uses stealth browser with Cloudflare bypass to fetch pages and
unified-washdb LLM to extract the actual business name.

Designed to fix truncated/broken names like "Pro" -> "Pro Power Wash LLC"
"""

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass
import requests

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from scripts.stealth_browser import StealthBrowser, PageData

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# LLM configuration - Use unified model for name extraction
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.getenv('OLLAMA_MODEL', 'unified-washdb-v2')  # Unified model for verification + standardization


# System prompt for name extraction - designed for standardization model
NAME_EXTRACTION_PROMPT = """You are a business name extraction assistant. Extract the EXACT official business name from the provided website data.

Look for the business name in this order of reliability:
1. JSON-LD schema "name" field (most reliable)
2. og:site_name meta tag
3. Title tag (remove suffixes like "| Home", "- Welcome")
4. H1 heading on homepage
5. Copyright notice at page bottom

RULES:
- Return ONLY the business name
- Keep legal suffixes: LLC, Inc, Corp, Co.
- Fix capitalization to Title Case
- Remove taglines and slogans
- If location is part of the name, keep it (e.g., "Austin Pressure Washing")
- If uncertain, return "UNKNOWN"

Respond with JSON: {"name": "Business Name Here", "confidence": 0.0-1.0, "source": "where found"}"""


@dataclass
class ExtractionResult:
    """Result of name extraction"""
    company_id: int
    original_name: str
    extracted_name: str
    confidence: float
    source: str
    success: bool
    error: Optional[str] = None
    cloudflare_blocked: bool = False


class NameExtractionService:
    """Service to extract business names from websites using stealth browser + LLM"""

    def __init__(self, headless: bool = False, display: str = ":99"):
        """
        Initialize the service

        Args:
            headless: Run browser in headless mode (not recommended)
            display: X11 display for headed mode (default :99 for Xvfb)
        """
        self.engine = create_engine(os.getenv('DATABASE_URL'))
        self.browser = StealthBrowser(headless=headless, display=display)
        self.processed = 0
        self.extracted = 0
        self.failed = 0
        self.cloudflare_blocked = 0

    def get_companies_needing_extraction(self, limit: int = 100) -> list:
        """Get companies with short/truncated names that need extraction"""
        with self.engine.connect() as conn:
            # Find companies with short names that are likely truncated
            # Focus on verified=true to prioritize real businesses
            result = conn.execute(text('''
                SELECT id, name, website
                FROM companies
                WHERE website IS NOT NULL
                AND LENGTH(name) <= 15
                AND (standardized_name IS NULL OR standardized_name = name)
                AND claude_verified = true
                ORDER BY LENGTH(name) ASC, id
                LIMIT :limit
            '''), {'limit': limit})

            companies = []
            for row in result:
                companies.append({
                    'id': row[0],
                    'name': row[1],
                    'website': row[2],
                })
            return companies

    def extract_name_with_llm(self, page_data: PageData, original_name: str) -> Dict[str, Any]:
        """Use standardization LLM to extract business name from page data"""
        # Build context for LLM
        context = f"""Original database name: {original_name}
Website URL: {page_data.url}
Page Title: {page_data.title}
H1 Text: {page_data.h1_text}
OG Site Name: {page_data.og_site_name}
OG Title: {page_data.og_title}
JSON-LD Name: {page_data.json_ld.get('name', 'N/A')}
JSON-LD Legal Name: {page_data.json_ld.get('legalName', 'N/A')}
Meta Description: {page_data.meta_description[:200] if page_data.meta_description else 'N/A'}
Page Text (first 500 chars): {page_data.page_text[:500] if page_data.page_text else 'N/A'}

Extract the official business name from this data."""

        # Format prompt for Mistral Instruct (standardization model format)
        prompt = f"<s>[INST] {NAME_EXTRACTION_PROMPT}\n\n{context} [/INST]"

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    'model': MODEL_NAME,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.1,
                        'num_predict': 200,
                        'top_p': 0.9,
                    }
                },
                timeout=45
            )

            response_text = response.json().get('response', '')

            # Parse JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                result = json.loads(response_text[json_start:json_end])
                name = result.get('name', 'UNKNOWN')

                # Validate extracted name
                if name and name != 'UNKNOWN' and len(name) > len(original_name):
                    return {
                        'name': name,
                        'confidence': result.get('confidence', 0.5),
                        'source': result.get('source', 'llm'),
                        'success': True,
                    }
                elif name and name != 'UNKNOWN':
                    return {
                        'name': name,
                        'confidence': result.get('confidence', 0.3),
                        'source': result.get('source', 'llm'),
                        'success': True,
                    }
                else:
                    return {
                        'name': 'UNKNOWN',
                        'confidence': 0,
                        'source': 'llm_no_result',
                        'success': False,
                    }
            else:
                # Try to extract name from non-JSON response
                name = response_text.strip().split('\n')[0].strip()
                # Clean up common artifacts
                for prefix in ['The business name is ', 'Business Name: ', 'Name: ']:
                    if name.startswith(prefix):
                        name = name[len(prefix):].strip()

                if name and len(name) < 100 and len(name) > len(original_name):
                    return {
                        'name': name,
                        'confidence': 0.3,
                        'source': 'llm_raw',
                        'success': True,
                    }
                return {
                    'name': 'UNKNOWN',
                    'confidence': 0,
                    'source': 'parse_error',
                    'success': False,
                }

        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {
                'name': 'UNKNOWN',
                'confidence': 0,
                'source': 'error',
                'success': False,
                'error': str(e),
            }

    def try_quick_extraction(self, page_data: PageData, original_name: str) -> Optional[Dict[str, Any]]:
        """Try to extract name without LLM using structured data"""
        candidates = []

        # Priority 1: JSON-LD name (most reliable)
        if page_data.json_ld.get('name'):
            name = page_data.json_ld['name'].strip()
            if len(name) > len(original_name) and len(name) < 100:
                candidates.append({
                    'name': name,
                    'confidence': 0.95,
                    'source': 'json_ld',
                })

        # Priority 1b: JSON-LD legalName
        if page_data.json_ld.get('legalName'):
            name = page_data.json_ld['legalName'].strip()
            if len(name) > len(original_name) and len(name) < 100:
                candidates.append({
                    'name': name,
                    'confidence': 0.93,
                    'source': 'json_ld_legal',
                })

        # Priority 2: OG site name
        if page_data.og_site_name:
            name = page_data.og_site_name.strip()
            if len(name) > len(original_name) and len(name) < 100:
                candidates.append({
                    'name': name,
                    'confidence': 0.85,
                    'source': 'og_site_name',
                })

        # Priority 3: Title (cleaned)
        if page_data.title:
            title = page_data.title.strip()
            # Remove common suffixes
            for suffix in [' | Home', ' - Home', ' | Welcome', ' - Welcome',
                          ' | Services', ' - Services', ' | About', ' - About',
                          ' | Contact', ' - Contact', ' | Homepage', ' - Homepage']:
                if title.lower().endswith(suffix.lower()):
                    title = title[:-len(suffix)].strip()

            # Take first part if title has separator
            for sep in [' | ', ' - ', ' – ', ' — ']:
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break

            if len(title) > len(original_name) and len(title) < 80:
                candidates.append({
                    'name': title,
                    'confidence': 0.7,
                    'source': 'title',
                })

        # Priority 4: H1 text
        if page_data.h1_text:
            h1 = page_data.h1_text.strip()
            # Filter out generic H1s
            skip_h1s = ['welcome', 'home', 'services', 'contact', 'about', 'about us']
            if (len(h1) > len(original_name) and
                len(h1) < 80 and
                h1.lower() not in skip_h1s):
                candidates.append({
                    'name': h1,
                    'confidence': 0.6,
                    'source': 'h1',
                })

        # Return best candidate
        if candidates:
            best = max(candidates, key=lambda x: x['confidence'])
            # Verify it contains original name or original is very short
            orig_lower = original_name.lower().replace(' ', '')
            best_lower = best['name'].lower().replace(' ', '')
            if orig_lower in best_lower or len(original_name) <= 5:
                return best

        return None

    def update_company_name(self, company_id: int, extracted_name: str,
                           confidence: float, source: str):
        """Update company with extracted name"""
        # Truncate source to fit VARCHAR(50)
        source_short = source[:50] if source else ''
        with self.engine.connect() as conn:
            conn.execute(text('''
                UPDATE companies
                SET standardized_name = :name,
                    standardized_name_source = :source,
                    standardized_name_confidence = :confidence,
                    name_length_flag = FALSE
                WHERE id = :id
            '''), {
                'id': company_id,
                'name': extracted_name,
                'source': source_short,
                'confidence': confidence,
            })
            conn.commit()

    def process_company(self, company: Dict[str, Any]) -> ExtractionResult:
        """Process a single company to extract its name"""
        company_id = company['id']
        original_name = company['name']
        website = company['website']

        logger.info(f"Processing: {original_name} ({website})")

        try:
            # Fetch page with stealth browser
            page_data = self.browser.fetch_page(website)

            if not page_data.success:
                # Check if Cloudflare blocked us
                if page_data.cloudflare_detected:
                    return ExtractionResult(
                        company_id=company_id,
                        original_name=original_name,
                        extracted_name=original_name,
                        confidence=0,
                        source='cloudflare_blocked',
                        success=False,
                        error='Cloudflare challenge failed',
                        cloudflare_blocked=True,
                    )
                return ExtractionResult(
                    company_id=company_id,
                    original_name=original_name,
                    extracted_name=original_name,
                    confidence=0,
                    source='fetch_failed',
                    success=False,
                    error=page_data.error,
                )

            # Try quick extraction first (no LLM)
            quick_result = self.try_quick_extraction(page_data, original_name)

            if quick_result and quick_result['confidence'] >= 0.8:
                # High confidence, use quick result
                extracted = quick_result['name']
                confidence = quick_result['confidence']
                source = quick_result['source']
            else:
                # Use LLM for extraction
                llm_result = self.extract_name_with_llm(page_data, original_name)

                if llm_result['success'] and llm_result['name'] != 'UNKNOWN':
                    extracted = llm_result['name']
                    confidence = llm_result['confidence']
                    source = f"llm_{llm_result['source']}"
                elif quick_result:
                    # Fall back to quick result
                    extracted = quick_result['name']
                    confidence = quick_result['confidence']
                    source = quick_result['source']
                else:
                    # No extraction possible
                    return ExtractionResult(
                        company_id=company_id,
                        original_name=original_name,
                        extracted_name=original_name,
                        confidence=0,
                        source='no_extraction',
                        success=False,
                    )

            # Update database
            self.update_company_name(company_id, extracted, confidence, source)

            return ExtractionResult(
                company_id=company_id,
                original_name=original_name,
                extracted_name=extracted,
                confidence=confidence,
                source=source,
                success=True,
            )

        except Exception as e:
            logger.error(f"Error processing {company_id}: {e}")
            return ExtractionResult(
                company_id=company_id,
                original_name=original_name,
                extracted_name=original_name,
                confidence=0,
                source='error',
                success=False,
                error=str(e),
            )

    def run(self, limit: int = 100, delay: float = 3.0):
        """Run the extraction service"""
        logger.info(f"Starting name extraction service (limit={limit}, model={MODEL_NAME})")

        try:
            self.browser.start()

            companies = self.get_companies_needing_extraction(limit)
            logger.info(f"Found {len(companies)} companies needing name extraction")

            for i, company in enumerate(companies):
                result = self.process_company(company)
                self.processed += 1

                if result.success:
                    self.extracted += 1
                    status = "EXTRACTED"
                elif result.cloudflare_blocked:
                    self.cloudflare_blocked += 1
                    self.failed += 1
                    status = "CF_BLOCKED"
                else:
                    self.failed += 1
                    status = "FAILED"

                logger.info(
                    f"[{i+1}/{len(companies)}] {status}: "
                    f"'{result.original_name}' -> '{result.extracted_name}' "
                    f"(conf={result.confidence:.2f}, src={result.source})"
                )

                # Delay between requests to avoid rate limiting
                if i < len(companies) - 1:
                    time.sleep(delay)

        finally:
            self.browser.stop()

        # Summary
        logger.info(f"\n=== Extraction Complete ===")
        logger.info(f"Processed: {self.processed}")
        logger.info(f"Extracted: {self.extracted}")
        logger.info(f"Failed: {self.failed}")
        logger.info(f"Cloudflare Blocked: {self.cloudflare_blocked}")

    def test_single(self, website: str, name: str = "Test"):
        """Test extraction on a single website"""
        logger.info(f"Testing extraction for: {website}")
        logger.info(f"Using model: {MODEL_NAME}")

        try:
            self.browser.start()

            page_data = self.browser.fetch_page(website)

            if not page_data.success:
                logger.error(f"Failed to fetch: {page_data.error}")
                if page_data.cloudflare_detected:
                    logger.error("Cloudflare challenge detected and failed")
                return

            logger.info(f"Page fetched successfully")
            logger.info(f"  Cloudflare detected: {page_data.cloudflare_detected}")
            logger.info(f"  Title: {page_data.title}")
            logger.info(f"  H1: {page_data.h1_text}")
            logger.info(f"  OG Site Name: {page_data.og_site_name}")
            logger.info(f"  JSON-LD Name: {page_data.json_ld.get('name', 'N/A')}")
            logger.info(f"  JSON-LD Legal Name: {page_data.json_ld.get('legalName', 'N/A')}")

            # Try quick extraction
            quick = self.try_quick_extraction(page_data, name)
            if quick:
                logger.info(f"\nQuick extraction: '{quick['name']}' (conf={quick['confidence']}, src={quick['source']})")

            # Try LLM extraction
            llm = self.extract_name_with_llm(page_data, name)
            logger.info(f"LLM extraction: '{llm['name']}' (conf={llm.get('confidence', 0)}, src={llm['source']})")

        finally:
            self.browser.stop()


def main():
    parser = argparse.ArgumentParser(description='Extract business names from websites using stealth browser + LLM')
    parser.add_argument('--limit', type=int, default=50, help='Max companies to process')
    parser.add_argument('--delay', type=float, default=3.0, help='Delay between requests (seconds)')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (not recommended)')
    parser.add_argument('--display', default=':99', help='X11 display for headed mode')
    parser.add_argument('--test', type=str, help='Test single website URL')
    parser.add_argument('--test-name', type=str, default='Test', help='Original name for test')

    args = parser.parse_args()

    service = NameExtractionService(
        headless=args.headless,
        display=args.display,
    )

    if args.test:
        service.test_single(args.test, args.test_name)
    else:
        service.run(limit=args.limit, delay=args.delay)


if __name__ == '__main__':
    main()

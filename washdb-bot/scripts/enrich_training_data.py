#!/usr/bin/env python3
"""
Enrichment Scraper for Training Data

Scrapes full website content for verified+standardized companies to create
richer training examples with actual page content instead of just signals.

Features:
- Full homepage text extraction (cleaned)
- Meta description and title
- About page detection and scraping
- Footer content extraction
- Schema.org structured data
- Progress saving (resumable)
- Rate limiting and error handling

Output:
- enriched_training_data.jsonl - Rich training examples
- enrichment_progress.json - Resume state
"""

import json
import os
import re
import time
import random
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import psycopg2
from psycopg2.extras import RealDictCursor


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

# Selenium imports
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/enrichment_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
OUTPUT_DIR = BASE_DIR / "data" / "enriched_training"
OUTPUT_DIR.mkdir(exist_ok=True)

PROGRESS_FILE = OUTPUT_DIR / "enrichment_progress.json"
OUTPUT_FILE = OUTPUT_DIR / "enriched_examples.jsonl"

# Database
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "washbot_db",
    "user": "washbot",
    "password": "Washdb123"
}

# Scraping config
MAX_CONTENT_LENGTH = 4000  # Max chars of content to include
REQUEST_DELAY = (3, 6)  # Random delay between requests
PAGE_TIMEOUT = 15  # Seconds
MAX_ERRORS_BEFORE_RESTART = 10

# System prompts for training
VERIFICATION_SYSTEM = """You are a business verification assistant. Analyze the website content and determine if this is a legitimate service provider offering exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet washing, Wood restoration.

Analyze the ACTUAL WEBSITE CONTENT provided and respond with JSON:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": {"pressure_washing": bool, "window_cleaning": bool, ...}, "reasoning": "brief explanation based on content"}"""

STANDARDIZATION_SYSTEM = """You are a business name standardization assistant. Extract the official business name from the website content.

Rules:
- Find the actual business name, not page titles or taglines
- Look in: logo text, about section, footer, contact info
- Remove legal suffixes (LLC, Inc) unless part of brand identity
- Preserve proper capitalization

Respond with ONLY the standardized business name."""


class ContentExtractor:
    """Extracts and cleans content from web pages."""

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove common noise
        noise_patterns = [
            r'cookie[s]?\s*(policy|consent|notice)',
            r'accept\s*(all\s*)?cookies',
            r'privacy\s*policy',
            r'terms\s*(of\s*service|and\s*conditions)',
            r'©\s*\d{4}',
            r'all\s*rights\s*reserved',
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    @staticmethod
    def extract_meta(driver) -> Dict[str, str]:
        """Extract meta tags."""
        meta = {}
        try:
            # Title
            meta['title'] = driver.title or ""

            # Meta description
            try:
                desc_elem = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
                meta['description'] = desc_elem.get_attribute('content') or ""
            except:
                meta['description'] = ""

            # OG title (often cleaner)
            try:
                og_title = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
                meta['og_title'] = og_title.get_attribute('content') or ""
            except:
                meta['og_title'] = ""

        except Exception as e:
            logger.debug(f"Meta extraction error: {e}")

        return meta

    @staticmethod
    def extract_schema(driver) -> Dict:
        """Extract Schema.org structured data."""
        schema_data = {}
        try:
            scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
            for script in scripts:
                try:
                    data = json.loads(script.get_attribute('innerHTML'))
                    if isinstance(data, dict):
                        schema_type = data.get('@type', '')
                        if 'LocalBusiness' in schema_type or 'Organization' in schema_type:
                            schema_data['name'] = data.get('name', '')
                            schema_data['description'] = data.get('description', '')
                            schema_data['address'] = data.get('address', {})
                            schema_data['telephone'] = data.get('telephone', '')
                            break
                except:
                    continue
        except Exception as e:
            logger.debug(f"Schema extraction error: {e}")
        return schema_data

    @staticmethod
    def extract_main_content(driver) -> str:
        """Extract main page content."""
        content_parts = []

        # Priority selectors for main content
        selectors = [
            'main',
            'article',
            '[role="main"]',
            '.main-content',
            '#main-content',
            '.content',
            '#content',
        ]

        for selector in selectors:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, selector)
                text = elem.text
                if len(text) > 200:
                    content_parts.append(text)
                    break
            except:
                continue

        # Fallback to body if no main content found
        if not content_parts:
            try:
                body = driver.find_element(By.TAG_NAME, 'body')
                content_parts.append(body.text[:5000])
            except:
                pass

        return ContentExtractor.clean_text(' '.join(content_parts))

    @staticmethod
    def extract_headers(driver) -> List[str]:
        """Extract H1 and H2 headers."""
        headers = []
        try:
            for tag in ['h1', 'h2']:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for elem in elements[:5]:  # Limit to first 5
                    text = elem.text.strip()
                    if text and len(text) < 200:
                        headers.append(text)
        except:
            pass
        return headers

    @staticmethod
    def extract_footer(driver) -> str:
        """Extract footer content (often has legal name)."""
        try:
            footer = driver.find_element(By.TAG_NAME, 'footer')
            return ContentExtractor.clean_text(footer.text[:500])
        except:
            return ""

    @staticmethod
    def extract_about_section(driver) -> str:
        """Try to find and extract about section."""
        about_selectors = [
            '#about', '.about', '[id*="about"]', '[class*="about"]',
            '#who-we-are', '.who-we-are',
            '#our-story', '.our-story',
        ]

        for selector in about_selectors:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, selector)
                text = elem.text
                if len(text) > 100:
                    return ContentExtractor.clean_text(text[:1000])
            except:
                continue
        return ""


class EnrichmentScraper:
    """Scrapes websites to enrich training data."""

    def __init__(self):
        self.driver = None
        self.error_count = 0
        self.processed = 0
        self.success = 0
        self.extractor = ContentExtractor()
        self.progress = self.load_progress()

    def load_progress(self) -> Dict:
        """Load progress from file."""
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        return {"last_id": 0, "processed": 0, "success": 0}

    def save_progress(self, last_id: int):
        """Save progress to file."""
        self.progress = {
            "last_id": last_id,
            "processed": self.processed,
            "success": self.success,
            "updated_at": datetime.now().isoformat()
        }
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def start_browser(self):
        """Start or restart browser."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

        logger.info("Starting browser...")
        self.driver = Driver(
            browser="chrome",
            headless=False,  # Headed for Xvfb
            uc=True,
            agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.error_count = 0
        time.sleep(2)

    def scrape_page(self, url: str) -> Optional[Dict]:
        """Scrape a single page and extract content."""
        try:
            self.driver.get(url)
            self.driver.implicitly_wait(PAGE_TIMEOUT)
            time.sleep(2)  # Let JS render

            # Check for blocks
            title = self.driver.title.lower() if self.driver.title else ""
            if any(x in title for x in ['captcha', 'blocked', 'forbidden', 'access denied']):
                logger.warning(f"Blocked: {url}")
                return None

            # Extract all content
            content = {
                "meta": self.extractor.extract_meta(self.driver),
                "schema": self.extractor.extract_schema(self.driver),
                "headers": self.extractor.extract_headers(self.driver),
                "main_content": self.extractor.extract_main_content(self.driver)[:MAX_CONTENT_LENGTH],
                "about": self.extractor.extract_about_section(self.driver),
                "footer": self.extractor.extract_footer(self.driver),
            }

            return content

        except TimeoutException:
            logger.warning(f"Timeout: {url}")
            return None
        except WebDriverException as e:
            logger.error(f"WebDriver error: {e}")
            self.error_count += 1
            if self.error_count >= MAX_ERRORS_BEFORE_RESTART:
                self.start_browser()
            return None
        except Exception as e:
            logger.error(f"Scrape error: {e}")
            return None

    def create_verification_example(self, company: Dict, content: Dict) -> Dict:
        """Create enriched verification training example."""
        # Build rich context
        context_parts = []

        context_parts.append(f"Company: {company['name']}")
        context_parts.append(f"Website: {company['website']}")
        context_parts.append(f"Domain: {company['domain']}")

        if company.get('phone'):
            context_parts.append(f"Phone: {company['phone']}")
        if company.get('address'):
            context_parts.append(f"Address: {company['address']}")
        if company.get('city') and company.get('state'):
            context_parts.append(f"Location: {company['city']}, {company['state']}")

        # Add actual content
        context_parts.append("")
        context_parts.append("=== WEBSITE CONTENT ===")

        if content['meta'].get('title'):
            context_parts.append(f"Page Title: {content['meta']['title']}")
        if content['meta'].get('description'):
            context_parts.append(f"Meta Description: {content['meta']['description']}")

        if content['headers']:
            context_parts.append(f"Headers: {', '.join(content['headers'][:5])}")

        if content['main_content']:
            context_parts.append(f"\nMain Content:\n{content['main_content'][:2000]}")

        if content['about']:
            context_parts.append(f"\nAbout Section:\n{content['about']}")

        if content['footer']:
            context_parts.append(f"\nFooter:\n{content['footer']}")

        if content['schema'].get('name'):
            context_parts.append(f"\nSchema.org Name: {content['schema']['name']}")

        context_parts.append("\n=== END CONTENT ===")
        context_parts.append("\nIs this a legitimate exterior cleaning service provider?")

        # Build response based on known label
        is_legit = bool(company.get('llm_verified', False))
        confidence = float(company.get('llm_confidence', 0.8) or 0.8)

        response = {
            "legitimate": is_legit,
            "confidence": round(confidence, 2),
            "services": {
                "pressure_washing": True,  # Simplified - would need real detection
                "window_cleaning": False,
            },
            "reasoning": f"Based on website content analysis. {'Appears to be a legitimate service provider.' if is_legit else 'Does not appear to be a legitimate service provider.'}"
        }

        return {
            "messages": [
                {"role": "system", "content": VERIFICATION_SYSTEM},
                {"role": "user", "content": '\n'.join(context_parts)},
                {"role": "assistant", "content": json.dumps(response, indent=2, cls=DecimalEncoder)}
            ],
            "task": "verification",
            "enriched": True,
            "company_id": company['id']
        }

    def create_standardization_example(self, company: Dict, content: Dict) -> Dict:
        """Create enriched standardization training example."""
        # Build rich context
        context_parts = []
        context_parts.append("Extract the official business name from this website:")
        context_parts.append("")
        context_parts.append(f"Original Name: {company['name']}")
        context_parts.append(f"Domain: {company['domain']}")

        if content['meta'].get('title'):
            context_parts.append(f"Page Title: {content['meta']['title']}")
        if content['meta'].get('og_title'):
            context_parts.append(f"OG Title: {content['meta']['og_title']}")

        if content['schema'].get('name'):
            context_parts.append(f"Schema.org Name: {content['schema']['name']}")

        if content['headers']:
            context_parts.append(f"Main Headers: {', '.join(content['headers'][:3])}")

        if content['main_content']:
            context_parts.append(f"\nHomepage Content:\n{content['main_content'][:1500]}")

        if content['about']:
            context_parts.append(f"\nAbout Section:\n{content['about'][:500]}")

        if content['footer']:
            context_parts.append(f"\nFooter:\n{content['footer'][:300]}")

        return {
            "messages": [
                {"role": "system", "content": STANDARDIZATION_SYSTEM},
                {"role": "user", "content": '\n'.join(context_parts)},
                {"role": "assistant", "content": company['standardized_name']}
            ],
            "task": "standardization",
            "enriched": True,
            "company_id": company['id']
        }

    def get_companies(self, limit: int = None) -> List[Dict]:
        """Get companies to scrape from database."""
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
        SELECT
            id, name, website, domain, phone, address, city, state,
            standardized_name, llm_verified, llm_confidence
        FROM companies
        WHERE llm_verified IS NOT NULL
          AND standardized_name IS NOT NULL
          AND standardized_name != ''
          AND website IS NOT NULL
          AND website != ''
          AND id > %s
        ORDER BY id
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, (self.progress.get('last_id', 0),))
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        return [dict(row) for row in rows]

    def run(self, limit: int = None):
        """Run the enrichment scraper."""
        logger.info("=" * 60)
        logger.info("ENRICHMENT SCRAPER STARTING")
        logger.info("=" * 60)

        companies = self.get_companies(limit)
        logger.info(f"Found {len(companies)} companies to scrape")

        if not companies:
            logger.info("No companies to process")
            return

        self.start_browser()

        # Open output file in append mode
        with open(OUTPUT_FILE, 'a') as f:
            for company in companies:
                try:
                    self.processed += 1

                    logger.info(f"[{self.processed}/{len(companies)}] Scraping: {company['name']} - {company['domain']}")

                    # Scrape the website
                    content = self.scrape_page(company['website'])

                    if content and content.get('main_content'):
                        # Create training examples
                        verif_example = self.create_verification_example(company, content)
                        std_example = self.create_standardization_example(company, content)

                        # Write to file
                        f.write(json.dumps(verif_example, cls=DecimalEncoder) + '\n')
                        f.write(json.dumps(std_example, cls=DecimalEncoder) + '\n')
                        f.flush()

                        self.success += 1
                        logger.info(f"  ✓ Success - content length: {len(content['main_content'])}")
                    else:
                        logger.warning(f"  ✗ No content extracted")

                    # Save progress
                    self.save_progress(company['id'])

                    # Rate limiting
                    delay = random.uniform(*REQUEST_DELAY)
                    time.sleep(delay)

                except KeyboardInterrupt:
                    logger.info("Interrupted by user")
                    break
                except Exception as e:
                    logger.error(f"Error processing {company['name']}: {e}")
                    continue

        # Cleanup
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

        logger.info("=" * 60)
        logger.info("ENRICHMENT COMPLETE")
        logger.info(f"Processed: {self.processed}")
        logger.info(f"Success: {self.success}")
        logger.info(f"Output: {OUTPUT_FILE}")
        logger.info("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Limit number of companies to scrape')
    parser.add_argument('--reset', action='store_true', help='Reset progress and start fresh')
    args = parser.parse_args()

    if args.reset and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        if OUTPUT_FILE.exists():
            OUTPUT_FILE.unlink()
        print("Progress reset")

    scraper = EnrichmentScraper()
    scraper.run(limit=args.limit)


if __name__ == "__main__":
    main()

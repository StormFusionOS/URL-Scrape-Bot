#!/usr/bin/env python3
"""
Fast Enrichment Scraper - Uses requests instead of Selenium

Much faster than Selenium version - can process ~1000 sites/hour.
Falls back gracefully if site requires JavaScript.
"""

import json
import os
import re
import time
import random
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import RealDictCursor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/enrichment_fast.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot")
OUTPUT_DIR = BASE_DIR / "data" / "enriched_training"
OUTPUT_DIR.mkdir(exist_ok=True)

PROGRESS_FILE = OUTPUT_DIR / "enrichment_fast_progress.json"
OUTPUT_FILE = OUTPUT_DIR / "enriched_examples_fast.jsonl"

# Database
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "washbot_db",
    "user": "washbot",
    "password": "Washdb123"
}

# Config
MAX_CONTENT_LENGTH = 4000
REQUEST_TIMEOUT = 10
MAX_WORKERS = 5  # Concurrent requests
BATCH_SIZE = 100

# User agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# System prompts
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


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def clean_text(text: str) -> str:
    """Clean extracted text."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    # Remove noise
    noise = ['cookie', 'privacy policy', 'terms of service', '©', 'all rights reserved']
    for n in noise:
        text = re.sub(n, '', text, flags=re.IGNORECASE)
    return text.strip()


def fetch_page(url: str) -> Optional[Dict]:
    """Fetch and parse a webpage using requests."""
    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                               allow_redirects=True, verify=False)

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script and style elements
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()

        # Extract content
        content = {
            'title': soup.title.string if soup.title else '',
            'meta_description': '',
            'headers': [],
            'main_content': '',
            'about': '',
            'footer': '',
        }

        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            content['meta_description'] = meta_desc.get('content', '')[:500]

        # Headers
        for tag in ['h1', 'h2']:
            for elem in soup.find_all(tag)[:5]:
                text = elem.get_text(strip=True)
                if text and len(text) < 200:
                    content['headers'].append(text)

        # Main content
        main = soup.find('main') or soup.find('article') or soup.find('body')
        if main:
            content['main_content'] = clean_text(main.get_text(' ', strip=True))[:MAX_CONTENT_LENGTH]

        # About section
        about = soup.find(id=re.compile('about', re.I)) or soup.find(class_=re.compile('about', re.I))
        if about:
            content['about'] = clean_text(about.get_text(' ', strip=True))[:1000]

        # Footer (re-parse since we removed it)
        soup2 = BeautifulSoup(response.text, 'html.parser')
        footer = soup2.find('footer')
        if footer:
            content['footer'] = clean_text(footer.get_text(' ', strip=True))[:500]

        return content

    except Exception as e:
        logger.debug(f"Fetch error for {url}: {e}")
        return None


def create_verification_example(company: Dict, content: Dict) -> Dict:
    """Create verification training example."""
    context_parts = [
        f"Company: {company['name']}",
        f"Website: {company['website']}",
        f"Domain: {company['domain']}",
    ]

    if company.get('phone'):
        context_parts.append(f"Phone: {company['phone']}")
    if company.get('city') and company.get('state'):
        context_parts.append(f"Location: {company['city']}, {company['state']}")

    context_parts.append("\n=== WEBSITE CONTENT ===")

    if content['title']:
        context_parts.append(f"Page Title: {content['title']}")
    if content['meta_description']:
        context_parts.append(f"Meta Description: {content['meta_description']}")
    if content['headers']:
        context_parts.append(f"Headers: {', '.join(content['headers'][:5])}")
    if content['main_content']:
        context_parts.append(f"\nMain Content:\n{content['main_content'][:2500]}")
    if content['about']:
        context_parts.append(f"\nAbout Section:\n{content['about']}")
    if content['footer']:
        context_parts.append(f"\nFooter:\n{content['footer']}")

    context_parts.append("\n=== END CONTENT ===")
    context_parts.append("\nIs this a legitimate exterior cleaning service provider?")

    is_legit = bool(company.get('llm_verified', False))
    confidence = float(company.get('llm_confidence', 0.8) or 0.8)

    response = {
        "legitimate": is_legit,
        "confidence": round(confidence, 2),
        "services": {"pressure_washing": is_legit, "window_cleaning": False},
        "reasoning": "Based on website content analysis."
    }

    return {
        "messages": [
            {"role": "system", "content": VERIFICATION_SYSTEM},
            {"role": "user", "content": '\n'.join(context_parts)},
            {"role": "assistant", "content": json.dumps(response, indent=2, cls=DecimalEncoder)}
        ],
        "task": "verification",
        "enriched": True
    }


def create_standardization_example(company: Dict, content: Dict) -> Dict:
    """Create standardization training example."""
    context_parts = [
        "Extract the official business name from this website:",
        "",
        f"Original Name: {company['name']}",
        f"Domain: {company['domain']}",
    ]

    if content['title']:
        context_parts.append(f"Page Title: {content['title']}")
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
        "enriched": True
    }


def process_company(company: Dict) -> Optional[List[Dict]]:
    """Process a single company."""
    try:
        content = fetch_page(company['website'])

        if not content or not content.get('main_content') or len(content['main_content']) < 100:
            return None

        verif = create_verification_example(company, content)
        std = create_standardization_example(company, content)

        return [verif, std]

    except Exception as e:
        logger.debug(f"Error processing {company['name']}: {e}")
        return None


def get_companies(offset: int = 0, limit: int = None) -> List[Dict]:
    """Get companies from database."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if limit:
        query = """
        SELECT id, name, website, domain, phone, city, state,
               standardized_name, llm_verified, llm_confidence
        FROM companies
        WHERE llm_verified IS NOT NULL
          AND standardized_name IS NOT NULL
          AND standardized_name != ''
          AND website IS NOT NULL
          AND website LIKE 'http%%'
        ORDER BY id
        OFFSET %s LIMIT %s
        """
        cursor.execute(query, (offset, limit))
    else:
        query = """
        SELECT id, name, website, domain, phone, city, state,
               standardized_name, llm_verified, llm_confidence
        FROM companies
        WHERE llm_verified IS NOT NULL
          AND standardized_name IS NOT NULL
          AND standardized_name != ''
          AND website IS NOT NULL
          AND website LIKE 'http%%'
        ORDER BY id
        OFFSET %s
        """
        cursor.execute(query, (offset,))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [dict(row) for row in rows]


def load_progress() -> Dict:
    """Load progress."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"offset": 0, "processed": 0, "success": 0}


def save_progress(progress: Dict):
    """Save progress."""
    progress['updated_at'] = datetime.now().isoformat()
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Limit companies')
    parser.add_argument('--reset', action='store_true', help='Reset progress')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS, help='Concurrent workers')
    args = parser.parse_args()

    if args.reset:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        if OUTPUT_FILE.exists():
            OUTPUT_FILE.unlink()
        print("Progress reset")

    progress = load_progress()

    logger.info("=" * 60)
    logger.info("FAST ENRICHMENT SCRAPER")
    logger.info("=" * 60)
    logger.info(f"Starting from offset: {progress['offset']}")

    # Get total count
    total_companies = len(get_companies(0, None))
    logger.info(f"Total companies to process: {total_companies}")

    # Process in batches
    offset = progress['offset']
    processed = progress['processed']
    success = progress['success']

    with open(OUTPUT_FILE, 'a') as f:
        while True:
            companies = get_companies(offset, BATCH_SIZE)

            if not companies:
                break

            if args.limit and processed >= args.limit:
                break

            logger.info(f"Processing batch: {offset} - {offset + len(companies)} ({processed}/{total_companies})")

            # Process with thread pool
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_company, c): c for c in companies}

                for future in as_completed(futures):
                    company = futures[future]
                    processed += 1

                    try:
                        result = future.result()
                        if result:
                            for example in result:
                                f.write(json.dumps(example, cls=DecimalEncoder) + '\n')
                            f.flush()
                            success += 1
                    except Exception as e:
                        logger.debug(f"Future error: {e}")

            offset += len(companies)
            progress = {"offset": offset, "processed": processed, "success": success}
            save_progress(progress)

            # Small delay between batches
            time.sleep(1)

    logger.info("=" * 60)
    logger.info("ENRICHMENT COMPLETE")
    logger.info(f"Processed: {processed}")
    logger.info(f"Success: {success}")
    logger.info(f"Examples generated: {success * 2}")
    logger.info("=" * 60)


if __name__ == "__main__":
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()

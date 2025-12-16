#!/usr/bin/env python3
"""
Fetch real business names from website titles for companies with poor-quality names.

This script:
1. Finds companies with low name_quality_score and flagged names
2. Fetches the website <title> tag using stealth browser (SeleniumBase UC)
3. Uses LLM (llama3.2:3b via Ollama) to extract the business name
4. Updates the standardized_name field

Usage:
    python scripts/fetch_business_names.py --limit 100 --min-score 0 --max-score 30
    python scripts/fetch_business_names.py --limit 500 --use-llm  # Use LLM extraction
    python scripts/fetch_business_names.py --limit 100 --stealth  # Use stealth browser
"""

import os
import sys
import re
import argparse
import asyncio
import json
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Try SeleniumBase for stealth browser (UC = undetected chromedriver)
try:
    from seleniumbase import Driver
    HAS_SELENIUMBASE = True
except ImportError:
    HAS_SELENIUMBASE = False

# Try playwright as fallback
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

import httpx
from bs4 import BeautifulSoup

# Ollama for LLM extraction
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2:3b"


def extract_name_with_llm(title: str, domain: str, original_name: str) -> str:
    """Use local LLM to extract business name from page title."""
    prompt = f"""Extract the business name from this website title. Return ONLY the business name, nothing else.

Website title: "{title}"
Domain: {domain}
Current name in database: "{original_name}"

Rules:
- Return the actual business name, not service descriptions
- If title is just a service description (like "Pressure Washing Services"), return "NONE"
- Remove "LLC", "Inc", location suffixes
- The name should be suitable for SEO/business listing
- Return ONLY the name, no explanation

Business name:"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 50,
                }
            },
            timeout=30.0
        )

        if response.status_code == 200:
            result = response.json()
            name = result.get("response", "").strip()

            # Clean up the response
            name = name.strip('"\'')
            name = re.sub(r'^(Business name:|Name:|The business name is:?)\s*', '', name, flags=re.IGNORECASE)
            name = name.strip()

            # Validate
            if name.upper() == "NONE" or len(name) < 3 or len(name) > 60:
                return None
            if name.lower() in ['none', 'n/a', 'unknown', 'not found']:
                return None

            return name
    except Exception as e:
        print(f"    LLM error: {e}")

    return None


def clean_title(title: str, original_name: str = None) -> str:
    """
    Clean and extract business name from page title.

    Common patterns:
    - "Business Name | Tagline"
    - "Business Name - City, State"
    - "Business Name | Pressure Washing in City"
    - "Home - Business Name"
    - "Welcome to Business Name"
    """
    if not title:
        return None

    # Remove common suffixes/prefixes
    title = title.strip()

    # Skip if title is too generic or describes services
    generic_titles = [
        'home', 'services', 'contact', 'about', 'cleaning services',
        'pressure washing', 'power washing', 'soft washing',
        'water restoration', 'fire restoration', 'damage restoration',
        'window cleaning', 'roof cleaning', 'house washing',
    ]
    if title.lower() in generic_titles:
        return None

    # Skip if title is primarily a service description (too long, starts with service type)
    service_patterns = [
        r'^(pressure|power|soft|window|roof|house|gutter|deck|fence|driveway)\s+wash',
        r'^(water|fire|storm|flood|mold)\s+(damage\s+)?(restoration|cleanup)',
        r'^(cleaning|washing|restoration)\s+services?\b',
        r'services?\s+(in|for|near)\s+',  # "Services in City"
    ]
    lower_title = title.lower()
    for pattern in service_patterns:
        if re.match(pattern, lower_title):
            return None

    # Split on common separators and take the most likely business name part
    separators = [' | ', ' - ', ' – ', ' — ', ' :: ', ' : ']
    parts = [title]
    for sep in separators:
        if sep in title:
            parts = title.split(sep)
            break

    # Generic terms to skip when looking for business name
    generic_starts = ['home', 'welcome to', 'about', 'contact', 'services', 'our']
    generic_contains = ['restoration service', 'cleaning service', 'washing service']

    best_part = None
    for part in parts:
        part = part.strip()
        lower_part = part.lower()

        # Skip empty or very short
        if len(part) < 3:
            continue

        # Skip generic parts
        if any(lower_part.startswith(g) for g in generic_starts):
            continue

        # Skip if contains generic service descriptions
        if any(g in lower_part for g in generic_contains):
            continue

        # Skip if it's just a service description
        if re.match(r'^(pressure|power|soft|window)\s+wash', lower_part):
            continue

        # Skip if too long (probably a description, not a name)
        if len(part) > 50:
            continue

        # This looks like a business name
        best_part = part
        break

    if not best_part:
        return None

    # Clean up the name
    name = best_part

    # Remove "LLC", "Inc", etc. at the end for cleaner display
    name = re.sub(r'\s+(LLC|Inc\.?|Corp\.?|Co\.?)\s*$', '', name, flags=re.IGNORECASE)

    # Remove "Welcome to" prefix
    name = re.sub(r'^Welcome\s+to\s+', '', name, flags=re.IGNORECASE)

    # Remove trailing location info like ", Austin TX" or "- City, ST"
    name = re.sub(r'[,\-]\s*[A-Za-z\s]+,?\s*[A-Z]{2}\s*$', '', name)

    # Remove trailing punctuation
    name = re.sub(r'[,\-\|:]+\s*$', '', name).strip()

    # Final length check - business names shouldn't be super long
    if len(name) > 60:
        return None

    # Final validation - make sure it's better than the original
    if original_name and len(name) <= len(original_name):
        return None

    return name.strip() if name.strip() else None


async def fetch_title_playwright(url: str, timeout: int = 15) -> str:
    """Fetch page title using Playwright (handles JS-rendered sites)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')
            title = await page.title()
            return title
        except Exception as e:
            return None
        finally:
            await browser.close()


# Global stealth browser instance (reused across batch)
_stealth_driver = None


def get_stealth_driver(headless: bool = False):
    """Get or create a stealth browser driver using SeleniumBase UC."""
    global _stealth_driver

    if _stealth_driver is None and HAS_SELENIUMBASE:
        try:
            # Use UC mode (undetected-chromedriver) with stealth settings
            # headless=False with xvfb for hidden headed browser
            _stealth_driver = Driver(
                uc=True,
                headless=headless,
                locale_code="en",
            )
            _stealth_driver.set_page_load_timeout(20)
            print("    [Stealth browser initialized]")
        except Exception as e:
            print(f"    [Failed to init stealth browser: {e}]")
            _stealth_driver = None

    return _stealth_driver


def close_stealth_driver():
    """Close the stealth browser driver."""
    global _stealth_driver
    if _stealth_driver:
        try:
            _stealth_driver.quit()
        except:
            pass
        _stealth_driver = None


def fetch_title_stealth(url: str, timeout: int = 15) -> str:
    """Fetch page title using stealth browser (SeleniumBase UC mode).

    This bypasses Cloudflare and other bot detection by using:
    - Undetected Chromedriver
    - Realistic browser fingerprint
    - Optional headed mode (hidden via xvfb)
    """
    if not HAS_SELENIUMBASE:
        return None

    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    driver = get_stealth_driver(headless=False)  # headed mode for better stealth
    if not driver:
        return None

    try:
        driver.get(url)
        time.sleep(2)  # Wait for page to settle (JS rendering, Cloudflare check)

        # Get title from the page
        title = driver.title

        # Also try to get from meta tags or JSON-LD
        if not title or title.lower() in ['', 'untitled', 'home']:
            try:
                # Try og:title
                og_title = driver.find_element("css selector", 'meta[property="og:title"]')
                if og_title:
                    title = og_title.get_attribute('content')
            except:
                pass

        return title if title else None

    except Exception as e:
        print(f"    [Stealth fetch error: {e}]")
        return None


async def fetch_title_httpx(url: str, timeout: int = 10) -> str:
    """Fetch page title using httpx (fast, but no JS)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                title_tag = soup.find('title')
                if title_tag:
                    return title_tag.get_text().strip()
        except Exception:
            pass
    return None


async def fetch_title(url: str, use_playwright: bool = False, use_stealth: bool = False) -> str:
    """Fetch page title from URL."""
    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if use_stealth and HAS_SELENIUMBASE:
        # Stealth is synchronous, run in executor
        return fetch_title_stealth(url)
    elif use_playwright and HAS_PLAYWRIGHT:
        return await fetch_title_playwright(url)
    else:
        return await fetch_title_httpx(url)


async def process_batch(companies: list, use_playwright: bool = False, use_llm: bool = False, use_stealth: bool = False) -> list:
    """Process a batch of companies (sequentially if using stealth, concurrently otherwise)."""

    # Stealth mode processes sequentially (shared browser instance)
    if use_stealth:
        results = []
        for company in companies:
            try:
                title = fetch_title_stealth(company['website'])
                results.append(title)
            except Exception as e:
                results.append(e)
    else:
        # Concurrent processing for httpx/playwright
        tasks = []
        for company in companies:
            tasks.append(fetch_title(company['website'], use_playwright, use_stealth=False))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    processed = []
    for company, result in zip(companies, results):
        if isinstance(result, Exception):
            result = None

        title = result
        cleaned_name = None

        if title:
            if use_llm:
                # Extract domain from website
                domain = company['website'].replace('http://', '').replace('https://', '').split('/')[0]
                cleaned_name = extract_name_with_llm(title, domain, company['name'])
            else:
                cleaned_name = clean_title(title, company['name'])

        processed.append({
            'id': company['id'],
            'original_name': company['name'],
            'website': company['website'],
            'raw_title': title,
            'cleaned_name': cleaned_name,
            'current_std_name': company.get('standardized_name'),
        })

    return processed


def main():
    parser = argparse.ArgumentParser(description='Fetch business names from websites')
    parser.add_argument('--limit', type=int, default=100, help='Max companies to process')
    parser.add_argument('--batch-size', type=int, default=10, help='Concurrent requests')
    parser.add_argument('--playwright', action='store_true', help='Use Playwright (slower but handles JS)')
    parser.add_argument('--stealth', action='store_true', help='Use stealth browser (SeleniumBase UC) to bypass Cloudflare')
    parser.add_argument('--use-llm', action='store_true', help='Use LLM (llama3.2:3b) for name extraction')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated')
    args = parser.parse_args()

    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)

    # Find companies needing name standardization
    # Only processes companies that haven't been standardized yet
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id, name, website, standardized_name
            FROM companies
            WHERE website IS NOT NULL
            AND website != ''
            AND (standardization_status IS NULL OR standardization_status != 'completed')
            ORDER BY id
            LIMIT :limit
        '''), {
            'limit': args.limit
        })

        companies = [dict(row._mapping) for row in result]

    if not companies:
        print("No companies found matching criteria")
        return

    # Determine fetch method
    if args.stealth:
        fetch_method = "Stealth Browser (SeleniumBase UC)"
    elif args.playwright:
        fetch_method = "Playwright"
    else:
        fetch_method = "httpx"

    print(f"Found {len(companies)} companies to process")
    print(f"Using {fetch_method} for fetching")
    if args.use_llm:
        print(f"Using LLM ({LLM_MODEL}) for name extraction")
    print("-" * 80)

    # Process in batches
    # Stealth mode: smaller batches since it's sequential
    # LLM mode: smaller batches to avoid overload
    if args.stealth:
        batch_size = min(args.batch_size, 5)  # Sequential, keep small
    elif args.use_llm:
        batch_size = min(args.batch_size, 5)
    else:
        batch_size = args.batch_size

    all_processed = []
    try:
        for i in range(0, len(companies), batch_size):
            batch = companies[i:i + batch_size]
            print(f"\nProcessing batch {i//batch_size + 1} ({len(batch)} companies)...")

            processed = asyncio.run(process_batch(batch, args.playwright, args.use_llm, args.stealth))
            all_processed.extend(processed)

            # Show progress for this batch
            for p in processed:
                if p['cleaned_name']:
                    status = "IMPROVED" if p['cleaned_name'] != p['original_name'] else "SAME"
                    print(f"  [{status}] \"{p['original_name']}\" -> \"{p['cleaned_name']}\"")
                else:
                    print(f"  [FAILED] \"{p['original_name']}\" - couldn't fetch title")

    finally:
        # Cleanup stealth browser if used
        if args.stealth:
            close_stealth_driver()
            print("\n[Stealth browser closed]")

    # Summary
    improved = [p for p in all_processed if p['cleaned_name'] and p['cleaned_name'] != p['original_name']]
    failed = [p for p in all_processed if not p['cleaned_name']]

    print("\n" + "=" * 80)
    print(f"SUMMARY: {len(improved)} improved, {len(failed)} failed, {len(all_processed) - len(improved) - len(failed)} unchanged")
    print("=" * 80)

    if args.dry_run:
        print("\n[DRY RUN] Would update:")
        for p in improved[:20]:
            print(f"  {p['id']}: \"{p['original_name']}\" -> \"{p['cleaned_name']}\"")
        if len(improved) > 20:
            print(f"  ... and {len(improved) - 20} more")
        return

    # Update database
    if improved:
        print(f"\nUpdating {len(improved)} companies in database...")
        session = Session()
        try:
            for p in improved:
                session.execute(text('''
                    UPDATE companies
                    SET standardized_name = :name,
                        standardized_name_source = 'website_title',
                        standardized_name_confidence = 0.85,
                        standardization_status = 'completed',
                        standardized_at = NOW(),
                        last_updated = NOW()
                    WHERE id = :id
                '''), {'id': p['id'], 'name': p['cleaned_name']})

            session.commit()
            print(f"Updated {len(improved)} companies!")
        except Exception as e:
            session.rollback()
            print(f"Error updating database: {e}")
        finally:
            session.close()


if __name__ == '__main__':
    main()

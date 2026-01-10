#!/usr/bin/env python3
"""
Claude Scrape + Verify - Fetch website content and verify with Claude API.

This script:
1. Fetches website HTML using requests (fast, no browser needed)
2. Extracts content using BeautifulSoup (same patterns as local LLM)
3. Sends to Claude API for verification
4. Stores both scraped content AND Claude's decision for training

Usage:
    python scripts/claude_scrape_verify.py [--limit N] [--workers N]
"""

import os
import sys
import json
import time
import logging
import argparse
import re
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import requests
import cloudscraper
from bs4 import BeautifulSoup
import anthropic
from sqlalchemy import create_engine, text
import random

# Configuration
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-3-haiku-20240307')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://washbot:Washdb123@127.0.0.1:5432/washbot_db')

# Rate limiting
REQUESTS_PER_MINUTE = 50
DELAY_BETWEEN_REQUESTS = 60.0 / REQUESTS_PER_MINUTE

# Content limits (same as local LLM)
SERVICES_TEXT_LIMIT = 2000
ABOUT_TEXT_LIMIT = 2000
HOMEPAGE_TEXT_LIMIT = 4000

# Request settings
REQUEST_TIMEOUT = 30  # Increased from 15s
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 3, 5]  # Seconds between retries

# Rotate user agents to avoid blocks
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Browser-like headers
def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }

# Cloudscraper session for anti-bot sites
_scraper = None
def get_cloudscraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
    return _scraper

# Service keywords
SERVICE_KEYWORDS = [
    "pressure wash", "power wash", "soft wash", "window clean",
    "roof clean", "gutter clean", "solar panel", "fleet wash",
    "deck", "fence", "house wash", "exterior clean"
]

# System prompt (exact same as local LLM)
SYSTEM_PROMPT = """You are a business verification assistant. Analyze the company information and determine if this is a legitimate service provider offering exterior cleaning services.

Target services: Pressure washing, Window cleaning, Soft washing, Roof cleaning, Gutter cleaning, Solar panel cleaning, Fleet/truck washing, Wood restoration.

Respond with ONLY a valid JSON object:
{"legitimate": true/false, "confidence": 0.0-1.0, "services": [], "reasoning": "brief explanation"}"""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/claude_scrape_verify.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('claude_scrape_verify')


def fetch_website(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch website HTML with retries, rotating user agents, and anti-bot bypass.

    Strategy:
    1. Try requests with browser-like headers (3 retries)
    2. If blocked (403/503), fallback to cloudscraper
    3. Try HTTP if HTTPS fails
    """
    if not url.startswith('http'):
        url = 'https://' + url

    last_error = None

    # Phase 1: Try standard requests with retries
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers=get_headers(),
                allow_redirects=True,
                verify=False  # Some small business sites have SSL issues
            )

            # Check for anti-bot blocks
            if response.status_code in (403, 503):
                if 'cloudflare' in response.text.lower() or 'captcha' in response.text.lower():
                    logger.debug(f"Anti-bot detected for {url}, will try cloudscraper")
                    break  # Exit to try cloudscraper

            response.raise_for_status()
            return response.text, response.url

        except requests.exceptions.SSLError:
            # Try HTTP fallback
            try:
                http_url = url.replace('https://', 'http://')
                response = requests.get(
                    http_url,
                    timeout=REQUEST_TIMEOUT,
                    headers=get_headers(),
                    allow_redirects=True
                )
                response.raise_for_status()
                return response.text, response.url
            except Exception as e:
                last_error = e

        except requests.exceptions.Timeout:
            last_error = "timeout"
            logger.debug(f"Timeout for {url} (attempt {attempt + 1}/{MAX_RETRIES})")

        except requests.exceptions.ConnectionError as e:
            last_error = e
            # Don't retry connection errors - site is likely down
            break

        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code in (403, 503):
                break  # Try cloudscraper
            # Don't retry 404, 500, etc.
            if e.response is not None and e.response.status_code >= 400:
                break

        except Exception as e:
            last_error = e

        # Exponential backoff between retries
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF[attempt] + random.uniform(0, 1))

    # Phase 2: Try cloudscraper for anti-bot protected sites
    try:
        scraper = get_cloudscraper()
        response = scraper.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()
        return response.text, response.url
    except Exception as e:
        logger.debug(f"Cloudscraper also failed for {url}: {e}")

    # Phase 3: Try HTTP with cloudscraper as last resort
    if url.startswith('https://'):
        try:
            http_url = url.replace('https://', 'http://')
            scraper = get_cloudscraper()
            response = scraper.get(
                http_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            return response.text, response.url
        except Exception as e:
            logger.debug(f"HTTP fallback failed for {url}: {e}")

    logger.debug(f"All fetch attempts failed for {url}: {last_error}")
    return None, None


def extract_content(html: str, url: str) -> Dict:
    """Extract content from HTML - same fields as local LLM uses."""
    soup = BeautifulSoup(html, 'html.parser')

    # Remove script and style elements
    for elem in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe']):
        elem.decompose()

    content = {}

    # Title
    title_tag = soup.find('title')
    content['title'] = title_tag.get_text().strip()[:200] if title_tag else ""

    # Meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    content['meta_description'] = meta_desc.get('content', '')[:500] if meta_desc else ""

    # H1
    h1 = soup.find('h1')
    content['h1'] = h1.get_text().strip()[:200] if h1 else ""

    # OG site name
    og_site = soup.find('meta', property='og:site_name')
    content['og_site_name'] = og_site.get('content', '')[:200] if og_site else ""

    # Services text - look for services-related content
    services_text = ""
    for keyword in ['services', 'what-we-do', 'our-services']:
        services_section = soup.find(['div', 'section'], class_=lambda x: x and keyword in x.lower() if x else False)
        if services_section:
            services_text = services_section.get_text(separator=' ', strip=True)[:SERVICES_TEXT_LIMIT]
            break

    # Also check for keywords in any text
    if not services_text:
        body = soup.find('body')
        if body:
            text = body.get_text(separator=' ', strip=True)
            for kw in SERVICE_KEYWORDS:
                if kw.lower() in text.lower():
                    # Extract surrounding context
                    idx = text.lower().find(kw.lower())
                    start = max(0, idx - 200)
                    end = min(len(text), idx + 500)
                    services_text = text[start:end]
                    break

    content['services_text'] = services_text

    # Homepage text (general body text)
    body = soup.find('body')
    if body:
        homepage_text = body.get_text(separator=' ', strip=True)
        # Clean up whitespace
        homepage_text = ' '.join(homepage_text.split())[:HOMEPAGE_TEXT_LIMIT]
        content['homepage_text'] = homepage_text
    else:
        content['homepage_text'] = ""

    # Phone numbers
    phone_pattern = r'[\(]?\d{3}[\)\-\.\s]?\d{3}[\-\.\s]?\d{4}'
    phones = re.findall(phone_pattern, html)
    content['phones'] = list(set(phones))[:3]

    # Emails
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, html)
    # Filter out common non-business emails
    emails = [e for e in emails if not any(x in e.lower() for x in ['example', 'test', 'domain', 'email'])]
    content['emails'] = list(set(emails))[:3]

    # Address (look in structured data or common patterns)
    address = ""
    # Check JSON-LD
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and 'address' in data:
                addr = data['address']
                if isinstance(addr, dict):
                    address = f"{addr.get('streetAddress', '')} {addr.get('addressLocality', '')} {addr.get('addressRegion', '')} {addr.get('postalCode', '')}"
                elif isinstance(addr, str):
                    address = addr
                break
        except:
            pass
    content['address'] = address.strip()[:200]

    return content


def build_verification_prompt(company_name: str, website: str, content: Dict) -> str:
    """Build prompt in EXACT same format as local LLM."""
    prompt = f"Company: {company_name}\n"
    prompt += f"Website: {website}\n"

    if content.get('phones'):
        prompt += f"Phone: {content['phones'][0]}\n"
    if content.get('title'):
        prompt += f"Page title: {content['title']}\n"
    if content.get('homepage_text'):
        prompt += f"\nHomepage excerpt:\n{content['homepage_text'][:HOMEPAGE_TEXT_LIMIT]}\n"
    if content.get('services_text'):
        prompt += f"\nServices page excerpt:\n{content['services_text'][:SERVICES_TEXT_LIMIT]}\n"

    prompt += "\nIs this a legitimate exterior cleaning service provider?"
    return prompt


def verify_with_claude(client: anthropic.Anthropic, prompt: str) -> Tuple[Optional[Dict], str]:
    """Call Claude API for verification."""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text

        # Parse JSON response
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(text)
        return {
            'legitimate': bool(parsed.get('legitimate', False)),
            'confidence': float(parsed.get('confidence', 0.5)),
            'services': parsed.get('services', []),
            'reasoning': str(parsed.get('reasoning', ''))
        }, raw

    except anthropic.RateLimitError:
        logger.warning("Rate limited, waiting...")
        time.sleep(60)
        return None, ""
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse Claude response")
        return None, raw if 'raw' in dir() else ""
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return None, ""


def update_company(engine, company_id: int, content: Dict, claude_result: Dict,
                   raw_response: str, user_prompt: str):
    """Update company with scraped content and Claude verification."""
    with engine.connect() as conn:
        is_legitimate = claude_result.get('legitimate', False)

        # Training data for LLM fine-tuning
        training_data = {
            'verified_at': datetime.now().isoformat(),
            'model': CLAUDE_MODEL,
            'scraped_content': content,
            'system_prompt': SYSTEM_PROMPT,
            'user_prompt': user_prompt,
            'response': {
                'legitimate': is_legitimate,
                'confidence': claude_result.get('confidence', 0.5),
                'services': claude_result.get('services', []),
                'reasoning': claude_result.get('reasoning', '')
            },
            'raw_response': raw_response
        }

        # Also store scraped content in parse_metadata for local LLM use
        scraped_metadata = {
            'title': content.get('title', ''),
            'services': content.get('services_text', ''),
            'homepage_text': content.get('homepage_text', ''),
            'phones': content.get('phones', []),
            'emails': content.get('emails', []),
            'scraped_at': datetime.now().isoformat()
        }

        conn.execute(text("""
            UPDATE companies
            SET
                verified = :verified,
                llm_verified = :llm_verified,
                claude_verified = true,
                claude_verified_at = NOW(),
                verification_type = 'claude_scraped',
                provider_status = :provider_status,
                parse_metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(parse_metadata, '{}'::jsonb),
                        '{scraped}',
                        CAST(:scraped AS jsonb)
                    ),
                    '{claude_training_data}',
                    CAST(:training_data AS jsonb)
                ),
                last_updated = NOW()
            WHERE id = :company_id
        """), {
            'company_id': company_id,
            'verified': is_legitimate,
            'llm_verified': is_legitimate,
            'provider_status': 'provider' if is_legitimate else 'non_provider',
            'scraped': json.dumps(scraped_metadata),
            'training_data': json.dumps(training_data)
        })
        conn.commit()


def update_company_failed(engine, company_id: int, company_name: str, website: str,
                          failure_reason: str):
    """
    Record failed fetch as training data - unreachable sites are not legitimate providers.
    This teaches the model that dead/unreachable websites = rejection.
    """
    with engine.connect() as conn:
        # Determine reasoning based on failure type
        if failure_reason == "fetch_failed":
            reasoning = "Website unreachable - domain may be expired, server down, or blocked"
        elif failure_reason == "no_content":
            reasoning = "Website returned no usable content - may be parked domain or empty site"
        else:
            reasoning = f"Verification failed: {failure_reason}"

        # Build a prompt as if we had content (for training consistency)
        user_prompt = f"Company: {company_name}\nWebsite: {website}\n\n[WEBSITE UNREACHABLE - No content could be retrieved]\n\nIs this a legitimate exterior cleaning service provider?"

        # Training data - model learns to reject unreachable sites
        training_data = {
            'verified_at': datetime.now().isoformat(),
            'model': 'fetch_failed',  # Mark as not from Claude
            'failure_reason': failure_reason,
            'system_prompt': SYSTEM_PROMPT,
            'user_prompt': user_prompt,
            'response': {
                'legitimate': False,
                'confidence': 0.9,  # High confidence in rejection
                'services': [],
                'reasoning': reasoning
            },
            'raw_response': None
        }

        scraped_metadata = {
            'fetch_failed': True,
            'failure_reason': failure_reason,
            'attempted_at': datetime.now().isoformat()
        }

        conn.execute(text("""
            UPDATE companies
            SET
                verified = false,
                llm_verified = false,
                claude_verified = true,
                claude_verified_at = NOW(),
                verification_type = 'fetch_failed',
                provider_status = 'unreachable',
                parse_metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(parse_metadata, '{}'::jsonb),
                        '{scraped}',
                        CAST(:scraped AS jsonb)
                    ),
                    '{claude_training_data}',
                    CAST(:training_data AS jsonb)
                ),
                last_updated = NOW()
            WHERE id = :company_id
        """), {
            'company_id': company_id,
            'scraped': json.dumps(scraped_metadata),
            'training_data': json.dumps(training_data)
        })
        conn.commit()


def get_companies(engine, limit: int = None) -> List[Dict]:
    """Get companies needing verification."""
    with engine.connect() as conn:
        query = """
            SELECT id, name, website, phone
            FROM companies
            WHERE verified IS NULL
              AND llm_verified = false
              AND website IS NOT NULL
            ORDER BY id
        """
        if limit:
            query += f" LIMIT {limit}"

        result = conn.execute(text(query))
        return [{'id': r[0], 'name': r[1], 'website': r[2], 'phone': r[3] or ''} for r in result]


def process_company(client: anthropic.Anthropic, engine, company: Dict) -> Tuple[bool, str]:
    """Process a single company: scrape + verify."""
    try:
        # Step 1: Fetch website
        html, final_url = fetch_website(company['website'])

        if not html:
            # Record fetch failure as training data
            update_company_failed(engine, company['id'], company['name'],
                                  company['website'], "fetch_failed")
            return False, "fetch_failed"

        # Step 2: Extract content
        content = extract_content(html, final_url or company['website'])

        if not content.get('homepage_text') and not content.get('title'):
            # Record no-content as training data
            update_company_failed(engine, company['id'], company['name'],
                                  company['website'], "no_content")
            return False, "no_content"

        # Step 3: Build prompt (same format as local LLM)
        prompt = build_verification_prompt(company['name'], company['website'], content)

        # Step 4: Verify with Claude
        result, raw = verify_with_claude(client, prompt)

        if not result:
            return False, "claude_failed"

        # Step 5: Update database
        update_company(engine, company['id'], content, result, raw, prompt)

        return result.get('legitimate', False), "success"

    except Exception as e:
        logger.error(f"Error processing {company['id']}: {e}")
        return False, f"error: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description='Scrape and verify with Claude')
    parser.add_argument('--limit', type=int, help='Limit number of companies')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    engine = create_engine(DATABASE_URL)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    logger.info("=" * 70)
    logger.info("CLAUDE SCRAPE + VERIFY")
    logger.info("=" * 70)
    logger.info(f"Model: {CLAUDE_MODEL}")
    logger.info(f"Limit: {args.limit or 'All'}")
    logger.info("=" * 70)

    companies = get_companies(engine, args.limit)
    logger.info(f"Found {len(companies)} companies to process")

    if args.dry_run:
        for c in companies[:5]:
            logger.info(f"  Would process: {c['id']} - {c['name']} - {c['website']}")
        return

    # Process
    verified = 0
    accepted = 0
    rejected = 0
    failed = 0
    start_time = time.time()

    for i, company in enumerate(companies):
        logger.info(f"[{i+1}/{len(companies)}] {company['name'][:40]}...")

        is_legit, status = process_company(client, engine, company)

        if status == "success":
            verified += 1
            if is_legit:
                accepted += 1
                logger.info(f"  ✓ ACCEPTED")
            else:
                rejected += 1
                logger.info(f"  ✗ REJECTED")
        else:
            failed += 1
            logger.info(f"  ! FAILED: {status}")

        time.sleep(DELAY_BETWEEN_REQUESTS)

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = verified / (elapsed / 60) if elapsed > 60 else 0
            logger.info(f"Progress: {verified} done ({accepted} acc, {rejected} rej, {failed} fail) | {rate:.1f}/min")

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Verified: {verified} ({accepted} accepted, {rejected} rejected)")
    logger.info(f"Failed: {failed}")
    logger.info(f"Time: {elapsed/60:.1f} min")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()

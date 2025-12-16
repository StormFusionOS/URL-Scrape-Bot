#!/usr/bin/env python3
"""
Bulk Name Standardization with Claude API.

This script:
1. Fetches companies that need name standardization
2. Retrieves website content (title, homepage text)
3. Sends to Claude API to extract the actual business name
4. Saves standardized names for LLM fine-tuning

Claude API analyzes the website content to infer the real business name,
not just parse an existing field.

Usage:
    python scripts/standardize_names_with_claude.py --limit 20000 --batch-size 50
"""

import os
import sys
import json
import asyncio
import logging
import argparse
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/claude_standardization.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Output directory
DATA_DIR = Path(__file__).parent.parent / "data" / "standardization"
DATA_DIR.mkdir(parents=True, exist_ok=True)


SYSTEM_PROMPT = """You are an SEO specialist extracting SEARCHABLE business names for Google and citation directories.

Your task: Extract the business name that people would use when searching for this company on Google.

SEO-FOCUSED RULES:

1. PRESERVE THE BRAND EXACTLY AS SHOWN - Do not modify:
   - "1-800-SWEEPER" stays "1-800-SWEEPER" (not "1800 Sweeper")
   - "1NolaProWash" stays "1NolaProWash" (don't add spaces)
   - "A&B Pressure Washing" stays with the ampersand
   - Special characters that are part of the brand identity

2. REMOVE ONLY LEGAL SUFFIXES:
   - LLC, L.L.C., Inc, Inc., Corp, Corp., Ltd, Ltd., Co.
   - Example: "Mike's Wash LLC" → "Mike's Wash"

3. KEEP LOCATION QUALIFIERS if they identify the business:
   - "Window Genie of North Dallas" - KEEP (franchise location)
   - "Austin Power Wash" - KEEP (location is part of brand)
   - "Pressure Washing Services - Austin TX" - Extract just "Pressure Washing Services" if generic

4. REMOVE TRAILING DESCRIPTIVE PHRASES:
   - "Mike's Wash - Professional Pressure Washing Services" → "Mike's Wash"
   - "Clean Pro | Best Pressure Washing in Texas" → "Clean Pro"
   - But keep if integral: "Mike's Pressure Washing" → "Mike's Pressure Washing"

5. WHAT TO EXTRACT:
   - The name people would type in Google to find this business
   - The name that would appear in citation directories (Yelp, BBB, etc.)
   - Usually found in: logo, title tag, homepage heading, or domain

OUTPUT FORMAT:
Respond with ONLY a JSON object:
{
    "business_name": "The Searchable Name" or null if cannot determine,
    "confidence": 0.0-1.0,
    "source": "title" or "content" or "domain",
    "reasoning": "Brief explanation"
}"""


async def fetch_website_content(url: str, timeout: float = 15.0) -> Dict:
    """
    Fetch website content including title and text.

    Returns dict with title, homepage_text, domain, success status.
    """
    result = {
        'url': url,
        'success': False,
        'title': None,
        'homepage_text': None,
        'domain': None,
        'error': None
    }

    try:
        # Parse domain
        parsed = urlparse(url)
        result['domain'] = parsed.netloc.replace('www.', '')

        # Fetch with redirects
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            verify=False  # Some sites have SSL issues
        ) as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                result['error'] = f"HTTP {response.status_code}"
                return result

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract title
            title_tag = soup.find('title')
            if title_tag:
                result['title'] = title_tag.get_text(strip=True)[:500]

            # Extract visible text (limited)
            # Remove script and style elements
            for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()

            # Get text from body
            body = soup.find('body')
            if body:
                text = body.get_text(separator=' ', strip=True)
                # Clean up whitespace
                text = ' '.join(text.split())
                result['homepage_text'] = text[:2000]  # Limit for API cost

            result['success'] = True

    except Exception as e:
        result['error'] = str(e)[:200]

    return result


async def extract_name_with_claude(
    company_name: str,
    url: str,
    title: str,
    homepage_text: str,
    domain: str,
    client: httpx.AsyncClient,
    api_key: str,
    model: str = "claude-3-haiku-20240307"
) -> Dict:
    """
    Call Claude API to extract standardized business name.
    """
    # Build context
    user_content = f"""Analyze this website and extract the business name:

Current Database Name: {company_name}
URL: {url}
Domain: {domain}

Website Title: {title or 'Not found'}

Homepage Content (first 2000 chars):
{homepage_text or 'Not available'}

Extract the actual business name from this content."""

    try:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": model,
                "max_tokens": 200,
                "temperature": 0.0,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}]
            },
            timeout=30.0
        )

        if response.status_code != 200:
            return {
                'success': False,
                'error': f"API error: {response.status_code}",
                'raw': response.text
            }

        data = response.json()
        content = data['content'][0]['text']

        # Parse JSON response
        try:
            # Find JSON in response
            if '{' in content:
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                result = json.loads(content[json_start:json_end])
                result['success'] = True
                result['tokens_in'] = data['usage']['input_tokens']
                result['tokens_out'] = data['usage']['output_tokens']
                return result
        except json.JSONDecodeError:
            pass

        return {
            'success': False,
            'error': 'Could not parse JSON response',
            'raw': content
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


async def process_batch(
    companies: List[Dict],
    api_key: str,
    model: str,
    semaphore: asyncio.Semaphore
) -> List[Dict]:
    """Process a batch of companies concurrently."""
    results = []

    async with httpx.AsyncClient() as client:
        async def process_one(company: Dict) -> Dict:
            async with semaphore:
                company_id = company['id']
                name = company['name']
                url = company['website']

                result = {
                    'company_id': company_id,
                    'original_name': name,
                    'url': url,
                    'standardized_name': None,
                    'confidence': 0.0,
                    'source': None,
                    'error': None
                }

                try:
                    # Fetch website
                    web_data = await fetch_website_content(url)

                    if not web_data['success']:
                        result['error'] = f"Fetch failed: {web_data['error']}"
                        return result

                    # Call Claude
                    claude_result = await extract_name_with_claude(
                        company_name=name,
                        url=url,
                        title=web_data['title'],
                        homepage_text=web_data['homepage_text'],
                        domain=web_data['domain'],
                        client=client,
                        api_key=api_key,
                        model=model
                    )

                    if claude_result.get('success'):
                        result['standardized_name'] = claude_result.get('business_name')
                        result['confidence'] = claude_result.get('confidence', 0.0)
                        result['source'] = claude_result.get('source')
                        result['reasoning'] = claude_result.get('reasoning')
                        result['tokens_in'] = claude_result.get('tokens_in', 0)
                        result['tokens_out'] = claude_result.get('tokens_out', 0)

                        # Include website data for training
                        result['title'] = web_data['title']
                        result['homepage_text'] = web_data['homepage_text'][:500]
                        result['domain'] = web_data['domain']
                    else:
                        result['error'] = claude_result.get('error')

                except Exception as e:
                    result['error'] = str(e)

                return result

        # Process concurrently
        tasks = [process_one(c) for c in companies]
        results = await asyncio.gather(*tasks)

    return results


def get_companies_to_process(engine, limit: int, offset: int = 0) -> List[Dict]:
    """Get companies that need standardization."""
    query = text("""
        SELECT id, name, website
        FROM companies
        WHERE verified = TRUE
          AND website IS NOT NULL
          AND (standardized_name IS NULL OR standardized_name_source != 'claude')
          AND LENGTH(name) <= 5  -- Prioritize short names (abbreviations)
        ORDER BY LENGTH(name) ASC, id ASC
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {'limit': limit, 'offset': offset})
        return [{'id': r[0], 'name': r[1], 'website': r[2]} for r in result]


def get_companies_all(engine, limit: int, offset: int = 0) -> List[Dict]:
    """Get all companies needing standardization (not just short names)."""
    query = text("""
        SELECT id, name, website
        FROM companies
        WHERE verified = TRUE
          AND website IS NOT NULL
          AND (standardized_name IS NULL OR standardized_name_source != 'claude')
        ORDER BY id ASC
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {'limit': limit, 'offset': offset})
        return [{'id': r[0], 'name': r[1], 'website': r[2]} for r in result]


def save_results_to_db(engine, results: List[Dict]):
    """Save standardization results to database."""
    update_query = text("""
        UPDATE companies
        SET standardized_name = :std_name,
            standardized_name_source = 'claude',
            standardized_name_confidence = :confidence
        WHERE id = :company_id
    """)

    updated = 0
    with engine.connect() as conn:
        for r in results:
            if r.get('standardized_name'):
                conn.execute(update_query, {
                    'company_id': r['company_id'],
                    'std_name': r['standardized_name'],
                    'confidence': r.get('confidence', 0.0)
                })
                updated += 1
        conn.commit()

    return updated


def save_training_data(results: List[Dict], output_path: Path):
    """Save results as training data for fine-tuning."""
    training_samples = []

    for r in results:
        if r.get('standardized_name') and r.get('title'):
            # Format: prompt -> completion
            sample = {
                'prompt': f"Extract business name:\nTitle: {r.get('title', '')}\nDomain: {r.get('domain', '')}\nHomepage: {r.get('homepage_text', '')[:300]}",
                'completion': r['standardized_name']
            }
            training_samples.append(sample)

    with open(output_path, 'a') as f:
        for sample in training_samples:
            f.write(json.dumps(sample) + '\n')

    return len(training_samples)


async def main():
    parser = argparse.ArgumentParser(description='Standardize names with Claude API')
    parser.add_argument('--limit', type=int, default=20000, help='Total companies to process')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    parser.add_argument('--concurrency', type=int, default=10, help='Concurrent requests')
    parser.add_argument('--model', default='claude-3-haiku-20240307', help='Claude model')
    parser.add_argument('--short-names-only', action='store_true', help='Only process short names')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to database')
    args = parser.parse_args()

    # Check API key
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key or api_key == 'your-api-key-here':
        logger.error("ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("CLAUDE NAME STANDARDIZATION")
    logger.info("=" * 60)
    logger.info(f"Limit: {args.limit}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Concurrency: {args.concurrency}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Dry run: {args.dry_run}")

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))

    # Output file for training data
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    training_file = DATA_DIR / f"claude_standardization_{timestamp}.jsonl"

    # Stats
    total_processed = 0
    total_standardized = 0
    total_errors = 0
    total_tokens_in = 0
    total_tokens_out = 0

    # Semaphore for concurrency control
    semaphore = asyncio.Semaphore(args.concurrency)

    offset = 0
    while total_processed < args.limit:
        # Get batch
        batch_limit = min(args.batch_size, args.limit - total_processed)

        if args.short_names_only:
            companies = get_companies_to_process(engine, batch_limit, offset)
        else:
            companies = get_companies_all(engine, batch_limit, offset)

        if not companies:
            logger.info("No more companies to process")
            break

        logger.info(f"\nProcessing batch: {len(companies)} companies (offset {offset})")

        # Process batch
        results = await process_batch(companies, api_key, args.model, semaphore)

        # Count results
        batch_standardized = sum(1 for r in results if r.get('standardized_name'))
        batch_errors = sum(1 for r in results if r.get('error'))
        batch_tokens_in = sum(r.get('tokens_in', 0) for r in results)
        batch_tokens_out = sum(r.get('tokens_out', 0) for r in results)

        total_processed += len(results)
        total_standardized += batch_standardized
        total_errors += batch_errors
        total_tokens_in += batch_tokens_in
        total_tokens_out += batch_tokens_out

        logger.info(f"  Standardized: {batch_standardized}/{len(results)}, Errors: {batch_errors}")
        logger.info(f"  Tokens: {batch_tokens_in} in, {batch_tokens_out} out")

        # Save to database
        if not args.dry_run:
            updated = save_results_to_db(engine, results)
            logger.info(f"  Database updated: {updated}")

        # Save training data
        saved = save_training_data(results, training_file)
        logger.info(f"  Training samples saved: {saved}")

        # Log some examples
        for r in results[:3]:
            if r.get('standardized_name'):
                logger.info(f"    {r['original_name']!r} -> {r['standardized_name']!r} ({r.get('confidence', 0):.2f})")

        offset += len(companies)

        # Rate limiting delay
        await asyncio.sleep(0.5)

    # Final stats
    logger.info("\n" + "=" * 60)
    logger.info("COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total processed: {total_processed}")
    logger.info(f"Total standardized: {total_standardized}")
    logger.info(f"Total errors: {total_errors}")
    logger.info(f"Total tokens: {total_tokens_in:,} in, {total_tokens_out:,} out")

    # Estimate cost (Haiku pricing)
    cost_in = (total_tokens_in / 1_000_000) * 0.25  # $0.25/M input
    cost_out = (total_tokens_out / 1_000_000) * 1.25  # $1.25/M output
    total_cost = cost_in + cost_out
    logger.info(f"Estimated cost: ${total_cost:.2f}")

    logger.info(f"\nTraining data saved to: {training_file}")


if __name__ == '__main__':
    asyncio.run(main())

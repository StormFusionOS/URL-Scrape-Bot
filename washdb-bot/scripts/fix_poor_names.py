#!/usr/bin/env python3
"""
Fix Poor Names - Fetch website titles for companies with low-quality names.

This script does a lightweight fetch of just the <title> tag to get better
business names without a full re-scrape.

Usage:
    ./venv/bin/python scripts/fix_poor_names.py [--limit 100] [--dry-run]
"""

import os
import sys
import re
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from playwright.async_api import async_playwright

from scrape_yp.name_standardizer import (
    score_name_quality,
    infer_name_from_domain,
    needs_standardization,
)


def clean_title(title: str, domain: str) -> str:
    """Clean website title to extract business name."""
    if not title:
        return ""

    cleaned = title.strip()

    # Skip generic titles
    generic_titles = ['home', 'welcome', 'homepage', 'official site', 'official website']
    if cleaned.lower() in generic_titles:
        return ""

    # Remove common suffixes
    patterns = [
        r'\s*[\|\-–—]\s*Home\s*$',
        r'\s*[\|\-–—]\s*Welcome\s*$',
        r'\s*[\|\-–—]\s*Official Site\s*$',
        r'\s*[\|\-–—]\s*Official Website\s*$',
        r'\s*[\|\-–—]\s*Homepage\s*$',
        r'\s*-\s*$',
        r'\s*\|\s*$',
    ]

    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Split on common separators and take the best part
    separators = [' | ', ' - ', ' – ', ' — ', ' :: ']
    for sep in separators:
        if sep in cleaned:
            parts = cleaned.split(sep)
            # Score each part and pick the best one
            best_part = None
            best_score = 0
            for part in parts:
                part = part.strip()
                # Skip generic parts
                if part.lower() in generic_titles:
                    continue
                # Skip location-only parts
                if re.match(r'^[A-Z][a-z]+,?\s*[A-Z]{2}$', part):
                    continue
                score = score_name_quality(part)
                if score > best_score and len(part) >= 3:
                    best_score = score
                    best_part = part
            if best_part:
                cleaned = best_part
            break

    # Remove location suffixes like "Austin, TX" or "| Austin Texas"
    cleaned = re.sub(r'\s*[\|\-–—,]\s*[A-Z][a-z]+,?\s*[A-Z]{2}\s*$', '', cleaned)

    # If the result is still too long (over 50 chars), it's probably not a clean name
    if len(cleaned) > 60:
        return ""

    return cleaned.strip()


async def fetch_title(page, url: str, timeout: int = 10000) -> str:
    """Fetch just the title from a URL."""
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
        title = await page.title()
        return title
    except Exception as e:
        return ""


async def fix_poor_names(limit: int = 100, dry_run: bool = False, min_score: int = 50):
    """
    Fix companies with poor-quality names by fetching website titles.

    Args:
        limit: Max companies to process
        dry_run: If True, don't update database
        min_score: Only process companies with score below this
    """
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    # Get companies with poor names
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, name, domain, name_quality_score
            FROM companies
            WHERE verified = TRUE
            AND domain IS NOT NULL
            AND name_quality_score < :min_score
            AND (standardized_name IS NULL OR standardized_name = name)
            ORDER BY name_quality_score ASC
            LIMIT :limit
        """), {'min_score': min_score, 'limit': limit})

        companies = result.fetchall()

    if not companies:
        print("No companies with poor names found!")
        return

    print(f"Found {len(companies)} companies with poor names (score < {min_score})")
    print()

    updated = 0
    failed = 0
    skipped = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()

        for company in companies:
            company_id = company[0]
            current_name = company[1]
            domain = company[2]
            current_score = company[3]

            # Build URL
            url = f"https://{domain}" if not domain.startswith('http') else domain

            print(f"[{company_id}] \"{current_name}\" (score: {current_score})")
            print(f"  Fetching: {url}")

            # Fetch title
            title = await fetch_title(page, url)

            if not title:
                print(f"  -> Failed to fetch title")
                failed += 1
                continue

            # Clean the title
            cleaned_name = clean_title(title, domain)
            new_score = score_name_quality(cleaned_name)

            print(f"  Title: \"{title}\"")
            print(f"  Cleaned: \"{cleaned_name}\" (score: {new_score})")

            # Only update if new name is better
            if new_score <= current_score:
                # Try domain inference as fallback
                inferred = infer_name_from_domain(domain)
                inferred_score = score_name_quality(inferred)

                if inferred_score > new_score:
                    cleaned_name = inferred
                    new_score = inferred_score
                    print(f"  Domain inferred: \"{cleaned_name}\" (score: {new_score})")

            if new_score <= current_score:
                print(f"  -> Skipped (no improvement)")
                skipped += 1
                continue

            # Update database
            if not dry_run:
                with engine.connect() as conn:
                    conn.execute(text("""
                        UPDATE companies
                        SET standardized_name = :new_name,
                            standardized_name_source = 'title_fetch',
                            standardized_name_confidence = 0.85
                        WHERE id = :id
                    """), {'id': company_id, 'new_name': cleaned_name})
                    conn.commit()

            print(f"  -> Updated: \"{cleaned_name}\"")
            updated += 1

            # Small delay to be nice to servers
            await asyncio.sleep(0.5)

        await browser.close()

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Processed: {len(companies)}")
    print(f"  Updated:   {updated}")
    print(f"  Failed:    {failed}")
    print(f"  Skipped:   {skipped}")
    if dry_run:
        print("  (DRY RUN - no changes made)")


def main():
    parser = argparse.ArgumentParser(
        description='Fix poor-quality business names by fetching website titles'
    )
    parser.add_argument('--limit', '-l', type=int, default=100,
                        help='Max companies to process (default: 100)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Preview without updating database')
    parser.add_argument('--min-score', '-s', type=int, default=50,
                        help='Process names with score below this (default: 50)')
    args = parser.parse_args()

    asyncio.run(fix_poor_names(
        limit=args.limit,
        dry_run=args.dry_run,
        min_score=args.min_score
    ))


if __name__ == '__main__':
    main()

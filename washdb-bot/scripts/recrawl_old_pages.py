#!/usr/bin/env python3
"""
Re-crawl old competitor pages that don't have main_text or embeddings.

This script:
1. Finds competitor_pages without main_text (old crawls)
2. Re-fetches each URL to get fresh HTML
3. Extracts main_text and stores it
4. Generates embeddings and stores in Qdrant
5. Updates freshness metadata

Usage:
    python scripts/recrawl_old_pages.py [--limit N] [--dry-run] [--delay SECONDS]
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seo_intelligence.services import (
    get_content_embedder,
    get_qdrant_manager,
    extract_main_content
)
from seo_intelligence.services.section_embedder import SectionEmbedder

load_dotenv()


def create_sections_from_text(text: str, chunk_size: int = 500) -> list:
    """
    Create sections from plain text by splitting into chunks.

    Returns:
        List of section dicts with heading, content, word_count, heading_level
    """
    if not text:
        return []

    # Split by paragraphs or double newlines
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    sections = []
    current_chunk = []
    current_words = 0
    section_num = 1

    for para in paragraphs:
        words = len(para.split())

        if current_words + words > chunk_size and current_chunk:
            # Save current chunk as section
            content = '\n\n'.join(current_chunk)
            sections.append({
                'heading': f'Section {section_num}',
                'content': content,
                'word_count': current_words,
                'heading_level': 2
            })
            section_num += 1
            current_chunk = [para]
            current_words = words
        else:
            current_chunk.append(para)
            current_words += words

    # Add remaining content
    if current_chunk:
        content = '\n\n'.join(current_chunk)
        sections.append({
            'heading': f'Section {section_num}',
            'content': content,
            'word_count': current_words,
            'heading_level': 2
        })

    return sections


def fetch_page_content(url: str, timeout: int = 30) -> tuple[str, str]:
    """
    Fetch page HTML and extract main text.

    Returns:
        Tuple of (html_content, main_text)
    """
    import requests
    from bs4 import BeautifulSoup

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        html = response.text

        # Extract main text
        main_text = extract_main_content(html)

        return html, main_text

    except Exception as e:
        raise Exception(f"Failed to fetch {url}: {e}")


def recrawl_old_pages(limit: int = 50, dry_run: bool = False, delay: float = 2.0):
    """Re-crawl old pages that need main_text and embeddings."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return

    engine = create_engine(database_url)
    embedder = get_content_embedder()
    qdrant = get_qdrant_manager()
    section_embedder = SectionEmbedder()

    if not embedder.is_available():
        print("ERROR: Embedding service unavailable")
        return

    print(f"Embedding model: {embedder.embedder.model_name}")
    print(f"Qdrant healthy: {qdrant.health_check()}")
    print(f"Delay between requests: {delay}s")

    # Find pages without main_text (old crawls that need re-crawling)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                cp.page_id,
                cp.url,
                cp.page_type,
                cp.competitor_id,
                c.domain as competitor_domain
            FROM competitor_pages cp
            LEFT JOIN competitors c ON cp.competitor_id = c.competitor_id
            WHERE cp.main_text IS NULL
              AND cp.url IS NOT NULL
              AND cp.url != ''
            ORDER BY cp.page_id ASC
            LIMIT :limit
        """), {"limit": limit})

        pages = result.fetchall()

    print(f"Found {len(pages)} pages to re-crawl")

    if dry_run:
        print("\nDRY RUN - not making changes")
        for page in pages[:10]:
            print(f"  Would re-crawl: {page.url}")
        if len(pages) > 10:
            print(f"  ... and {len(pages) - 10} more")
        return

    success_count = 0
    error_count = 0
    skip_count = 0

    for i, page in enumerate(pages):
        try:
            print(f"\n[{i+1}/{len(pages)}] Re-crawling page {page.page_id}: {page.url[:60]}...")

            # Fetch page content
            html_content, main_text = fetch_page_content(page.url)

            if not main_text or len(main_text.strip()) < 50:
                print(f"  Skipping - insufficient content ({len(main_text) if main_text else 0} chars)")
                skip_count += 1
                time.sleep(delay)
                continue

            print(f"  Fetched {len(main_text)} chars of main text")

            # Generate page embedding
            chunks, embeddings = embedder.embed_content(main_text)

            if not chunks or not embeddings:
                print(f"  Skipping - embedding failed")
                error_count += 1
                time.sleep(delay)
                continue

            print(f"  Generated {len(chunks)} chunks")

            # Store page embedding in Qdrant
            qdrant.upsert_competitor_page(
                page_id=page.page_id,
                site_id=page.competitor_id or 0,
                url=page.url,
                title="",  # We don't have the title from simple fetch
                page_type=page.page_type or 'unknown',
                vector=embeddings[0]
            )

            # Store section embeddings
            sections = create_sections_from_text(main_text)
            if sections:
                section_count = section_embedder.embed_and_store_sections(
                    page_id=page.page_id,
                    site_id=page.competitor_id or 0,
                    url=page.url,
                    page_type=page.page_type or 'unknown',
                    sections=sections
                )
                print(f"  Stored {section_count} section embeddings")
            else:
                print(f"  No sections created")

            # Update database with main_text, embedding info, and freshness
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE competitor_pages
                    SET main_text = :main_text,
                        embedding_version = :version,
                        embedded_at = NOW(),
                        embedding_chunk_count = :chunk_count,
                        last_verified_at = NOW(),
                        crawl_age_bucket = 'fresh',
                        data_confidence = 1.0
                    WHERE page_id = :page_id
                """), {
                    "main_text": main_text[:50000] if main_text else None,
                    "version": os.getenv("EMBEDDING_VERSION", "v1.0"),
                    "chunk_count": len(chunks),
                    "page_id": page.page_id
                })
                conn.commit()

            success_count += 1
            print(f"  ✓ Successfully re-crawled and embedded")

            # Rate limiting delay
            if i < len(pages) - 1:
                time.sleep(delay)

        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            time.sleep(delay)

    print(f"\n{'='*60}")
    print(f"Re-crawl complete:")
    print(f"  Success: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Errors:  {error_count}")

    # Show Qdrant stats
    stats = qdrant.get_collection_stats('competitor_pages')
    print(f"\nQdrant competitor_pages: {stats['points_count']} vectors")

    section_stats = qdrant.get_collection_stats('content_sections')
    print(f"Qdrant content_sections: {section_stats['points_count']} vectors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-crawl old competitor pages")
    parser.add_argument("--limit", type=int, default=50, help="Max pages to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't make changes")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests (seconds)")

    args = parser.parse_args()
    recrawl_old_pages(limit=args.limit, dry_run=args.dry_run, delay=args.delay)

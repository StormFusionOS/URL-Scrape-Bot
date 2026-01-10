#!/usr/bin/env python3
"""
Backfill embeddings for existing competitor pages that don't have embeddings.

This script:
1. Finds competitor_pages without embedding_version set
2. Fetches the page HTML from metadata or re-crawls
3. Generates embeddings and stores in Qdrant
4. Updates the database with embedding metadata

Usage:
    python scripts/backfill_embeddings.py [--limit N] [--dry-run]
"""

import os
import sys
import json
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

load_dotenv()


def backfill_embeddings(limit: int = 100, dry_run: bool = False):
    """Backfill embeddings for existing competitor pages."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return

    engine = create_engine(database_url)
    embedder = get_content_embedder()
    qdrant = get_qdrant_manager()

    if not embedder.is_available():
        print("ERROR: Embedding service unavailable")
        return

    print(f"Embedding model: {embedder.embedder.model_name}")
    print(f"Qdrant healthy: {qdrant.health_check()}")

    # Find pages without embeddings that have HTML content in metadata or main_text
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                page_id,
                url,
                page_type,
                competitor_id,
                metadata,
                main_text
            FROM competitor_pages
            WHERE embedding_version IS NULL
            ORDER BY page_id ASC
            LIMIT :limit
        """), {"limit": limit})

        pages = result.fetchall()

    print(f"Found {len(pages)} pages to process")

    if dry_run:
        print("DRY RUN - not making changes")
        for page in pages[:5]:
            print(f"  Would process: {page.url}")
        return

    success_count = 0
    error_count = 0
    skip_count = 0

    for page in pages:
        try:
            # Get HTML from metadata if available
            # Handle both dict (JSONB) and string (JSON) metadata
            if isinstance(page.metadata, dict):
                metadata = page.metadata
            elif page.metadata:
                metadata = json.loads(page.metadata)
            else:
                metadata = {}
            html_content = metadata.get('html_content', '')

            # Try to get main_text from: 1) Extract from HTML, 2) Use stored main_text column
            main_text = None
            if html_content:
                main_text = extract_main_content(html_content)
            elif page.main_text:
                # Use the stored main_text column
                main_text = page.main_text

            if not main_text:
                print(f"  Skipping {page.page_id} - no HTML content or main_text (needs re-crawl)")
                skip_count += 1
                continue

            if len(main_text.strip()) < 50:
                print(f"  Skipping {page.page_id} - insufficient content ({len(main_text) if main_text else 0} chars)")
                skip_count += 1
                continue

            # Generate embedding
            chunks, embeddings = embedder.embed_content(main_text)

            if not chunks or not embeddings:
                print(f"  Skipping {page.page_id} - embedding failed")
                error_count += 1
                continue

            # Store in Qdrant
            qdrant.upsert_competitor_page(
                page_id=page.page_id,
                site_id=page.competitor_id,
                url=page.url,
                title=metadata.get('title', ''),
                page_type=page.page_type or 'unknown',
                vector=embeddings[0]
            )

            # Update database
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE competitor_pages
                    SET embedding_version = :version,
                        embedded_at = NOW(),
                        embedding_chunk_count = :chunk_count
                    WHERE page_id = :page_id
                """), {
                    "version": os.getenv("EMBEDDING_VERSION", "v1.0"),
                    "chunk_count": len(chunks),
                    "page_id": page.page_id
                })
                conn.commit()

            success_count += 1
            print(f"  Embedded page {page.page_id}: {page.url[:50]}... ({len(chunks)} chunks)")

        except Exception as e:
            print(f"  Error processing page {page.page_id}: {e}")
            error_count += 1

    print(f"\nBackfill complete: {success_count} success, {skip_count} skipped (need re-crawl), {error_count} errors")

    # Show Qdrant stats
    stats = qdrant.get_collection_stats('competitor_pages')
    print(f"Qdrant competitor_pages: {stats['points_count']} vectors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill embeddings for competitor pages")
    parser.add_argument("--limit", type=int, default=100, help="Max pages to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't make changes")

    args = parser.parse_args()
    backfill_embeddings(limit=args.limit, dry_run=args.dry_run)

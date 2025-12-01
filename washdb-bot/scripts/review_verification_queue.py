#!/usr/bin/env python3
"""
CLI tool for reviewing verification queue items.

Displays companies that need manual review and allows setting human labels.

Usage:
    python scripts/review_verification_queue.py [--limit N] [--filter STATUS]

Options:
    --limit N           Number of items to review (default: 50)
    --filter STATUS     Filter by status: needs_review, failed, all (default: needs_review)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runner.logging_setup import get_logger

load_dotenv()

logger = get_logger("review_queue")

# Valid human labels
VALID_LABELS = {
    'p': 'provider',
    'n': 'non_provider',
    'd': 'directory',
    'a': 'agency',
    'b': 'blog',
    'f': 'franchise',
}


def get_review_queue(session, limit: int = 50, filter_status: str = 'needs_review',
                     active_learning: bool = False):
    """
    Get companies that need review.

    Args:
        session: SQLAlchemy session
        limit: Maximum items to fetch
        filter_status: Filter type (needs_review, failed, all)
        active_learning: If True, prioritize uncertain items (score near 0.5)

    Returns:
        List of company dicts
    """
    if filter_status == 'needs_review':
        where_clause = """
            parse_metadata->'verification'->>'needs_review' = 'true'
            AND (parse_metadata->'verification'->>'human_label' IS NULL)
        """
    elif filter_status == 'failed':
        where_clause = """
            parse_metadata->'verification'->>'status' = 'failed'
            AND (parse_metadata->'verification'->>'human_label' IS NULL)
        """
    else:  # all unreviewed
        where_clause = """
            parse_metadata->'verification'->>'status' IS NOT NULL
            AND (parse_metadata->'verification'->>'human_label' IS NULL)
        """

    # Active learning: prioritize uncertain items (final_score closest to 0.5)
    # Also prioritize where heuristics and ML disagree
    if active_learning:
        order_clause = """
            ORDER BY
                ABS(COALESCE((parse_metadata->'verification'->>'final_score')::float, 0.5) - 0.5) ASC,
                ABS(
                    COALESCE((parse_metadata->'verification'->>'combined_score')::float, 0.5) -
                    COALESCE((parse_metadata->'verification'->>'ml_prob')::float,
                             (parse_metadata->'verification'->>'combined_score')::float, 0.5)
                ) DESC
        """
    else:
        order_clause = """
            ORDER BY
                parse_metadata->'verification'->>'verified_at' DESC NULLS LAST
        """

    query = text(f"""
        SELECT
            id,
            name,
            website,
            domain,
            source,
            parse_metadata
        FROM companies
        WHERE {where_clause}
        {order_clause}
        LIMIT :limit
    """)

    result = session.execute(query, {'limit': limit})

    companies = []
    for row in result:
        companies.append({
            'id': row.id,
            'name': row.name,
            'website': row.website,
            'domain': row.domain,
            'source': row.source,
            'parse_metadata': row.parse_metadata or {}
        })

    return companies


def display_company(company: dict, index: int, total: int):
    """Display company information for review."""
    verification = company['parse_metadata'].get('verification', {})

    print("\n" + "=" * 70)
    print(f"  [{index}/{total}] Company Review")
    print("=" * 70)

    print(f"\n  ID:      {company['id']}")
    print(f"  Name:    {company['name']}")
    print(f"  Website: {company['website']}")
    print(f"  Domain:  {company['domain']}")
    print(f"  Source:  {company['source']}")

    print("\n  --- Verification Results ---")
    print(f"  Status:         {verification.get('status', 'N/A')}")
    print(f"  Score:          {verification.get('score', 0):.2f}")
    print(f"  Combined Score: {verification.get('combined_score', 0):.2f}")
    final_score = verification.get('final_score')
    if final_score is not None:
        print(f"  Final Score:    {final_score:.2f}")
    ml_prob = verification.get('ml_prob')
    if ml_prob is not None:
        print(f"  ML Probability: {ml_prob:.2f}")
    print(f"  Is Legitimate:  {verification.get('is_legitimate', 'N/A')}")
    print(f"  Tier:           {verification.get('tier', 'N/A')}")

    red_flags = verification.get('red_flags', [])
    if red_flags:
        print(f"  Red Flags:      {', '.join(red_flags[:5])}")

    quality_signals = verification.get('quality_signals', [])
    if quality_signals:
        print(f"  Quality:        {', '.join(quality_signals[:5])}")

    # LLM classification details
    llm_class = verification.get('llm_classification', {})
    if llm_class:
        print("\n  --- LLM Classification ---")
        print(f"  Type:      {llm_class.get('type', 'N/A')}")
        print(f"  Pressure:  {llm_class.get('pressure_washing', False)}")
        print(f"  Window:    {llm_class.get('window_cleaning', False)}")
        print(f"  Wood:      {llm_class.get('wood_restoration', False)}")

    # Services detected
    services = verification.get('services_detected', {})
    if services:
        print("\n  --- Services Detected ---")
        for svc, detected in services.items():
            if detected.get('any'):
                res = '✓' if detected.get('residential') else '-'
                com = '✓' if detected.get('commercial') else '-'
                print(f"  {svc.title():12} Res:{res} Com:{com}")

    # Triage reason
    triage_reason = verification.get('triage_reason')
    if triage_reason:
        print(f"\n  Triage: {triage_reason}")

    print("\n" + "-" * 70)


def prompt_for_label():
    """Prompt user for label input."""
    print("\n  Choose label:")
    print("    [p] provider       - Real service provider")
    print("    [n] non_provider   - Not a service provider")
    print("    [d] directory      - Directory/listing site")
    print("    [a] agency         - Marketing agency/lead gen")
    print("    [b] blog           - Blog/informational")
    print("    [f] franchise      - Franchise opportunity")
    print("    [s] skip           - Skip for now")
    print("    [o] open           - Open website in browser")
    print("    [q] quit           - Exit review")

    while True:
        choice = input("\n  Label: ").strip().lower()

        if choice == 'q':
            return 'quit'
        if choice == 's':
            return 'skip'
        if choice == 'o':
            return 'open'
        if choice in VALID_LABELS:
            # Ask for optional notes
            notes = input("  Notes (optional): ").strip()
            return VALID_LABELS[choice], notes

        print("  Invalid choice. Please try again.")


def update_human_label(session, company_id: int, label: str, notes: str = ""):
    """Update company with human label."""
    query = text("""
        UPDATE companies
        SET parse_metadata = jsonb_set(
            jsonb_set(
                jsonb_set(
                    COALESCE(parse_metadata, '{}'::jsonb),
                    '{verification,human_label}',
                    to_jsonb(:label::text)
                ),
                '{verification,human_notes}',
                to_jsonb(:notes::text)
            ),
            '{verification,reviewed_at}',
            to_jsonb(:reviewed_at::text)
        ),
        last_updated = NOW()
        WHERE id = :company_id
    """)

    session.execute(query, {
        'company_id': company_id,
        'label': label,
        'notes': notes,
        'reviewed_at': datetime.now().isoformat()
    })
    session.commit()


def open_website(url: str):
    """Open website in default browser."""
    import webbrowser
    try:
        webbrowser.open(url)
        print(f"  Opened: {url}")
    except Exception as e:
        print(f"  Failed to open browser: {e}")


def main():
    parser = argparse.ArgumentParser(description='Review verification queue')
    parser.add_argument('--limit', type=int, default=50, help='Number of items to review')
    parser.add_argument('--filter', dest='filter_status', default='needs_review',
                       choices=['needs_review', 'failed', 'all'],
                       help='Filter by status')
    parser.add_argument('--active-learning', '-a', action='store_true',
                       help='Prioritize uncertain items (active learning mode)')

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  VERIFICATION REVIEW QUEUE")
    print("=" * 70)
    print(f"  Filter: {args.filter_status}")
    print(f"  Limit:  {args.limit}")
    if args.active_learning:
        print("  Mode:   ACTIVE LEARNING (prioritizing uncertain items)")

    # Connect to database
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Get companies to review
        companies = get_review_queue(session, args.limit, args.filter_status,
                                     active_learning=args.active_learning)

        if not companies:
            print("\n  No companies to review. Queue is empty!")
            return 0

        print(f"\n  Found {len(companies)} companies to review")

        # Stats
        stats = {
            'reviewed': 0,
            'skipped': 0,
            'by_label': {}
        }

        # Review loop
        for i, company in enumerate(companies, 1):
            display_company(company, i, len(companies))

            while True:
                result = prompt_for_label()

                if result == 'quit':
                    print("\n  Exiting review...")
                    break

                if result == 'skip':
                    stats['skipped'] += 1
                    break

                if result == 'open':
                    open_website(company['website'])
                    continue

                # Got a label
                label, notes = result
                update_human_label(session, company['id'], label, notes)
                print(f"\n  ✓ Labeled as: {label}")

                stats['reviewed'] += 1
                stats['by_label'][label] = stats['by_label'].get(label, 0) + 1
                break

            if result == 'quit':
                break

        # Summary
        print("\n" + "=" * 70)
        print("  REVIEW SESSION COMPLETE")
        print("=" * 70)
        print(f"  Total Reviewed: {stats['reviewed']}")
        print(f"  Skipped:        {stats['skipped']}")

        if stats['by_label']:
            print("\n  Labels Applied:")
            for label, count in sorted(stats['by_label'].items()):
                print(f"    {label}: {count}")

        return 0

    except KeyboardInterrupt:
        print("\n\n  Review interrupted.")
        return 1

    except Exception as e:
        logger.error(f"Review failed: {e}")
        return 1

    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())

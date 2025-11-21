"""
SEO Intelligence CLI

Main command-line interface for all SEO intelligence operations.

Usage:
    python -m seo_intelligence.cli <command> [options]

Commands:
    serp        - Scrape Google SERPs for keyword rankings
    competitor  - Crawl competitor websites
    backlink    - Check for backlinks
    citation    - Check citation directories
    audit       - Run technical SEO audits
    las         - Calculate Local Authority Scores
    embed       - Manage vector embeddings and semantic search
    changes     - Manage pending changes
    status      - Show system status
"""

import argparse
import sys
from datetime import datetime

from runner.logging_setup import get_logger

logger = get_logger("seo_cli")


def cmd_serp(args):
    """Run SERP scraper."""
    from seo_intelligence.scrapers import get_serp_scraper

    scraper = get_serp_scraper(
        headless=not args.visible,
        use_proxy=not args.no_proxy,
    )

    if args.query:
        snapshot = scraper.scrape_query(
            query=args.query,
            location=args.location,
        )

        if snapshot:
            print(f"\nResults for '{args.query}':")
            print("=" * 60)
            for result in snapshot.results[:args.limit]:
                print(f"{result.position}. {result.title}")
                print(f"   {result.url}")
                print()
    else:
        print("Please provide a query with --query")


def cmd_competitor(args):
    """Run competitor crawler."""
    from seo_intelligence.scrapers import get_competitor_crawler

    crawler = get_competitor_crawler(
        headless=not args.visible,
        use_proxy=not args.no_proxy,
    )

    if args.domain:
        result = crawler.crawl_competitor(
            domain=args.domain,
            name=args.name,
            location=args.location,
        )

        if result:
            print(f"\nResults for {args.domain}:")
            print("=" * 60)
            print(f"Pages crawled: {result['pages_crawled']}")
            print(f"Total words: {result['total_words']}")
            print(f"Schema types: {result['schema_types']}")
    else:
        print("Please provide a domain with --domain")


def cmd_audit(args):
    """Run technical audit."""
    from seo_intelligence.scrapers import get_technical_auditor

    auditor = get_technical_auditor(
        headless=not args.visible,
        use_proxy=False,
    )

    if args.url:
        result = auditor.audit_page(args.url)

        print(f"\nAudit Results for {args.url}")
        print("=" * 60)
        print(f"Overall Score: {result.overall_score:.0f}/100")
        print(f"  SEO: {result.seo_score:.0f}")
        print(f"  Performance: {result.performance_score:.0f}")
        print(f"  Accessibility: {result.accessibility_score:.0f}")
        print(f"  Security: {result.security_score:.0f}")
        print()
        print(f"Issues Found: {len(result.issues)}")
        print(f"  Critical: {len(result.critical_issues)}")
        print(f"  High: {len(result.high_issues)}")

        if result.issues and args.verbose:
            print("\nAll Issues:")
            for issue in result.issues:
                print(f"  [{issue.severity.upper()}] {issue.description}")
    else:
        print("Please provide a URL with --url")


def cmd_las(args):
    """Calculate Local Authority Score."""
    from seo_intelligence.services import get_las_calculator

    calculator = get_las_calculator()

    if args.name:
        result = calculator.calculate(args.name, args.domain)

        print(f"\nLocal Authority Score for '{args.name}'")
        print("=" * 60)
        print(f"Overall Score: {result.las_score:.1f} ({result.grade})")
        print()
        print("Components:")
        print(f"  Citations:    {result.components.citation_score:.1f}/100")
        print(f"  Backlinks:    {result.components.backlink_score:.1f}/100")
        print(f"  Reviews:      {result.components.review_score:.1f}/100")
        print(f"  Completeness: {result.components.completeness_score:.1f}/100")
        print()
        print("Recommendations:")
        for i, rec in enumerate(result.recommendations, 1):
            print(f"  {i}. {rec}")
    else:
        print("Please provide a business name with --name")


def cmd_changes(args):
    """Manage pending changes."""
    from seo_intelligence.services import get_change_manager

    manager = get_change_manager()

    if args.list:
        changes = manager.get_pending_changes(limit=args.limit)
        print(f"\nPending Changes ({len(changes)} total)")
        print("=" * 60)
        for change in changes:
            print(f"[{change['change_id']}] {change['change_type']} - {change['entity_type']}")
            print(f"    Priority: {change['priority']}")
            print(f"    Reason: {change['reason'][:60]}...")
            print()

    elif args.approve:
        if manager.approve_change(args.approve, reviewer="cli"):
            print(f"Change {args.approve} approved")
        else:
            print(f"Failed to approve change {args.approve}")

    elif args.reject:
        if manager.reject_change(args.reject, reviewer="cli", reason=args.reason or "Rejected via CLI"):
            print(f"Change {args.reject} rejected")
        else:
            print(f"Failed to reject change {args.reject}")

    elif args.stats:
        stats = manager.get_stats()
        print("\nChange Log Statistics")
        print("=" * 60)
        print(f"Pending: {stats.get('total_pending', 0)}")
        print(f"Approved: {stats.get('total_approved', 0)}")
        print(f"Applied: {stats.get('total_applied', 0)}")
        print(f"Rejected: {stats.get('total_rejected', 0)}")
        print(f"Last 24h: {stats.get('changes_last_24h', 0)}")

    else:
        print("Use --list, --approve ID, --reject ID, or --stats")


def cmd_embed(args):
    """Manage vector embeddings and semantic search."""
    from seo_intelligence.services import get_content_embedder, get_qdrant_manager
    import os
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    # Initialize services
    try:
        embedder = get_content_embedder()
        qdrant = get_qdrant_manager()

        # Get database connection
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            print("ERROR: DATABASE_URL not set")
            return

        engine = create_engine(database_url, echo=False)

    except Exception as e:
        print(f"ERROR: Failed to initialize embedding services: {e}")
        return

    # Initialize Qdrant collections
    if args.initialize:
        print("\nInitializing Qdrant Collections")
        print("=" * 60)
        try:
            qdrant.initialize_collections()

            # Check stats
            for collection in [qdrant.COMPETITOR_PAGES, qdrant.SERP_SNIPPETS]:
                stats = qdrant.get_collection_stats(collection)
                print(f"\n{collection}:")
                print(f"  Vectors: {stats['vectors_count']}")
                print(f"  Status: {stats['status']}")

            print("\n✓ Collections initialized successfully")
        except Exception as e:
            print(f"ERROR: Failed to initialize collections: {e}")
        return

    # Embed single page
    if args.page_id:
        print(f"\nEmbedding Page {args.page_id}")
        print("=" * 60)

        with Session(engine) as session:
            # Fetch page data
            result = session.execute(
                text("""
                    SELECT cp.page_id, cp.competitor_id, cp.url, cp.title,
                           cp.page_type, cp.content_hash
                    FROM competitor_pages cp
                    WHERE cp.page_id = :page_id
                """),
                {"page_id": args.page_id}
            ).fetchone()

            if not result:
                print(f"ERROR: Page {args.page_id} not found")
                return

            page_id, site_id, url, title, page_type, content_hash = result

            # Note: We don't have the original HTML stored, so we can't re-embed
            # This command is mainly for demonstration. In production, you'd need to
            # either store HTML or re-crawl the page
            print(f"Page: {url}")
            print(f"Title: {title}")
            print(f"Type: {page_type}")
            print(f"\nNote: Re-embedding requires original HTML or re-crawling")
        return

    # Re-embed all pages
    if args.reembed_all:
        print("\nRe-embedding All Pages")
        print("=" * 60)
        print("This will re-embed all competitor pages with the current model version.")

        with Session(engine) as session:
            # Get pages needing re-embedding
            result = session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM competitor_pages
                    WHERE embedding_version IS NULL
                       OR embedding_version != :version
                """),
                {"version": os.getenv("EMBEDDING_VERSION", "v1.0")}
            )
            count = result.fetchone()[0]

            print(f"\nPages needing re-embedding: {count}")
            print("\nNote: Re-embedding requires original HTML content.")
            print("Use the competitor crawler to re-crawl pages with embeddings enabled.")
        return

    # Semantic search for competitor pages
    if args.search and args.query:
        print(f"\nSemantic Search: '{args.query}'")
        print("=" * 60)

        try:
            # Embed the query
            query_vector = embedder.embed_single(args.query)

            # Search similar pages
            results = qdrant.search_similar_pages(
                query_vector=query_vector,
                limit=args.limit,
                page_type=args.page_type
            )

            if results:
                print(f"\nFound {len(results)} similar pages:\n")
                for i, result in enumerate(results, 1):
                    print(f"{i}. {result['title']}")
                    print(f"   URL: {result['url']}")
                    print(f"   Type: {result['page_type']}")
                    print(f"   Score: {result['score']:.3f}")
                    print()
            else:
                print("\nNo results found. Make sure pages are embedded first.")

        except Exception as e:
            print(f"ERROR: Search failed: {e}")
        return

    # Show embedding status
    if args.status:
        print("\nEmbedding Status")
        print("=" * 60)

        # Show embedding configuration
        print("\nConfiguration:")
        info = embedder.get_info()
        print(f"  Model: {info['model_name']}")
        print(f"  Version: {info['embedding_version']}")
        print(f"  Dimension: {info['dimension']}")
        print(f"  Chunk Size: {info['chunk_size']} tokens")

        # Check Qdrant health
        print("\nQdrant:")
        if qdrant.health_check():
            print(f"  [OK] Connected to {qdrant.host}:{qdrant.port}")

            # Get collection stats
            try:
                for collection in [qdrant.COMPETITOR_PAGES, qdrant.SERP_SNIPPETS]:
                    stats = qdrant.get_collection_stats(collection)
                    print(f"\n  {collection}:")
                    print(f"    Vectors: {stats['vectors_count']}")
                    print(f"    Status: {stats['status']}")
            except Exception as e:
                print(f"  [WARN] Could not get collection stats: {e}")
        else:
            print(f"  [ERR] Could not connect to Qdrant")

        # Database stats
        with Session(engine) as session:
            result = session.execute(
                text("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(embedding_version) as embedded,
                        COUNT(CASE WHEN embedding_version = :version THEN 1 END) as current_version
                    FROM competitor_pages
                """),
                {"version": os.getenv("EMBEDDING_VERSION", "v1.0")}
            ).fetchone()

            print("\nDatabase (competitor_pages):")
            print(f"  Total pages: {result[0]}")
            print(f"  Embedded: {result[1]}")
            print(f"  Current version: {result[2]}")

            result = session.execute(
                text("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(embedding_version) as embedded
                    FROM serp_results
                """)
            ).fetchone()

            print("\nDatabase (serp_results):")
            print(f"  Total results: {result[0]}")
            print(f"  Embedded snippets: {result[1]}")

        print()
        return

    # If no specific action, show help
    print("Use --initialize, --page-id, --reembed-all, --search, or --status")


def cmd_status(args):
    """Show system status."""
    print("\nSEO Intelligence System Status")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Check services
    services = [
        ("Rate Limiter", "seo_intelligence.services.get_rate_limiter"),
        ("Robots Checker", "seo_intelligence.services.get_robots_checker"),
        ("Content Hasher", "seo_intelligence.services.get_content_hasher"),
        ("Change Manager", "seo_intelligence.services.get_change_manager"),
        ("LAS Calculator", "seo_intelligence.services.get_las_calculator"),
        ("Task Logger", "seo_intelligence.services.get_task_logger"),
        ("Content Embedder", "seo_intelligence.services.get_content_embedder"),
        ("Qdrant Manager", "seo_intelligence.services.get_qdrant_manager"),
    ]

    print("Services:")
    for name, import_path in services:
        try:
            module_path, func_name = import_path.rsplit('.', 1)
            module = __import__(module_path, fromlist=[func_name])
            getattr(module, func_name)()
            print(f"  [OK] {name}")
        except Exception as e:
            print(f"  [ERR] {name}: {e}")

    # Check scrapers
    scrapers = [
        ("SERP Scraper", "seo_intelligence.scrapers.get_serp_scraper"),
        ("Competitor Crawler", "seo_intelligence.scrapers.get_competitor_crawler"),
        ("Technical Auditor", "seo_intelligence.scrapers.get_technical_auditor"),
        ("Backlink Crawler", "seo_intelligence.scrapers.get_backlink_crawler"),
        ("Citation Crawler", "seo_intelligence.scrapers.get_citation_crawler"),
    ]

    print("\nScrapers:")
    for name, import_path in scrapers:
        try:
            module_path, func_name = import_path.rsplit('.', 1)
            module = __import__(module_path, fromlist=[func_name])
            print(f"  [OK] {name}")
        except Exception as e:
            print(f"  [ERR] {name}: {e}")

    # Check database
    print("\nDatabase:")
    try:
        import os
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            print(f"  [OK] DATABASE_URL configured")
        else:
            print(f"  [WARN] DATABASE_URL not set")
    except Exception as e:
        print(f"  [ERR] {e}")

    print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SEO Intelligence CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m seo_intelligence.cli serp --query "pressure washing austin"
  python -m seo_intelligence.cli competitor --domain example.com
  python -m seo_intelligence.cli audit --url https://mysite.com
  python -m seo_intelligence.cli las --name "My Business" --domain mysite.com
  python -m seo_intelligence.cli embed --initialize
  python -m seo_intelligence.cli embed --status
  python -m seo_intelligence.cli embed --search --query "power washing services"
  python -m seo_intelligence.cli changes --list
  python -m seo_intelligence.cli status
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # SERP command
    serp_parser = subparsers.add_parser('serp', help='Scrape Google SERPs')
    serp_parser.add_argument('--query', '-q', help='Search query')
    serp_parser.add_argument('--location', '-l', help='Location context')
    serp_parser.add_argument('--limit', type=int, default=10, help='Result limit')
    serp_parser.add_argument('--visible', action='store_true', help='Show browser')
    serp_parser.add_argument('--no-proxy', action='store_true', help='Disable proxy')

    # Competitor command
    comp_parser = subparsers.add_parser('competitor', help='Crawl competitor')
    comp_parser.add_argument('--domain', '-d', help='Competitor domain')
    comp_parser.add_argument('--name', '-n', help='Business name')
    comp_parser.add_argument('--location', '-l', help='Location')
    comp_parser.add_argument('--visible', action='store_true', help='Show browser')
    comp_parser.add_argument('--no-proxy', action='store_true', help='Disable proxy')

    # Audit command
    audit_parser = subparsers.add_parser('audit', help='Run technical audit')
    audit_parser.add_argument('--url', '-u', help='URL to audit')
    audit_parser.add_argument('--visible', action='store_true', help='Show browser')
    audit_parser.add_argument('--verbose', '-v', action='store_true', help='Show all issues')

    # LAS command
    las_parser = subparsers.add_parser('las', help='Calculate LAS score')
    las_parser.add_argument('--name', '-n', help='Business name')
    las_parser.add_argument('--domain', '-d', help='Business domain')

    # Changes command
    changes_parser = subparsers.add_parser('changes', help='Manage changes')
    changes_parser.add_argument('--list', action='store_true', help='List pending')
    changes_parser.add_argument('--approve', type=int, help='Approve by ID')
    changes_parser.add_argument('--reject', type=int, help='Reject by ID')
    changes_parser.add_argument('--reason', help='Rejection reason')
    changes_parser.add_argument('--stats', action='store_true', help='Show stats')
    changes_parser.add_argument('--limit', type=int, default=20, help='List limit')

    # Embed command
    embed_parser = subparsers.add_parser('embed', help='Manage embeddings')
    embed_parser.add_argument('--initialize', action='store_true', help='Initialize Qdrant collections')
    embed_parser.add_argument('--page-id', type=int, help='Embed single page by ID')
    embed_parser.add_argument('--reembed-all', action='store_true', help='Re-embed all pages')
    embed_parser.add_argument('--search', action='store_true', help='Semantic search')
    embed_parser.add_argument('--query', '-q', help='Search query')
    embed_parser.add_argument('--page-type', help='Filter by page type')
    embed_parser.add_argument('--limit', type=int, default=10, help='Search result limit')
    embed_parser.add_argument('--status', action='store_true', help='Show embedding status')

    # Status command
    subparsers.add_parser('status', help='Show system status')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Dispatch to command
    commands = {
        'serp': cmd_serp,
        'competitor': cmd_competitor,
        'audit': cmd_audit,
        'las': cmd_las,
        'embed': cmd_embed,
        'changes': cmd_changes,
        'status': cmd_status,
    }

    if args.command in commands:
        try:
            commands[args.command](args)
        except KeyboardInterrupt:
            print("\nInterrupted")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

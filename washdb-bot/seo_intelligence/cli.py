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

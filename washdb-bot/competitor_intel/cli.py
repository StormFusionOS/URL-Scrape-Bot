"""
Competitor Intelligence CLI

Provides command-line utilities for testing and debugging competitor tracking.
"""

import sys
from typing import Optional
from datetime import datetime

from db.database_manager import DatabaseManager
from utils.logging_config import get_logger

logger = get_logger("CompetitorIntelCLI")


def test_competitor(competitor_id: int, module: Optional[str] = None):
    """
    Test competitor intelligence gathering for a single competitor.

    Args:
        competitor_id: The competitor ID to test
        module: Optional specific module to test (runs all if None)
    """
    db = DatabaseManager()

    # Fetch competitor info
    with db.get_session() as session:
        from sqlalchemy import text
        result = session.execute(
            text("SELECT name, domain, website_url FROM competitors WHERE competitor_id = :id"),
            {"id": competitor_id}
        ).fetchone()

        if not result:
            logger.error(f"Competitor {competitor_id} not found")
            sys.exit(1)

        name, domain, website_url = result

    print(f"\n{'='*60}")
    print(f"Testing Competitor Intelligence")
    print(f"{'='*60}")
    print(f"ID:     {competitor_id}")
    print(f"Name:   {name}")
    print(f"Domain: {domain}")
    print(f"URL:    {website_url}")
    print(f"Module: {module or 'ALL'}")
    print(f"{'='*60}\n")

    if module:
        _run_single_module(competitor_id, module, domain, website_url)
    else:
        _run_all_modules(competitor_id, domain, website_url)


def _run_single_module(competitor_id: int, module: str, domain: str, website_url: str):
    """Run a single module test."""
    from competitor_intel.config import MODULE_TIMEOUTS

    start_time = datetime.now()
    print(f"[{module}] Starting...")

    try:
        if module == "site_crawl":
            result = _test_site_crawl(competitor_id, domain, website_url)
        elif module == "serp_track":
            result = _test_serp_track(competitor_id, domain)
        elif module == "citations":
            result = _test_citations(competitor_id, domain)
        elif module == "reviews":
            result = _test_reviews(competitor_id, domain)
        elif module == "technical":
            result = _test_technical(competitor_id, website_url)
        elif module == "services":
            result = _test_services(competitor_id, website_url)
        elif module == "synthesis":
            result = _test_synthesis(competitor_id)
        else:
            print(f"Unknown module: {module}")
            return

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[{module}] Completed in {elapsed:.1f}s")
        print(f"Result: {result}")

    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[{module}] FAILED after {elapsed:.1f}s: {e}")
        logger.exception(f"Module {module} failed")


def _run_all_modules(competitor_id: int, domain: str, website_url: str):
    """Run all modules in sequence."""
    from competitor_intel.config import MODULE_ORDER

    results = {}
    total_start = datetime.now()

    for module in MODULE_ORDER:
        module_key = module.replace("_check", "").replace("_aggregate", "").replace("_audit", "").replace("_extract", "")
        _run_single_module(competitor_id, module_key, domain, website_url)
        print()

    total_elapsed = (datetime.now() - total_start).total_seconds()
    print(f"\n{'='*60}")
    print(f"All modules completed in {total_elapsed:.1f}s")
    print(f"{'='*60}")


def _test_site_crawl(competitor_id: int, domain: str, website_url: str) -> dict:
    """Test site crawling module."""
    from seo_intelligence.scrapers.competitor_crawler_selenium import CompetitorCrawlerSelenium
    from competitor_intel.config import SITE_CRAWL_PAGES

    crawler = CompetitorCrawlerSelenium()
    result = crawler.crawl_site(
        domain=domain,
        start_url=website_url,
        max_pages=SITE_CRAWL_PAGES,
        competitor_id=competitor_id
    )

    return {
        "pages_crawled": result.get("pages_crawled", 0),
        "links_found": result.get("links_found", 0),
        "services_detected": result.get("services_detected", []),
    }


def _test_serp_track(competitor_id: int, domain: str) -> dict:
    """Test SERP tracking module."""
    # Get keywords assigned to this competitor
    db = DatabaseManager()

    with db.get_session() as session:
        from sqlalchemy import text
        keywords = session.execute(
            text("""
                SELECT DISTINCT keyword_text
                FROM keyword_company_tracking kct
                JOIN company_competitors cc ON kct.company_id = cc.company_id
                WHERE cc.competitor_id = :cid
                LIMIT 10
            """),
            {"cid": competitor_id}
        ).fetchall()

    if not keywords:
        return {"message": "No keywords to track", "positions": []}

    from seo_intelligence.scrapers.serp_scraper_selenium import SerpScraperSelenium

    scraper = SerpScraperSelenium()
    positions = []

    for (keyword,) in keywords[:5]:  # Test with 5 keywords
        result = scraper.run(keyword)
        for r in result.get("organic_results", []):
            if domain in r.get("url", ""):
                positions.append({
                    "keyword": keyword,
                    "position": r.get("position"),
                    "url": r.get("url")
                })
                break

    return {"keywords_checked": len(keywords), "positions_found": positions}


def _test_citations(competitor_id: int, domain: str) -> dict:
    """Test citation checking module."""
    from seo_intelligence.scrapers.citation_crawler_selenium import CitationCrawlerSelenium

    crawler = CitationCrawlerSelenium()
    result = crawler.check_citations(domain=domain)

    return {
        "directories_checked": result.get("directories_checked", 0),
        "citations_found": result.get("citations_found", 0),
        "sources": result.get("sources", []),
    }


def _test_reviews(competitor_id: int, domain: str) -> dict:
    """Test review aggregation module."""
    from competitor_intel.config import REVIEW_SOURCES

    # This would use a review scraper - placeholder for now
    return {
        "sources_to_check": REVIEW_SOURCES,
        "message": "Review aggregation not yet implemented"
    }


def _test_technical(competitor_id: int, website_url: str) -> dict:
    """Test technical audit module."""
    from seo_intelligence.scrapers.technical_auditor_selenium import TechnicalAuditorSelenium

    auditor = TechnicalAuditorSelenium()
    result = auditor.audit_page(website_url)

    return {
        "overall_score": result.get("overall_score"),
        "issues_found": result.get("issues_count", 0),
        "categories": result.get("category_scores", {}),
    }


def _test_services(competitor_id: int, website_url: str) -> dict:
    """Test service extraction module."""
    # This would use the service extractor - placeholder for now
    return {
        "message": "Service extraction not yet implemented",
        "url": website_url
    }


def _test_synthesis(competitor_id: int) -> dict:
    """Test intelligence synthesis module."""
    # This would aggregate all data - placeholder for now
    return {
        "message": "Intelligence synthesis not yet implemented",
        "competitor_id": competitor_id
    }


def list_competitors(limit: int = 50, show_inactive: bool = False):
    """List competitors in the database."""
    db = DatabaseManager()

    with db.get_session() as session:
        from sqlalchemy import text

        query = """
            SELECT competitor_id, name, domain, business_type, is_active,
                   intel_initial_complete, priority_tier
            FROM competitors
            WHERE 1=1
        """
        if not show_inactive:
            query += " AND is_active = true"
        query += f" ORDER BY competitor_id LIMIT {limit}"

        results = session.execute(text(query)).fetchall()

    print(f"\n{'ID':<6} {'Name':<40} {'Domain':<30} {'Active':<8} {'Intel':<8} {'Tier':<6}")
    print("-" * 100)

    for row in results:
        cid, name, domain, btype, active, intel_done, tier = row
        name_short = (name[:37] + "...") if name and len(name) > 40 else (name or "")
        domain_short = (domain[:27] + "...") if domain and len(domain) > 30 else (domain or "")
        print(f"{cid:<6} {name_short:<40} {domain_short:<30} {str(active):<8} {str(intel_done or False):<8} {tier or 2:<6}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Competitor Intelligence CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Test command
    test_p = subparsers.add_parser("test", help="Test competitor")
    test_p.add_argument("competitor_id", type=int)
    test_p.add_argument("--module", "-m")

    # List command
    list_p = subparsers.add_parser("list", help="List competitors")
    list_p.add_argument("--limit", "-l", type=int, default=50)
    list_p.add_argument("--inactive", "-i", action="store_true")

    args = parser.parse_args()

    if args.command == "test":
        test_competitor(args.competitor_id, args.module)
    elif args.command == "list":
        list_competitors(args.limit, args.inactive)
    else:
        parser.print_help()

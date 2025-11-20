#!/usr/bin/env python3
"""
Installation validation script for SEO Intelligence system.

Checks:
- Python version
- Required packages
- Module imports
- Database connectivity
- Qdrant connectivity (optional)

Usage:
    python validate_installation.py [--database-url URL] [--qdrant-url URL]
"""
import argparse
import os
import sys
from importlib import import_module
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).parent
parent_dir = script_dir.parent.parent
sys.path.insert(0, str(parent_dir))


def check_python_version():
    """Check Python version >= 3.8."""
    print("=" * 60)
    print("Checking Python Version")
    print("=" * 60)

    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major >= 3 and version.minor >= 8:
        print(f"✓ Python {version_str} (OK)")
        return True
    else:
        print(f"✗ Python {version_str} (Need 3.8+)")
        return False


def check_required_packages():
    """Check if required packages are installed."""
    print("\n" + "=" * 60)
    print("Checking Required Packages")
    print("=" * 60)

    required_packages = [
        ('sqlalchemy', 'SQLAlchemy ORM'),
        ('requests', 'HTTP client'),
        ('bs4', 'BeautifulSoup HTML parser'),
        ('dotenv', 'python-dotenv'),
        ('playwright', 'Playwright browser automation'),
    ]

    optional_packages = [
        ('feedparser', 'RSS/Atom parser (for URL discovery)'),
        ('sentence_transformers', 'Embeddings (for semantic search)'),
        ('qdrant_client', 'Qdrant vector database client'),
    ]

    all_ok = True

    # Check required
    print("\nRequired:")
    for package, description in required_packages:
        try:
            import_module(package)
            print(f"  ✓ {package:20} - {description}")
        except ImportError:
            print(f"  ✗ {package:20} - {description} (MISSING)")
            all_ok = False

    # Check optional
    print("\nOptional:")
    for package, description in optional_packages:
        try:
            import_module(package)
            print(f"  ✓ {package:20} - {description}")
        except ImportError:
            print(f"  ⚠ {package:20} - {description} (missing, but optional)")

    return all_ok


def check_module_imports():
    """Check if SEO Intelligence modules can be imported."""
    print("\n" + "=" * 60)
    print("Checking SEO Intelligence Modules")
    print("=" * 60)

    modules = [
        ('seo_intelligence.infrastructure.robots_parser', 'Robots.txt parser'),
        ('seo_intelligence.infrastructure.rate_limiter', 'Rate limiter'),
        ('seo_intelligence.infrastructure.http_client', 'HTTP client'),
        ('seo_intelligence.infrastructure.task_logger', 'Task logger'),
        ('seo_intelligence.serp.scraper', 'SERP scraper'),
        ('seo_intelligence.serp.extractor', 'SERP extractor'),
        ('seo_intelligence.competitor.hasher', 'Page hasher'),
        ('seo_intelligence.competitor.parser', 'Page parser'),
        ('seo_intelligence.competitor.snapshot', 'Snapshot manager'),
        ('seo_intelligence.backlinks.tracker', 'Backlinks tracker'),
        ('seo_intelligence.backlinks.las_calculator', 'LAS calculator'),
        ('seo_intelligence.citations.scraper', 'Citations scraper'),
        ('seo_intelligence.audits.auditor', 'Technical auditor'),
    ]

    optional_modules = [
        ('seo_intelligence.competitor.url_seeder', 'URL seeder (needs feedparser)'),
        ('seo_intelligence.competitor.embeddings', 'Embeddings (needs qdrant_client)'),
        ('seo_intelligence.competitor.crawler', 'Crawler (needs qdrant_client)'),
    ]

    all_ok = True

    # Check required modules
    print("\nCore Modules:")
    for module_name, description in modules:
        try:
            import_module(module_name)
            print(f"  ✓ {description}")
        except Exception as e:
            print(f"  ✗ {description} - Error: {e}")
            all_ok = False

    # Check optional modules
    print("\nOptional Modules:")
    for module_name, description in optional_modules:
        try:
            import_module(module_name)
            print(f"  ✓ {description}")
        except ImportError as e:
            print(f"  ⚠ {description} - {e} (optional)")
        except Exception as e:
            print(f"  ✗ {description} - Error: {e}")

    return all_ok


def check_database(database_url):
    """Check database connectivity."""
    print("\n" + "=" * 60)
    print("Checking Database Connectivity")
    print("=" * 60)

    if not database_url:
        print("  ⚠ DATABASE_URL not provided (use --database-url or set environment variable)")
        return None

    try:
        from sqlalchemy import create_engine, text

        # Hide password in output
        safe_url = database_url.split('@')[-1] if '@' in database_url else database_url
        print(f"  Connecting to: {safe_url}")

        engine = create_engine(database_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"  ✓ Connected successfully")
            print(f"  PostgreSQL version: {version.split(',')[0]}")
            return True

    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return False


def check_qdrant(qdrant_url):
    """Check Qdrant connectivity."""
    print("\n" + "=" * 60)
    print("Checking Qdrant Connectivity (Optional)")
    print("=" * 60)

    if not qdrant_url:
        print("  ⚠ QDRANT_URL not provided (optional, for vector embeddings)")
        return None

    try:
        from qdrant_client import QdrantClient

        print(f"  Connecting to: {qdrant_url}")
        client = QdrantClient(url=qdrant_url)
        collections = client.get_collections()
        print(f"  ✓ Connected successfully")
        print(f"  Collections: {len(collections.collections)}")
        return True

    except ImportError:
        print("  ⚠ qdrant-client not installed (optional)")
        return None

    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Validate SEO Intelligence system installation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='Database URL to test (optional)'
    )

    parser.add_argument(
        '--qdrant-url',
        type=str,
        default=None,
        help='Qdrant URL to test (optional)'
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("SEO Intelligence System - Installation Validation")
    print("=" * 60)

    # Run checks
    results = {
        'python': check_python_version(),
        'packages': check_required_packages(),
        'modules': check_module_imports(),
        'database': check_database(args.database_url),
        'qdrant': check_qdrant(args.qdrant_url)
    }

    # Summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)

    required_checks = ['python', 'packages', 'modules']
    required_ok = all(results[k] for k in required_checks if results[k] is not None)

    print("\nRequired Components:")
    for check in required_checks:
        status = "✓ PASS" if results[check] else "✗ FAIL"
        print(f"  {check.title():15} {status}")

    print("\nOptional Components:")
    for check in ['database', 'qdrant']:
        if results[check] is None:
            status = "⚠ NOT CHECKED"
        elif results[check]:
            status = "✓ PASS"
        else:
            status = "✗ FAIL"
        print(f"  {check.title():15} {status}")

    print("\n" + "=" * 60)

    if required_ok:
        print("✓ All required components validated successfully!")
        print("\nNext steps:")
        print("  1. Set DATABASE_URL environment variable")
        print("  2. Run database migration: python scripts/run_migration.py")
        print("  3. Configure cron jobs for automated scraping")
        sys.exit(0)
    else:
        print("✗ Some required components failed validation")
        print("\nPlease install missing packages:")
        print("  pip install -r requirements.txt")
        print("  playwright install chromium")
        sys.exit(1)


if __name__ == '__main__':
    main()

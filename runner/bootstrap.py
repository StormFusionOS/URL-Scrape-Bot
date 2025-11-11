#!/usr/bin/env python3
"""
Bootstrap script for washdb-bot.

This script:
- Loads environment variables from .env
- Verifies database connectivity
- Creates required directories (data/, logs/)
- Prints "Bootstrap OK" on success
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


def load_environment():
    """Load environment variables from .env file."""
    # Get the project root (parent of runner/)
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"

    if not env_file.exists():
        print(f"ERROR: .env file not found at {env_file}")
        print("Please copy .env.example to .env and configure it.")
        sys.exit(1)

    load_dotenv(env_file)
    print(f"✓ Loaded environment from {env_file}")


def verify_database():
    """Verify database connectivity."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("ERROR: DATABASE_URL not set in .env file")
        sys.exit(1)

    print(f"✓ Found DATABASE_URL")

    try:
        # Create engine and test connection
        engine = create_engine(database_url, echo=False)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.scalar()
            print(f"✓ Database connection successful")
            print(f"  PostgreSQL version: {version.split(',')[0]}")

        engine.dispose()

    except OperationalError as e:
        print(f"ERROR: Could not connect to database")
        print(f"  {e}")
        print("\nPlease verify:")
        print("  1. PostgreSQL is running")
        print("  2. Database 'washdb' exists")
        print("  3. User credentials are correct")
        print("  4. DATABASE_URL in .env is correct")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error connecting to database: {e}")
        sys.exit(1)


def create_directories():
    """Create required directories if they don't exist."""
    project_root = Path(__file__).parent.parent

    directories = [
        project_root / "data",
        project_root / "logs",
    ]

    for directory in directories:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created directory: {directory.name}/")
        else:
            print(f"✓ Directory exists: {directory.name}/")


def verify_environment_vars():
    """Verify all required environment variables are set."""
    required_vars = [
        "DATABASE_URL",
        "LOG_LEVEL",
        "YP_BASE",
        "CRAWL_DELAY_SECONDS",
        "MAX_CONCURRENT_SITE_SCRAPES",
    ]

    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print(f"ERROR: Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print("\nPlease check your .env file")
        sys.exit(1)

    print(f"✓ All required environment variables set")


def main():
    """Run bootstrap checks."""
    print("=" * 60)
    print("washdb-bot Bootstrap")
    print("=" * 60)
    print()

    # Load environment
    load_environment()

    # Verify all environment variables
    verify_environment_vars()

    # Verify database connection
    verify_database()

    # Create directories
    create_directories()

    print()
    print("=" * 60)
    print("Bootstrap OK")
    print("=" * 60)
    print()
    print("You can now run the application:")
    print("  - GUI: python gui/main.py")
    print("  - YP Scraper: python scrape_yp/main.py")
    print("  - Site Scraper: python scrape_site/main.py")
    print()


if __name__ == "__main__":
    main()

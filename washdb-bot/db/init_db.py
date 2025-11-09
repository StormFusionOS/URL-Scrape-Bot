#!/usr/bin/env python3
"""
Database initialization script for washdb-bot.

This script:
- Loads environment variables from .env
- Creates database engine
- Creates all tables defined in models
- Prints "DB ready" on success

Usage:
    python -m db.init_db
    # or
    python db/init_db.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

# Import Base and all models
from db.models import Base, Company


def load_environment():
    """Load environment variables from .env file."""
    # Try to find .env in the project root
    current_dir = Path(__file__).parent.parent  # Go up to project root
    env_file = current_dir / ".env"

    if not env_file.exists():
        print(f"ERROR: .env file not found at {env_file}")
        print("Please copy .env.example to .env and configure it.")
        sys.exit(1)

    load_dotenv(env_file)
    print(f"✓ Loaded environment from {env_file}")


def init_database():
    """Initialize the database by creating all tables."""
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("ERROR: DATABASE_URL not set in .env file")
        sys.exit(1)

    print(f"✓ Found DATABASE_URL")

    try:
        # Create engine
        engine = create_engine(database_url, echo=True)
        print(f"✓ Created database engine")

        # Create all tables
        print("\nCreating tables...")
        Base.metadata.create_all(engine)

        print("\n" + "=" * 60)
        print("DB ready")
        print("=" * 60)
        print(f"\nCreated tables:")
        for table_name in Base.metadata.tables.keys():
            print(f"  - {table_name}")
        print()

        # Dispose of the engine
        engine.dispose()

    except SQLAlchemyError as e:
        print(f"\nERROR: Database initialization failed")
        print(f"  {e}")
        print("\nPlease verify:")
        print("  1. PostgreSQL is running")
        print("  2. Database 'washdb' exists")
        print("  3. User credentials are correct")
        print("  4. DATABASE_URL in .env is correct")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Unexpected error during initialization: {e}")
        sys.exit(1)


def main():
    """Main entry point for database initialization."""
    print("=" * 60)
    print("washdb-bot Database Initialization")
    print("=" * 60)
    print()

    # Load environment variables
    load_environment()

    # Initialize database
    init_database()


if __name__ == "__main__":
    main()

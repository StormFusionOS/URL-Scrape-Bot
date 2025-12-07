#!/usr/bin/env python3
"""
Run Claude Auto-Tuning System database migration.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment")
    sys.exit(1)

# Convert SQLAlchemy format to psycopg2 format
# postgresql+psycopg:// -> postgresql://
DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

# Path to migration file
migration_file = Path(__file__).parent.parent / "db" / "migrations" / "029_add_claude_tables.sql"

if not migration_file.exists():
    print(f"ERROR: Migration file not found: {migration_file}")
    sys.exit(1)

# Read migration SQL
with open(migration_file, 'r') as f:
    migration_sql = f.read()

# Connect and run migration
try:
    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()

    print(f"Running migration: {migration_file.name}")
    cursor.execute(migration_sql)

    print("✓ Migration completed successfully!")

    # Show verification
    print("\nVerifying tables:")
    cursor.execute("""
        SELECT tablename FROM pg_tables
        WHERE tablename IN ('claude_review_queue', 'claude_review_audit', 'claude_prompt_versions', 'claude_rate_limits')
        ORDER BY tablename
    """)
    tables = cursor.fetchall()
    for (table,) in tables:
        print(f"  ✓ {table}")

    print(f"\nTotal tables created: {len(tables)}")

    # Show initial prompt version
    cursor.execute("SELECT version, is_active FROM claude_prompt_versions")
    prompts = cursor.fetchall()
    print(f"\nPrompt versions: {len(prompts)}")
    for version, is_active in prompts:
        status = "ACTIVE" if is_active else "inactive"
        print(f"  ✓ {version} ({status})")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"ERROR: Migration failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

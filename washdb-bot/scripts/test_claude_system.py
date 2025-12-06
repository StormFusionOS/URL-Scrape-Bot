#!/usr/bin/env python3
"""
Test Claude Auto-Tuning System

Quick verification that all components are working.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()


def test_environment():
    """Test environment variables."""
    print("=" * 70)
    print("TESTING ENVIRONMENT")
    print("=" * 70)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        print(f"✓ ANTHROPIC_API_KEY set: {masked}")
    else:
        print("✗ ANTHROPIC_API_KEY not found!")
        return False

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        print("✓ DATABASE_URL set")
    else:
        print("✗ DATABASE_URL not found!")
        return False

    return True


def test_database():
    """Test database tables exist."""
    print("\n" + "=" * 70)
    print("TESTING DATABASE")
    print("=" * 70)

    try:
        from db.database_manager import DatabaseManager

        db = DatabaseManager()
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Check tables
            cursor.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE tablename LIKE 'claude_%'
                ORDER BY tablename
            """)
            tables = cursor.fetchall()

            expected = ['claude_prompt_versions', 'claude_rate_limits', 'claude_review_audit', 'claude_review_queue']
            found = [t[0] for t in tables]

            for table in expected:
                if table in found:
                    print(f"✓ Table exists: {table}")
                else:
                    print(f"✗ Table missing: {table}")
                    return False

            # Check prompt version
            cursor.execute("SELECT version, is_active FROM claude_prompt_versions WHERE is_active = true")
            row = cursor.fetchone()
            if row:
                print(f"✓ Active prompt version: {row[0]}")
            else:
                print("⚠ No active prompt version (expected v1.0)")

        return True

    except Exception as e:
        print(f"✗ Database error: {e}")
        return False


def test_api_client():
    """Test Claude API connection."""
    print("\n" + "=" * 70)
    print("TESTING CLAUDE API")
    print("=" * 70)

    try:
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say 'test successful' and nothing else."}]
        )

        result = response.content[0].text
        print(f"✓ API connection successful: {result}")
        return True

    except Exception as e:
        print(f"✗ API connection failed: {e}")
        return False


def test_components():
    """Test component imports."""
    print("\n" + "=" * 70)
    print("TESTING COMPONENT IMPORTS")
    print("=" * 70)

    components = [
        'verification.claude_api_client',
        'verification.claude_prompt_manager',
        'verification.few_shot_selector',
        'verification.claude_service',
        'verification.jobs.claude_queue_builder',
        'verification.jobs.claude_prompt_optimizer',
        'verification.jobs.claude_ml_retrainer'
    ]

    all_ok = True
    for component in components:
        try:
            __import__(component)
            print(f"✓ {component}")
        except Exception as e:
            print(f"✗ {component}: {e}")
            all_ok = False

    return all_ok


def test_queue_builder():
    """Test queue builder (dry run)."""
    print("\n" + "=" * 70)
    print("TESTING QUEUE BUILDER")
    print("=" * 70)

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from verification.jobs.claude_queue_builder import queue_borderline_companies

        result = queue_borderline_companies(limit=10, dry_run=True)

        print(f"Would queue: {result.get('would_queue', 0)} companies")
        print(f"  Priority 10: {result.get('priority_10', 0)}")
        print(f"  Priority 50: {result.get('priority_50', 0)}")
        print(f"  Priority 100: {result.get('priority_100', 0)}")

        return True

    except Exception as e:
        print(f"✗ Queue builder error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "CLAUDE AUTO-TUNING SYSTEM TEST" + " " * 23 + "║")
    print("╚" + "═" * 68 + "╝")

    results = []

    # Run tests
    results.append(("Environment", test_environment()))
    results.append(("Database", test_database()))
    results.append(("Claude API", test_api_client()))
    results.append(("Components", test_components()))
    results.append(("Queue Builder", test_queue_builder()))

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:10} {name}")
        if not passed:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("\n✓ ALL TESTS PASSED - System is ready!")
        print("\nNext steps:")
        print("  1. Start Claude service: ./venv/bin/python verification/claude_service.py")
        print("  2. Queue companies: ./venv/bin/python verification/jobs/claude_queue_builder.py")
        print("  3. Monitor: tail -f logs/claude_service.log")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED - Check errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Quick test script to validate scrape batch functionality.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from niceui.backend_facade import backend
from datetime import datetime


def test_scrape_batch():
    """Test scrape batch with tiny limit."""
    print("=" * 60)
    print("TESTING SCRAPE BATCH WITH TINY LIMIT")
    print("=" * 60)

    # Configuration
    limit = 3
    stale_days = 30
    only_missing_email = False

    print(f"\nConfiguration:")
    print(f"  Limit: {limit}")
    print(f"  Stale Days: {stale_days}")
    print(f"  Only Missing Email: {only_missing_email}")
    print()

    # Track start time
    start_time = datetime.now()
    print(f"Start Time: {start_time.strftime('%H:%M:%S')}")
    print("\nRunning scrape batch...")
    print("-" * 60)

    try:
        # Run the scrape
        result = backend.scrape_batch(
            limit=limit,
            stale_days=stale_days,
            only_missing_email=only_missing_email,
            cancel_flag=None
        )

        # Calculate elapsed time and rate
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        items_per_min = (result["processed"] / elapsed * 60) if elapsed > 0 else 0

        print("-" * 60)
        print(f"\nEnd Time: {end_time.strftime('%H:%M:%S')}")
        print(f"Elapsed: {elapsed:.1f}s")
        print(f"Rate: {items_per_min:.1f} items/min")
        print()

        # Display results
        print("RESULTS:")
        print("=" * 60)
        print(f"  Processed: {result['processed']}")
        print(f"  Updated:   {result['updated']} ✓")
        print(f"  Skipped:   {result['skipped']} ⊘")
        print(f"  Errors:    {result['errors']} ✗")
        print("=" * 60)

        # Validation
        print("\nVALIDATION:")
        total = result['updated'] + result['skipped'] + result['errors']
        if total == result['processed']:
            print(f"  ✓ Counts add up correctly: {total} = {result['processed']}")
        else:
            print(f"  ✗ Count mismatch: {total} != {result['processed']}")

        if result['processed'] <= limit:
            print(f"  ✓ Processed within limit: {result['processed']} <= {limit}")
        else:
            print(f"  ✗ Exceeded limit: {result['processed']} > {limit}")

        print("\n✓ Test completed successfully!")

    except Exception as e:
        print(f"\n✗ Test failed with error:")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    test_scrape_batch()

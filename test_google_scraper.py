#!/usr/bin/env python3
"""
Test script for Google Business Scraper

Tests the Playwright-based Google Maps scraper with a simple search.

Usage:
    python test_google_scraper.py
"""

import asyncio
import json
from pathlib import Path

from scrape_google.google_client import GoogleBusinessClient
from scrape_google.google_config import GoogleConfig
from scrape_google.google_logger import GoogleScraperLogger


async def test_search():
    """Test Google Maps search functionality."""
    print("=" * 70)
    print("Google Business Scraper - Test Script")
    print("=" * 70)
    print()

    # Create configuration (with faster delays for testing)
    config = GoogleConfig()

    # Override delays for faster testing (use defaults in production)
    print("Configuration:")
    print(f"  - Rate limit: {config.rate_limit.min_delay}-{config.rate_limit.max_delay}s")
    print(f"  - Browser: {config.playwright.browser_type}")
    print(f"  - Headless: {config.playwright.headless}")
    print(f"  - Max results: {config.scraping.max_results_per_search}")
    print()

    # Override for faster testing (ONLY for testing - use defaults in production)
    print("⚠️  OVERRIDING delays for faster testing (use defaults in production)")
    config.rate_limit.min_delay = 5  # 5 seconds instead of 30
    config.rate_limit.max_delay = 10  # 10 seconds instead of 60
    config.scraping.max_results_per_search = 3  # Only 3 results for testing
    print(f"  - Test rate limit: {config.rate_limit.min_delay}-{config.rate_limit.max_delay}s")
    print(f"  - Test max results: {config.scraping.max_results_per_search}")
    print()

    # Create logger
    logger = GoogleScraperLogger(log_dir="logs")

    print("Starting browser...")
    print()

    # Create client and run test
    async with GoogleBusinessClient(config=config, logger=logger) as client:
        print("Browser started successfully!")
        print()

        # Test search
        test_query = "car wash"
        test_location = "Seattle, WA"

        print(f"Testing search: '{test_query}' in '{test_location}'")
        print("This will take a few moments due to rate limiting...")
        print()

        try:
            results = await client.search_google_maps(
                query=test_query,
                location=test_location,
                max_results=3
            )

            print(f"✓ Search completed successfully!")
            print(f"  Found {len(results)} results")
            print()

            if results:
                print("Results:")
                print("-" * 70)
                for idx, business in enumerate(results, 1):
                    print(f"\n{idx}. {business.get('name', 'N/A')}")
                    print(f"   Address: {business.get('address', 'N/A')}")
                    print(f"   Place ID: {business.get('place_id', 'N/A')}")
                    print(f"   URL: {business.get('url', 'N/A')[:80]}...")

                print()
                print("-" * 70)

                # Test scraping details for first business
                if results[0].get('url'):
                    print()
                    print(f"Testing detailed scrape for: {results[0].get('name', 'N/A')}")
                    print("This will take another moment...")
                    print()

                    details = await client.scrape_business_details(results[0]['url'])

                    if details:
                        print("✓ Business details scraped successfully!")
                        print()
                        print("Extracted fields:")
                        print("-" * 70)

                        for field, value in details.items():
                            if not field.startswith('_'):  # Skip metadata fields
                                print(f"  {field}: {value}")

                        print()
                        print(f"  Data completeness: {details.get('data_completeness', 0):.2f}")
                        print("-" * 70)
                    else:
                        print("✗ No details extracted")

            else:
                print("No results found (this might indicate CAPTCHA or detection)")

            print()
            print("Session statistics:")
            print("-" * 70)
            stats = client.get_stats()
            for key, value in stats.items():
                print(f"  {key}: {value}")
            print("-" * 70)

        except Exception as e:
            print(f"✗ Error during test: {e}")
            import traceback
            traceback.print_exc()

    print()
    print("Browser closed")
    print()
    print("=" * 70)
    print("Test completed!")
    print()
    print("Check logs in logs/ directory:")
    print("  - logs/google_scrape.log     - Main scraping operations")
    print("  - logs/google_errors.log     - Errors only")
    print("  - logs/google_metrics.log    - Performance metrics")
    print("  - logs/google_operations.log - Business operations")
    print("=" * 70)


def main():
    """Main entry point."""
    try:
        asyncio.run(test_search())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

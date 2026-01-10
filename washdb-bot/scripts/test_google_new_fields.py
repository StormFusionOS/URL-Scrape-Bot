#!/usr/bin/env python3
"""Test Google scraper with new enhanced fields."""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db.models import Company, GoogleTarget
from scrape_google.google_crawl_city_first import crawl_single_target


async def main():
    """Test Google scraper on a single target."""

    database_url = os.getenv("DATABASE_URL")
    engine = create_engine(database_url)

    with Session(engine) as session:
        # Get a PLANNED target (small city for quick test)
        target = (
            session.query(GoogleTarget)
            .filter(GoogleTarget.status == "PLANNED")
            .filter(GoogleTarget.state_id == "RI")  # Rhode Island for quick test
            .order_by(GoogleTarget.id)
            .first()
        )

        if not target:
            print("No PLANNED targets found for RI, trying any state...")
            target = (
                session.query(GoogleTarget)
                .filter(GoogleTarget.status == "PLANNED")
                .order_by(GoogleTarget.id)
                .first()
            )

        if not target:
            print("No PLANNED targets found!")
            return

        print(f"Testing with target: {target.city}, {target.state_id} - {target.category_label}")
        print(f"Target ID: {target.id}")
        print("-" * 60)

        # Run the scraper
        try:
            results, stats = await crawl_single_target(
                target=target,
                session=session,
                save_to_db=True,
            )

            print(f"\nResults: {stats}")
            print(f"Total businesses found: {len(results)}")

            # Check for new fields in the results
            for i, result in enumerate(results[:3]):  # First 3
                print(f"\n--- Business {i+1}: {result.get('name')} ---")
                print(f"  website: {result.get('website', 'N/A')}")
                print(f"  place_id: {result.get('place_id', 'N/A')}")
                print(f"  hours: {result.get('hours', 'N/A')}")
                print(f"  price_range: {result.get('price_range', 'N/A')}")
                print(f"  category: {result.get('category', 'N/A')}")
                print(f"  reviews_count: {result.get('reviews_count', 'N/A')}")
                print(f"  city: {result.get('city', 'N/A')}")
                print(f"  state: {result.get('state', 'N/A')}")

            # Check database for saved records with new fields
            if results:
                print("\n" + "=" * 60)
                print("Checking database for saved records with new fields...")

                # Get recently saved companies from Google
                recent = session.execute(
                    text("""
                        SELECT
                            id, name, domain,
                            google_place_id, google_hours, google_price_range,
                            google_category, google_business_url, reviews_google
                        FROM companies
                        WHERE source = 'Google'
                        ORDER BY id DESC
                        LIMIT 5
                    """)
                ).fetchall()

                for row in recent:
                    print(f"\nCompany ID {row[0]}: {row[1]}")
                    print(f"  domain: {row[2]}")
                    print(f"  google_place_id: {row[3]}")
                    print(f"  google_hours: {row[4]}")
                    print(f"  google_price_range: {row[5]}")
                    print(f"  google_category: {row[6]}")
                    print(f"  google_business_url: {row[7]}")
                    print(f"  reviews_google: {row[8]}")

        except Exception as e:
            print(f"Error during scrape: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

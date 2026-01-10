#!/usr/bin/env python3
"""Test YP scraper with new enhanced fields."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db.models import Company, YPTarget
from scrape_yp.yp_crawl_city_first import crawl_single_target
from scrape_yp.yp_filter import YPFilter


def main():
    """Test YP scraper on a single target."""

    # Initialize filter
    yp_filter = YPFilter()

    database_url = os.getenv("DATABASE_URL")
    engine = create_engine(database_url)

    with Session(engine) as session:
        # Get a planned target (small city for quick test)
        target = (
            session.query(YPTarget)
            .filter(YPTarget.status == "planned")
            .filter(YPTarget.state_id == "RI")
            .order_by(YPTarget.id)
            .first()
        )

        if not target:
            print("No planned targets found for RI, trying any state...")
            target = (
                session.query(YPTarget)
                .filter(YPTarget.status == "planned")
                .order_by(YPTarget.id)
                .first()
            )

        if not target:
            print("No planned targets found!")
            return

        print(f"Testing with target: {target.city}, {target.state_id} - {target.category_label}")
        print(f"Target ID: {target.id}")
        print("-" * 60)

        # Run the scraper
        try:
            results, stats = crawl_single_target(
                target=target,
                session=session,
                yp_filter=yp_filter,
            )

            print(f"\nResults: {stats}")
            print(f"Total businesses found: {len(results)}")

            # Check for new fields in the results
            for i, result in enumerate(results[:5]):  # First 5
                print(f"\n--- Business {i+1}: {result.get('name')} ---")
                print(f"  website: {result.get('website', 'N/A')}")
                print(f"  years_in_business: {result.get('years_in_business', 'N/A')}")
                print(f"  certifications: {result.get('certifications', 'N/A')}")
                print(f"  social_links: {result.get('social_links', 'N/A')}")
                print(f"  yp_photo_count: {result.get('yp_photo_count', 'N/A')}")
                print(f"  rating_yp: {result.get('rating_yp', 'N/A')}")
                print(f"  reviews_yp: {result.get('reviews_yp', 'N/A')}")

            # Check database for saved records with new fields
            if results:
                print("\n" + "=" * 60)
                print("Checking database for saved records with new fields...")

                # Get recently saved companies from YP
                recent = session.execute(
                    text("""
                        SELECT
                            id, name, domain,
                            years_in_business, certifications, social_links,
                            yp_photo_count, rating_yp, reviews_yp
                        FROM companies
                        WHERE source = 'YP'
                        ORDER BY id DESC
                        LIMIT 5
                    """)
                ).fetchall()

                for row in recent:
                    print(f"\nCompany ID {row[0]}: {row[1]}")
                    print(f"  domain: {row[2]}")
                    print(f"  years_in_business: {row[3]}")
                    print(f"  certifications: {row[4]}")
                    print(f"  social_links: {row[5]}")
                    print(f"  yp_photo_count: {row[6]}")
                    print(f"  rating_yp: {row[7]}")
                    print(f"  reviews_yp: {row[8]}")

        except Exception as e:
            print(f"Error during scrape: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

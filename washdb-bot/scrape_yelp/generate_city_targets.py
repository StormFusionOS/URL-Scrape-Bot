"""
Generate Yelp city-first scraping targets.

This module generates target lists by expanding:
  state_ids → all cities → all allowed categories

Each target represents a city × category combination to be scraped from Yelp.

Usage:
    python -m scrape_yelp.generate_city_targets --states RI CA TX
    python -m scrape_yelp.generate_city_targets --states RI --clear
"""

import argparse
import csv
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from db.models import CityRegistry, YelpTarget

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file")

CATEGORIES_PATH = "scrape_yelp/categories.csv"


def load_categories(csv_path: str) -> list[dict]:
    """
    Load category label → keyword mappings from CSV.

    Returns:
        List of dicts with keys: 'label', 'keyword', 'source'
    """
    categories = []
    full_path = Path(project_root) / csv_path

    if not full_path.exists():
        raise FileNotFoundError(f"Categories file not found: {full_path}")

    with open(full_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categories.append({
                "label": row["label"].strip(),
                "keyword": row["keyword"].strip(),
                "source": row.get("source", "").strip(),
            })

    return categories


def tier_to_max_results(tier: int) -> int:
    """
    Map population tier to max results target.

    Args:
        tier: Population tier (1=high, 2=medium, 3=low)

    Returns:
        Max results count (20-60)
    """
    tier_map = {
        1: 60,  # High-population cities: fetch more results
        2: 40,  # Medium-population cities
        3: 20,  # Low-population cities: fetch fewer results
    }
    return tier_map.get(tier, 20)


def generate_targets(session, state_ids: list[str], clear_existing: bool = False) -> int:
    """
    Generate Yelp scraping targets for specified states.

    Process:
    1. Query CityRegistry for all active cities in state_ids
    2. Load categories from CSV
    3. For each city × category:
       - Calculate max_results based on population tier
       - Set priority from city registry
       - Insert into yelp_targets table
    4. Handle duplicates gracefully (ON CONFLICT DO NOTHING)

    Args:
        session: SQLAlchemy session
        state_ids: List of 2-letter state codes (e.g., ['RI', 'CA'])
        clear_existing: If True, clear existing targets for these states first

    Returns:
        Number of targets created
    """
    print(f"\n{'='*70}")
    print(f"Yelp Target Generation")
    print(f"{'='*70}")
    print(f"States: {', '.join(state_ids)}")
    print(f"Clear existing: {clear_existing}")
    print()

    # Step 1: Clear existing targets if requested
    if clear_existing:
        print("🗑️  Clearing existing targets...")
        deleted_count = session.execute(
            delete(YelpTarget).where(YelpTarget.state_id.in_(state_ids))
        ).rowcount
        session.commit()
        print(f"   ✓ Deleted {deleted_count:,} existing targets\n")

    # Step 2: Query cities
    print("🏙️  Querying cities from registry...")
    cities = (
        session.query(CityRegistry)
        .filter(CityRegistry.state_id.in_(state_ids))
        .filter(CityRegistry.active == True)
        .order_by(CityRegistry.priority, CityRegistry.population.desc())
        .all()
    )
    print(f"   ✓ Found {len(cities):,} active cities\n")

    if not cities:
        print("⚠️  No active cities found for specified states")
        return 0

    # Step 3: Load categories
    print("📋 Loading categories...")
    categories = load_categories(CATEGORIES_PATH)
    print(f"   ✓ Loaded {len(categories)} categories\n")

    # Step 4: Generate targets
    print("🎯 Generating targets...")
    targets_created = 0
    targets_skipped = 0
    batch_size = 1000
    batch = []

    for i, city in enumerate(cities, 1):
        for category in categories:
            # Calculate max_results based on population tier
            max_results = tier_to_max_results(city.priority)

            # Create target
            target = YelpTarget(
                provider="Yelp",
                state_id=city.state_id,
                city=city.city,
                city_slug=city.city_slug,
                lat=city.lat,
                lng=city.lng,
                category_label=category["label"],
                category_keyword=category["keyword"],
                max_results=max_results,
                priority=city.priority,
                status="PLANNED",
            )

            batch.append(target)

            # Insert batch
            if len(batch) >= batch_size:
                try:
                    session.bulk_save_objects(batch)
                    session.commit()
                    targets_created += len(batch)
                    batch = []
                except Exception as e:
                    # Handle duplicates
                    session.rollback()
                    # Try inserting one by one to identify duplicates
                    for t in batch:
                        try:
                            session.add(t)
                            session.commit()
                            targets_created += 1
                        except Exception:
                            session.rollback()
                            targets_skipped += 1
                    batch = []

        # Progress update
        if i % 10 == 0 or i == len(cities):
            print(f"   Progress: {i}/{len(cities)} cities processed "
                  f"({targets_created + targets_skipped:,} targets, "
                  f"{targets_created:,} created, {targets_skipped:,} skipped)")

    # Insert remaining batch
    if batch:
        try:
            session.bulk_save_objects(batch)
            session.commit()
            targets_created += len(batch)
        except Exception as e:
            session.rollback()
            for t in batch:
                try:
                    session.add(t)
                    session.commit()
                    targets_created += 1
                except Exception:
                    session.rollback()
                    targets_skipped += 1

    # Summary
    print(f"\n{'='*70}")
    print(f"✅ Target Generation Complete")
    print(f"{'='*70}")
    print(f"Cities processed: {len(cities):,}")
    print(f"Categories: {len(categories)}")
    print(f"Targets created: {targets_created:,}")
    print(f"Targets skipped (duplicates): {targets_skipped:,}")
    print(f"Total targets: {targets_created + targets_skipped:,}")
    print(f"{'='*70}\n")

    return targets_created


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate Yelp city-first scraping targets"
    )
    parser.add_argument(
        "--states",
        type=str,
        required=True,
        help="Comma-separated list of state codes (e.g., 'RI,CA,TX')"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing targets for these states before generating"
    )

    args = parser.parse_args()

    # Parse state list
    state_ids = [s.strip().upper() for s in args.states.split(",")]

    # Connect to database
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Generate targets
        targets_created = generate_targets(
            session,
            state_ids,
            clear_existing=args.clear
        )

        if targets_created > 0:
            print(f"✅ Successfully generated {targets_created:,} Yelp targets")
        else:
            print("⚠️  No targets were generated")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()

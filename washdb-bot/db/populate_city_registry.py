"""
Populate City Registry from uscities.csv dataset.

This script:
1. Creates the city_registry and yp_targets tables if they don't exist
2. Reads uscities.csv (31,255 cities)
3. Calculates population percentiles for tier assignment
4. Generates city slugs and yp_geo for each city
5. Inserts all cities into the city_registry table

Usage:
    python db/populate_city_registry.py
"""

import csv
import os
import statistics
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, CityRegistry, YPTarget
from scrape_yp.city_slug import (
    calculate_population_tier,
    generate_city_slug,
    generate_yp_geo,
)

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file")

CSV_PATH = "/home/rivercityscrape/Downloads/uscities.csv"


def create_tables(engine):
    """Create all tables if they don't exist."""
    print("Creating database tables...")
    Base.metadata.create_all(engine)
    print("✓ Tables created successfully")


def read_cities_csv(csv_path: str) -> list[dict]:
    """
    Read cities from CSV file.

    Returns:
        List of city dictionaries with all fields
    """
    print(f"Reading cities from {csv_path}...")
    cities = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cities.append(row)

    print(f"✓ Read {len(cities):,} cities from CSV")
    return cities


def calculate_percentiles(cities: list[dict]) -> tuple[int, int]:
    """
    Calculate population percentiles for tier assignment.

    Returns:
        (percentile_90, percentile_50) - thresholds for high/medium/low tiers
    """
    print("Calculating population percentiles...")

    # Extract populations (handle missing/empty values)
    populations = []
    for city in cities:
        pop_str = city.get("population", "").strip()
        if pop_str:
            try:
                populations.append(int(pop_str))
            except ValueError:
                pass

    if not populations:
        print("⚠ Warning: No valid population data found, using defaults")
        return (100000, 10000)  # Default thresholds

    # Sort populations for percentile calculation
    populations.sort()

    # Calculate percentiles manually (90th and 50th)
    n = len(populations)
    idx_90 = int(n * 0.90)
    idx_50 = int(n * 0.50)

    percentile_90 = populations[idx_90]
    percentile_50 = populations[idx_50]

    print(f"  90th percentile (Tier A threshold): {percentile_90:,}")
    print(f"  50th percentile (Tier B threshold): {percentile_50:,}")

    return (percentile_90, percentile_50)


def parse_boolean(value: str) -> bool:
    """Parse string boolean to Python bool."""
    return value.strip().upper() == "TRUE"


def populate_registry(session, cities: list[dict], percentile_90: int, percentile_50: int):
    """
    Populate city_registry table with all cities.

    Args:
        session: SQLAlchemy session
        cities: List of city dicts from CSV
        percentile_90: 90th percentile population threshold
        percentile_50: 50th percentile population threshold
    """
    print(f"\nPopulating city_registry with {len(cities):,} cities...")

    batch_size = 1000
    total_inserted = 0
    total_skipped = 0

    city_objects = []
    used_slugs = set()  # Track used slugs to handle duplicates

    for idx, row in enumerate(cities, 1):
        try:
            # Parse population
            population = None
            pop_str = row.get("population", "").strip()
            if pop_str:
                try:
                    population = int(pop_str)
                except ValueError:
                    population = None

            # Parse density
            density = None
            density_str = row.get("density", "").strip()
            if density_str:
                try:
                    density = float(density_str)
                except ValueError:
                    density = None

            # Parse coordinates
            try:
                lat = float(row["lat"])
                lng = float(row["lng"])
            except (ValueError, KeyError):
                print(f"⚠ Skipping city {row.get('city')} - invalid coordinates")
                total_skipped += 1
                continue

            # Parse ranking
            ranking = None
            ranking_str = row.get("ranking", "").strip()
            if ranking_str:
                try:
                    ranking = int(ranking_str)
                except ValueError:
                    ranking = None

            # Calculate tier and priority
            if population:
                tier = calculate_population_tier(population, percentile_90, percentile_50)
            else:
                tier = 3  # Default to low priority if no population data

            # Generate slugs
            city_name = row["city"]
            state_id = row["state_id"]
            city_slug = generate_city_slug(city_name, state_id)
            yp_geo = generate_yp_geo(city_name, state_id)

            # Handle duplicate slugs by appending county name
            if city_slug in used_slugs:
                county_name = row.get("county_name", "").strip()
                if county_name:
                    # Append county to make unique
                    county_slug = county_name.lower().replace(" ", "-")
                    city_slug = f"{city_slug}-{county_slug}"

                # If still duplicate, append a counter
                counter = 2
                original_slug = city_slug
                while city_slug in used_slugs:
                    city_slug = f"{original_slug}-{counter}"
                    counter += 1

            used_slugs.add(city_slug)

            # Create CityRegistry object
            city_obj = CityRegistry(
                city=city_name,
                city_ascii=row["city_ascii"],
                state_id=state_id,
                state_name=row["state_name"],
                county_fips=row.get("county_fips") or None,
                county_name=row.get("county_name") or None,
                lat=lat,
                lng=lng,
                population=population,
                density=density,
                timezone=row.get("timezone") or None,
                zips=row.get("zips") or None,
                ranking=ranking,
                source=row.get("source", "shape"),
                military=parse_boolean(row.get("military", "FALSE")),
                incorporated=parse_boolean(row.get("incorporated", "TRUE")),
                active=True,  # All cities active by default
                city_slug=city_slug,
                yp_geo=yp_geo,
                priority=tier,
            )

            city_objects.append(city_obj)

            # Batch insert
            if len(city_objects) >= batch_size:
                try:
                    session.bulk_save_objects(city_objects)
                    session.commit()
                    total_inserted += len(city_objects)
                    print(f"  Inserted {total_inserted:,} cities...")
                except Exception as batch_error:
                    print(f"⚠ Batch insert error: {batch_error}")
                    session.rollback()
                    total_skipped += len(city_objects)
                finally:
                    city_objects = []

        except Exception as e:
            print(f"⚠ Error processing city {row.get('city', 'unknown')}: {e}")
            total_skipped += 1
            continue

    # Insert remaining cities
    if city_objects:
        try:
            session.bulk_save_objects(city_objects)
            session.commit()
            total_inserted += len(city_objects)
        except Exception as batch_error:
            print(f"⚠ Final batch insert error: {batch_error}")
            session.rollback()
            total_skipped += len(city_objects)

    print(f"\n✓ City Registry populated:")
    print(f"  Inserted: {total_inserted:,} cities")
    print(f"  Skipped:  {total_skipped:,} cities")


def generate_state_summary(session):
    """Generate and display summary of cities per state."""
    from sqlalchemy import func

    print("\n" + "=" * 60)
    print("City Registry Summary by State")
    print("=" * 60)

    # Query cities per state
    results = (
        session.query(
            CityRegistry.state_id,
            CityRegistry.state_name,
            func.count(CityRegistry.id).label("city_count"),
        )
        .group_by(CityRegistry.state_id, CityRegistry.state_name)
        .order_by(func.count(CityRegistry.id).desc())
        .all()
    )

    print(f"{'State':5s} {'State Name':20s} {'Cities':>10s}")
    print("-" * 60)

    total_cities = 0
    for state_id, state_name, city_count in results:
        print(f"{state_id:5s} {state_name:20s} {city_count:>10,d}")
        total_cities += city_count

    print("-" * 60)
    print(f"{'TOTAL':5s} {' ':20s} {total_cities:>10,d}")
    print("=" * 60)


def main():
    """Main execution function."""
    print("=" * 60)
    print("City Registry Population Script")
    print("=" * 60)

    # Create database engine
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Step 1: Create tables
        create_tables(engine)

        # Step 2: Check if registry already has data
        existing_count = session.query(CityRegistry).count()
        if existing_count > 0:
            print(f"\n⚠ Warning: city_registry already has {existing_count:,} entries")
            response = input("Clear existing data and re-populate? (yes/no): ")
            if response.lower() != "yes":
                print("Aborted.")
                return

            # Clear existing data
            session.query(CityRegistry).delete()
            session.commit()
            print("✓ Existing data cleared")

        # Step 3: Read cities from CSV
        cities = read_cities_csv(CSV_PATH)

        # Step 4: Calculate percentiles
        percentile_90, percentile_50 = calculate_percentiles(cities)

        # Step 5: Populate registry
        populate_registry(session, cities, percentile_90, percentile_50)

        # Step 6: Generate summary
        generate_state_summary(session)

        print("\n✓ City Registry population complete!")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        session.rollback()
        return 1

    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

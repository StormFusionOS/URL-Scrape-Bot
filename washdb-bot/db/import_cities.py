#!/usr/bin/env python3
"""
Import uscities.csv data into city_registry table.

This script:
1. Reads uscities.csv
2. Parses ZIP codes from space-separated "zips" column
3. Assigns priority tiers based on population
4. Loads data into city_registry table
"""
import csv
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from runner.logging_setup import get_logger

logger = get_logger("import_cities")

# Database connection
DB_USER = "scraper_user"
DB_PASSWORD = "ScraperPass123"
DB_HOST = "localhost"
DB_NAME = "scraper"
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

# Population thresholds for tier assignment
TIER_A_MIN = 100000  # Cities >= 100k population
TIER_B_MIN = 25000   # Cities >= 25k population
# All others get Tier C

def assign_tier(population):
    """Assign tier based on population."""
    if not population or population < TIER_B_MIN:
        return 'C'
    elif population < TIER_A_MIN:
        return 'B'
    else:
        return 'A'

def parse_zips(zips_str):
    """
    Parse space-separated ZIP codes.

    Returns:
        tuple: (zips_str, primary_zip) where primary_zip is the first ZIP code
    """
    if not zips_str or zips_str.strip() == "":
        return (None, None)

    # Clean up the string
    zips_str = zips_str.strip()

    # Split by spaces and get first ZIP
    zip_list = zips_str.split()
    primary_zip = zip_list[0] if zip_list else None

    return (zips_str, primary_zip)

def import_cities(csv_path: str):
    """Import cities from CSV into database."""

    if not Path(csv_path).exists():
        logger.error(f"CSV file not found: {csv_path}")
        return False

    logger.info(f"Importing cities from {csv_path}")

    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        # Clear existing data
        logger.info("Clearing existing city_registry data...")
        conn.execute(text("TRUNCATE TABLE city_registry RESTART IDENTITY CASCADE"))
        conn.commit()

        # Read CSV and insert rows
        inserted = 0
        skipped = 0

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            batch = []
            batch_size = 1000

            for row in reader:
                try:
                    # Parse population
                    population = int(row.get('population') or 0) if row.get('population') else None

                    # Parse ZIP codes
                    zips_str, primary_zip = parse_zips(row.get('zips', ''))

                    # Skip cities without ZIP codes
                    if not primary_zip:
                        skipped += 1
                        continue

                    # Assign tier
                    tier = assign_tier(population)

                    # Parse other numeric fields
                    lat = float(row['lat']) if row.get('lat') else None
                    lng = float(row['lng']) if row.get('lng') else None
                    density = float(row['density']) if row.get('density') else None
                    ranking = int(row['ranking']) if row.get('ranking') else None

                    batch.append({
                        'city': row['city'],
                        'city_ascii': row['city_ascii'],
                        'state_id': row['state_id'],
                        'state_name': row['state_name'],
                        'county_name': row.get('county_name'),
                        'lat': lat,
                        'lng': lng,
                        'population': population,
                        'density': density,
                        'timezone': row.get('timezone'),
                        'ranking': ranking,
                        'zips': zips_str,
                        'primary_zip': primary_zip,
                        'tier': tier,
                    })

                    # Insert batch when full
                    if len(batch) >= batch_size:
                        conn.execute(text("""
                            INSERT INTO city_registry (
                                city, city_ascii, state_id, state_name, county_name,
                                lat, lng, population, density, timezone, ranking,
                                zips, primary_zip, tier
                            ) VALUES (
                                :city, :city_ascii, :state_id, :state_name, :county_name,
                                :lat, :lng, :population, :density, :timezone, :ranking,
                                :zips, :primary_zip, :tier
                            )
                        """), batch)
                        conn.commit()
                        inserted += len(batch)
                        logger.info(f"Imported {inserted} cities...")
                        batch = []

                except Exception as e:
                    logger.error(f"Error processing row {row.get('city')}: {e}")
                    skipped += 1

            # Insert remaining batch
            if batch:
                conn.execute(text("""
                    INSERT INTO city_registry (
                        city, city_ascii, state_id, state_name, county_name,
                        lat, lng, population, density, timezone, ranking,
                        zips, primary_zip, tier
                    ) VALUES (
                        :city, :city_ascii, :state_id, :state_name, :county_name,
                        :lat, :lng, :population, :density, :timezone, :ranking,
                        :zips, :primary_zip, :tier
                    )
                """), batch)
                conn.commit()
                inserted += len(batch)

    logger.info("=" * 60)
    logger.info(f"Import complete!")
    logger.info(f"  Inserted: {inserted}")
    logger.info(f"  Skipped: {skipped}")
    logger.info("=" * 60)

    # Show tier distribution
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT tier, COUNT(*) as count
            FROM city_registry
            GROUP BY tier
            ORDER BY tier
        """))

        logger.info("Tier Distribution:")
        for row in result:
            logger.info(f"  Tier {row.tier}: {row.count} cities")

    return True

def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Import uscities.csv into city_registry table")
    parser.add_argument(
        '--csv',
        default='/home/rivercityscrape/Downloads/uscities.csv',
        help='Path to uscities.csv file'
    )

    args = parser.parse_args()

    success = import_cities(args.csv)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

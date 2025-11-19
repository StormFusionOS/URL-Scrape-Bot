#!/usr/bin/env python3
"""
Import uscities.csv data into city_registry table (using psycopg directly).
"""
import csv
import sys
from pathlib import Path

# Try to import psycopg (PostgreSQL adapter)
try:
    import psycopg
except ImportError:
    try:
        import psycopg2 as psycopg
        # Map psycopg2 to psycopg interface
        psycopg.connect = psycopg.connect
    except ImportError:
        print("ERROR: Neither psycopg nor psycopg2 is installed")
        print("Try: pip3 install psycopg2-binary --break-system-packages")
        sys.exit(1)

# Database connection
DB_USER = "scraper_user"
DB_PASSWORD = "ScraperPass123"
DB_HOST = "localhost"
DB_NAME = "scraper"

# Population thresholds for tier assignment
TIER_A_MIN = 100000  # Cities >= 100k population
TIER_B_MIN = 25000   # Cities >= 25k population

def assign_tier(population):
    """Assign tier based on population."""
    if not population or population < TIER_B_MIN:
        return 'C'
    elif population < TIER_A_MIN:
        return 'B'
    else:
        return 'A'

def parse_zips(zips_str):
    """Parse space-separated ZIP codes."""
    if not zips_str or zips_str.strip() == "":
        return (None, None)

    zips_str = zips_str.strip()
    zip_list = zips_str.split()
    primary_zip = zip_list[0] if zip_list else None

    return (zips_str, primary_zip)

def import_cities(csv_path: str):
    """Import cities from CSV into database."""

    if not Path(csv_path).exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return False

    print(f"Importing cities from {csv_path}")

    # Connect to database
    conn = psycopg.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    cur = conn.cursor()

    try:
        # Clear existing data
        print("Clearing existing city_registry data...")
        cur.execute("TRUNCATE TABLE city_registry RESTART IDENTITY CASCADE")
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

                    batch.append((
                        row['city'],
                        row['city_ascii'],
                        row['state_id'],
                        row['state_name'],
                        row.get('county_name'),
                        lat,
                        lng,
                        population,
                        density,
                        row.get('timezone'),
                        ranking,
                        zips_str,
                        primary_zip,
                        tier,
                    ))

                    # Insert batch when full
                    if len(batch) >= batch_size:
                        cur.executemany("""
                            INSERT INTO city_registry (
                                city, city_ascii, state_id, state_name, county_name,
                                lat, lng, population, density, timezone, ranking,
                                zips, primary_zip, tier
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (city_ascii, state_id) DO NOTHING
                        """, batch)
                        conn.commit()
                        inserted += len(batch)
                        print(f"Imported {inserted} cities...")
                        batch = []

                except Exception as e:
                    print(f"ERROR processing row {row.get('city')}: {e}")
                    skipped += 1

            # Insert remaining batch
            if batch:
                cur.executemany("""
                    INSERT INTO city_registry (
                        city, city_ascii, state_id, state_name, county_name,
                        lat, lng, population, density, timezone, ranking,
                        zips, primary_zip, tier
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (city_ascii, state_id) DO NOTHING
                """, batch)
                conn.commit()
                inserted += len(batch)

        print("=" * 60)
        print(f"Import complete!")
        print(f"  Inserted: {inserted}")
        print(f"  Skipped: {skipped}")
        print("=" * 60)

        # Show tier distribution
        cur.execute("""
            SELECT tier, COUNT(*) as count
            FROM city_registry
            GROUP BY tier
            ORDER BY tier
        """)

        print("Tier Distribution:")
        for row in cur.fetchall():
            print(f"  Tier {row[0]}: {row[1]} cities")

        # Show sample cities
        print("\nSample cities by tier:")
        for tier in ['A', 'B', 'C']:
            cur.execute("""
                SELECT city, state_id, population, primary_zip
                FROM city_registry
                WHERE tier = %s
                ORDER BY population DESC NULLS LAST
                LIMIT 3
            """, (tier,))

            print(f"\n  Tier {tier}:")
            for row in cur.fetchall():
                city, state, pop, zip_code = row
                print(f"    {city}, {state} (pop: {pop:,}, ZIP: {zip_code})")

        return True

    finally:
        cur.close()
        conn.close()

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

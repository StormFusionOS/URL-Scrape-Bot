"""
Generate Yellow Pages city-first scraping targets.

This module generates target lists by expanding:
  state_ids → all cities → all allowed categories

Each target represents a city × category combination to be scraped.

Usage:
    python -m scrape_yp.generate_city_targets --states RI CA TX

Auto-regeneration:
    The check_and_regenerate_if_needed() function can be called at startup
    to automatically regenerate targets when category configuration changes.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import CityRegistry, YPTarget
from scrape_yp.city_slug import tier_to_max_pages

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file")

CATEGORY_SLUGS_PATH = "data/yp_category_slugs.csv"
YP_BASE_URL = "https://www.yellowpages.com"


def load_category_slugs(csv_path: str) -> list[dict]:
    """
    Load category label → slug mappings from CSV.

    Returns:
        List of dicts with keys: 'label', 'slug'
    """
    categories = []
    full_path = Path(project_root) / csv_path

    if not full_path.exists():
        raise FileNotFoundError(f"Category slugs file not found: {full_path}")

    with open(full_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categories.append({
                "label": row["label"].strip(),
                "slug": row["slug"].strip(),
            })

    return categories


def build_primary_url(city_slug: str, category_slug: str) -> str:
    """
    Build primary city-category URL.

    Format: https://www.yellowpages.com/{city-slug}-{state}/category-slug

    Args:
        city_slug: City-state slug (e.g., 'los-angeles-ca')
        category_slug: Category slug (e.g., 'window-cleaning')

    Returns:
        Full URL string
    """
    return f"{YP_BASE_URL}/{city_slug}/{category_slug}"


def build_fallback_url(category_label: str, yp_geo: str) -> str:
    """
    Build fallback search URL.

    Format: https://www.yellowpages.com/search?search_terms={category}&geo_location_terms={City, ST}

    Args:
        category_label: Human-readable category (e.g., 'Window Cleaning')
        yp_geo: Geo format (e.g., 'Los Angeles, CA')

    Returns:
        Full search URL string
    """
    search_terms = quote_plus(category_label)
    geo_terms = quote_plus(yp_geo)
    return f"{YP_BASE_URL}/search?search_terms={search_terms}&geo_location_terms={geo_terms}"


def generate_targets(session, state_ids: list[str], clear_existing: bool = False) -> int:
    """
    Generate YP targets for specified states.

    Args:
        session: SQLAlchemy session
        state_ids: List of 2-letter state codes (e.g., ['RI', 'CA', 'TX'])
        clear_existing: If True, clear existing targets for these states first

    Returns:
        Number of targets generated
    """
    print(f"\nGenerating YP targets for states: {', '.join(state_ids)}")
    print("=" * 60)

    # Step 1: Load category slugs
    print("Loading category slugs...")
    categories = load_category_slugs(CATEGORY_SLUGS_PATH)
    print(f"  ✓ Loaded {len(categories)} categories")

    # Step 2: Clear existing targets if requested
    if clear_existing:
        print("Clearing existing targets...")
        deleted = (
            session.query(YPTarget)
            .filter(YPTarget.state_id.in_(state_ids))
            .delete(synchronize_session=False)
        )
        session.commit()
        print(f"  ✓ Deleted {deleted} existing targets")

    # Step 3: Fetch cities for these states
    print("Fetching cities from registry...")
    cities = (
        session.query(CityRegistry)
        .filter(
            CityRegistry.state_id.in_(state_ids),
            CityRegistry.active == True,
        )
        .all()
    )
    print(f"  ✓ Found {len(cities)} cities across {len(state_ids)} state(s)")

    # Step 4: Generate targets (city × category)
    print("\nGenerating targets (city × category)...")

    targets_generated = 0
    batch_size = 1000
    target_objects = []

    for city in cities:
        for category in categories:
            # Build URLs
            primary_url = build_primary_url(city.city_slug, category["slug"])
            fallback_url = build_fallback_url(category["label"], city.yp_geo)

            # Calculate max_pages from priority tier
            max_pages = tier_to_max_pages(city.priority)

            # Create target object
            target = YPTarget(
                provider="YP",
                state_id=city.state_id,
                city=city.city,
                city_slug=city.city_slug,
                yp_geo=city.yp_geo,
                category_label=category["label"],
                category_slug=category["slug"],
                primary_url=primary_url,
                fallback_url=fallback_url,
                max_pages=max_pages,
                priority=city.priority,
                status="planned",
                attempts=0,
            )

            target_objects.append(target)

            # Batch insert
            if len(target_objects) >= batch_size:
                session.bulk_save_objects(target_objects)
                session.commit()
                targets_generated += len(target_objects)
                print(f"  Inserted {targets_generated:,} targets...")
                target_objects = []

    # Insert remaining targets
    if target_objects:
        session.bulk_save_objects(target_objects)
        session.commit()
        targets_generated += len(target_objects)

    print(f"\n✓ Target generation complete:")
    print(f"  States: {len(state_ids)}")
    print(f"  Cities: {len(cities):,}")
    print(f"  Categories: {len(categories)}")
    print(f"  Targets Generated: {targets_generated:,}")
    print(f"  Expected: {len(cities) * len(categories):,}")

    return targets_generated


def generate_summary_report(session, state_ids: list[str]):
    """Generate and display summary of targets by state and category."""
    from sqlalchemy import func

    print("\n" + "=" * 60)
    print("Target Summary by State")
    print("=" * 60)

    # Query targets per state
    results = (
        session.query(
            YPTarget.state_id,
            func.count(YPTarget.id).label("target_count"),
        )
        .filter(YPTarget.state_id.in_(state_ids))
        .group_by(YPTarget.state_id)
        .order_by(func.count(YPTarget.id).desc())
        .all()
    )

    print(f"{'State':6s} {'Targets':>12s}")
    print("-" * 60)

    total_targets = 0
    for state_id, target_count in results:
        print(f"{state_id:6s} {target_count:>12,d}")
        total_targets += target_count

    print("-" * 60)
    print(f"{'TOTAL':6s} {total_targets:>12,d}")
    print("=" * 60)


CATEGORY_HASH_FILE = Path(project_root) / "data" / ".yp_category_hash.json"
ALL_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
]


def compute_category_hash() -> str:
    """
    Compute a hash of the category configuration files.

    Returns:
        SHA256 hash of combined category files
    """
    hasher = hashlib.sha256()

    # Files that affect category configuration
    config_files = [
        Path(project_root) / "data" / "yp_category_slugs.csv",
        Path(project_root) / "data" / "yp_category_allowlist.txt",
        Path(project_root) / "data" / "yp_category_blocklist.txt",
    ]

    for file_path in config_files:
        if file_path.exists():
            with open(file_path, "rb") as f:
                hasher.update(f.read())

    return hasher.hexdigest()


def get_stored_hash() -> dict:
    """
    Get the stored category hash and metadata.

    Returns:
        Dict with 'hash' and 'regenerated_at' keys, or empty dict if not found
    """
    if CATEGORY_HASH_FILE.exists():
        try:
            with open(CATEGORY_HASH_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_hash(hash_value: str):
    """
    Save the current category hash.

    Args:
        hash_value: SHA256 hash to save
    """
    from datetime import datetime

    data = {
        "hash": hash_value,
        "regenerated_at": datetime.now().isoformat(),
    }

    CATEGORY_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CATEGORY_HASH_FILE, "w") as f:
        json.dump(data, f, indent=2)


def check_and_regenerate_if_needed(state_ids: list[str] = None, force: bool = False) -> bool:
    """
    Check if category configuration has changed and regenerate targets if needed.

    This function should be called at YP scraper startup to ensure targets
    are up-to-date with the latest category configuration.

    Args:
        state_ids: List of state codes to regenerate (default: all states)
        force: Force regeneration even if hash hasn't changed

    Returns:
        True if targets were regenerated, False otherwise
    """
    if state_ids is None:
        state_ids = ALL_STATES

    current_hash = compute_category_hash()
    stored = get_stored_hash()
    stored_hash = stored.get("hash", "")

    if not force and current_hash == stored_hash:
        print(f"✓ Category configuration unchanged (hash: {current_hash[:12]}...)")
        return False

    print("=" * 60)
    print("Category configuration changed - regenerating targets")
    print("=" * 60)
    if stored_hash:
        print(f"  Old hash: {stored_hash[:12]}...")
        print(f"  New hash: {current_hash[:12]}...")

    # Create database engine
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Generate targets with clear (to remove old categories)
        generate_targets(
            session,
            state_ids,
            clear_existing=True
        )

        # Save new hash
        save_hash(current_hash)

        # Generate summary report
        generate_summary_report(session, state_ids)

        print("\n✓ Target auto-regeneration complete!")
        return True

    except Exception as e:
        print(f"\n✗ Auto-regeneration error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return False

    finally:
        session.close()


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Generate YP city-first targets")
    parser.add_argument(
        "--states",
        type=str,
        required=True,
        help="Comma-separated list of state codes (e.g., 'RI,CA,TX')",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing targets for these states before generating",
    )

    args = parser.parse_args()

    # Parse state list
    state_ids = [s.strip().upper() for s in args.states.split(",")]

    print("=" * 60)
    print("Yellow Pages Target Generator")
    print("=" * 60)

    # Create database engine
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Generate targets
        targets_generated = generate_targets(
            session,
            state_ids,
            clear_existing=args.clear
        )

        # Generate summary report
        generate_summary_report(session, state_ids)

        print("\n✓ Target generation complete!")
        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())

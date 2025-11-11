"""
Bing query variant generator for washdb-bot.

This module implements multi-variant query generation based on the Yellow Pages
enterprise implementation guide (Prompt E). For each category×location pair, it
generates 5-8 different query variants to maximize recall while minimizing duplication.

Core Patterns:
- Exact phrase + location (quoted primary synonym)
- Synonym rotation (2-4 top variants)
- Evidence operators (intitle:, inurl:) on 25-35% of queries
- Optional directory targeting (site:yellowpages.com)
- Negative keywords applied to all queries

Usage:
    from scrape_bing.query_variants import generate_query_variants

    variants = generate_query_variants("pressure washing", "AL")
    for variant in variants:
        print(variant['query'])
"""

import random
from typing import List, Dict, Any


# ==============================================================================
# Service Taxonomy (Prompt A - Simplified for Core Categories)
# ==============================================================================

CATEGORY_SYNONYMS = {
    "pressure washing": {
        "primary": "pressure washing",
        "synonyms": ["power washing", "pressure wash", "power wash", "pressure cleaning", "jet wash"],
        "short": "pressure wash"  # For intitle: operator
    },
    "soft washing": {
        "primary": "soft washing",
        "synonyms": ["soft wash", "softwashing", "low pressure wash", "soft washing service"],
        "short": "soft wash"
    },
    "house washing": {
        "primary": "house washing",
        "synonyms": ["home washing", "siding cleaning", "exterior washing", "exterior house wash"],
        "short": "house wash"
    },
    "roof cleaning": {
        "primary": "roof cleaning",
        "synonyms": ["roof wash", "roof soft wash", "algae removal", "moss removal"],
        "short": "roof clean"
    },
    "gutter cleaning": {
        "primary": "gutter cleaning",
        "synonyms": ["gutter cleanout", "downspout cleaning", "gutter brightening"],
        "short": "gutter clean"
    },
    "window cleaning": {
        "primary": "window cleaning",
        "synonyms": ["window washing", "glass cleaning", "storefront window cleaning"],
        "short": "window clean"
    },
    "concrete cleaning": {
        "primary": "concrete cleaning",
        "synonyms": ["driveway cleaning", "sidewalk cleaning", "patio cleaning", "pool deck cleaning"],
        "short": "concrete clean"
    },
    "deck cleaning": {
        "primary": "deck cleaning",
        "synonyms": ["deck wash", "deck restoration", "deck staining"],
        "short": "deck clean"
    },
    "fence cleaning": {
        "primary": "fence cleaning",
        "synonyms": ["fence wash", "fence restoration", "fence staining"],
        "short": "fence clean"
    },
    "paver cleaning": {
        "primary": "paver cleaning",
        "synonyms": ["paver wash", "paver sealing", "patio paver sealing"],
        "short": "paver clean"
    }
}


# ==============================================================================
# Negative Keywords (Prompt C)
# ==============================================================================

# Global negatives applied to all queries
GLOBAL_NEGATIVES = [
    "rental", "for sale", "parts", "detergent", "chemical supplier",
    "hose", "nozzle", "trailer sales", "repair", "hardware store"
]

# Category-specific negatives
CATEGORY_NEGATIVES = {
    "window cleaning": ["tint", "film", "replacement", "install", "glazing contractor"],
    "roof cleaning": ["roofer", "roofing", "roof replacement", "shingles install"],
    "gutter cleaning": ["install", "replacement", "guards sales", "leaf filter"],
    "concrete cleaning": ["concrete contractor", "foundation repair", "asphalt paving"],
    "paver cleaning": ["concrete contractor", "foundation repair", "asphalt paving"],
    "deck cleaning": ["builder", "carpentry", "lumber", "pergola"],
    "fence cleaning": ["fence company", "install", "builder", "carpentry"]
}


# ==============================================================================
# Location Utilities
# ==============================================================================

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}


def expand_location(location: str) -> str:
    """
    Expand state code to full name if applicable.

    Args:
        location: Location string (e.g., "AL", "Peoria IL")

    Returns:
        Expanded location (e.g., "Alabama", "Peoria IL")
    """
    return STATE_NAMES.get(location.upper(), location)


def get_merged_negatives(category: str) -> List[str]:
    """
    Build merged negative keyword list for a category.

    Merges global negatives with category-specific negatives.

    Args:
        category: Service category (e.g., "pressure washing")

    Returns:
        List of negative keywords
    """
    merged = GLOBAL_NEGATIVES.copy()

    # Add category-specific negatives if they exist
    category_key = category.lower()
    if category_key in CATEGORY_NEGATIVES:
        merged.extend(CATEGORY_NEGATIVES[category_key])

    return merged


def format_negatives(negatives: List[str]) -> str:
    """
    Format negative keywords for Bing query.

    Args:
        negatives: List of negative keywords

    Returns:
        Formatted string like "-rental -parts -detergent"
    """
    return " ".join(f"-{kw}" for kw in negatives)


# ==============================================================================
# Query Variant Generator (Prompt E)
# ==============================================================================

def generate_query_variants(
    category: str,
    location: str,
    variants_per_pair: int = 6,
    apply_evidence_ops_ratio: float = 0.35,
    include_directory_targeting: bool = False
) -> List[Dict[str, Any]]:
    """
    Generate 5-8 query variants for a category × location pair.

    Implements Prompt E recipe for multi-variant Bing queries:
    - Exact phrase + location (quoted primary)
    - Synonym rotation (2-4 variants)
    - Evidence operators (intitle:, inurl:) on ~35% of queries
    - Optional Yellow Pages directory targeting
    - Negative keywords on all queries

    Args:
        category: Service category (e.g., "pressure washing")
        location: Geographic location (e.g., "AL", "Peoria IL")
        variants_per_pair: Number of variants to generate (default: 6)
        apply_evidence_ops_ratio: Ratio of queries with operators (default: 0.35)
        include_directory_targeting: Include site:yellowpages.com variant

    Returns:
        List of variant dicts with keys:
        - query: Full query string
        - pattern: Pattern type (exact, synonym, operator, directory)
        - negatives: List of negative keywords used

    Example:
        >>> variants = generate_query_variants("pressure washing", "AL")
        >>> len(variants)
        6
        >>> variants[0]['query']
        '"pressure washing" Alabama -rental -parts -detergent -repair'
    """
    # Normalize category key
    category_key = category.lower()

    # Get category data or fall back to generic
    if category_key in CATEGORY_SYNONYMS:
        cat_data = CATEGORY_SYNONYMS[category_key]
        primary = cat_data["primary"]
        synonyms = cat_data["synonyms"]
        short = cat_data["short"]
    else:
        # Fallback for unknown categories
        primary = category
        synonyms = [category]
        short = category.split()[0] if " " in category else category

    # Expand location
    location_expanded = expand_location(location)

    # Get merged negative keywords
    negatives = get_merged_negatives(category_key)
    negatives_str = format_negatives(negatives)

    # Generate variants
    variants = []

    # 1. Exact phrase + location (primary synonym, quoted)
    variants.append({
        "query": f'"{primary}" {location_expanded} {negatives_str}',
        "pattern": "exact",
        "negatives": negatives
    })

    # 2. Synonym variants (2-4 top synonyms, unquoted)
    # Randomly select synonyms for variation
    num_synonyms = min(3, len(synonyms))  # Use up to 3 synonyms
    selected_synonyms = random.sample(synonyms, num_synonyms) if len(synonyms) >= num_synonyms else synonyms
    for syn in selected_synonyms:
        variants.append({
            "query": f'{syn} {location_expanded} {negatives_str}',
            "pattern": "synonym",
            "negatives": negatives
        })

    # 3. Evidence operators (apply to ~35% of variants)
    # - intitle:"{{short synonym}}" {{location}}
    # - inurl:services {{primary}} {{location}}
    num_operator_variants = max(1, int(variants_per_pair * apply_evidence_ops_ratio))

    if num_operator_variants >= 1:
        variants.append({
            "query": f'intitle:"{short}" {location_expanded} {negatives_str}',
            "pattern": "operator_intitle",
            "negatives": negatives
        })

    if num_operator_variants >= 2:
        variants.append({
            "query": f'inurl:services {primary} {location_expanded} {negatives_str}',
            "pattern": "operator_inurl",
            "negatives": negatives
        })

    # 4. Optional directory targeting (Yellow Pages harvesting)
    if include_directory_targeting:
        variants.append({
            "query": f'site:yellowpages.com "{primary}" {location_expanded}',
            "pattern": "directory",
            "negatives": []  # YP queries typically don't need negatives
        })

    # Limit to requested number of variants
    variants = variants[:variants_per_pair]

    # Shuffle variants to randomize execution order (prevents detection patterns)
    random.shuffle(variants)

    # Add variant index for tracking
    for idx, variant in enumerate(variants, 1):
        variant["variant_index"] = idx
        variant["category"] = category
        variant["location"] = location

    return variants


# ==============================================================================
# Testing / CLI
# ==============================================================================

if __name__ == "__main__":
    # Test with pressure washing + Alabama
    print("=" * 80)
    print("BING QUERY VARIANT GENERATOR TEST")
    print("=" * 80)
    print()

    category = "pressure washing"
    location = "AL"

    print(f"Category: {category}")
    print(f"Location: {location}")
    print()

    variants = generate_query_variants(category, location, variants_per_pair=6)

    print(f"Generated {len(variants)} query variants:")
    print("-" * 80)

    for variant in variants:
        print(f"\n{variant['variant_index']}. Pattern: {variant['pattern']}")
        print(f"   Query: {variant['query']}")
        print(f"   Negatives: {len(variant['negatives'])} keywords")

    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

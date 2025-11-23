#!/usr/bin/env python3
"""
Test script for LLM verifier.

Tests the LLM classification on sample companies to validate:
1. Prompt engineering works correctly
2. Response parsing is robust
3. Scoring logic is reasonable
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from scrape_site.llm_verifier import get_llm_verifier


def test_pressure_washing_company():
    """Test classification of a clear pressure washing company."""
    print("\n" + "="*70)
    print("TEST 1: Clear Pressure Washing Company")
    print("="*70)

    verifier = get_llm_verifier()

    result = verifier.classify_company(
        company_name="Under Pressure Power Washing LLC",
        services_text="We provide professional pressure washing services for driveways, decks, siding, and more. Residential and commercial cleaning.",
        about_text="Family-owned pressure washing business serving Austin since 2010.",
        homepage_text="Get your property looking like new with our expert power washing services."
    )

    print(f"Company: Under Pressure Power Washing LLC")
    print(f"Result: {result}")

    if result:
        score, details = verifier.calculate_llm_score(result)
        print(f"Score: {score}/100")
        print(f"Details: {details}")

        # Assertions
        assert result['type'] == 1, "Should be type 1 (service provider)"
        assert result['pressure_washing'] == True, "Should detect pressure washing"
        print("✅ PASSED")
    else:
        print("❌ FAILED: No result returned")

    return result


def test_multi_service_company():
    """Test classification of company offering multiple services."""
    print("\n" + "="*70)
    print("TEST 2: Multi-Service Company")
    print("="*70)

    verifier = get_llm_verifier()

    result = verifier.classify_company(
        company_name="Sparkle Clean Pros",
        services_text="""
        Our Services:
        - Pressure Washing: Driveways, sidewalks, patios
        - Window Cleaning: Inside and outside, all types
        - Deck Restoration: Staining, sealing, refinishing

        We serve both homeowners and businesses throughout the DFW metroplex.
        """,
        about_text="Full-service exterior cleaning company. Licensed and insured.",
        homepage_text="Complete exterior care for your property. Free estimates!"
    )

    print(f"Company: Sparkle Clean Pros")
    print(f"Result: {result}")

    if result:
        score, details = verifier.calculate_llm_score(result)
        print(f"Score: {score}/100")
        print(f"Details: {details}")

        # Assertions
        assert result['type'] == 1, "Should be type 1 (service provider)"
        assert result['pressure_washing'] == True, "Should detect pressure washing"
        assert result['window_cleaning'] == True, "Should detect window cleaning"
        assert result['wood_restoration'] == True, "Should detect wood restoration"
        assert result['scope'] == 1, "Should detect both residential and commercial"
        print("✅ PASSED")
    else:
        print("❌ FAILED: No result returned")

    return result


def test_equipment_seller():
    """Test classification of equipment seller (should be rejected)."""
    print("\n" + "="*70)
    print("TEST 3: Equipment Seller (Should Reject)")
    print("="*70)

    verifier = get_llm_verifier()

    result = verifier.classify_company(
        company_name="Pressure Washer Depot",
        services_text="Shop our wide selection of pressure washers, pumps, nozzles, and accessories. Free shipping on orders over $50.",
        about_text="Online retailer of pressure washing equipment since 2005.",
        homepage_text="Buy the best pressure washers at the lowest prices. Add to cart today!"
    )

    print(f"Company: Pressure Washer Depot")
    print(f"Result: {result}")

    if result:
        score, details = verifier.calculate_llm_score(result)
        print(f"Score: {score}/100")
        print(f"Details: {details}")

        # Assertions
        assert result['type'] == 2, "Should be type 2 (equipment seller)"
        assert score < 30, "Score should be low for equipment seller"
        print("✅ PASSED")
    else:
        print("❌ FAILED: No result returned")

    return result


def test_blog_content():
    """Test classification of blog/informational content (should be rejected)."""
    print("\n" + "="*70)
    print("TEST 4: Blog/Informational Content (Should Reject)")
    print("="*70)

    verifier = get_llm_verifier()

    result = verifier.classify_company(
        company_name="Home Cleaning Tips",
        services_text="In this article, we'll explain how to pressure wash your driveway. Step 1: Choose the right pressure washer. Step 2: Prepare the surface...",
        about_text="DIY home improvement guides and tutorials for homeowners.",
        homepage_text="Learn how to clean your home like a pro with our expert guides."
    )

    print(f"Company: Home Cleaning Tips")
    print(f"Result: {result}")

    if result:
        score, details = verifier.calculate_llm_score(result)
        print(f"Score: {score}/100")
        print(f"Details: {details}")

        # Assertions
        assert result['type'] in [3, 5], "Should be type 3 (training) or 5 (blog)"
        assert score < 30, "Score should be low for blog content"
        print("✅ PASSED")
    else:
        print("❌ FAILED: No result returned")

    return result


def test_residential_only():
    """Test classification of residential-only service."""
    print("\n" + "="*70)
    print("TEST 5: Residential-Only Service")
    print("="*70)

    verifier = get_llm_verifier()

    result = verifier.classify_company(
        company_name="Home Window Cleaners",
        services_text="Professional window cleaning for homeowners. We clean inside and outside windows, screens, and tracks. Serving residential properties only.",
        about_text="Residential window cleaning specialists. Family-owned and operated.",
        homepage_text="Keep your home's windows sparkling clean year-round."
    )

    print(f"Company: Home Window Cleaners")
    print(f"Result: {result}")

    if result:
        score, details = verifier.calculate_llm_score(result)
        print(f"Score: {score}/100")
        print(f"Details: {details}")

        # Assertions
        assert result['type'] == 1, "Should be type 1 (service provider)"
        assert result['window_cleaning'] == True, "Should detect window cleaning"
        assert result['scope'] == 2, "Should detect residential only"
        print("✅ PASSED")
    else:
        print("❌ FAILED: No result returned")

    return result


def main():
    """Run all tests."""
    print("\n" + "#"*70)
    print("# LLM VERIFIER TEST SUITE")
    print("#"*70)

    try:
        # Run tests
        test_pressure_washing_company()
        test_multi_service_company()
        test_equipment_seller()
        test_blog_content()
        test_residential_only()

        print("\n" + "="*70)
        print("ALL TESTS COMPLETED")
        print("="*70)

    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

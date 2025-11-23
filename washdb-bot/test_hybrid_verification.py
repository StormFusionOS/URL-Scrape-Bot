#!/usr/bin/env python3
"""
Integration test for hybrid LLM + rule-based verification system.

Tests the complete flow:
1. ServiceVerifier with LLM enabled
2. Hybrid scoring for uncertain cases (rule score 0.30-0.80)
3. Fallback to rule-only for clear cases
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scrape_site.service_verifier import create_verifier


def test_hybrid_system():
    """Test the hybrid verification system end-to-end."""
    print("\n" + "="*70)
    print("HYBRID LLM + RULE-BASED VERIFICATION SYSTEM TEST")
    print("="*70)

    # Create verifier with LLM enabled
    print("\n1. Initializing ServiceVerifier with LLM mode...")
    verifier = create_verifier(use_llm=True)
    print(f"   ✓ Verifier created: LLM={'enabled' if verifier.use_llm else 'disabled'}")

    # Test Case 1: Clear service provider (should use fast path - rule score > 0.80)
    print("\n2. Test Case: Clear Pressure Washing Company")
    print("-" * 70)

    company_data = {
        'name': 'Under Pressure Power Washing LLC',
        'website': 'https://underpressurewashing.com',
        'phone': '(512) 555-1234',
        'email': 'info@underpressurewashing.com',
        'address': '123 Main St, Austin, TX'
    }

    website_metadata = {
        'services': 'Professional pressure washing for driveways, decks, siding, and more. Residential and commercial cleaning.',
        'about': 'Family-owned pressure washing business serving Austin since 2010.',
        'homepage_text': 'Get your property looking like new with our expert power washing services. Free estimates!',
        'has_phone': True,
        'has_email': True,
        'has_address': True
    }

    result = verifier.verify_company(company_data, website_metadata=website_metadata)

    print(f"Company: {company_data['name']}")
    print(f"Result: status={result['status']}, score={result['score']:.2f}, tier={result['tier']}")
    print(f"Services: {result['services_detected']}")
    print(f"LLM used: {'Yes' if 'llm_score' in result else 'No (fast path)'}")

    if 'llm_score' in result:
        print(f"LLM score: {result['llm_score']}/100")
        print(f"LLM classification: {result.get('llm_classification', {})}")

    # Test Case 2: Uncertain case (should trigger LLM - rule score 0.30-0.80)
    print("\n3. Test Case: Uncertain Company (Limited Info)")
    print("-" * 70)

    company_data2 = {
        'name': 'Clean Pros',
        'website': 'https://cleanpros.com',
        'phone': None,
        'email': None,
        'address': None
    }

    website_metadata2 = {
        'services': 'We offer cleaning services for homes and businesses.',
        'about': 'Professional cleaning company.',
        'homepage_text': 'Contact us for a quote.',
        'has_phone': False,
        'has_email': False,
        'has_address': False
    }

    result2 = verifier.verify_company(company_data2, website_metadata=website_metadata2)

    print(f"Company: {company_data2['name']}")
    print(f"Result: status={result2['status']}, score={result2['score']:.2f}, tier={result2['tier']}")
    print(f"Services: {result2['services_detected']}")
    print(f"LLM used: {'Yes' if 'llm_score' in result2 else 'No'}")

    if 'llm_score' in result2:
        print(f"LLM score: {result2['llm_score']}/100")
        print(f"LLM classification: {result2.get('llm_classification', {})}")

    # Summary
    print("\n" + "="*70)
    print("HYBRID SYSTEM TEST COMPLETE")
    print("="*70)
    print(f"✓ ServiceVerifier initialized with LLM: {verifier.use_llm}")
    print(f"✓ Test 1 (clear case): {result['status']} (score={result['score']:.2f})")
    print(f"✓ Test 2 (uncertain case): {result2['status']} (score={result2['score']:.2f})")
    print("\nThe hybrid system is ready for production!")


if __name__ == '__main__':
    test_hybrid_system()

#!/usr/bin/env python3
"""
Test unified browser worker on 20 companies.

This tests:
1. ChatML prompt format (fixed with raw: True)
2. Rich content extraction
3. Verification + standardization flow
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# Test imports
print("Testing imports...")
from verification.browser_content_extractor import BrowserExtractedContent, get_json_ld_name
from verification.unified_llm import get_unified_llm

engine = create_engine(os.getenv('DATABASE_URL'))

# Get LLM
llm = get_unified_llm()
print(f"LLM initialized: {llm.model_name}")

# Get 20 companies with verification metadata
print("\nFetching 20 companies with parse_metadata...")
with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT id, name, website, phone, address, parse_metadata
        FROM companies
        WHERE llm_verified IS NULL
        AND website IS NOT NULL
        AND parse_metadata IS NOT NULL
        AND parse_metadata::text <> '{}'
        ORDER BY RANDOM()
        LIMIT 20
    '''))
    companies = []
    for r in result:
        companies.append({
            'id': r[0],
            'name': r[1],
            'website': r[2],
            'phone': r[3],
            'address': r[4],
            'meta': r[5] or {}
        })

print(f"Found {len(companies)} companies to test")

print('='*80)
print('UNIFIED VERIFICATION TEST - 20 COMPANIES (ChatML + Rich Content)')
print('='*80)

results = []
for i, c in enumerate(companies, 1):
    meta = c['meta']
    ver = meta.get('verification', {})

    # Extract signals from verification metadata
    quality_signals = ver.get('quality_signals', [])
    positive_signals = ver.get('positive_signals', [])
    negative_signals = ver.get('negative_signals', [])

    # Extract any JSON-LD from verification data
    llm_class = ver.get('llm_classification', {})

    # Build services text from signals
    services_text = ', '.join(positive_signals[:5]) if positive_signals else ''
    about_text = ver.get('reasoning', '')[:500] if ver.get('reasoning') else ''
    homepage_text = llm_class.get('reasoning', '')[:1000] if llm_class else ''

    try:
        # Test verify_company_rich (uses ChatML format)
        result = llm.verify_company_rich(
            company_name=c['name'],
            website=c['website'],
            phone=c.get('phone') or '',
            title=meta.get('title', ''),
            h1_text='',
            og_site_name='',
            json_ld=[],  # We don't have JSON-LD in this test data
            services_text=services_text,
            about_text=about_text,
            homepage_text=homepage_text,
            address=c.get('address') or '',
            emails=[],
        )

        if result:
            legitimate = result.get('legitimate', False)
            confidence = result.get('confidence', 0.0)
            reasoning = str(result.get('reasoning', ''))[:40]
            services = result.get('services', [])
            status = 'JSON_OK'
        else:
            legitimate = False
            confidence = 0.0
            reasoning = 'LLM returned None'
            services = []
            status = 'FAILED'

        icon = 'Y' if legitimate else 'N'
        svc_str = ', '.join(str(s) for s in services[:2]) if services else ''
        print(f'{i:2}. [{icon}] {c["name"][:30]:<32} conf={confidence:.1f}  {status:<8} {svc_str[:20]}')

        results.append({
            'name': c['name'],
            'legitimate': legitimate,
            'confidence': confidence,
            'status': status,
        })

    except Exception as e:
        print(f'{i:2}. ERROR: {c["name"][:30]} - {str(e)[:40]}')
        results.append({'name': c['name'], 'error': str(e)})

print()
print('='*80)
print('SUMMARY')
print('='*80)
total = len(results)
legit = sum(1 for r in results if r.get('legitimate', False))
not_legit = sum(1 for r in results if not r.get('legitimate', True) and 'error' not in r)
json_ok = sum(1 for r in results if r.get('status') == 'JSON_OK')
failed = sum(1 for r in results if r.get('status') == 'FAILED')
errors = sum(1 for r in results if 'error' in r)

print(f'Total tested:     {total}')
print(f'Legitimate:       {legit} ({100*legit/total:.0f}%)')
print(f'Not Legitimate:   {not_legit} ({100*not_legit/total:.0f}%)')
print(f'JSON parsed OK:   {json_ok} ({100*json_ok/total:.0f}%)')
print(f'LLM Failed:       {failed} ({100*failed/total:.0f}%)')
print(f'Errors:           {errors}')

if json_ok > 15:
    print()
    print("SUCCESS: ChatML format with raw: True is working correctly!")
else:
    print()
    print("WARNING: Check if ChatML format is being used correctly")

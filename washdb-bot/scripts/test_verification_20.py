#!/usr/bin/env python3
"""Test verification LLM on 20 companies using training data format."""

import os
import sys
import json
import requests
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv('DATABASE_URL'))

# System prompt matching training data exactly
SYSTEM_PROMPT = '''You are a business verification assistant. Your task is to determine if a company is a legitimate service provider that offers exterior building and property cleaning services.

Target services include:
- Pressure washing / power washing
- Window cleaning
- Soft washing
- Roof cleaning
- Gutter cleaning
- Solar panel cleaning
- Fleet/truck washing
- Wood restoration / deck cleaning

Analyze the company information and respond with a JSON object containing:
- legitimate: true/false - Is this a legitimate service provider?
- confidence: 0.0-1.0 - How confident are you?
- services: object with service types detected
- quality_signals: list of positive indicators
- red_flags: list of concerns or issues'''

# Get 20 companies with verification metadata
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

print('='*80)
print('VERIFICATION TEST - 20 COMPANIES (Training Format)')
print('='*80)

results = []
for i, c in enumerate(companies, 1):
    meta = c['meta']
    ver = meta.get('verification', {})

    # Extract signals from verification metadata
    quality_signals = ver.get('quality_signals', [])
    red_flags = ver.get('red_flags', [])
    positive_signals = ver.get('positive_signals', [])
    negative_signals = ver.get('negative_signals', [])

    # Build user content matching training format
    content = f"Company: {c['name']}\n"
    content += f"Website: {c['website']}\n"
    if c.get('phone'):
        content += f"Phone: {c['phone']}\n"
    if c.get('address'):
        content += f"Address: {c['address']}\n"

    if quality_signals:
        content += f"Quality signals: {', '.join(quality_signals[:5])}\n"
    if red_flags:
        content += f"Red flags: {', '.join(red_flags[:5])}\n"
    if positive_signals:
        content += f"Positive signals: {', '.join(positive_signals[:5])}\n"
    if negative_signals:
        content += f"Negative signals: {', '.join(negative_signals[:5])}\n"

    content += "\nIs this a legitimate service provider? Provide your assessment."

    # Use ChatML format matching training
    prompt = f'<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{content}<|im_end|>\n<|im_start|>assistant\n'

    try:
        resp = requests.post('http://localhost:11434/api/generate', json={
            'model': 'unified-washdb-v2',
            'prompt': prompt,
            'stream': False,
            'raw': True,
            'options': {'temperature': 0.1, 'num_predict': 300}
        }, timeout=60)

        text_resp = resp.json().get('response', '')

        # Try to parse JSON
        json_start = text_resp.find('{')
        json_end = text_resp.rfind('}') + 1

        if json_start >= 0 and json_end > json_start:
            try:
                parsed = json.loads(text_resp[json_start:json_end])
                legitimate = parsed.get('legitimate', False)
                confidence = parsed.get('confidence', 0.5)
                services = parsed.get('services', {})
                reasoning = str(parsed.get('quality_signals', parsed.get('reasoning', '')))[:50]
                status = 'JSON_OK'
            except:
                legitimate = False
                confidence = 0.3
                services = {}
                reasoning = 'JSON parse failed'
                status = 'FALLBACK'
        else:
            legitimate = False
            confidence = 0.3
            services = {}
            reasoning = text_resp[:40].replace('\n', ' ')
            status = 'FALLBACK'

        result = {
            'name': c['name'][:35],
            'website': c['website'][:40],
            'legitimate': legitimate,
            'confidence': confidence,
            'services': services,
            'reasoning': reasoning,
            'status': status
        }
        results.append(result)

        icon = 'Y' if legitimate else 'N'
        svc_str = ', '.join(k for k,v in services.items() if v) if isinstance(services, dict) else str(services)[:20]
        print(f'{i:2}. [{icon}] {c["name"][:30]:<32} conf={confidence:.1f}  {status:<8} {svc_str[:25]}')

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
fallback = sum(1 for r in results if r.get('status') == 'FALLBACK')
errors = sum(1 for r in results if 'error' in r)

print(f'Total tested:     {total}')
print(f'Legitimate:       {legit} ({100*legit/total:.0f}%)')
print(f'Not Legitimate:   {not_legit} ({100*not_legit/total:.0f}%)')
print(f'JSON parsed OK:   {json_ok} ({100*json_ok/total:.0f}%)')
print(f'Fallback parsed:  {fallback} ({100*fallback/total:.0f}%)')
print(f'Errors:           {errors}')

print()
print('='*80)
print('DETAILED RESULTS')
print('='*80)
for r in results:
    if 'error' not in r:
        icon = 'Y' if r['legitimate'] else 'N'
        svc_str = ', '.join(k for k,v in r.get('services', {}).items() if v) if isinstance(r.get('services'), dict) else ''
        print(f"[{icon}] {r['name'][:35]:<37} | {r['status']:<8} | conf={r['confidence']:.1f} | {svc_str[:30] or r['reasoning'][:30]}")

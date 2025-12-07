#!/usr/bin/env python3
"""Test Claude API to find working model name."""

import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('ANTHROPIC_API_KEY')
print(f"API Key: {api_key[:20]}...")

client = anthropic.Anthropic(api_key=api_key)

# Try different model names
model_names = [
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-latest",
    "claude-3-sonnet-20240229",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]

for model in model_names:
    print(f"\nTrying model: {model}")
    try:
        message = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": "Hi"
            }]
        )
        print(f"  ✓ SUCCESS! Model {model} works!")
        print(f"  Response: {message.content[0].text}")
        break
    except Exception as e:
        print(f"  ✗ Failed: {str(e)[:100]}")

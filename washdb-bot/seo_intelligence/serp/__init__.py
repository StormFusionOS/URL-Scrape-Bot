"""
SERP scraper module for monitoring search engine results.

Fetches Google SERP results for tracked keywords and stores:
- Top 10 organic results (position, url, title, description)
- Featured snippets (type, content, url)
- People Also Ask (PAA) questions

Uses Playwright for rendering JavaScript and capturing accurate SERP data.
"""

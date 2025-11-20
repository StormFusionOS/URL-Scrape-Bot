"""
Backlinks tracking module for Local Authority Score (LAS) calculation.

Tracks outbound links from competitor pages:
- Link extraction with position classification (in-body vs boilerplate)
- Deduplication and storage
- Link health monitoring (alive/dead)
- Aggregate backlink profiles by domain
"""

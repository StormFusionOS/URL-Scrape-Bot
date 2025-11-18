#!/usr/bin/env python3
"""
HomeAdvisor scraper client.

Responsibilities:
- Build search URLs for (category, state, page)
- Fetch list pages with retries, delay, (optional) proxy & UA rotation
- Parse list pages into candidate profiles
- Fetch each profile page to extract external website, phone, address, ratings

Note: Be polite. Respect robots.txt / ToS.
"""
from __future__ import annotations
import os, re, time, json, random
from typing import Optional, Dict, List
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from runner.logging_setup import get_logger

logger = get_logger("ha_client")

# --- Config ---
HA_BASE = "https://www.homeadvisor.com"
CRAWL_DELAY_SECONDS = int(os.getenv("HA_CRAWL_DELAY", "2"))
MAX_RETRIES = int(os.getenv("HA_MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = int(os.getenv("HA_RETRY_BACKOFF", "2"))
USE_BROWSER = os.getenv("HA_USE_BROWSER", "true").lower() == "true"  # Default to browser mode since HA requires JS
PROXY_URL = os.getenv("HA_PROXY_URL") or None

USER_AGENTS = [
    # rotate if HA blocks a specific UA
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]
OVERRIDE_UA = os.getenv("HA_USER_AGENT") or None

def _headers() -> Dict[str, str]:
    ua = OVERRIDE_UA or random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

def _proxies():
    return {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

# --- URL builder ---
def build_search_url(category: str, state: str = None, page: int = 1, zip_code: Optional[str] = None) -> str:
    """
    Build HomeAdvisor search URL.

    RECOMMENDED: Use ZIP code-based searches for better results.
    LEGACY: State-level searches still supported but may return fewer results.

    Args:
        category: Service category (e.g., "power washing")
        state: State code (e.g., "AL") - used for legacy state-level searches
        page: Page number (default: 1)
        zip_code: ZIP code for search (e.g., "35218") - RECOMMENDED

    Returns:
        Search URL string
    """
    cat_slug = re.sub(r"[^a-z0-9]+", "-", category.strip().lower())

    # ZIP code-based search (RECOMMENDED)
    if zip_code:
        # Normalize category to query string format
        query = category.strip().lower().replace(" ", "+")

        # Build base URL with ZIP code search
        base_url = (
            f"{HA_BASE}/find"
            f"?postalCode={zip_code}"
            f"&query={query}"
            f"&searchType=SiteTaskSearch"
            f"&initialSearch=true"
        )

        # Add page parameter if page > 1
        if page > 1:
            base_url += f"&startIndex={20 * (page - 1)}"  # HomeAdvisor uses startIndex, 20 results per page

        return base_url

    # Legacy state-level search (backward compatibility)
    elif state:
        base_url = f"{HA_BASE}/near-me/{cat_slug}/?state={state}"

        # Add page parameter if page > 1
        if page > 1:
            base_url += f"&page={page}"

        return base_url

    else:
        raise ValueError("Either zip_code or state is required for HomeAdvisor searches")

# --- Fetch with retries ---
def fetch_url(url: str, delay: Optional[int] = None) -> Optional[str]:
    """
    Fetch URL using either browser automation or HTTP requests.

    Uses Playwright if USE_BROWSER is True (default for HomeAdvisor),
    otherwise falls back to requests library.
    """
    if delay is None:
        delay = CRAWL_DELAY_SECONDS

    # Use browser automation if enabled
    if USE_BROWSER:
        logger.info(f"[Browser Mode] Fetching {url}")
        try:
            from scrape_ha.ha_browser import get_browser
            browser = get_browser()

            # Wait for business cards or profile content to load
            wait_selector = 'div[data-testid], article, div[class*="pro"], div[class*="business"]'

            html = browser.fetch_page(url, wait_for_selector=wait_selector, delay=delay)
            return html
        except Exception as e:
            logger.error(f"Browser fetch failed for {url}: {e}", exc_info=True)
            return None

    # Fallback to HTTP requests
    if delay > 0:
        time.sleep(delay)

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=_headers(), proxies=_proxies(), timeout=30)
            if resp.status_code == 429:
                backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(f"429 Too Many Requests on {url}; backing off {backoff}s")
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            if len(resp.text) < 256:
                # Likely interstitial or bot wall; backoff & retry
                time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
                continue
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt+1}/{MAX_RETRIES} failed for {url}: {e}")
            time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
    return None

# --- Parsers ---
PROFILE_HREF_RE = re.compile(r"^/pro/|^/sp/|^/rated\.|/rated\.|/profile$", re.I)

def parse_list_page(html: str) -> List[Dict]:
    """Extract profile cards from a HomeAdvisor result page."""
    soup = BeautifulSoup(html, "lxml")
    out: List[Dict] = []

    # Strategy A: JSON-LD blocks (organization / localBusiness)
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")  # may be array or object
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            if obj.get("@type", "").lower() not in {"localbusiness", "organization"}:
                continue
            name = obj.get("name")
            telephone = obj.get("telephone")
            url = obj.get("url")
            addr = None
            if isinstance(obj.get("address"), dict):
                parts = [obj["address"].get(k) for k in ("streetAddress","addressLocality","addressRegion","postalCode")]
                addr = ", ".join([p for p in parts if p])
            rating = None
            reviews = None
            if isinstance(obj.get("aggregateRating"), dict):
                rating = obj["aggregateRating"].get("ratingValue")
                reviews = obj["aggregateRating"].get("reviewCount")
            # We also try to capture the HA profile link from mainEntityOfPage or sameAs
            profile_url = obj.get("mainEntityOfPage") or obj.get("sameAs") or url
            out.append({
                "name": name,
                "phone": telephone,
                "address": addr,
                "profile_url": profile_url if isinstance(profile_url, str) else None,
                "rating_ha": float(rating) if rating else None,
                "reviews_ha": int(reviews) if reviews else None,
            })

    # Strategy B: Card DOM fallbacks (very defensive)
    for a in soup.select("a[href]"):
        href = a.get("href","")
        if PROFILE_HREF_RE.search(href):
            card = a.find_parent(["article","div","li"]) or a
            name = (card.get_text(" ", strip=True) or "").split("•")[0][:120]
            out.append({
                "name": name or None,
                "profile_url": urljoin(HA_BASE, href),
            })

    # De‑dupe by profile_url
    seen = set()
    uniq = []
    for r in out:
        key = r.get("profile_url") or r.get("name")
        if key and key not in seen:
            uniq.append(r); seen.add(key)
    return uniq

def parse_profile_for_company(html: str) -> Dict:
    """On a company profile, try to extract external website, phone, address, ratings."""
    soup = BeautifulSoup(html, "lxml")
    result: Dict = {}

    # JSON‑LD first
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        obj = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        if isinstance(obj, dict):
            result["name"] = result.get("name") or obj.get("name")
            if isinstance(obj.get("address"), dict):
                parts = [obj["address"].get(k) for k in ("streetAddress","addressLocality","addressRegion","postalCode")]
                result["address"] = result.get("address") or ", ".join([p for p in parts if p])
            if isinstance(obj.get("aggregateRating"), dict):
                result["rating_ha"] = result.get("rating_ha") or obj["aggregateRating"].get("ratingValue")
                result["reviews_ha"] = result.get("reviews_ha") or obj["aggregateRating"].get("reviewCount")
            result["phone"] = result.get("phone") or obj.get("telephone")
            # External website may be under 'url' or 'sameAs' (filter non‑HA)
            candidates = []
            for key in ("url","sameAs"):
                v = obj.get(key)
                if isinstance(v, list):
                    candidates.extend(v)
                elif isinstance(v, str):
                    candidates.append(v)
            for u in candidates:
                if isinstance(u,str) and "homeadvisor.com" not in u and "angi.com" not in u:
                    result["website"] = u
                    break

    # Fallback: any outbound http(s) links not pointing to HA
    if not result.get("website"):
        for a in soup.select("a[href]"):
            href = a["href"]
            if href.startswith(("http://","https://")) and "homeadvisor.com" not in href and "angi.com" not in href:
                result["website"] = href
                break

    return result

"""
Enterprise SERP Session Pool Manager

Manages a pool of persistent, warm Google browser sessions that behave like real users.
This is the core of a Serper.dev-like system running on your own infrastructure.

Key principles:
1. Sessions are LONG-LIVED (days/weeks, not minutes)
2. Sessions are WARMED regularly (browse YouTube, news, etc.)
3. Sessions have ACCEPTED consent (cookies stored)
4. Sessions search SLOWLY (minutes between queries, not seconds)
5. Sessions behave HUMANLY (typing, scrolling, clicking)

Architecture:
    ┌─────────────────────────────────────────────────┐
    │           SerpSessionPool                       │
    │  ┌─────────┐ ┌─────────┐ ┌─────────┐          │
    │  │Session 1│ │Session 2│ │Session 3│ ...      │
    │  │(warm)   │ │(warm)   │ │(cooling)│          │
    │  └─────────┘ └─────────┘ └─────────┘          │
    └─────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────┐
    │           SessionWarmer (background)            │
    │  - Visits YouTube every 30-60 min              │
    │  - Scrolls Google News                         │
    │  - Makes session look like real user           │
    └─────────────────────────────────────────────────┘

Usage:
    pool = SerpSessionPool(num_sessions=5)
    await pool.initialize()

    # Get a warm session for searching
    session = await pool.get_session(geo_location="Boston, MA")
    results = await session.search("pressure washing near me")
"""

import os
import json
import time
import random
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor
import queue

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from runner.logging_setup import get_logger

load_dotenv()

logger = get_logger("serp_session_pool")

# Configuration constants
# Use just 1 session to avoid Playwright asyncio conflicts when creating multiple browsers
# For 24/7 slow scraping (20 queries/hour), 1 session is sufficient
DEFAULT_NUM_SESSIONS = 1
MAX_SEARCHES_PER_SESSION_PER_DAY = 12
MIN_DELAY_BETWEEN_SEARCHES_SEC = 300  # 5 minutes minimum
MAX_DELAY_BETWEEN_SEARCHES_SEC = 1800  # 30 minutes maximum
SESSION_WARM_INTERVAL_SEC = 1800  # Warm each session every 30 minutes
SESSION_PROFILE_DIR = "data/serp_sessions"


@dataclass
class SessionStats:
    """Statistics for a single session."""
    session_id: int
    created_at: datetime = field(default_factory=datetime.now)
    last_search_at: Optional[datetime] = None
    last_warm_at: Optional[datetime] = None
    searches_today: int = 0
    searches_total: int = 0
    successes: int = 0
    failures: int = 0
    consent_accepted: bool = False
    is_healthy: bool = True
    current_proxy: Optional[str] = None

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 1.0

    @property
    def can_search(self) -> bool:
        """Check if this session can perform another search."""
        if not self.is_healthy:
            return False
        if self.searches_today >= MAX_SEARCHES_PER_SESSION_PER_DAY:
            return False
        if self.last_search_at:
            elapsed = (datetime.now() - self.last_search_at).total_seconds()
            if elapsed < MIN_DELAY_BETWEEN_SEARCHES_SEC:
                return False
        return True

    @property
    def needs_warming(self) -> bool:
        """Check if this session needs to be warmed."""
        if not self.last_warm_at:
            return True
        elapsed = (datetime.now() - self.last_warm_at).total_seconds()
        return elapsed > SESSION_WARM_INTERVAL_SEC

    def reset_daily(self):
        """Reset daily counters (call at midnight)."""
        self.searches_today = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_search_at": self.last_search_at.isoformat() if self.last_search_at else None,
            "last_warm_at": self.last_warm_at.isoformat() if self.last_warm_at else None,
            "searches_today": self.searches_today,
            "searches_total": self.searches_total,
            "successes": self.successes,
            "failures": self.failures,
            "consent_accepted": self.consent_accepted,
            "is_healthy": self.is_healthy,
            "success_rate": self.success_rate,
        }


@dataclass
class HumanBehaviorConfig:
    """Configuration for human-like behavior simulation."""

    # Typing behavior
    typing_speed_cps: tuple = (3, 8)  # Characters per second range
    typo_chance: float = 0.03  # 3% chance of typo
    typo_correction_delay: tuple = (0.5, 1.5)  # Seconds to notice typo

    # Search behavior
    pre_search_delay: tuple = (2, 5)  # Seconds before typing
    post_type_delay: tuple = (0.5, 2)  # Seconds after typing before Enter
    result_load_wait: tuple = (2, 4)  # Seconds to wait for results

    # Scrolling behavior
    scroll_probability: float = 0.8  # 80% chance to scroll results
    scroll_amount_range: tuple = (200, 600)  # Pixels per scroll
    scroll_pause_range: tuple = (0.5, 2)  # Seconds between scrolls
    num_scrolls_range: tuple = (2, 5)  # Number of scroll actions

    # Result interaction
    click_result_probability: float = 0.2  # 20% chance to click a result
    time_on_result_page: tuple = (5, 30)  # Seconds spent on clicked page
    back_to_serp_delay: tuple = (1, 3)  # Seconds before returning to SERP

    # Session warming
    warm_actions_per_cycle: int = 3  # Number of warming actions per cycle
    warm_sites: list = field(default_factory=lambda: [
        "https://www.youtube.com",
        "https://news.google.com",
        "https://www.google.com/maps",
        "https://trends.google.com",
    ])

    # Interstitial browsing (between searches)
    browse_between_searches: bool = True
    browse_probability: float = 0.7  # 70% chance to browse between searches
    browse_sites: list = field(default_factory=lambda: [
        # News & Media
        "https://www.reddit.com",
        "https://www.cnn.com",
        "https://www.bbc.com/news",
        "https://www.nytimes.com",
        "https://www.theguardian.com",
        "https://news.ycombinator.com",
        # Entertainment
        "https://www.youtube.com",
        "https://www.twitch.tv",
        "https://www.imdb.com",
        "https://www.rottentomatoes.com",
        # Shopping & Reference
        "https://www.amazon.com",
        "https://www.ebay.com",
        "https://www.wikipedia.org",
        "https://www.weather.com",
        # Tech
        "https://www.github.com",
        "https://stackoverflow.com",
        "https://www.producthunt.com",
        # Social (landing pages only)
        "https://www.linkedin.com",
        "https://www.pinterest.com",
    ])
    browse_time_range: tuple = (15, 60)  # Seconds to spend on each site
    browse_actions_range: tuple = (1, 3)  # Number of sites to visit between searches


class SerpResultCache:
    """
    24-hour cache for SERP results.

    Reduces actual Google queries by serving cached results for identical queries.
    """

    def __init__(self, db_url: str = None, ttl_hours: int = 24):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.ttl_hours = ttl_hours
        self._ensure_table()

    def _ensure_table(self):
        """Create cache table if it doesn't exist."""
        engine = create_engine(self.db_url)
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS serp_cache (
                    cache_key VARCHAR(64) PRIMARY KEY,
                    query TEXT NOT NULL,
                    location TEXT,
                    results JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    expires_at TIMESTAMP NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_serp_cache_expires
                ON serp_cache(expires_at)
            """))
            conn.commit()
        logger.info("SERP cache table ready")

    def _make_key(self, query: str, location: str = None) -> str:
        """Create cache key from query and location."""
        key_str = f"{query.lower().strip()}:{(location or '').lower().strip()}"
        return hashlib.sha256(key_str.encode()).hexdigest()[:64]

    def get(self, query: str, location: str = None) -> Optional[dict]:
        """Get cached result if available and not expired."""
        cache_key = self._make_key(query, location)

        engine = create_engine(self.db_url)
        with Session(engine) as session:
            result = session.execute(
                text("""
                    SELECT results FROM serp_cache
                    WHERE cache_key = :key AND expires_at > NOW()
                """),
                {"key": cache_key}
            ).fetchone()

            if result:
                logger.debug(f"Cache HIT for query: {query[:50]}...")
                return result[0]

        logger.debug(f"Cache MISS for query: {query[:50]}...")
        return None

    def set(self, query: str, results: dict, location: str = None):
        """Store result in cache."""
        cache_key = self._make_key(query, location)
        expires_at = datetime.now() + timedelta(hours=self.ttl_hours)

        engine = create_engine(self.db_url)
        with Session(engine) as session:
            session.execute(
                text("""
                    INSERT INTO serp_cache (cache_key, query, location, results, expires_at)
                    VALUES (:key, :query, :location, :results, :expires_at)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        results = :results,
                        expires_at = :expires_at,
                        created_at = NOW()
                """),
                {
                    "key": cache_key,
                    "query": query,
                    "location": location,
                    "results": json.dumps(results),
                    "expires_at": expires_at,
                }
            )
            session.commit()
        logger.debug(f"Cached result for query: {query[:50]}...")

    def cleanup_expired(self):
        """Remove expired entries."""
        engine = create_engine(self.db_url)
        with Session(engine) as session:
            result = session.execute(
                text("DELETE FROM serp_cache WHERE expires_at < NOW()")
            )
            session.commit()
            logger.info(f"Cleaned up {result.rowcount} expired cache entries")


class GoogleSession:
    """
    A single persistent Google browser session.

    This represents one "user" who:
    - Has accepted Google consent
    - Has browsing history
    - Searches occasionally (not constantly)
    - Behaves like a human
    """

    def __init__(
        self,
        session_id: int,
        proxy: str = None,
        profile_dir: str = None,
        behavior_config: HumanBehaviorConfig = None,
    ):
        self.session_id = session_id
        self.proxy = proxy
        self.profile_dir = profile_dir or f"{SESSION_PROFILE_DIR}/session_{session_id}"
        self.behavior = behavior_config or HumanBehaviorConfig()
        self.stats = SessionStats(session_id=session_id)

        self._launcher = None  # Camoufox launcher
        self._browser = None   # Playwright browser
        self._page = None      # Active page
        self._context = None   # Browser context
        self._lock = Lock()

        # Ensure profile directory exists
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self._load_stats()

    def _load_stats(self):
        """Load session stats from disk."""
        stats_file = Path(self.profile_dir) / "stats.json"
        if stats_file.exists():
            try:
                with open(stats_file) as f:
                    data = json.load(f)
                self.stats.consent_accepted = data.get("consent_accepted", False)
                self.stats.searches_total = data.get("searches_total", 0)
                self.stats.successes = data.get("successes", 0)
                self.stats.failures = data.get("failures", 0)
                logger.debug(f"Loaded stats for session {self.session_id}")
            except Exception as e:
                logger.warning(f"Could not load stats for session {self.session_id}: {e}")

    def _save_stats(self):
        """Save session stats to disk."""
        stats_file = Path(self.profile_dir) / "stats.json"
        try:
            with open(stats_file, "w") as f:
                json.dump(self.stats.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save stats for session {self.session_id}: {e}")

    def _get_browser(self):
        """Get or create browser instance."""
        if self._browser is None:
            self._create_browser()
        return self._browser

    def _create_browser(self):
        """Create a new Camoufox browser with persistent profile."""
        try:
            import asyncio

            # Patch asyncio.get_running_loop BEFORE importing/using Camoufox
            # This prevents "Playwright Sync API inside asyncio loop" errors
            # when nest_asyncio is applied globally
            original_get_running_loop = asyncio.get_running_loop

            def patched_get_running_loop():
                raise RuntimeError("no running event loop")

            asyncio.get_running_loop = patched_get_running_loop

            try:
                from camoufox.sync_api import Camoufox

                # Build Camoufox launcher options
                launcher_options = {
                    "headless": False,  # Headed for better evasion
                    "humanize": True,
                    "i_know_what_im_doing": True,
                }

                # Create launcher and start browser (must be within patched asyncio)
                self._launcher = Camoufox(**launcher_options)
                self._browser = self._launcher.start()  # Returns Playwright browser

                # Build context options
                context_options = {}

                if self.proxy:
                    # Parse proxy URL and build Playwright proxy config
                    # Playwright expects {"server": "http://host:port", "username": "...", "password": "..."}
                    from urllib.parse import urlparse
                    parsed = urlparse(self.proxy)
                    proxy_config = {
                        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                    }
                    if parsed.username:
                        proxy_config["username"] = parsed.username
                    if parsed.password:
                        proxy_config["password"] = parsed.password
                    context_options["proxy"] = proxy_config
                    logger.debug(f"Session {self.session_id}: Proxy config: server={proxy_config['server']}")

                # Load storage state if it exists (for persistent sessions)
                storage_file = Path(self.profile_dir) / "storage_state.json"
                if storage_file.exists():
                    try:
                        context_options["storage_state"] = str(storage_file)
                        logger.debug(f"Session {self.session_id}: Loading storage state from {storage_file}")
                    except Exception as e:
                        logger.warning(f"Session {self.session_id}: Could not load storage state: {e}")

                # Create context and page
                self._context = self._browser.new_context(**context_options)
                self._page = self._context.new_page()
                self._page.set_default_timeout(30000)

            finally:
                # Restore original asyncio function
                asyncio.get_running_loop = original_get_running_loop

            self.stats.current_proxy = self.proxy
            logger.info(f"Session {self.session_id}: Browser created with proxy {self.proxy}")

            # Warm up the browser with a neutral search to avoid detection
            self._warm_up_browser()

        except Exception as e:
            logger.error(f"Session {self.session_id}: Failed to create browser: {e}")
            self.stats.is_healthy = False
            raise

    def _warm_up_browser(self):
        """Warm up browser with a neutral search before actual SERP queries."""
        try:
            import time
            logger.info(f"Session {self.session_id}: Warming up browser...")

            # Do a neutral warm-up search
            self._page.goto("https://www.google.com/search?q=whats+happening+today",
                           wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Handle consent popup if present
            try:
                consent_btn = self._page.query_selector('button[id="L2AGLb"]')
                if consent_btn and consent_btn.is_visible():
                    consent_btn.click()
                    logger.debug(f"Session {self.session_id}: Clicked consent button")
                    time.sleep(1)
            except Exception:
                pass

            # Check for CAPTCHA
            url = self._page.url
            if "/sorry/" in url:
                logger.warning(f"Session {self.session_id}: Got CAPTCHA during warm-up")
                self.stats.is_healthy = False
            else:
                logger.info(f"Session {self.session_id}: Browser warm-up successful")
                time.sleep(2)

        except Exception as e:
            logger.warning(f"Session {self.session_id}: Warm-up failed: {e}")

    def _close_browser(self):
        """Close browser and save state."""
        if self._context:
            try:
                # Save storage state before closing
                storage_file = Path(self.profile_dir) / "storage_state.json"
                self._context.storage_state(path=str(storage_file))
            except Exception as e:
                logger.warning(f"Session {self.session_id}: Could not save storage state: {e}")

            try:
                self._context.close()
            except:
                pass

        if self._browser:
            try:
                self._browser.close()
            except:
                pass

        if self._launcher:
            try:
                self._launcher.stop()
            except:
                pass

        self._launcher = None
        self._browser = None
        self._page = None
        self._context = None

    def _human_delay(self, range_tuple: tuple):
        """Sleep for a random duration within range."""
        delay = random.uniform(range_tuple[0], range_tuple[1])
        time.sleep(delay)

    def _type_humanly(self, element, text: str):
        """Type text with human-like timing and occasional typos."""
        for i, char in enumerate(text):
            # Occasional typo
            if random.random() < self.behavior.typo_chance and i < len(text) - 1:
                # Type wrong character
                wrong_char = random.choice("abcdefghijklmnopqrstuvwxyz")
                element.type(wrong_char, delay=random.randint(50, 150))
                self._human_delay(self.behavior.typo_correction_delay)
                # Backspace and correct
                element.press("Backspace")
                time.sleep(random.uniform(0.1, 0.3))

            # Type the correct character
            delay_ms = int(1000 / random.uniform(*self.behavior.typing_speed_cps))
            element.type(char, delay=delay_ms)

    def _scroll_naturally(self):
        """Scroll the page like a human would."""
        if random.random() > self.behavior.scroll_probability:
            return

        num_scrolls = random.randint(*self.behavior.num_scrolls_range)
        for _ in range(num_scrolls):
            scroll_amount = random.randint(*self.behavior.scroll_amount_range)
            self._page.mouse.wheel(0, scroll_amount)
            self._human_delay(self.behavior.scroll_pause_range)

    def browse_random_sites(self):
        """
        Browse random safe sites to look like a real user.

        Called between Google searches to make browsing patterns look natural.
        Real users don't just do search after search - they browse Reddit,
        check the news, watch YouTube, etc.
        """
        if not self.behavior.browse_between_searches:
            return

        if random.random() > self.behavior.browse_probability:
            logger.debug(f"Session {self.session_id}: Skipping interstitial browse (random)")
            return

        try:
            # Pick random number of sites to visit
            num_sites = random.randint(*self.behavior.browse_actions_range)
            sites_to_visit = random.sample(
                self.behavior.browse_sites,
                min(num_sites, len(self.behavior.browse_sites))
            )

            for site in sites_to_visit:
                try:
                    logger.debug(f"Session {self.session_id}: Browsing {site}")

                    # Navigate to site
                    self._page.goto(site, wait_until="domcontentloaded", timeout=30000)

                    # Simulate reading/browsing
                    browse_time = random.uniform(*self.behavior.browse_time_range)

                    # Do some scrolling while "reading"
                    scroll_intervals = int(browse_time / 5)  # Scroll every ~5 seconds
                    for _ in range(max(1, scroll_intervals)):
                        self._human_delay((3, 7))
                        self._scroll_naturally()

                    # Maybe click something (but not links that leave the page)
                    if random.random() < 0.3:
                        try:
                            # Try to click a non-navigation element
                            clickable = self._page.query_selector_all("button, [role='button'], .btn")
                            if clickable:
                                element = random.choice(clickable[:5])
                                if element.is_visible():
                                    element.click()
                                    self._human_delay((1, 3))
                        except:
                            pass

                    logger.debug(f"Session {self.session_id}: Spent {browse_time:.0f}s on {site}")

                except Exception as e:
                    logger.debug(f"Session {self.session_id}: Browse failed for {site}: {e}")
                    # Continue with next site, don't fail the whole browse session

            logger.info(f"Session {self.session_id}: Interstitial browsing complete ({len(sites_to_visit)} sites)")

        except Exception as e:
            logger.warning(f"Session {self.session_id}: Interstitial browsing error: {e}")
            # Don't fail the session, just continue

    def accept_consent(self) -> bool:
        """Accept Google consent dialog if present."""
        if self.stats.consent_accepted:
            return True

        consent_selectors = [
            "button#L2AGLb",  # "I agree" button (old)
            "[aria-label='Accept all']",
            "button:has-text('Accept all')",
            "button:has-text('I agree')",
            "[data-ved] button:has-text('Accept')",
        ]

        for selector in consent_selectors:
            try:
                btn = self._page.query_selector(selector)
                if btn and btn.is_visible():
                    self._human_delay((0.5, 1.5))
                    btn.click()
                    self._human_delay((1, 2))
                    self.stats.consent_accepted = True
                    self._save_stats()
                    logger.info(f"Session {self.session_id}: Consent accepted")
                    return True
            except Exception:
                pass

        return False

    def warm_session(self):
        """
        Warm the session by browsing like a real user.

        This makes the session look legitimate to Google.
        """
        with self._lock:
            try:
                browser = self._get_browser()

                # Pick random warming actions
                warm_sites = random.sample(
                    self.behavior.warm_sites,
                    min(self.behavior.warm_actions_per_cycle, len(self.behavior.warm_sites))
                )

                for site in warm_sites:
                    try:
                        logger.debug(f"Session {self.session_id}: Warming with {site}")
                        self._page.goto(site, wait_until="domcontentloaded", timeout=30000)
                        self._human_delay((2, 5))
                        self._scroll_naturally()
                        self._human_delay((3, 8))
                    except Exception as e:
                        logger.warning(f"Session {self.session_id}: Warm action failed for {site}: {e}")

                self.stats.last_warm_at = datetime.now()
                self._save_stats()
                logger.info(f"Session {self.session_id}: Warming complete")

            except Exception as e:
                logger.error(f"Session {self.session_id}: Warming failed: {e}")
                self.stats.is_healthy = False

    def search(self, query: str, location: str = None) -> Optional[dict]:
        """
        Perform a Google search with human-like behavior.

        Args:
            query: Search query
            location: Geographic location for local results

        Returns:
            Parsed SERP results or None if failed
        """
        with self._lock:
            if not self.stats.can_search:
                logger.warning(f"Session {self.session_id}: Cannot search (limit reached or cooling down)")
                return None

            try:
                browser = self._get_browser()

                # Browse random sites first to look like a real user
                # Real users don't just Google search back-to-back
                self.browse_random_sites()

                # Navigate to Google
                google_url = "https://www.google.com"
                if location:
                    # Add location parameter
                    google_url += f"?near={location.replace(' ', '+')}"

                self._page.goto(google_url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(self.behavior.pre_search_delay)

                # Accept consent if needed
                self.accept_consent()

                # Find search box
                search_box = None
                search_selectors = [
                    "textarea[name='q']",
                    "input[name='q']",
                    "[aria-label='Search']",
                ]
                for selector in search_selectors:
                    try:
                        search_box = self._page.query_selector(selector)
                        if search_box and search_box.is_visible():
                            break
                    except:
                        pass

                if not search_box:
                    logger.error(f"Session {self.session_id}: Could not find search box")
                    self.stats.failures += 1
                    return None

                # Click search box
                search_box.click()
                self._human_delay((0.3, 0.8))

                # Type query humanly
                self._type_humanly(search_box, query)
                self._human_delay(self.behavior.post_type_delay)

                # Press Enter
                search_box.press("Enter")

                # Wait for results
                self._human_delay(self.behavior.result_load_wait)

                # Wait for results container
                try:
                    self._page.wait_for_selector("#search, #rso", timeout=10000)
                except:
                    # Check for consent page or CAPTCHA
                    if self.accept_consent():
                        self._page.wait_for_selector("#search, #rso", timeout=10000)

                # Scroll naturally through results
                self._scroll_naturally()

                # Get page HTML for parsing
                html = self._page.content()

                # Parse results using existing parser
                from seo_intelligence.scrapers.serp_parser import get_serp_parser
                parser = get_serp_parser()
                snapshot = parser.parse(html, query, location)

                # Convert SerpSnapshot to dict and normalize keys for compatibility
                results = snapshot.to_dict()
                # Map 'results' to 'organic_results' for compatibility with rest of system
                results["organic_results"] = results.pop("results", [])

                # Validate results
                organic_count = len(results.get("organic_results", []))
                local_count = len(results.get("local_pack", []))
                if results and (organic_count > 0 or local_count > 0):
                    self.stats.successes += 1
                    self.stats.searches_today += 1
                    self.stats.searches_total += 1
                    self.stats.last_search_at = datetime.now()
                    logger.info(f"Session {self.session_id}: Search SUCCESS for '{query[:30]}...' - {organic_count} organic, {local_count} local results")
                else:
                    self.stats.failures += 1
                    logger.warning(f"Session {self.session_id}: Search returned no results for '{query[:30]}...'")

                # Maybe click a result (looks more human)
                if random.random() < self.behavior.click_result_probability:
                    self._click_random_result()

                self._save_stats()
                return results

            except Exception as e:
                logger.error(f"Session {self.session_id}: Search failed: {e}")
                self.stats.failures += 1
                self.stats.is_healthy = False
                self._save_stats()
                return None

    def _click_random_result(self):
        """Click a random organic result to look more human."""
        try:
            results = self._page.query_selector_all("#search a[href^='http']")
            if results:
                result = random.choice(results[:5])  # Pick from top 5
                result.click()
                self._human_delay(self.behavior.time_on_result_page)
                self._page.go_back()
                self._human_delay(self.behavior.back_to_serp_delay)
        except Exception as e:
            logger.debug(f"Session {self.session_id}: Could not click result: {e}")

    def close(self):
        """Close this session."""
        self._save_stats()
        self._close_browser()
        logger.info(f"Session {self.session_id}: Closed")


class SerpSessionPool:
    """
    Pool of persistent Google sessions.

    Manages multiple sessions, distributes queries, handles warming.
    """

    def __init__(
        self,
        num_sessions: int = DEFAULT_NUM_SESSIONS,
        proxy_list: List[str] = None,
    ):
        self.num_sessions = num_sessions
        self.proxy_list = proxy_list or []
        self.sessions: List[GoogleSession] = []
        self.cache = SerpResultCache()

        self._warmer_thread: Optional[Thread] = None
        self._warmer_running = False
        self._query_queue = queue.Queue()
        self._lock = Lock()

        # Daily reset tracking
        self._last_daily_reset = datetime.now().date()

    def initialize(self):
        """Initialize all sessions.

        IMPORTANT: This creates browsers synchronously in the calling thread.
        All subsequent browser operations should happen in the same thread
        (the scheduler thread) to avoid Playwright threading issues.
        """
        logger.info(f"Initializing SERP session pool with {self.num_sessions} sessions")

        for i in range(self.num_sessions):
            proxy = self.proxy_list[i % len(self.proxy_list)] if self.proxy_list else None
            session = GoogleSession(
                session_id=i,
                proxy=proxy,
            )
            self.sessions.append(session)

            # Create browser synchronously now to avoid threading issues later
            # All browser ops must happen in the same thread (scheduler thread)
            try:
                session._create_browser()
                logger.info(f"Session {i}: Browser created with proxy {proxy}")
            except Exception as e:
                logger.error(f"Session {i}: Failed to create browser: {e}")
                session.stats.is_healthy = False

        # Do initial warm for healthy sessions
        for session in self.sessions:
            if session.stats.is_healthy and session._browser:
                try:
                    session.warm_session()
                except Exception as e:
                    logger.error(f"Session {session.session_id}: Initial warming failed: {e}")

        # Start background warmer (for maintenance only, not browser creation)
        self._start_warmer()

        logger.info(f"SERP session pool initialized with {len(self.sessions)} sessions")

    def _start_warmer(self):
        """Start background session warmer thread."""
        self._warmer_running = True
        self._warmer_thread = Thread(target=self._warmer_loop, daemon=True)
        self._warmer_thread.start()
        logger.info("Session warmer started")

    def _warmer_loop(self):
        """Background loop for maintenance only.

        NOTE: We don't do browser operations here because Playwright
        requires all browser ops to happen in the same thread.
        Session warming happens in the scheduler thread instead.
        """
        while self._warmer_running:
            try:
                # Check for daily reset
                today = datetime.now().date()
                if today > self._last_daily_reset:
                    self._daily_reset()
                    self._last_daily_reset = today

                # Just log session health - no browser operations
                healthy = sum(1 for s in self.sessions if s.stats.is_healthy)
                needs_warm = sum(1 for s in self.sessions if s.stats.needs_warming)
                logger.debug(f"Session health: {healthy}/{len(self.sessions)} healthy, {needs_warm} need warming")

                # Sleep before next check
                time.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Warmer loop error: {e}")
                time.sleep(60)

    def _daily_reset(self):
        """Reset daily counters for all sessions."""
        logger.info("Performing daily reset for all sessions")
        for session in self.sessions:
            session.stats.reset_daily()

        # Also cleanup cache
        self.cache.cleanup_expired()

    def get_available_session(self, geo_hint: str = None) -> Optional[GoogleSession]:
        """
        Get an available session for searching.

        Args:
            geo_hint: Optional geographic hint to match proxy location

        Returns:
            An available session or None if all are busy/exhausted
        """
        with self._lock:
            # Sort sessions by availability and success rate
            available = [s for s in self.sessions if s.stats.can_search]

            if not available:
                logger.warning("No available sessions for searching")
                return None

            # Prefer sessions with higher success rates
            available.sort(key=lambda s: s.stats.success_rate, reverse=True)

            # TODO: Match geo_hint to proxy location if specified

            return available[0]

    def search(self, query: str, location: str = None, use_cache: bool = True) -> Optional[dict]:
        """
        Search Google using the session pool.

        Args:
            query: Search query
            location: Geographic location for local results
            use_cache: Whether to check cache first

        Returns:
            SERP results or None if failed
        """
        # Check cache first
        if use_cache:
            cached = self.cache.get(query, location)
            if cached:
                logger.info(f"Returning cached result for '{query[:30]}...'")
                return cached

        # Get available session
        session = self.get_available_session(geo_hint=location)
        if not session:
            logger.error(f"No session available for query: {query[:30]}...")
            return None

        # Perform search
        results = session.search(query, location)

        # Cache successful results
        if results and use_cache:
            self.cache.set(query, results, location)

        return results

    def get_pool_stats(self) -> dict:
        """Get statistics for the entire pool."""
        return {
            "num_sessions": len(self.sessions),
            "healthy_sessions": sum(1 for s in self.sessions if s.stats.is_healthy),
            "available_sessions": sum(1 for s in self.sessions if s.stats.can_search),
            "total_searches_today": sum(s.stats.searches_today for s in self.sessions),
            "total_searches_all_time": sum(s.stats.searches_total for s in self.sessions),
            "overall_success_rate": (
                sum(s.stats.successes for s in self.sessions) /
                max(1, sum(s.stats.successes + s.stats.failures for s in self.sessions))
            ),
            "sessions": [s.stats.to_dict() for s in self.sessions],
        }

    def shutdown(self):
        """Shutdown the pool gracefully."""
        logger.info("Shutting down SERP session pool")

        self._warmer_running = False
        if self._warmer_thread:
            self._warmer_thread.join(timeout=5)

        for session in self.sessions:
            try:
                session.close()
            except Exception as e:
                logger.error(f"Error closing session {session.session_id}: {e}")

        logger.info("SERP session pool shutdown complete")


# Singleton instance
_pool_instance: Optional[SerpSessionPool] = None
_pool_lock = Lock()


def get_serp_session_pool(
    num_sessions: int = DEFAULT_NUM_SESSIONS,
    proxy_list: List[str] = None,
    initialize: bool = True,
) -> SerpSessionPool:
    """Get or create the global SERP session pool."""
    global _pool_instance

    with _pool_lock:
        if _pool_instance is None:
            _pool_instance = SerpSessionPool(
                num_sessions=num_sessions,
                proxy_list=proxy_list,
            )
            if initialize:
                _pool_instance.initialize()

        return _pool_instance


def shutdown_serp_session_pool():
    """Shutdown the global SERP session pool."""
    global _pool_instance

    with _pool_lock:
        if _pool_instance:
            _pool_instance.shutdown()
            _pool_instance = None

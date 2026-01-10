"""
Artifact Capture Layer for SEO Scrapers

This module provides dataclasses and utilities for capturing raw artifacts
(HTML, screenshots, headers, traces) so data can be re-parsed later without
re-scraping. This is critical for:
- Debugging parser failures
- Re-running LLM extraction with different models
- Training data collection
- Handling markup changes and lazy-loading issues
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
import hashlib
import json
import gzip
import os


@dataclass
class ScrapeQualityProfile:
    """
    Configuration for scraping quality vs speed tradeoffs.

    Higher quality settings capture more data but are slower and more
    likely to trigger anti-bot measures.
    """
    # What to capture
    capture_html: bool = True
    capture_screenshot: bool = False
    capture_trace: bool = False  # HAR/performance trace
    capture_console: bool = False  # JS console errors/warnings
    capture_network: bool = False  # Blocked requests, etc.

    # Wait strategies
    wait_strategy: str = "domcontentloaded"  # domcontentloaded, networkidle, load
    extra_wait_seconds: float = 0.0  # Additional wait after load event

    # Page interaction
    scroll_page: bool = False
    scroll_steps: int = 3  # Number of scroll steps
    scroll_delay: float = 0.5  # Seconds between scroll steps
    expand_elements: bool = False  # Click to expand PAA, FAQ, accordions

    # Retry logic
    second_pass_on_low_completeness: bool = False
    completeness_threshold: float = 0.75  # Re-fetch if below this
    max_retries: int = 1

    # Viewport
    viewport_width: int = 1920
    viewport_height: int = 1080
    mobile_emulation: bool = False

    # Timeouts (milliseconds)
    navigation_timeout: int = 30000
    wait_timeout: int = 10000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'capture_html': self.capture_html,
            'capture_screenshot': self.capture_screenshot,
            'capture_trace': self.capture_trace,
            'capture_console': self.capture_console,
            'capture_network': self.capture_network,
            'wait_strategy': self.wait_strategy,
            'extra_wait_seconds': self.extra_wait_seconds,
            'scroll_page': self.scroll_page,
            'scroll_steps': self.scroll_steps,
            'scroll_delay': self.scroll_delay,
            'expand_elements': self.expand_elements,
            'second_pass_on_low_completeness': self.second_pass_on_low_completeness,
            'completeness_threshold': self.completeness_threshold,
            'max_retries': self.max_retries,
            'viewport_width': self.viewport_width,
            'viewport_height': self.viewport_height,
            'mobile_emulation': self.mobile_emulation,
            'navigation_timeout': self.navigation_timeout,
            'wait_timeout': self.wait_timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScrapeQualityProfile':
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PageArtifact:
    """
    Captures all raw data from a page fetch for later re-parsing.

    This is the foundation that allows:
    - Offline re-parsing without re-scraping
    - LLM extraction with different prompts/models
    - Debugging parser failures
    - Training data collection
    """
    # Request info
    url: str
    final_url: str  # After redirects

    # Response info
    status_code: int = 0
    response_headers: Dict[str, str] = field(default_factory=dict)

    # Content
    html_raw: str = ""  # Initial HTML before JS
    html_rendered: Optional[str] = None  # After JS execution (if different)
    text_main: Optional[str] = None  # Readability-extracted main content

    # Files (paths, not content - stored separately)
    screenshot_path: Optional[str] = None  # Full page screenshot
    screenshot_clipped_paths: Dict[str, str] = field(default_factory=dict)  # Named region screenshots
    trace_path: Optional[str] = None  # HAR/trace file

    # Errors and signals
    console_errors: List[str] = field(default_factory=list)
    console_warnings: List[str] = field(default_factory=list)
    blocked_requests: List[str] = field(default_factory=list)
    detected_captcha: bool = False
    detected_consent_overlay: bool = False
    detected_login_wall: bool = False

    # Fetch metadata
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    engine: str = "playwright"  # playwright, selenium, requests
    proxy_used: Optional[str] = None
    locale: Optional[str] = None
    geo_location: Optional[Dict[str, float]] = None  # lat, lng
    user_agent: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None  # width, height

    # Quality profile used
    quality_profile: Optional[Dict[str, Any]] = None

    # Custom metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Computed fields
    fetch_duration_ms: Optional[int] = None
    html_size_bytes: Optional[int] = None

    def __post_init__(self):
        """Compute derived fields."""
        if self.html_raw and self.html_size_bytes is None:
            self.html_size_bytes = len(self.html_raw.encode('utf-8'))

    @property
    def domain(self) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        return urlparse(self.final_url or self.url).netloc

    @property
    def url_hash(self) -> str:
        """Generate a short hash of the URL for file naming."""
        return hashlib.md5(self.url.encode()).hexdigest()[:12]

    @property
    def has_errors(self) -> bool:
        """Check if there were any errors during fetch."""
        return (
            self.status_code >= 400 or
            self.detected_captcha or
            self.detected_login_wall or
            len(self.console_errors) > 0
        )

    @property
    def completeness_score(self) -> float:
        """
        Estimate how complete the fetch was (0-1).
        Used for retry decisions.
        """
        score = 1.0

        # Penalize for errors
        if self.status_code >= 400:
            score -= 0.5
        if self.detected_captcha:
            score -= 0.3
        if self.detected_login_wall:
            score -= 0.3
        if self.detected_consent_overlay:
            score -= 0.1
        if len(self.blocked_requests) > 5:
            score -= 0.1

        # Reward for content
        if self.html_raw and len(self.html_raw) > 1000:
            score += 0.1
        if self.text_main and len(self.text_main) > 100:
            score += 0.1

        return max(0.0, min(1.0, score))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'url': self.url,
            'final_url': self.final_url,
            'status_code': self.status_code,
            'response_headers': self.response_headers,
            'html_raw': self.html_raw,
            'html_rendered': self.html_rendered,
            'text_main': self.text_main,
            'screenshot_path': self.screenshot_path,
            'screenshot_clipped_paths': self.screenshot_clipped_paths,
            'trace_path': self.trace_path,
            'console_errors': self.console_errors,
            'console_warnings': self.console_warnings,
            'blocked_requests': self.blocked_requests,
            'detected_captcha': self.detected_captcha,
            'detected_consent_overlay': self.detected_consent_overlay,
            'detected_login_wall': self.detected_login_wall,
            'timestamp': self.timestamp.isoformat(),
            'engine': self.engine,
            'proxy_used': self.proxy_used,
            'locale': self.locale,
            'geo_location': self.geo_location,
            'user_agent': self.user_agent,
            'viewport': self.viewport,
            'quality_profile': self.quality_profile,
            'metadata': self.metadata,
            'fetch_duration_ms': self.fetch_duration_ms,
            'html_size_bytes': self.html_size_bytes,
            'domain': self.domain,
            'url_hash': self.url_hash,
            'has_errors': self.has_errors,
            'completeness_score': self.completeness_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PageArtifact':
        """Create from dictionary."""
        # Convert timestamp string back to datetime
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])

        # Remove computed properties
        data.pop('domain', None)
        data.pop('url_hash', None)
        data.pop('has_errors', None)
        data.pop('completeness_score', None)

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ArtifactStorage:
    """
    Manages storage of artifacts to disk with compression and organization.

    Directory structure:
    data/artifacts/
        {domain}/
            {date}/
                {url_hash}/
                    metadata.json
                    html_raw.html.gz
                    html_rendered.html.gz (if different)
                    screenshot.png
                    trace.har.gz
    """

    def __init__(self, base_dir: str = "data/artifacts"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_artifact_dir(self, artifact: PageArtifact) -> Path:
        """Get directory for storing an artifact."""
        domain = artifact.domain.replace(':', '_').replace('/', '_')
        date_str = artifact.timestamp.strftime('%Y-%m-%d')
        artifact_dir = self.base_dir / domain / date_str / artifact.url_hash
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def save(self, artifact: PageArtifact, compress: bool = True) -> str:
        """
        Save artifact to disk.

        Returns the path to the artifact directory.
        """
        artifact_dir = self._get_artifact_dir(artifact)

        # Save metadata (always JSON, includes everything except large content)
        metadata = artifact.to_dict()
        metadata.pop('html_raw', None)
        metadata.pop('html_rendered', None)
        metadata.pop('text_main', None)

        with open(artifact_dir / 'metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2, default=str)

        # Save HTML (compressed)
        if artifact.html_raw:
            html_path = artifact_dir / ('html_raw.html.gz' if compress else 'html_raw.html')
            if compress:
                with gzip.open(html_path, 'wt', encoding='utf-8') as f:
                    f.write(artifact.html_raw)
            else:
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(artifact.html_raw)

        # Save rendered HTML if different
        if artifact.html_rendered and artifact.html_rendered != artifact.html_raw:
            rendered_path = artifact_dir / ('html_rendered.html.gz' if compress else 'html_rendered.html')
            if compress:
                with gzip.open(rendered_path, 'wt', encoding='utf-8') as f:
                    f.write(artifact.html_rendered)
            else:
                with open(rendered_path, 'w', encoding='utf-8') as f:
                    f.write(artifact.html_rendered)

        # Save main text
        if artifact.text_main:
            with open(artifact_dir / 'text_main.txt', 'w', encoding='utf-8') as f:
                f.write(artifact.text_main)

        return str(artifact_dir)

    def load(self, artifact_dir: str) -> Optional[PageArtifact]:
        """Load an artifact from disk."""
        artifact_path = Path(artifact_dir)

        if not artifact_path.exists():
            return None

        # Load metadata
        metadata_path = artifact_path / 'metadata.json'
        if not metadata_path.exists():
            return None

        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        # Load HTML
        html_raw = None
        for html_file in ['html_raw.html.gz', 'html_raw.html']:
            html_path = artifact_path / html_file
            if html_path.exists():
                if html_file.endswith('.gz'):
                    with gzip.open(html_path, 'rt', encoding='utf-8') as f:
                        html_raw = f.read()
                else:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        html_raw = f.read()
                break

        # Load rendered HTML
        html_rendered = None
        for html_file in ['html_rendered.html.gz', 'html_rendered.html']:
            html_path = artifact_path / html_file
            if html_path.exists():
                if html_file.endswith('.gz'):
                    with gzip.open(html_path, 'rt', encoding='utf-8') as f:
                        html_rendered = f.read()
                else:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        html_rendered = f.read()
                break

        # Load main text
        text_main = None
        text_path = artifact_path / 'text_main.txt'
        if text_path.exists():
            with open(text_path, 'r', encoding='utf-8') as f:
                text_main = f.read()

        # Reconstruct artifact
        metadata['html_raw'] = html_raw or ""
        metadata['html_rendered'] = html_rendered
        metadata['text_main'] = text_main

        return PageArtifact.from_dict(metadata)

    def list_artifacts(
        self,
        domain: Optional[str] = None,
        date: Optional[str] = None,
        limit: int = 100
    ) -> List[str]:
        """List artifact directories matching criteria."""
        results = []

        if domain:
            domain_dir = self.base_dir / domain.replace(':', '_').replace('/', '_')
            if not domain_dir.exists():
                return []
            search_dirs = [domain_dir]
        else:
            search_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]

        for domain_dir in search_dirs:
            if date:
                date_dirs = [domain_dir / date]
            else:
                date_dirs = sorted(
                    [d for d in domain_dir.iterdir() if d.is_dir()],
                    reverse=True
                )

            for date_dir in date_dirs:
                if not date_dir.exists():
                    continue

                for artifact_dir in date_dir.iterdir():
                    if artifact_dir.is_dir() and (artifact_dir / 'metadata.json').exists():
                        results.append(str(artifact_dir))
                        if len(results) >= limit:
                            return results

        return results

    def cleanup_old(self, days: int = 30) -> int:
        """Remove artifacts older than specified days. Returns count deleted."""
        import shutil
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime('%Y-%m-%d')
        deleted = 0

        for domain_dir in self.base_dir.iterdir():
            if not domain_dir.is_dir():
                continue

            for date_dir in domain_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                if date_dir.name < cutoff_str:
                    shutil.rmtree(date_dir)
                    deleted += 1

            # Remove empty domain dirs
            if not any(domain_dir.iterdir()):
                domain_dir.rmdir()

        return deleted


# Pre-configured quality profiles
DEFAULT_QUALITY_PROFILE = ScrapeQualityProfile(
    capture_html=True,
    capture_screenshot=False,
    wait_strategy="domcontentloaded",
    extra_wait_seconds=1.0,
    scroll_page=False,
)

HIGH_QUALITY_PROFILE = ScrapeQualityProfile(
    capture_html=True,
    capture_screenshot=True,
    capture_trace=True,
    capture_console=True,
    wait_strategy="networkidle",
    extra_wait_seconds=3.0,
    scroll_page=True,
    scroll_steps=6,
    scroll_delay=0.8,
    expand_elements=True,
    second_pass_on_low_completeness=True,
    completeness_threshold=0.7,
)

FAST_PROFILE = ScrapeQualityProfile(
    capture_html=True,
    capture_screenshot=False,
    wait_strategy="domcontentloaded",
    extra_wait_seconds=0.0,
    scroll_page=False,
    navigation_timeout=15000,
    wait_timeout=5000,
)

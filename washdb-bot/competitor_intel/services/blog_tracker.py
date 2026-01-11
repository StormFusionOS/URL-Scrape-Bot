"""
Blog Tracker for Competitor Intelligence

Discovers and tracks competitor blog content:
- Blog page detection
- Post discovery and extraction
- Publishing velocity analysis
- Topic/keyword tracking
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import text

from competitor_intel.config import BLOG_CONFIG
from db.database_manager import create_session

logger = logging.getLogger(__name__)


@dataclass
class BlogPost:
    """A discovered blog post."""
    url: str
    title: str
    published_date: Optional[datetime] = None
    author: Optional[str] = None
    excerpt: Optional[str] = None
    word_count: int = 0
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class BlogAnalysis:
    """Analysis of competitor blog activity."""
    competitor_id: int
    has_blog: bool
    blog_url: Optional[str] = None
    total_posts: int = 0
    posts_last_30_days: int = 0
    posts_last_90_days: int = 0
    avg_posts_per_month: float = 0.0
    avg_word_count: int = 0
    top_categories: List[str] = field(default_factory=list)
    last_post_date: Optional[datetime] = None
    is_active: bool = False  # Posted in last 90 days


class BlogTracker:
    """
    Discovers and tracks competitor blog content.

    Features:
    - Blog page detection from common URL patterns
    - Post extraction from blog listings
    - Publishing velocity calculation
    - Category/topic tracking
    """

    # Common blog URL patterns
    BLOG_PATTERNS = [
        '/blog',
        '/blog/',
        '/blogs',
        '/news',
        '/articles',
        '/posts',
        '/resources/blog',
        '/company/blog',
        '/about/blog',
    ]

    def __init__(self):
        self.max_posts = BLOG_CONFIG.get("max_posts_to_track", 50)
        self.track_velocity = BLOG_CONFIG.get("track_velocity", True)

        logger.info("BlogTracker initialized")

    def discover_blog(self, html: str, base_url: str) -> Optional[str]:
        """
        Discover blog URL from website HTML.

        Args:
            html: Website HTML content
            base_url: The base website URL

        Returns:
            Blog URL if found, None otherwise
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Method 1: Check navigation links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '').lower()
            text = a_tag.get_text().lower().strip()

            # Check href patterns
            for pattern in self.BLOG_PATTERNS:
                if pattern in href:
                    return self._normalize_blog_url(a_tag['href'], base_url)

            # Check link text
            if text in ['blog', 'news', 'articles', 'resources']:
                return self._normalize_blog_url(a_tag['href'], base_url)

        # Method 2: Check for RSS feed links
        rss_link = soup.find('link', attrs={'type': 'application/rss+xml'})
        if rss_link and rss_link.get('href'):
            # RSS found, likely has blog
            rss_href = rss_link['href']
            # Try to infer blog URL from RSS
            if '/feed' in rss_href:
                blog_url = rss_href.replace('/feed', '')
                return self._normalize_blog_url(blog_url, base_url)

        return None

    def _normalize_blog_url(self, url: str, base_url: str) -> str:
        """Normalize blog URL to absolute form."""
        if url.startswith('http'):
            return url
        return urljoin(base_url, url)

    def extract_posts(self, blog_html: str, blog_url: str) -> List[BlogPost]:
        """
        Extract blog posts from a blog listing page.

        Args:
            blog_html: Blog page HTML
            blog_url: The blog URL

        Returns:
            List of BlogPost objects
        """
        soup = BeautifulSoup(blog_html, 'html.parser')
        posts = []

        # Common blog post container patterns
        post_containers = self._find_post_containers(soup)

        for container in post_containers[:self.max_posts]:
            post = self._extract_post_from_container(container, blog_url)
            if post:
                posts.append(post)

        # If no structured containers, try article tags
        if not posts:
            for article in soup.find_all('article')[:self.max_posts]:
                post = self._extract_post_from_container(article, blog_url)
                if post:
                    posts.append(post)

        logger.info(f"Extracted {len(posts)} blog posts from {blog_url}")
        return posts

    def _find_post_containers(self, soup: BeautifulSoup) -> List:
        """Find blog post containers using common patterns."""
        containers = []

        # Try common class patterns
        class_patterns = [
            'post', 'blog-post', 'entry', 'article-item',
            'blog-item', 'news-item', 'blog-card', 'post-card',
        ]

        for pattern in class_patterns:
            found = soup.find_all(class_=re.compile(pattern, re.I))
            if found:
                containers.extend(found)
                break  # Use first matching pattern

        return containers

    def _extract_post_from_container(
        self, container, blog_url: str
    ) -> Optional[BlogPost]:
        """Extract post data from a container element."""
        # Find title
        title_elem = container.find(['h1', 'h2', 'h3', 'h4'])
        if not title_elem:
            return None

        title = title_elem.get_text().strip()
        if not title or len(title) < 5:
            return None

        # Find URL
        link = title_elem.find('a') or container.find('a')
        url = ""
        if link and link.get('href'):
            url = self._normalize_blog_url(link['href'], blog_url)

        # Find date
        published_date = self._extract_date(container)

        # Find author
        author = self._extract_author(container)

        # Find excerpt
        excerpt = None
        excerpt_elem = container.find(['p', 'div'], class_=re.compile(r'excerpt|summary|desc', re.I))
        if excerpt_elem:
            excerpt = excerpt_elem.get_text().strip()[:300]

        # Find categories/tags
        categories = self._extract_categories(container)

        return BlogPost(
            url=url,
            title=title,
            published_date=published_date,
            author=author,
            excerpt=excerpt,
            categories=categories,
        )

    def _extract_date(self, container) -> Optional[datetime]:
        """Extract publication date from container."""
        # Look for time element
        time_elem = container.find('time')
        if time_elem:
            datetime_attr = time_elem.get('datetime')
            if datetime_attr:
                try:
                    return datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

        # Look for date class elements
        date_elem = container.find(class_=re.compile(r'date|time|posted', re.I))
        if date_elem:
            date_text = date_elem.get_text().strip()
            parsed = self._parse_date_text(date_text)
            if parsed:
                return parsed

        return None

    def _parse_date_text(self, text: str) -> Optional[datetime]:
        """Parse common date text formats."""
        import re
        from datetime import datetime

        # Common patterns
        patterns = [
            r'(\w+ \d{1,2}, \d{4})',  # January 15, 2024
            r'(\d{1,2}/\d{1,2}/\d{4})',  # 01/15/2024
            r'(\d{4}-\d{2}-\d{2})',  # 2024-01-15
            r'(\d{1,2} \w+ \d{4})',  # 15 January 2024
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                for fmt in ['%B %d, %Y', '%m/%d/%Y', '%Y-%m-%d', '%d %B %Y']:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue

        return None

    def _extract_author(self, container) -> Optional[str]:
        """Extract author from container."""
        author_elem = container.find(class_=re.compile(r'author|by-line|byline', re.I))
        if author_elem:
            text = author_elem.get_text().strip()
            # Clean up "By Author Name" format
            text = re.sub(r'^by\s+', '', text, flags=re.I)
            return text[:100] if text else None
        return None

    def _extract_categories(self, container) -> List[str]:
        """Extract categories/tags from container."""
        categories = []

        cat_elem = container.find(class_=re.compile(r'categor|tag|topic', re.I))
        if cat_elem:
            # Multiple category links
            cat_links = cat_elem.find_all('a')
            if cat_links:
                categories = [a.get_text().strip() for a in cat_links]
            else:
                # Single category text
                text = cat_elem.get_text().strip()
                if text:
                    categories = [text]

        return categories[:5]  # Limit

    def analyze_blog(self, competitor_id: int, posts: List[BlogPost] = None) -> BlogAnalysis:
        """
        Analyze blog activity for a competitor.

        Args:
            competitor_id: The competitor ID
            posts: Optional list of posts (fetches from DB if not provided)

        Returns:
            BlogAnalysis with metrics
        """
        if posts is None:
            posts = self._fetch_posts_from_db(competitor_id)

        if not posts:
            return BlogAnalysis(
                competitor_id=competitor_id,
                has_blog=False,
            )

        now = datetime.now()
        thirty_days_ago = now - timedelta(days=30)
        ninety_days_ago = now - timedelta(days=90)

        posts_30d = [p for p in posts if p.published_date and p.published_date >= thirty_days_ago]
        posts_90d = [p for p in posts if p.published_date and p.published_date >= ninety_days_ago]

        # Calculate velocity
        dated_posts = [p for p in posts if p.published_date]
        if len(dated_posts) >= 2:
            sorted_posts = sorted(dated_posts, key=lambda p: p.published_date)
            date_range = (sorted_posts[-1].published_date - sorted_posts[0].published_date).days
            months = max(1, date_range / 30)
            avg_per_month = len(dated_posts) / months
        else:
            avg_per_month = len(posts)

        # Top categories
        cat_counts = {}
        for p in posts:
            for cat in p.categories:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        top_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Average word count
        word_counts = [p.word_count for p in posts if p.word_count > 0]
        avg_word_count = int(sum(word_counts) / len(word_counts)) if word_counts else 0

        # Last post date
        last_post = None
        if dated_posts:
            last_post = max(p.published_date for p in dated_posts)

        return BlogAnalysis(
            competitor_id=competitor_id,
            has_blog=True,
            total_posts=len(posts),
            posts_last_30_days=len(posts_30d),
            posts_last_90_days=len(posts_90d),
            avg_posts_per_month=round(avg_per_month, 2),
            avg_word_count=avg_word_count,
            top_categories=[cat for cat, _ in top_cats],
            last_post_date=last_post,
            is_active=len(posts_90d) > 0,
        )

    def _fetch_posts_from_db(self, competitor_id: int) -> List[BlogPost]:
        """Fetch blog posts from database."""
        session = create_session()
        try:
            result = session.execute(text("""
                SELECT url, title, published_date, author,
                       excerpt, word_count, categories
                FROM competitor_blog_posts
                WHERE competitor_id = :competitor_id
                ORDER BY published_date DESC
            """), {"competitor_id": competitor_id}).fetchall()

            return [
                BlogPost(
                    url=r[0],
                    title=r[1],
                    published_date=r[2],
                    author=r[3],
                    excerpt=r[4],
                    word_count=r[5] or 0,
                    categories=r[6].split(',') if r[6] else [],
                )
                for r in result
            ]
        finally:
            session.close()

    def save_posts(self, competitor_id: int, posts: List[BlogPost], blog_url: str = None):
        """Save blog posts to database."""
        session = create_session()
        try:
            for post in posts:
                # Check if exists by URL
                existing = session.execute(text("""
                    SELECT id FROM competitor_blog_posts
                    WHERE competitor_id = :competitor_id AND url = :url
                """), {
                    "competitor_id": competitor_id,
                    "url": post.url,
                }).fetchone()

                if existing:
                    # Update
                    session.execute(text("""
                        UPDATE competitor_blog_posts
                        SET title = :title,
                            published_date = :published_date,
                            author = :author,
                            excerpt = :excerpt,
                            word_count = :word_count,
                            categories = :categories,
                            last_checked_at = NOW()
                        WHERE id = :id
                    """), {
                        "id": existing[0],
                        "title": post.title,
                        "published_date": post.published_date,
                        "author": post.author,
                        "excerpt": post.excerpt,
                        "word_count": post.word_count,
                        "categories": ','.join(post.categories),
                    })
                else:
                    # Insert
                    session.execute(text("""
                        INSERT INTO competitor_blog_posts (
                            competitor_id, url, title, published_date,
                            author, excerpt, word_count, categories
                        ) VALUES (
                            :competitor_id, :url, :title, :published_date,
                            :author, :excerpt, :word_count, :categories
                        )
                    """), {
                        "competitor_id": competitor_id,
                        "url": post.url,
                        "title": post.title,
                        "published_date": post.published_date,
                        "author": post.author,
                        "excerpt": post.excerpt,
                        "word_count": post.word_count,
                        "categories": ','.join(post.categories),
                    })

            session.commit()
            logger.info(f"Saved {len(posts)} blog posts for competitor {competitor_id}")
        except Exception as e:
            logger.error(f"Failed to save blog posts: {e}")
            session.rollback()
        finally:
            session.close()


def discover_blog_posts(html: str, base_url: str) -> Tuple[Optional[str], List[BlogPost]]:
    """
    Convenience function to discover blog and extract posts.

    Args:
        html: Website HTML content
        base_url: The base website URL

    Returns:
        Tuple of (blog_url, list of posts)
    """
    tracker = BlogTracker()
    blog_url = tracker.discover_blog(html, base_url)
    return blog_url, []  # Posts would require fetching blog page

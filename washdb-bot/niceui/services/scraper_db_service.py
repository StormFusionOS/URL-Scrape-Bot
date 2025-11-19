"""
Scraper Database Service
Provides data access functions for the scraped data viewer dashboard
"""

import psycopg2
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'database': 'scraper',
    'user': 'scraper_user',
    'password': 'ScraperPass123',
    'port': 5432
}


def get_db_connection():
    """Get a connection to the scraper database"""
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"Failed to connect to scraper database: {e}")
        raise


def get_overview_stats() -> Dict[str, Any]:
    """
    Get high-level summary statistics

    Returns:
        dict: Overview statistics including counts and recent activity
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        stats = {}

        # Total competitors
        cursor.execute("SELECT COUNT(*) FROM competitors")
        stats['total_competitors'] = cursor.fetchone()[0]

        # Total URLs
        cursor.execute("SELECT COUNT(*) FROM competitor_urls")
        stats['total_urls'] = cursor.fetchone()[0]

        # URL status breakdown
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM competitor_urls
            GROUP BY status
            ORDER BY count DESC
        """)
        stats['url_status'] = {row[0]: row[1] for row in cursor.fetchall()}

        # Crawl job stats
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM crawl_jobs_partitioned
            GROUP BY status
        """)
        stats['job_status'] = {row[0]: row[1] for row in cursor.fetchall()}

        # Total backlinks
        cursor.execute("SELECT COUNT(*) FROM backlinks_partitioned")
        stats['total_backlinks'] = cursor.fetchone()[0]

        # Most recent crawl
        cursor.execute("""
            SELECT MAX(last_crawled)
            FROM competitor_urls
            WHERE last_crawled IS NOT NULL
        """)
        stats['last_crawl_time'] = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return stats

    except Exception as e:
        logger.error(f"Failed to get overview stats: {e}")
        return {}


def get_competitors_list(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get list of all competitors with metadata

    Args:
        limit: Maximum number of records to return
        offset: Offset for pagination

    Returns:
        list: Competitor records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.competitor_id,
                c.competitor_domain,
                c.competitor_name,
                c.category,
                c.priority,
                c.robots_txt,
                c.sitemap_data::text,
                c.feed_data::text,
                COUNT(DISTINCT cu.competitor_url_id) as url_count,
                MAX(cu.last_crawled) as last_crawl
            FROM competitors c
            LEFT JOIN competitor_urls cu ON c.competitor_domain = cu.domain
            GROUP BY c.competitor_id
            ORDER BY c.competitor_id DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

        columns = [desc[0] for desc in cursor.description]
        competitors = []

        for row in cursor.fetchall():
            comp = dict(zip(columns, row))
            competitors.append(comp)

        cursor.close()
        conn.close()

        return competitors

    except Exception as e:
        logger.error(f"Failed to get competitors list: {e}")
        return []


def get_url_queue_status(status_filter: Optional[str] = None,
                         node_type_filter: Optional[str] = None,
                         limit: int = 100,
                         offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get competitor URLs with optional filters

    Args:
        status_filter: Filter by status (pending/crawling/completed/failed)
        node_type_filter: Filter by node type (local/national)
        limit: Maximum number of records
        offset: Offset for pagination

    Returns:
        list: URL records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                competitor_url_id,
                url,
                domain,
                node_type,
                status,
                priority,
                last_crawled,
                crawl_count,
                consecutive_failures,
                last_error
            FROM competitor_urls
            WHERE 1=1
        """
        params = []

        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)

        if node_type_filter:
            query += " AND node_type = %s"
            params.append(node_type_filter)

        query += " ORDER BY priority DESC, added_date DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cursor.execute(query, params)

        columns = [desc[0] for desc in cursor.description]
        urls = []

        for row in cursor.fetchall():
            url_data = dict(zip(columns, row))
            urls.append(url_data)

        cursor.close()
        conn.close()

        return urls

    except Exception as e:
        logger.error(f"Failed to get URL queue: {e}")
        return []


def get_crawl_jobs_summary(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent crawl jobs

    Args:
        limit: Maximum number of jobs to return

    Returns:
        list: Crawl job records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                job_id,
                url,
                job_type,
                priority,
                status,
                claimed_by,
                started_at,
                completed_at,
                attempts,
                max_attempts,
                last_error,
                created_at
            FROM crawl_jobs_partitioned
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))

        columns = [desc[0] for desc in cursor.description]
        jobs = []

        for row in cursor.fetchall():
            job = dict(zip(columns, row))
            jobs.append(job)

        cursor.close()
        conn.close()

        return jobs

    except Exception as e:
        logger.error(f"Failed to get crawl jobs: {e}")
        return []


def get_recent_changes(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent content changes detected

    Args:
        limit: Maximum number of changes to return

    Returns:
        list: Change records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                change_history_id,
                url,
                previous_hash,
                new_hash,
                similarity_score,
                has_changed,
                change_type,
                detected_at,
                change_summary,
                segment_change_ratio
            FROM change_history
            WHERE has_changed = true
            ORDER BY detected_at DESC
            LIMIT %s
        """, (limit,))

        columns = [desc[0] for desc in cursor.description]
        changes = []

        for row in cursor.fetchall():
            change = dict(zip(columns, row))
            changes.append(change)

        cursor.close()
        conn.close()

        return changes

    except Exception as e:
        logger.error(f"Failed to get recent changes: {e}")
        return []


def get_backlinks_summary(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get backlink data

    Args:
        limit: Maximum number of backlinks
        offset: Offset for pagination

    Returns:
        list: Backlink records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                backlink_id,
                source_url,
                source_domain,
                target_url,
                target_domain,
                anchor_text,
                link_region,
                rel_attr,
                first_seen,
                last_checked,
                alive
            FROM backlinks_partitioned
            ORDER BY first_seen DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

        columns = [desc[0] for desc in cursor.description]
        backlinks = []

        for row in cursor.fetchall():
            backlink = dict(zip(columns, row))
            backlinks.append(backlink)

        cursor.close()
        conn.close()

        return backlinks

    except Exception as e:
        logger.error(f"Failed to get backlinks: {e}")
        return []


def get_backlink_stats() -> Dict[str, Any]:
    """
    Get backlink statistics

    Returns:
        dict: Backlink stats including total, unique domains, dofollow ratio
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        stats = {}

        # Total backlinks
        cursor.execute("SELECT COUNT(*) FROM backlinks_partitioned")
        stats['total_backlinks'] = cursor.fetchone()[0]

        # Unique referring domains
        cursor.execute("SELECT COUNT(DISTINCT source_domain) FROM backlinks_partitioned")
        stats['unique_domains'] = cursor.fetchone()[0]

        # Dofollow vs nofollow
        cursor.execute("""
            SELECT rel_attr, COUNT(*) as count
            FROM backlinks_partitioned
            GROUP BY rel_attr
        """)
        stats['rel_breakdown'] = {row[0] or 'dofollow': row[1] for row in cursor.fetchall()}

        # Alive vs dead links
        cursor.execute("""
            SELECT alive, COUNT(*) as count
            FROM backlinks_partitioned
            GROUP BY alive
        """)
        alive_data = {row[0]: row[1] for row in cursor.fetchall()}
        stats['alive_count'] = alive_data.get(True, 0)
        stats['dead_count'] = alive_data.get(False, 0)

        cursor.close()
        conn.close()

        return stats

    except Exception as e:
        logger.error(f"Failed to get backlink stats: {e}")
        return {}


def check_seo_analytics_data() -> Dict[str, bool]:
    """
    Check if SEO analytics tables have data

    Returns:
        dict: Boolean flags for each analytics table
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        availability = {}

        # Check key analytics tables
        tables_to_check = [
            'seo_analytics.onpage_seo_metrics',
            'seo_analytics.technical_seo_metrics',
            'seo_analytics.content_metrics',
            'seo_analytics.core_web_vitals',
            'seo_analytics.keyword_rankings',
            'seo_analytics.backlink_intelligence'
        ]

        for table in tables_to_check:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            availability[table.split('.')[-1]] = count > 0

        cursor.close()
        conn.close()

        return availability

    except Exception as e:
        logger.error(f"Failed to check analytics data: {e}")
        return {}


def reset_crawling_urls_to_pending(limit: int = 100) -> Dict[str, Any]:
    """
    Reset URLs from 'crawling' status to 'pending' status

    Args:
        limit: Maximum number of URLs to reset

    Returns:
        dict: Result with count of URLs reset
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Reset crawling URLs to pending
        query = """
            UPDATE competitor_urls
            SET status = 'pending'
            WHERE competitor_url_id IN (
                SELECT competitor_url_id
                FROM competitor_urls
                WHERE status = 'crawling'
                ORDER BY competitor_url_id DESC
                LIMIT %s
            )
            RETURNING competitor_url_id
        """

        cursor.execute(query, (limit,))
        reset_ids = cursor.fetchall()
        count = len(reset_ids)

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Reset {count} URLs from 'crawling' to 'pending'")
        return {
            'success': True,
            'count': count,
            'message': f'Successfully reset {count} URLs to pending status'
        }

    except Exception as e:
        logger.error(f"Failed to reset URLs: {e}")
        return {
            'success': False,
            'count': 0,
            'message': f'Error: {str(e)}'
        }

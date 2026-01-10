"""
Batch Database Insert Helpers

Provides efficient bulk insert/upsert operations for high-volume data.
Uses psycopg2.extras.execute_values for optimal PostgreSQL performance.

Usage:
    from db.batch_helpers import BatchInserter

    inserter = BatchInserter()

    # Insert many rows efficiently
    inserter.batch_insert(
        table='serp_results',
        columns=['keyword_id', 'position', 'url', 'title'],
        rows=[(1, 1, 'https://...', 'Title 1'), (1, 2, 'https://...', 'Title 2')],
        batch_size=1000
    )

    # Upsert with conflict handling
    inserter.batch_upsert(
        table='discovery_citations',
        columns=['company_id', 'source_domain', 'url'],
        rows=[(1, 'yelp.com', 'https://...')],
        conflict_columns=['company_id', 'source_domain'],
        update_columns=['url', 'updated_at']
    )
"""

import os
from typing import List, Tuple, Optional, Any, Dict
from datetime import datetime
from contextlib import contextmanager

import psycopg2
from psycopg2 import extras
from dotenv import load_dotenv

from runner.logging_setup import get_logger

load_dotenv()
logger = get_logger("batch_helpers")


class BatchInserter:
    """Efficient batch insert operations using psycopg2"""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize batch inserter.

        Args:
            database_url: PostgreSQL connection string. Defaults to DATABASE_URL env var.
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")

        # Convert SQLAlchemy URL format to psycopg2 format if needed
        if self.database_url.startswith("postgresql+psycopg2://"):
            self.database_url = self.database_url.replace("postgresql+psycopg2://", "postgresql://")

    @contextmanager
    def get_connection(self):
        """Get a psycopg2 connection with autocommit disabled."""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
        finally:
            conn.close()

    def batch_insert(
        self,
        table: str,
        columns: List[str],
        rows: List[Tuple],
        batch_size: int = 1000,
        returning: Optional[str] = None
    ) -> int:
        """
        Insert rows in batches using execute_values.

        Args:
            table: Target table name
            columns: List of column names
            rows: List of tuples with values for each row
            batch_size: Number of rows per batch
            returning: Optional column to return (e.g., 'id')

        Returns:
            Number of rows inserted
        """
        if not rows:
            return 0

        col_str = ", ".join(columns)
        sql = f"INSERT INTO {table} ({col_str}) VALUES %s"

        if returning:
            sql += f" RETURNING {returning}"

        total_inserted = 0
        returned_values = []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]
                    try:
                        if returning:
                            result = extras.execute_values(
                                cur, sql, batch,
                                template=None,
                                page_size=batch_size,
                                fetch=True
                            )
                            returned_values.extend(result)
                        else:
                            extras.execute_values(
                                cur, sql, batch,
                                template=None,
                                page_size=batch_size
                            )
                        total_inserted += len(batch)
                        conn.commit()

                        if (i + batch_size) % 10000 == 0:
                            logger.info(f"Inserted {total_inserted}/{len(rows)} rows into {table}")

                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Batch insert failed at row {i}: {e}")
                        raise

        logger.info(f"Batch insert complete: {total_inserted} rows into {table}")
        return total_inserted

    def batch_upsert(
        self,
        table: str,
        columns: List[str],
        rows: List[Tuple],
        conflict_columns: List[str],
        update_columns: Optional[List[str]] = None,
        batch_size: int = 1000
    ) -> int:
        """
        Upsert rows in batches (INSERT ... ON CONFLICT DO UPDATE).

        Args:
            table: Target table name
            columns: List of column names
            rows: List of tuples with values for each row
            conflict_columns: Columns that form the unique constraint
            update_columns: Columns to update on conflict (None = all non-conflict columns)
            batch_size: Number of rows per batch

        Returns:
            Number of rows affected
        """
        if not rows:
            return 0

        # Determine which columns to update
        if update_columns is None:
            update_columns = [c for c in columns if c not in conflict_columns]

        col_str = ", ".join(columns)
        conflict_str = ", ".join(conflict_columns)

        # Build SET clause for ON CONFLICT UPDATE
        if update_columns:
            update_parts = [f"{col} = EXCLUDED.{col}" for col in update_columns]
            update_str = ", ".join(update_parts)
            sql = f"""
                INSERT INTO {table} ({col_str}) VALUES %s
                ON CONFLICT ({conflict_str}) DO UPDATE SET {update_str}
            """
        else:
            sql = f"""
                INSERT INTO {table} ({col_str}) VALUES %s
                ON CONFLICT ({conflict_str}) DO NOTHING
            """

        total_affected = 0

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]
                    try:
                        extras.execute_values(
                            cur, sql, batch,
                            template=None,
                            page_size=batch_size
                        )
                        total_affected += cur.rowcount
                        conn.commit()

                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Batch upsert failed at row {i}: {e}")
                        raise

        logger.info(f"Batch upsert complete: {total_affected} rows affected in {table}")
        return total_affected

    def batch_update(
        self,
        table: str,
        set_columns: List[str],
        where_columns: List[str],
        rows: List[Tuple],
        batch_size: int = 1000
    ) -> int:
        """
        Update rows in batches using VALUES clause for efficient multi-row updates.

        Args:
            table: Target table name
            set_columns: Columns to update (must be first in tuple order)
            where_columns: Columns for WHERE clause (must be last in tuple order)
            rows: List of tuples: (set_col1_val, ..., where_col1_val, ...)
            batch_size: Number of rows per batch

        Returns:
            Number of rows updated
        """
        if not rows:
            return 0

        # Build column lists with type casting
        all_columns = set_columns + where_columns
        col_positions = ", ".join([f"v.c{i+1}" for i in range(len(all_columns))])

        # Build SET clause
        set_parts = [f"{col} = v.c{i+1}" for i, col in enumerate(set_columns)]
        set_str = ", ".join(set_parts)

        # Build WHERE clause
        where_offset = len(set_columns)
        where_parts = [f"t.{col} = v.c{where_offset + i + 1}" for i, col in enumerate(where_columns)]
        where_str = " AND ".join(where_parts)

        # Build VALUES template
        values_template = "(" + ", ".join(["%s"] * len(all_columns)) + ")"

        sql = f"""
            UPDATE {table} t
            SET {set_str}
            FROM (VALUES %s) AS v({", ".join([f"c{i+1}" for i in range(len(all_columns))])})
            WHERE {where_str}
        """

        total_updated = 0

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]
                    try:
                        extras.execute_values(
                            cur, sql, batch,
                            template=values_template,
                            page_size=batch_size
                        )
                        total_updated += cur.rowcount
                        conn.commit()

                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Batch update failed at row {i}: {e}")
                        raise

        logger.info(f"Batch update complete: {total_updated} rows updated in {table}")
        return total_updated


# Convenience functions

def get_batch_inserter(database_url: Optional[str] = None) -> BatchInserter:
    """Get a BatchInserter instance."""
    return BatchInserter(database_url)


def batch_insert_serp_results(
    rows: List[Dict[str, Any]],
    batch_size: int = 1000
) -> int:
    """
    Batch insert SERP results.

    Args:
        rows: List of dicts with keys: keyword_id, position, url, title, snippet, domain
        batch_size: Rows per batch

    Returns:
        Number of rows inserted
    """
    if not rows:
        return 0

    columns = ['keyword_id', 'position', 'url', 'title', 'snippet', 'domain', 'created_at']
    now = datetime.utcnow()

    tuples = [
        (
            r.get('keyword_id'),
            r.get('position'),
            r.get('url'),
            r.get('title'),
            r.get('snippet'),
            r.get('domain'),
            now
        )
        for r in rows
    ]

    inserter = get_batch_inserter()
    return inserter.batch_insert('serp_results', columns, tuples, batch_size)


def batch_upsert_discovery_citations(
    rows: List[Dict[str, Any]],
    batch_size: int = 500
) -> int:
    """
    Batch upsert discovery citations.

    Args:
        rows: List of dicts with keys: company_id, source_domain, url, business_name, etc.
        batch_size: Rows per batch

    Returns:
        Number of rows affected
    """
    if not rows:
        return 0

    columns = [
        'company_id', 'source_domain', 'url', 'business_name',
        'address', 'phone', 'rating', 'review_count', 'updated_at'
    ]
    now = datetime.utcnow()

    tuples = [
        (
            r.get('company_id'),
            r.get('source_domain'),
            r.get('url'),
            r.get('business_name'),
            r.get('address'),
            r.get('phone'),
            r.get('rating'),
            r.get('review_count'),
            now
        )
        for r in rows
    ]

    inserter = get_batch_inserter()
    return inserter.batch_upsert(
        table='discovery_citations',
        columns=columns,
        rows=tuples,
        conflict_columns=['company_id', 'source_domain'],
        update_columns=['url', 'business_name', 'address', 'phone', 'rating', 'review_count', 'updated_at'],
        batch_size=batch_size
    )


def batch_upsert_backlinks(
    rows: List[Dict[str, Any]],
    batch_size: int = 500
) -> int:
    """
    Batch upsert backlinks.

    Args:
        rows: List of dicts with backlink data
        batch_size: Rows per batch

    Returns:
        Number of rows affected
    """
    if not rows:
        return 0

    columns = [
        'target_url', 'source_url', 'source_domain', 'anchor_text',
        'is_dofollow', 'context_snippet', 'discovered_at', 'last_seen_at'
    ]
    now = datetime.utcnow()

    tuples = [
        (
            r.get('target_url'),
            r.get('source_url'),
            r.get('source_domain'),
            r.get('anchor_text'),
            r.get('is_dofollow', True),
            r.get('context_snippet'),
            r.get('discovered_at', now),
            now
        )
        for r in rows
    ]

    inserter = get_batch_inserter()
    return inserter.batch_upsert(
        table='backlinks',
        columns=columns,
        rows=tuples,
        conflict_columns=['target_url', 'source_url'],
        update_columns=['anchor_text', 'is_dofollow', 'context_snippet', 'last_seen_at'],
        batch_size=batch_size
    )

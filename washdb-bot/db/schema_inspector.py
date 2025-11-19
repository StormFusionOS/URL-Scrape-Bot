"""
Database Schema Inspector
Dynamic table discovery and metadata extraction
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


@dataclass
class TableInfo:
    """Table information"""
    schema: str
    name: str
    row_count: int
    is_partitioned: bool
    description: Optional[str] = None
    last_updated: Optional[datetime] = None


@dataclass
class ColumnInfo:
    """Column information"""
    name: str
    data_type: str
    is_nullable: bool
    default_value: Optional[str] = None


@dataclass
class PartitionInfo:
    """Partition information for time-series tables"""
    parent_table: str
    partition_name: str
    partition_expression: str
    min_value: Optional[str] = None
    max_value: Optional[str] = None


class SchemaInspector:
    """Inspect database schema and provide metadata"""

    def __init__(self, db_manager):
        """Initialize with database manager"""
        self.db = db_manager

    def get_schemas(self) -> List[str]:
        """Get list of available schemas"""
        query = text("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """)

        with self.db.get_session() as session:
            result = session.execute(query)
            return [row[0] for row in result.fetchall()]

    def get_tables(self, schema: str = 'public') -> List[TableInfo]:
        """Get all tables in a schema with metadata"""
        # Query to get tables with row counts
        query = text("""
            SELECT
                t.table_schema,
                t.table_name,
                COALESCE(c.reltuples::bigint, 0) as row_count,
                CASE WHEN p.partstrat IS NOT NULL THEN true ELSE false END as is_partitioned,
                obj_description(c.oid) as description
            FROM information_schema.tables t
            LEFT JOIN pg_class c ON c.relname = t.table_name
            LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_partitioned_table p ON p.partrelid = c.oid
            WHERE t.table_schema = :schema
              AND t.table_type = 'BASE TABLE'
              AND n.nspname = t.table_schema
            ORDER BY t.table_name
        """)

        tables = []

        with self.db.get_session() as session:
            result = session.execute(query, {'schema': schema})
            for row in result.fetchall():
                # Get last updated time from pg_stat_user_tables
                last_updated = self._get_table_last_updated(session, row[0], row[1])

                tables.append(TableInfo(
                    schema=row[0],
                    name=row[1],
                    row_count=row[2],
                    is_partitioned=row[3],
                    description=row[4],
                    last_updated=last_updated
                ))

        return tables

    def _get_table_last_updated(self, session, schema: str, table_name: str) -> Optional[datetime]:
        """Get last update time for a table"""
        query = text("""
            SELECT
                GREATEST(
                    COALESCE(last_autovacuum, '1970-01-01'::timestamp),
                    COALESCE(last_autoanalyze, '1970-01-01'::timestamp),
                    COALESCE(last_vacuum, '1970-01-01'::timestamp),
                    COALESCE(last_analyze, '1970-01-01'::timestamp)
                ) as last_updated
            FROM pg_stat_user_tables
            WHERE schemaname = :schema AND relname = :table_name
        """)

        try:
            result = session.execute(query, {'schema': schema, 'table_name': table_name})
            row = result.fetchone()
            if row and row[0]:
                return row[0]
        except Exception as e:
            logger.debug(f"Could not get last updated time for {schema}.{table_name}: {e}")

        return None

    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Get column information for a table"""
        query = text("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
            ORDER BY ordinal_position
        """)

        columns = []

        with self.db.get_session() as session:
            result = session.execute(query, {'schema': schema, 'table': table})
            for row in result.fetchall():
                columns.append(ColumnInfo(
                    name=row[0],
                    data_type=row[1],
                    is_nullable=(row[2] == 'YES'),
                    default_value=row[3]
                ))

        return columns

    def get_partitions(self, schema: str, table: str) -> List[PartitionInfo]:
        """Get partition information for a partitioned table"""
        query = text("""
            SELECT
                par.relname as parent_table,
                child.relname as partition_name,
                pg_get_expr(child.relpartbound, child.oid) as partition_expression
            FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_class child ON pg_inherits.inhrelid = child.oid
            JOIN pg_namespace nmsp_parent ON nmsp_parent.oid = parent.relnamespace
            JOIN pg_namespace nmsp_child ON nmsp_child.oid = child.relnamespace
            JOIN pg_class par ON par.oid = parent.oid
            WHERE nmsp_parent.nspname = :schema
              AND parent.relname = :table
            ORDER BY child.relname
        """)

        partitions = []

        with self.db.get_session() as session:
            result = session.execute(query, {'schema': schema, 'table': table})
            for row in result.fetchall():
                partitions.append(PartitionInfo(
                    parent_table=row[0],
                    partition_name=row[1],
                    partition_expression=row[2]
                ))

        return partitions

    def get_table_sample(self, schema: str, table: str, limit: int = 5) -> Tuple[List[str], List[tuple]]:
        """Get sample rows from a table"""
        # Get column names
        columns = self.get_columns(schema, table)
        column_names = [col.name for col in columns]

        # Build query with proper schema qualification
        qualified_table = f'"{schema}"."{table}"'
        query = text(f'SELECT * FROM {qualified_table} LIMIT :limit')

        with self.db.get_session() as session:
            result = session.execute(query, {'limit': limit})
            rows = result.fetchall()

        return column_names, rows

    def get_table_row_count(self, schema: str, table: str, exact: bool = False) -> int:
        """Get row count for a table (exact or estimated)"""
        if exact:
            # Exact count (slower for large tables)
            qualified_table = f'"{schema}"."{table}"'
            query = text(f'SELECT COUNT(*) FROM {qualified_table}')

            with self.db.get_session() as session:
                result = session.execute(query)
                return result.scalar()
        else:
            # Estimated count (fast)
            query = text("""
                SELECT c.reltuples::bigint
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :schema
                  AND c.relname = :table
            """)

            with self.db.get_session() as session:
                result = session.execute(query, {'schema': schema, 'table': table})
                row = result.fetchone()
                return row[0] if row else 0

    def is_partitioned_table(self, schema: str, table: str) -> bool:
        """Check if a table is partitioned"""
        query = text("""
            SELECT EXISTS (
                SELECT 1
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_partitioned_table p ON p.partrelid = c.oid
                WHERE n.nspname = :schema
                  AND c.relname = :table
            )
        """)

        with self.db.get_session() as session:
            result = session.execute(query, {'schema': schema, 'table': table})
            return result.scalar()

    def search_table_data(self, schema: str, table: str, search_term: str,
                         limit: int = 100, offset: int = 0) -> Tuple[List[str], List[tuple], int]:
        """Search for data in a table across all text columns"""
        # Get column names
        columns = self.get_columns(schema, table)
        column_names = [col.name for col in columns]

        # Build search condition for text columns
        text_columns = [col.name for col in columns if 'char' in col.data_type.lower() or 'text' in col.data_type.lower()]

        if not text_columns:
            # No text columns to search, return empty
            return column_names, [], 0

        # Build WHERE clause
        search_conditions = [f'"{col}"::text ILIKE :search' for col in text_columns]
        where_clause = ' OR '.join(search_conditions)

        # Build queries
        qualified_table = f'"{schema}"."{table}"'
        count_query = text(f'SELECT COUNT(*) FROM {qualified_table} WHERE {where_clause}')
        data_query = text(f'SELECT * FROM {qualified_table} WHERE {where_clause} LIMIT :limit OFFSET :offset')

        search_pattern = f'%{search_term}%'

        with self.db.get_session() as session:
            # Get total count
            count_result = session.execute(count_query, {'search': search_pattern})
            total_count = count_result.scalar()

            # Get data
            data_result = session.execute(data_query, {
                'search': search_pattern,
                'limit': limit,
                'offset': offset
            })
            rows = data_result.fetchall()

        return column_names, rows, total_count


def get_schema_inspector(db_manager) -> SchemaInspector:
    """Get schema inspector instance"""
    return SchemaInspector(db_manager)

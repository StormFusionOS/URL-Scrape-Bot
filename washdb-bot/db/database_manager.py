"""
Database Connection Manager for Washbot
SQLAlchemy-based dual-database connection manager
Supports both washbot_db (primary) and scraper (SEO intelligence) databases
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Generator, Literal
from dotenv import load_dotenv

from runner.logging_setup import get_logger

# Load environment
load_dotenv()

logger = get_logger("database_manager")

DatabaseType = Literal['washdb', 'scraper']


class DatabaseManager:
    """Manages dual database connections with connection pooling"""

    def __init__(self):
        # Washbot database (primary - URL discovery and business data)
        self.washdb_engine = None
        self.WashdbSessionLocal = None

        # Scraper database (SEO analytics and crawl data)
        self.scraper_engine = None
        self.ScraperSessionLocal = None

        self._initialize_engines()

    def _initialize_engines(self):
        """Initialize SQLAlchemy engines for both databases with connection pooling"""
        try:
            # Initialize washbot database engine (primary)
            washdb_url = os.getenv("DATABASE_URL")
            if not washdb_url:
                raise RuntimeError("DATABASE_URL not set in environment")

            self.washdb_engine = create_engine(
                washdb_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,  # Verify connections before using
                pool_recycle=3600,  # Recycle connections after 1 hour
                echo=False
            )
            self.WashdbSessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.washdb_engine
            )
            logger.info("Washbot database engine initialized successfully")

            # Initialize scraper database engine (SEO intelligence)
            scraper_url = os.getenv("SCRAPER_DATABASE_URL")
            if scraper_url:
                self.scraper_engine = create_engine(
                    scraper_url,
                    poolclass=QueuePool,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    echo=False
                )
                self.ScraperSessionLocal = sessionmaker(
                    autocommit=False,
                    autoflush=False,
                    bind=self.scraper_engine
                )
                logger.info("Scraper database engine initialized successfully")
            else:
                logger.warning("SCRAPER_DATABASE_URL not set - SEO features will be unavailable")

        except Exception as e:
            logger.error(f"Failed to initialize database engines: {e}")
            raise

    @contextmanager
    def get_session(self, db_type: DatabaseType = 'washdb') -> Generator[Session, None, None]:
        """
        Context manager for database sessions

        Args:
            db_type: Which database to connect to ('washdb' or 'scraper')

        Usage:
            with db_manager.get_session() as session:
                result = session.execute(text("SELECT * FROM companies"))

            with db_manager.get_session('scraper') as session:
                result = session.execute(text("SELECT * FROM competitor_urls"))

        Yields:
            Database session

        Raises:
            RuntimeError: If scraper database is not configured
        """
        if db_type == 'scraper':
            if not self.ScraperSessionLocal:
                raise RuntimeError("Scraper database not configured. Set SCRAPER_DATABASE_URL in .env")
            session = self.ScraperSessionLocal()
        else:
            session = self.WashdbSessionLocal()

        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error ({db_type}): {e}")
            raise
        finally:
            session.close()

    def execute_query(self, query: str, params: dict = None, db_type: DatabaseType = 'washdb'):
        """
        Execute a raw SQL query

        Args:
            query: SQL query string
            params: Query parameters (optional)
            db_type: Which database to query ('washdb' or 'scraper')

        Returns:
            Query result
        """
        from sqlalchemy import text

        with self.get_session(db_type) as session:
            if params:
                result = session.execute(text(query), params)
            else:
                result = session.execute(text(query))
            return result.fetchall()

    def get_connection_health(self, db_type: DatabaseType = 'washdb') -> dict:
        """
        Check database connection health with latency measurement

        Args:
            db_type: Which database to check ('washdb' or 'scraper')

        Returns:
            dict with keys: connected (bool), latency_ms (float), error (str)
        """
        import time
        from sqlalchemy import text

        result = {
            'connected': False,
            'latency_ms': None,
            'error': None
        }

        try:
            start_time = time.time()
            with self.get_session(db_type) as session:
                session.execute(text("SELECT 1"))

            latency = (time.time() - start_time) * 1000  # Convert to ms
            result['connected'] = True
            result['latency_ms'] = round(latency, 2)

        except Exception as e:
            result['connected'] = False
            result['error'] = str(e)
            logger.error(f"Connection health check failed for {db_type}: {e}")

        return result

    def close(self):
        """Close all database connections"""
        try:
            if self.washdb_engine:
                self.washdb_engine.dispose()
                logger.info("Washbot database engine closed")

            if self.scraper_engine:
                self.scraper_engine.dispose()
                logger.info("Scraper database engine closed")
        except Exception as e:
            logger.error(f"Error closing database engines: {e}")


# Global instance
_db_manager = None


def get_db_manager() -> DatabaseManager:
    """Get the global DatabaseManager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


# Backwards compatibility with existing code
def create_session() -> Session:
    """
    Create a database session (washbot database)
    Maintains backwards compatibility with existing code

    Returns:
        SQLAlchemy Session instance for washbot database
    """
    db_manager = get_db_manager()
    # Return a raw session (not context managed)
    return db_manager.WashdbSessionLocal()

    @contextmanager
    def get_connection(self):
        """
        Get raw database connection (psycopg2).
        For backwards compatibility with code expecting raw connections.
        """
        from sqlalchemy import text
        session = self.WashdbSessionLocal()
        try:
            # Get raw connection from session
            connection = session.connection().connection
            yield connection
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            session.close()

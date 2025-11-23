"""
Database Manager for Washdb-Bot GUI Backend

Handles connections to the washdb PostgreSQL database only.
Does NOT connect to other bot databases.
"""

import logging
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

# Import models from parent db module
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from db.models import Base, Company, DiscoveryRun
except ImportError:
    # Models not yet available
    Base = None
    Company = None
    DiscoveryRun = None

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections for the GUI backend.

    Connects ONLY to washdb database (washdb-bot's PostgreSQL).
    """

    def __init__(self, database_url: str):
        """
        Initialize database manager.

        Args:
            database_url: PostgreSQL connection string for washdb
        """
        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
        self._initialize_engine()

    def _initialize_engine(self):
        """Initialize SQLAlchemy engine and session factory."""
        try:
            self.engine = create_engine(
                self.database_url,
                pool_pre_ping=True,  # Verify connections before using
                pool_size=10,
                max_overflow=20,
                echo=False  # Set to True for SQL debugging
            )

            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )

            logger.info(f"Database engine initialized for washdb")
        except Exception as e:
            logger.error(f"Failed to initialize database engine: {e}")
            raise

    @contextmanager
    def get_session(self) -> Session:
        """
        Get a database session context manager.

        Usage:
            with db_manager.get_session() as session:
                companies = session.query(Company).all()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check_connection(self) -> bool:
        """
        Check if database connection is working.

        Returns:
            True if connected, False otherwise
        """
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    def get_companies(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get companies from database.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            filters: Optional filters (e.g., {'has_website': True})

        Returns:
            List of company dictionaries
        """
        if Company is None:
            logger.warning("Company model not available")
            return []

        try:
            with self.get_session() as session:
                query = session.query(Company)

                # Apply filters if provided
                if filters:
                    if 'has_website' in filters:
                        query = query.filter(Company.website.isnot(None))
                    if 'has_phone' in filters:
                        query = query.filter(Company.phone.isnot(None))

                # Apply pagination
                companies = query.offset(offset).limit(limit).all()

                # Convert to dictionaries
                return [
                    {
                        'id': c.id,
                        'name': c.name,
                        'website': c.website,
                        'phone': c.phone,
                        'email': c.email,
                        'address': c.address,
                        'created_at': c.created_at.isoformat() if c.created_at else None,
                        'updated_at': c.updated_at.isoformat() if c.updated_at else None
                    }
                    for c in companies
                ]
        except Exception as e:
            logger.error(f"Error fetching companies: {e}")
            return []

    def get_company_count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Get total count of companies.

        Args:
            filters: Optional filters

        Returns:
            Total count
        """
        if Company is None:
            return 0

        try:
            with self.get_session() as session:
                query = session.query(Company)

                # Apply filters if provided
                if filters:
                    if 'has_website' in filters:
                        query = query.filter(Company.website.isnot(None))
                    if 'has_phone' in filters:
                        query = query.filter(Company.phone.isnot(None))

                return query.count()
        except Exception as e:
            logger.error(f"Error counting companies: {e}")
            return 0

    def get_discovery_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recent discovery runs.

        Args:
            limit: Maximum number of results

        Returns:
            List of discovery run dictionaries
        """
        if DiscoveryRun is None:
            logger.warning("DiscoveryRun model not available")
            return []

        try:
            with self.get_session() as session:
                runs = session.query(DiscoveryRun)\
                    .order_by(DiscoveryRun.started_at.desc())\
                    .limit(limit)\
                    .all()

                return [
                    {
                        'id': r.id,
                        'status': r.status,
                        'total_discovered': r.total_discovered,
                        'started_at': r.started_at.isoformat() if r.started_at else None,
                        'completed_at': r.completed_at.isoformat() if r.completed_at else None
                    }
                    for r in runs
                ]
        except Exception as e:
            logger.error(f"Error fetching discovery runs: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with stats
        """
        try:
            with self.get_session() as session:
                stats = {
                    'total_companies': session.query(Company).count() if Company else 0,
                    'companies_with_website': session.query(Company).filter(Company.website.isnot(None)).count() if Company else 0,
                    'companies_with_phone': session.query(Company).filter(Company.phone.isnot(None)).count() if Company else 0,
                    'companies_with_email': session.query(Company).filter(Company.email.isnot(None)).count() if Company else 0,
                    'total_discovery_runs': session.query(DiscoveryRun).count() if DiscoveryRun else 0
                }
                return stats
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            return {
                'total_companies': 0,
                'companies_with_website': 0,
                'companies_with_phone': 0,
                'companies_with_email': 0,
                'total_discovery_runs': 0
            }

    def close(self):
        """Close database connections."""
        if self.engine:
            self.engine.dispose()
            logger.info("Database connections closed")

"""
Resource Manager

Singleton manager for shared resources: database connections,
memory monitoring, and cleanup routines.
"""

import gc
import os
import threading
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from runner.logging_setup import get_logger


logger = get_logger("ResourceManager")


class ResourceManager:
    """
    Singleton resource manager for SEO orchestrator.

    Provides:
    - Connection pool management
    - Memory monitoring
    - Cleanup routines between modules/cycles
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._db_url = self._get_default_db_url()
        self._engine = None
        self._Session = None
        self._active_sessions: Dict[str, Session] = {}

        # Memory thresholds
        self._memory_warning_threshold = 0.80  # 80%
        self._memory_critical_threshold = 0.90  # 90%

        self._init_connection_pool()

    def _get_default_db_url(self) -> str:
        """Get default database URL from environment."""
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        return database_url

    def _init_connection_pool(self):
        """Initialize SQLAlchemy connection pool."""
        try:
            self._engine = create_engine(
                self._db_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,  # Recycle connections after 30 min
                pool_pre_ping=True   # Verify connections before use
            )
            self._Session = sessionmaker(bind=self._engine)
            logger.info("Connection pool initialized")

        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise

    @contextmanager
    def session_scope(self, module: str = "default"):
        """
        Context manager for database sessions with module tracking.

        Args:
            module: Module name for tracking

        Yields:
            SQLAlchemy Session
        """
        session = self._Session()
        self._active_sessions[module] = session

        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._active_sessions.pop(module, None)

    def get_session(self, module: str = "default") -> Session:
        """
        Get a new database session.

        Args:
            module: Module name for tracking

        Returns:
            SQLAlchemy Session (caller must close)
        """
        session = self._Session()
        self._active_sessions[module] = session
        return session

    def release_session(self, module: str):
        """
        Release a session for a module.

        Args:
            module: Module name
        """
        session = self._active_sessions.pop(module, None)
        if session:
            try:
                session.close()
            except Exception:
                pass

    def check_memory(self) -> Tuple[float, bool]:
        """
        Check current memory usage.

        Returns:
            Tuple of (usage_percent, is_critical)
        """
        try:
            import psutil
            memory = psutil.virtual_memory()
            usage_percent = memory.percent / 100.0

            is_critical = usage_percent >= self._memory_critical_threshold

            if usage_percent >= self._memory_warning_threshold:
                logger.warning(f"Memory usage at {usage_percent:.1%}")

            return usage_percent, is_critical

        except ImportError:
            # psutil not available, return safe defaults
            return 0.5, False
        except Exception as e:
            logger.error(f"Error checking memory: {e}")
            return 0.5, False

    def cleanup_between_modules(self):
        """
        Light cleanup between modules.

        - Clears Python garbage
        - Checks memory usage
        """
        logger.debug("Running between-module cleanup")

        # Force garbage collection
        gc.collect()

        # Check memory
        usage, is_critical = self.check_memory()

        if is_critical:
            logger.warning("Critical memory usage, running aggressive cleanup")
            self._aggressive_cleanup()

    def cleanup_between_cycles(self):
        """
        Thorough cleanup between cycles.

        - Clears all caches
        - Force garbage collection
        - Recycles database connections
        """
        logger.info("Running between-cycle cleanup")

        # Close any lingering sessions
        for module, session in list(self._active_sessions.items()):
            try:
                session.close()
            except Exception:
                pass
        self._active_sessions.clear()

        # Force garbage collection (multiple passes)
        gc.collect()
        gc.collect()
        gc.collect()

        # Recycle connection pool
        if self._engine:
            self._engine.dispose()
            self._init_connection_pool()

        logger.info("Between-cycle cleanup complete")

    def _aggressive_cleanup(self):
        """Aggressive cleanup when memory is critical."""
        # Close all sessions
        for module, session in list(self._active_sessions.items()):
            try:
                session.close()
            except Exception:
                pass
        self._active_sessions.clear()

        # Multiple garbage collection passes
        for _ in range(3):
            gc.collect()

        # Dispose and recreate connection pool
        if self._engine:
            self._engine.dispose()
            self._init_connection_pool()

    def get_pool_status(self) -> Dict[str, Any]:
        """
        Get connection pool status.

        Returns:
            Dict with pool statistics
        """
        if not self._engine:
            return {"status": "not_initialized"}

        pool = self._engine.pool
        return {
            "status": "active",
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "active_sessions": list(self._active_sessions.keys())
        }

    def shutdown(self):
        """Shutdown resource manager and cleanup."""
        logger.info("Shutting down resource manager")

        # Close all sessions
        for module, session in list(self._active_sessions.items()):
            try:
                session.close()
            except Exception:
                pass
        self._active_sessions.clear()

        # Dispose connection pool
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._Session = None

        logger.info("Resource manager shutdown complete")


def get_resource_manager() -> ResourceManager:
    """Get the singleton ResourceManager instance."""
    return ResourceManager()

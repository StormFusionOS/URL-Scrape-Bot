"""
Cycle State Manager

Dual persistence for SEO cycle state: PostgreSQL primary, JSON fallback.
Enables crash recovery and resume from checkpoint.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from runner.logging_setup import get_logger


logger = get_logger("CycleStateManager")


@dataclass
class ModuleState:
    """State for a single module within a cycle."""
    module_name: str
    status: str = "pending"  # pending, running, completed, failed
    last_company_id: Optional[int] = None
    companies_processed: int = 0
    errors: int = 0
    last_heartbeat: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class CycleState:
    """State for the entire SEO cycle."""
    cycle_id: str
    status: str = "running"  # running, paused, completed, failed
    current_module_index: int = 0
    cycle_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    modules: Dict[str, ModuleState] = None

    def __post_init__(self):
        if self.modules is None:
            self.modules = {}


class CycleStateManager:
    """
    Manages SEO cycle state with dual persistence.

    Primary: PostgreSQL (seo_cycle_state, seo_module_state tables)
    Fallback: JSON file (data/seo_cycle_state.json)
    """

    MODULE_ORDER = ["serp", "citations", "backlinks", "technical", "seo_worker"]

    def __init__(self, db_url: Optional[str] = None, json_path: Optional[str] = None):
        """
        Initialize state manager.

        Args:
            db_url: PostgreSQL connection URL
            json_path: Path to JSON fallback file
        """
        self.db_url = db_url or self._get_default_db_url()
        self.json_path = Path(json_path or "data/seo_cycle_state.json")

        # Ensure data directory exists
        self.json_path.parent.mkdir(parents=True, exist_ok=True)

        # Database setup
        self._engine = None
        self._Session = None
        self._db_available = False

        self._init_database()

        # Current state
        self._current_state: Optional[CycleState] = None

    def _get_default_db_url(self) -> str:
        """Get default database URL from environment."""
        import os
        database_url = os.environ.get('DATABASE_URL', '')
        # Convert psycopg format to standard postgresql format
        if 'postgresql+psycopg' in database_url:
            database_url = database_url.replace('postgresql+psycopg', 'postgresql')
        return database_url

    def _init_database(self):
        """Initialize database connection and create tables if needed."""
        try:
            self._engine = create_engine(self.db_url, pool_pre_ping=True)
            self._Session = sessionmaker(bind=self._engine)

            # Create tables if not exist
            with self._engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS seo_cycle_state (
                        cycle_id UUID PRIMARY KEY,
                        started_at TIMESTAMP DEFAULT NOW(),
                        status VARCHAR(50) DEFAULT 'running',
                        current_module_index INTEGER DEFAULT 0,
                        cycle_count INTEGER DEFAULT 0,
                        completed_at TIMESTAMP
                    )
                """))

                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS seo_module_state (
                        id SERIAL PRIMARY KEY,
                        cycle_id UUID REFERENCES seo_cycle_state(cycle_id) ON DELETE CASCADE,
                        module_name VARCHAR(100),
                        status VARCHAR(50) DEFAULT 'pending',
                        last_company_id INTEGER,
                        companies_processed INTEGER DEFAULT 0,
                        errors INTEGER DEFAULT 0,
                        last_heartbeat TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        UNIQUE (cycle_id, module_name)
                    )
                """))

                conn.commit()

            self._db_available = True
            logger.info("Database initialized successfully")

        except Exception as e:
            logger.warning(f"Database unavailable, using JSON fallback: {e}")
            self._db_available = False

    @contextmanager
    def _session_scope(self):
        """Context manager for database sessions."""
        session = self._Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_or_create_cycle(self) -> CycleState:
        """
        Get existing active cycle or create a new one.

        Returns:
            CycleState: Active cycle state
        """
        # Try to load existing state
        state = self._load_state()

        if state and state.status == "running":
            logger.info(f"Resuming existing cycle {state.cycle_id}")
            self._current_state = state
            return state

        # Create new cycle
        state = CycleState(
            cycle_id=str(uuid.uuid4()),
            status="running",
            current_module_index=0,
            cycle_count=0,
            started_at=datetime.now(),
            modules={name: ModuleState(module_name=name) for name in self.MODULE_ORDER}
        )

        self._save_state(state)
        self._current_state = state

        logger.info(f"Created new cycle {state.cycle_id}")
        return state

    def _load_state(self) -> Optional[CycleState]:
        """Load state from database or JSON fallback."""
        if self._db_available:
            return self._load_from_db()
        return self._load_from_json()

    def _load_from_db(self) -> Optional[CycleState]:
        """Load state from PostgreSQL."""
        try:
            with self._session_scope() as session:
                # Get most recent running cycle
                result = session.execute(text("""
                    SELECT cycle_id, started_at, status, current_module_index, cycle_count, completed_at
                    FROM seo_cycle_state
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                    LIMIT 1
                """))

                row = result.fetchone()
                if not row:
                    return None

                cycle_id = str(row[0])

                # Load module states
                module_result = session.execute(text("""
                    SELECT module_name, status, last_company_id, companies_processed,
                           errors, last_heartbeat, started_at, completed_at
                    FROM seo_module_state
                    WHERE cycle_id = :cycle_id
                """), {"cycle_id": cycle_id})

                modules = {}
                for mrow in module_result:
                    modules[mrow[0]] = ModuleState(
                        module_name=mrow[0],
                        status=mrow[1] or "pending",
                        last_company_id=mrow[2],
                        companies_processed=mrow[3] or 0,
                        errors=mrow[4] or 0,
                        last_heartbeat=mrow[5],
                        started_at=mrow[6],
                        completed_at=mrow[7]
                    )

                # Fill in missing modules
                for name in self.MODULE_ORDER:
                    if name not in modules:
                        modules[name] = ModuleState(module_name=name)

                return CycleState(
                    cycle_id=cycle_id,
                    status=row[2],
                    current_module_index=row[3] or 0,
                    cycle_count=row[4] or 0,
                    started_at=row[1],
                    completed_at=row[5],
                    modules=modules
                )

        except Exception as e:
            logger.error(f"Error loading from database: {e}")
            return self._load_from_json()

    def _load_from_json(self) -> Optional[CycleState]:
        """Load state from JSON file."""
        if not self.json_path.exists():
            return None

        try:
            with open(self.json_path, 'r') as f:
                data = json.load(f)

            modules = {}
            for name, mdata in data.get('modules', {}).items():
                modules[name] = ModuleState(
                    module_name=mdata['module_name'],
                    status=mdata.get('status', 'pending'),
                    last_company_id=mdata.get('last_company_id'),
                    companies_processed=mdata.get('companies_processed', 0),
                    errors=mdata.get('errors', 0),
                    last_heartbeat=datetime.fromisoformat(mdata['last_heartbeat']) if mdata.get('last_heartbeat') else None,
                    started_at=datetime.fromisoformat(mdata['started_at']) if mdata.get('started_at') else None,
                    completed_at=datetime.fromisoformat(mdata['completed_at']) if mdata.get('completed_at') else None
                )

            return CycleState(
                cycle_id=data['cycle_id'],
                status=data.get('status', 'running'),
                current_module_index=data.get('current_module_index', 0),
                cycle_count=data.get('cycle_count', 0),
                started_at=datetime.fromisoformat(data['started_at']) if data.get('started_at') else None,
                completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
                modules=modules
            )

        except Exception as e:
            logger.error(f"Error loading from JSON: {e}")
            return None

    def _save_state(self, state: CycleState):
        """Save state to database and JSON backup."""
        if self._db_available:
            self._save_to_db(state)
        self._save_to_json(state)

    def _save_to_db(self, state: CycleState):
        """Save state to PostgreSQL."""
        try:
            with self._session_scope() as session:
                # Upsert cycle state
                session.execute(text("""
                    INSERT INTO seo_cycle_state
                        (cycle_id, started_at, status, current_module_index, cycle_count, completed_at)
                    VALUES
                        (:cycle_id, :started_at, :status, :current_module_index, :cycle_count, :completed_at)
                    ON CONFLICT (cycle_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        current_module_index = EXCLUDED.current_module_index,
                        cycle_count = EXCLUDED.cycle_count,
                        completed_at = EXCLUDED.completed_at
                """), {
                    "cycle_id": state.cycle_id,
                    "started_at": state.started_at,
                    "status": state.status,
                    "current_module_index": state.current_module_index,
                    "cycle_count": state.cycle_count,
                    "completed_at": state.completed_at
                })

                # Upsert module states
                for module in state.modules.values():
                    session.execute(text("""
                        INSERT INTO seo_module_state
                            (cycle_id, module_name, status, last_company_id, companies_processed,
                             errors, last_heartbeat, started_at, completed_at)
                        VALUES
                            (:cycle_id, :module_name, :status, :last_company_id, :companies_processed,
                             :errors, :last_heartbeat, :started_at, :completed_at)
                        ON CONFLICT (cycle_id, module_name) DO UPDATE SET
                            status = EXCLUDED.status,
                            last_company_id = EXCLUDED.last_company_id,
                            companies_processed = EXCLUDED.companies_processed,
                            errors = EXCLUDED.errors,
                            last_heartbeat = EXCLUDED.last_heartbeat,
                            started_at = EXCLUDED.started_at,
                            completed_at = EXCLUDED.completed_at
                    """), {
                        "cycle_id": state.cycle_id,
                        "module_name": module.module_name,
                        "status": module.status,
                        "last_company_id": module.last_company_id,
                        "companies_processed": module.companies_processed,
                        "errors": module.errors,
                        "last_heartbeat": module.last_heartbeat,
                        "started_at": module.started_at,
                        "completed_at": module.completed_at
                    })

        except Exception as e:
            logger.error(f"Error saving to database: {e}")

    def _save_to_json(self, state: CycleState):
        """Save state to JSON file."""
        try:
            data = {
                "cycle_id": state.cycle_id,
                "status": state.status,
                "current_module_index": state.current_module_index,
                "cycle_count": state.cycle_count,
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "completed_at": state.completed_at.isoformat() if state.completed_at else None,
                "modules": {}
            }

            for name, module in state.modules.items():
                data["modules"][name] = {
                    "module_name": module.module_name,
                    "status": module.status,
                    "last_company_id": module.last_company_id,
                    "companies_processed": module.companies_processed,
                    "errors": module.errors,
                    "last_heartbeat": module.last_heartbeat.isoformat() if module.last_heartbeat else None,
                    "started_at": module.started_at.isoformat() if module.started_at else None,
                    "completed_at": module.completed_at.isoformat() if module.completed_at else None
                }

            with open(self.json_path, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving to JSON: {e}")

    def update_module_progress(
        self,
        module: str,
        last_company_id: Optional[int] = None,
        companies_processed: Optional[int] = None,
        errors: Optional[int] = None,
        status: Optional[str] = None
    ):
        """
        Update progress for a specific module.

        Args:
            module: Module name
            last_company_id: Last processed company ID (resume cursor)
            companies_processed: Total companies processed
            errors: Total errors
            status: Module status
        """
        if not self._current_state:
            return

        if module not in self._current_state.modules:
            self._current_state.modules[module] = ModuleState(module_name=module)

        mod_state = self._current_state.modules[module]

        if last_company_id is not None:
            mod_state.last_company_id = last_company_id
        if companies_processed is not None:
            mod_state.companies_processed = companies_processed
        if errors is not None:
            mod_state.errors = errors
        if status is not None:
            mod_state.status = status
            if status == "running" and not mod_state.started_at:
                mod_state.started_at = datetime.now()
            elif status in ("completed", "failed"):
                mod_state.completed_at = datetime.now()

        self._save_state(self._current_state)

    def get_resume_point(self, module: str) -> Optional[int]:
        """
        Get the resume point (last_company_id) for a module.

        Args:
            module: Module name

        Returns:
            Last processed company ID, or None to start from beginning
        """
        if not self._current_state:
            return None

        mod_state = self._current_state.modules.get(module)
        if not mod_state:
            return None

        return mod_state.last_company_id

    def heartbeat(self, module: str):
        """
        Record heartbeat for a module.

        Args:
            module: Module name
        """
        if not self._current_state:
            return

        if module in self._current_state.modules:
            self._current_state.modules[module].last_heartbeat = datetime.now()
            self._save_state(self._current_state)

    def detect_stuck_modules(self, timeout_seconds: int = 300) -> List[str]:
        """
        Detect modules that haven't sent heartbeat within timeout.

        Args:
            timeout_seconds: Heartbeat timeout in seconds

        Returns:
            List of stuck module names
        """
        if not self._current_state:
            return []

        stuck = []
        cutoff = datetime.now() - timedelta(seconds=timeout_seconds)

        for name, mod_state in self._current_state.modules.items():
            if mod_state.status == "running":
                if mod_state.last_heartbeat and mod_state.last_heartbeat < cutoff:
                    stuck.append(name)
                elif not mod_state.last_heartbeat and mod_state.started_at and mod_state.started_at < cutoff:
                    stuck.append(name)

        return stuck

    def advance_to_next_module(self):
        """Advance to the next module in the cycle."""
        if not self._current_state:
            return

        self._current_state.current_module_index += 1

        # If we've completed all modules, increment cycle count
        if self._current_state.current_module_index >= len(self.MODULE_ORDER):
            self._current_state.current_module_index = 0
            self._current_state.cycle_count += 1

            # Reset module states for new cycle
            for mod_state in self._current_state.modules.values():
                mod_state.status = "pending"
                mod_state.last_company_id = None
                mod_state.companies_processed = 0
                mod_state.errors = 0
                mod_state.last_heartbeat = None
                mod_state.started_at = None
                mod_state.completed_at = None

            logger.info(f"Starting cycle {self._current_state.cycle_count + 1}")

        self._save_state(self._current_state)

    def get_current_module(self) -> Optional[str]:
        """Get the name of the current module to process."""
        if not self._current_state:
            return None

        idx = self._current_state.current_module_index
        if 0 <= idx < len(self.MODULE_ORDER):
            return self.MODULE_ORDER[idx]
        return None

    def mark_cycle_completed(self):
        """Mark the current cycle as completed."""
        if not self._current_state:
            return

        self._current_state.status = "completed"
        self._current_state.completed_at = datetime.now()
        self._save_state(self._current_state)

    def mark_cycle_failed(self, reason: str = ""):
        """Mark the current cycle as failed."""
        if not self._current_state:
            return

        self._current_state.status = "failed"
        self._current_state.completed_at = datetime.now()
        self._save_state(self._current_state)
        logger.error(f"Cycle marked as failed: {reason}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get full cycle status for dashboard.

        Returns:
            Dict with cycle and module status
        """
        if not self._current_state:
            return {
                "cycle_id": None,
                "status": "not_started",
                "cycle_count": 0,
                "current_module": None,
                "modules": {}
            }

        return {
            "cycle_id": self._current_state.cycle_id,
            "status": self._current_state.status,
            "cycle_count": self._current_state.cycle_count,
            "current_module": self.get_current_module(),
            "current_module_index": self._current_state.current_module_index,
            "started_at": self._current_state.started_at.isoformat() if self._current_state.started_at else None,
            "modules": {
                name: {
                    "status": mod.status,
                    "companies_processed": mod.companies_processed,
                    "errors": mod.errors,
                    "last_company_id": mod.last_company_id,
                    "last_heartbeat": mod.last_heartbeat.isoformat() if mod.last_heartbeat else None
                }
                for name, mod in self._current_state.modules.items()
            }
        }

    def reset_state(self):
        """Reset all state (for fresh start)."""
        self._current_state = None

        if self._db_available:
            try:
                with self._session_scope() as session:
                    session.execute(text("DELETE FROM seo_module_state"))
                    session.execute(text("DELETE FROM seo_cycle_state"))
            except Exception as e:
                logger.error(f"Error resetting database state: {e}")

        if self.json_path.exists():
            self.json_path.unlink()

        logger.info("State reset complete")

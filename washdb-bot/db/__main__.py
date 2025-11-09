"""
CLI entry point for database module.

This allows running the database initialization as a module:
    python -m db.init_db
"""

from db.init_db import main

if __name__ == "__main__":
    main()

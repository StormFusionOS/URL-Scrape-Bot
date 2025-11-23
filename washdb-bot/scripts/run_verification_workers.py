#!/usr/bin/env python3
"""
Launch verification worker pool.

This script starts a pool of worker processes that continuously
verify companies from the database.

Usage:
    python scripts/run_verification_workers.py --workers 5
    python scripts/run_verification_workers.py --workers 3 --config config.json
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from verification.verification_worker_pool import main

if __name__ == '__main__':
    main()

"""
Allow running as python -m niceui
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from niceui.main import run

if __name__ == '__main__':
    run()

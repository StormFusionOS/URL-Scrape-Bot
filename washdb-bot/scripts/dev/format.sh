#!/bin/bash
# Code Formatting Script
# Runs black formatter on the codebase

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================="
echo "Code Formatting (Black)"
echo "========================================="
echo ""

cd "$PROJECT_ROOT"

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run black formatter
echo "Formatting Python code..."
black .

echo ""
echo "✓ Formatting complete!"
echo ""
echo "Files have been reformatted according to Black style guide."

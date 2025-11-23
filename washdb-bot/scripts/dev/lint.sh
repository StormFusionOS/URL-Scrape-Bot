#!/bin/bash
# Code Linting Script
# Runs ruff linter on the codebase

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================="
echo "Code Linting (Ruff)"
echo "========================================="
echo ""

cd "$PROJECT_ROOT"

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run ruff linter
echo "Linting Python code..."
echo ""

if ruff check .; then
    echo ""
    echo "✓ No linting errors found!"
else
    echo ""
    echo "⚠ Linting issues found. Run 'ruff check --fix .' to auto-fix some issues."
    exit 1
fi

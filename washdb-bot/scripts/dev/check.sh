#!/bin/bash
# Pre-Commit Check Script
# Runs all code quality checks (format, lint, tests)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================="
echo "Pre-Commit Checks"
echo "========================================="
echo ""

cd "$PROJECT_ROOT"

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Track failures
FAILURES=0

# 1. Format check
echo "[1/3] Checking code formatting..."
if black --check . > /dev/null 2>&1; then
    echo "  ✓ Code formatting OK"
else
    echo "  ✗ Code formatting issues found"
    echo "    Run './scripts/dev/format.sh' to auto-format"
    FAILURES=$((FAILURES + 1))
fi

# 2. Linting
echo ""
echo "[2/3] Running linter..."
if ruff check . > /dev/null 2>&1; then
    echo "  ✓ Linting passed"
else
    echo "  ✗ Linting issues found"
    echo "    Run './scripts/dev/lint.sh' for details"
    FAILURES=$((FAILURES + 1))
fi

# 3. Tests (optional, can be slow)
echo ""
echo "[3/3] Running tests (unit only, fast)..."
if pytest tests/unit -q > /dev/null 2>&1; then
    echo "  ✓ Unit tests passed"
elif pytest tests/ -q --co -q > /dev/null 2>&1; then
    # No unit tests directory, run all tests
    if pytest tests/ -q -x > /dev/null 2>&1; then
        echo "  ✓ Tests passed"
    else
        echo "  ✗ Tests failed"
        echo "    Run 'pytest tests/' for details"
        FAILURES=$((FAILURES + 1))
    fi
else
    echo "  ⊘ No tests found or tests disabled"
fi

# Summary
echo ""
echo "========================================="
if [ $FAILURES -eq 0 ]; then
    echo "✓ All checks passed!"
    echo "========================================="
    echo ""
    echo "Ready to commit!"
    exit 0
else
    echo "✗ $FAILURES check(s) failed"
    echo "========================================="
    echo ""
    echo "Please fix the issues above before committing."
    exit 1
fi

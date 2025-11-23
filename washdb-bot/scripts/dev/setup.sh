#!/bin/bash
# Development Environment Setup Script
# This script sets up a complete development environment for the URL Scrape Bot

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================="
echo "URL Scrape Bot - Dev Environment Setup"
echo "========================================="
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Check Python version
echo "[1/7] Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo "❌ Error: Python 3.11+ required. Found: Python $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION detected"

# Create/activate virtual environment
echo ""
echo "[2/7] Setting up virtual environment..."
if [ ! -d "venv" ]; then
    echo "Creating new virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
echo ""
echo "[3/7] Upgrading pip..."
pip install --upgrade pip -q
echo "✓ pip upgraded"

# Install dependencies
echo ""
echo "[4/7] Installing Python dependencies..."
pip install -r requirements.txt -q
echo "✓ Dependencies installed"

# Install Playwright browsers
echo ""
echo "[5/7] Installing Playwright browsers..."
if command -v playwright &> /dev/null; then
    playwright install chromium
    echo "✓ Playwright browsers installed"
else
    echo "❌ Warning: playwright command not found. Try running 'playwright install' manually."
fi

# Check PostgreSQL connection
echo ""
echo "[6/7] Verifying PostgreSQL connection..."
if [ -f ".env" ]; then
    # Source .env file to get DATABASE_URL
    export $(grep -v '^#' .env | xargs)

    if [ -n "$DATABASE_URL" ]; then
        # Try to connect to PostgreSQL
        if python3 -c "from sqlalchemy import create_engine; engine = create_engine('$DATABASE_URL'); engine.connect()" 2>/dev/null; then
            echo "✓ PostgreSQL connection successful"
        else
            echo "⚠ Warning: Could not connect to PostgreSQL"
            echo "  Make sure PostgreSQL is running and DATABASE_URL in .env is correct"
            echo "  Run 'python db/init_db.py' to initialize the database"
        fi
    else
        echo "⚠ Warning: DATABASE_URL not set in .env"
    fi
else
    echo "⚠ Warning: .env file not found"
    echo "  Copy .env.example to .env and configure DATABASE_URL"
fi

# Initialize database (optional)
echo ""
echo "[7/7] Database initialization..."
read -p "Initialize/update database tables? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python db/init_db.py
    echo "✓ Database initialized"
else
    echo "⊘ Skipped database initialization"
fi

# Summary
echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Activate virtual environment:"
echo "     source venv/bin/activate"
echo ""
echo "  2. Configure environment (if not done):"
echo "     cp .env.example .env"
echo "     # Edit .env with your database credentials"
echo ""
echo "  3. Run the dashboard:"
echo "     ./scripts/dev/run-gui.sh"
echo "     # Or: python niceui/main.py"
echo ""
echo "  4. Run a test scrape:"
echo "     ./scripts/dev/run-scrape.sh --target yp --city 'Peoria, IL'"
echo ""
echo "See docs/QUICKSTART-dev.md for more information."
echo ""

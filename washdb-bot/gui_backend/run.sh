#!/bin/bash
# ⚠️ DEPRECATED: This script is deprecated and no longer maintained
#
# The Flask-based gui_backend has been replaced by NiceGUI.
#
# Use the following command instead:
#   cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot
#   source venv/bin/activate
#   python -m niceui.main
#
# Or use the restart_dashboard.sh script in the parent directory.

echo "=========================================="
echo "⚠️  DEPRECATED: gui_backend/run.sh"
echo "=========================================="
echo ""
echo "This Flask-based backend has been replaced by NiceGUI."
echo ""
echo "To start the active web interface, run:"
echo ""
echo "  cd /home/rivercityscrape/URL-Scrape-Bot/washdb-bot"
echo "  source venv/bin/activate"
echo "  python -m niceui.main"
echo ""
echo "Or use: ./restart_dashboard.sh"
echo ""
echo "=========================================="
exit 1

# Original script (disabled)
: <<'DISABLED'

echo "=========================================="
echo "Washdb-Bot GUI Backend Startup"
echo "=========================================="
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

# Check if venv exists
if [ ! -d "$PARENT_DIR/venv" ]; then
    echo "❌ Virtual environment not found at $PARENT_DIR/venv"
    echo "Creating virtual environment..."
    python3 -m venv "$PARENT_DIR/venv"
fi

# Activate venv
echo "🔧 Activating virtual environment..."
source "$PARENT_DIR/venv/bin/activate"

# Install requirements if needed
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "📦 Installing/updating requirements..."
    pip install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# Check .env file
if [ ! -f "$PARENT_DIR/.env" ]; then
    echo "⚠️  Warning: .env file not found at $PARENT_DIR/.env"
    echo "Using default configuration..."
fi

# Start the application
echo ""
echo "🚀 Starting Washdb-Bot GUI Backend..."
echo "   Port: 5001"
echo "   Access: http://127.0.0.1:5001"
echo ""
echo "Press Ctrl+C to stop"
echo "=========================================="
echo ""

cd "$SCRIPT_DIR"
python app.py

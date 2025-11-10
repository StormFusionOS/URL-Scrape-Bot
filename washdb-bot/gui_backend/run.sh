#!/bin/bash
# Startup script for Washdb-Bot GUI Backend

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

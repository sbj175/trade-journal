#!/bin/bash

echo "Starting OptionLedger Admin..."
echo "=============================="

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load .env if present (for ADMIN_SECRET, DATABASE_URL, etc.)
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Warning: No virtual environment found at 'venv'"
fi

# Check if required dependencies are installed
if ! python3 -c "import uvicorn" 2>/dev/null; then
    echo "Error: uvicorn not found. Please install dependencies:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Verify ADMIN_SECRET is set
if [ -z "$ADMIN_SECRET" ]; then
    echo "Error: ADMIN_SECRET not set. Add it to .env or export it:"
    echo "  echo 'ADMIN_SECRET=your-secret' >> .env"
    exit 1
fi

# Start the admin dashboard
echo "Starting Admin Dashboard on http://localhost:${ADMIN_PORT:-8001}"
echo "Press Ctrl+C to stop the server"
echo ""
python3 admin_app.py

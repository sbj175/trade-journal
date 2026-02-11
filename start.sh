#!/bin/bash

echo "Starting OptionEdge..."
echo "===================="

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

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

# Start the application
echo "Starting FastAPI server on http://localhost:8000"
echo "Press Ctrl+C to stop the server"
echo ""
python3 app.py
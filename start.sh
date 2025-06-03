#!/bin/bash
# Start Trade Journal Web Application

echo "🚀 Starting Trade Journal..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Check if dependencies are installed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Start the application
echo "Opening Trade Journal..."
echo ""
echo "Access from Windows browser at:"
echo "  → http://localhost:8000"
echo "  → http://127.0.0.1:8000"
echo ""
echo "If those don't work, find your WSL IP with: hostname -I"
echo "Then use: http://<wsl-ip>:8000"
echo ""
echo "Press Ctrl+C to stop the server"

# Don't try to open browser from WSL
# The user will open it from Windows

# Start the server
python3 app.py
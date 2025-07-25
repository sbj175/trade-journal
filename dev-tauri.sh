#!/bin/bash

echo "Starting Trade Journal development environment..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "Error: npm is not installed"
    exit 1
fi

# Install npm dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi

# Function to cleanup on exit
cleanup() {
    echo -e "\n\nShutting down..."
    # Kill all child processes
    jobs -p | xargs -r kill 2>/dev/null
    exit 0
}

# Set up trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    PYTHON_CMD="python"
elif [ -d ".venv" ]; then
    echo "Activating .venv virtual environment..."
    source .venv/bin/activate
    PYTHON_CMD="python"
else
    echo "Warning: No virtual environment found, using system Python"
    PYTHON_CMD="python3"
fi

# Verify uvicorn is available
if ! $PYTHON_CMD -c "import uvicorn" 2>/dev/null; then
    echo "Error: uvicorn not found. Please install dependencies:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Start the Python server in the background
echo "Starting Python server with $PYTHON_CMD..."
$PYTHON_CMD app.py &
PYTHON_PID=$!

# Wait for Python server to start
echo "Waiting for Python server to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8000 > /dev/null; then
        echo "Python server is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Error: Python server failed to start"
        exit 1
    fi
    sleep 1
done

# Start Tauri development server
echo "Starting Tauri development server..."
npm run dev

# Wait for all background processes
wait
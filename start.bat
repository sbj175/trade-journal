@echo off
REM Start Trade Journal Web Application

echo Starting Trade Journal...

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Check and install dependencies if needed
python -c "import fastapi" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Start the application
echo Opening Trade Journal in your browser...
echo Dashboard: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server

REM Open browser
start http://localhost:8000

REM Start the server
python app.py
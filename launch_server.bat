@echo off
cd /d "%~dp0"

echo Current directory: %CD%
echo Starting Trade Journal Python server...
echo.

REM Check if virtual environment exists and is valid
set REBUILD_VENV=0

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found.
    set REBUILD_VENV=1
    goto :SETUP_VENV
)

REM Test if the venv actually works
"venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Virtual environment is broken.
    set REBUILD_VENV=1
    goto :SETUP_VENV
)

REM Check if required packages are installed
"venv\Scripts\python.exe" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Virtual environment is missing required packages.
    set REBUILD_VENV=1
    goto :SETUP_VENV
)

goto :RUN_APP

:SETUP_VENV
echo Setting up virtual environment...
echo.

REM Remove broken venv if it exists
if exist "venv" (
    echo Removing broken virtual environment...
    rmdir /s /q "venv"
    echo.
)

REM Create virtual environment
echo Creating new virtual environment...
python -m venv venv

REM Check if venv creation was successful
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Failed to create virtual environment
    echo Please ensure Python is installed and added to PATH
    pause
    exit /b 1
)

echo Virtual environment created successfully!
echo.

REM Upgrade pip
echo Upgrading pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip
echo.

REM Install requirements if file exists
if exist "requirements.txt" (
    echo Installing required packages...
    "venv\Scripts\pip.exe" install -r requirements.txt
    echo.
    echo All packages installed successfully!
) else (
    echo WARNING: requirements.txt not found. No packages installed.
    pause
    exit /b 1
)
echo.

:RUN_APP
REM Activate virtual environment and run the app
echo Using virtual environment from: venv
"venv\Scripts\python.exe" app.py

echo.
echo Python server has stopped.
pause
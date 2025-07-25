@echo off
cd /d "%~dp0"

echo Fixing virtual environment...
echo.

REM Check if venv exists
if exist "venv\Scripts\python.exe" (
    echo Found existing virtual environment. Installing dependencies...
    echo.
    
    REM Upgrade pip first
    echo Upgrading pip...
    "venv\Scripts\python.exe" -m pip install --upgrade pip
    echo.
    
    REM Install all requirements
    if exist "requirements.txt" (
        echo Installing required packages from requirements.txt...
        "venv\Scripts\pip.exe" install -r requirements.txt
        echo.
        echo All packages installed successfully!
    ) else (
        echo ERROR: requirements.txt not found!
        pause
        exit /b 1
    )
) else (
    echo ERROR: Virtual environment not found at venv\
    echo Please run: python -m venv venv
    pause
    exit /b 1
)

echo.
echo Virtual environment fixed! You can now run launch_server.bat
pause
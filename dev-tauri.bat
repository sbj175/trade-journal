@echo off
echo Starting Trade Journal development environment...

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

:: Check if npm is installed
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: npm is not installed or not in PATH
    exit /b 1
)

:: Install npm dependencies if needed
if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
)

:: Start the Python server in a new window
echo Starting Python server...
start "Trade Journal Python Server" cmd /c "python app.py"

:: Wait for Python server to start
echo Waiting for Python server to be ready...
timeout /t 5 /nobreak >nul

:: Check if server is running
powershell -Command "try { Invoke-WebRequest -Uri 'http://localhost:8000' -UseBasicParsing -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo Error: Python server failed to start
    echo Please check if port 8000 is already in use or if there are any Python errors
    pause
    exit /b 1
)

echo Python server is ready!

:: Start Tauri development server
echo Starting Tauri development server...
call npm run dev

:: When Tauri closes, kill the Python server
echo Shutting down Python server...
taskkill /fi "WindowTitle eq Trade Journal Python Server*" /t /f >nul 2>&1

pause
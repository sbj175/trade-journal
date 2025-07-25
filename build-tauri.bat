@echo off
echo Building Trade Journal desktop application...

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

:: Check if Rust is installed
where cargo >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Rust is not installed
    echo Please install Rust from https://rustup.rs/
    exit /b 1
)

:: Install npm dependencies if needed
if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
)

:: Clean previous builds
echo Cleaning previous builds...
if exist "src-tauri\target\release\bundle" (
    rmdir /s /q "src-tauri\target\release\bundle"
)

:: Build the Tauri application
echo Building Tauri application...
call npm run build

:: Check if build was successful
if %errorlevel% equ 0 (
    echo.
    echo Build successful!
    echo.
    echo Built applications can be found in:
    echo   src-tauri\target\release\bundle\
    echo.
    
    :: List the built files
    if exist "src-tauri\target\release\bundle" (
        echo Available packages:
        for /r "src-tauri\target\release\bundle" %%f in (*.msi *.exe) do (
            echo   - %%~nxf
        )
    )
) else (
    echo.
    echo Build failed!
    exit /b 1
)

echo.
echo Note: The Windows installer (.msi) and portable executable (.exe) are ready for distribution.
pause
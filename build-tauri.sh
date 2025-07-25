#!/bin/bash

echo "Building Trade Journal desktop application..."

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

# Check if Rust is installed
if ! command -v cargo &> /dev/null; then
    echo "Error: Rust is not installed"
    echo "Please install Rust from https://rustup.rs/"
    exit 1
fi

# Install npm dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf src-tauri/target/release/bundle

# Build the Tauri application
echo "Building Tauri application..."
npm run build

# Check if build was successful
if [ $? -eq 0 ]; then
    echo -e "\n✅ Build successful!"
    echo -e "\nBuilt applications can be found in:"
    echo "  src-tauri/target/release/bundle/"
    
    # List the built files
    if [ -d "src-tauri/target/release/bundle" ]; then
        echo -e "\nAvailable packages:"
        find src-tauri/target/release/bundle -type f -name "*.deb" -o -name "*.AppImage" -o -name "*.dmg" -o -name "*.msi" -o -name "*.exe" 2>/dev/null | while read -r file; do
            echo "  - $(basename "$file")"
        done
    fi
else
    echo -e "\n❌ Build failed!"
    exit 1
fi

echo -e "\nNote: To build for Windows, copy this project to a Windows machine and run build-tauri.bat"
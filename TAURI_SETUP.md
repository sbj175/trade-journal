# Tauri Setup for Trade Journal

This document describes the Tauri desktop application setup for Trade Journal.

## Prerequisites

- Node.js and npm (already installed)
- Rust (will be installed automatically if needed)
- Python environment with FastAPI server dependencies

## Development

To run the app in development mode:

```bash
./dev-tauri.sh
```

This script will:
1. Start the FastAPI server automatically
2. Launch the Tauri development window
3. Handle graceful shutdown of the Python process

Alternatively, you can run manually:
```bash
# Terminal 1: Start FastAPI server
python app.py

# Terminal 2: Start Tauri dev server
npm run dev
```

## Building

To build the desktop application:

```bash
./build-tauri.sh
```

The built executable will be located in `src-tauri/target/release/`.

## Configuration

- Window configuration is in `src-tauri/tauri.conf.json`
- Python server management is in `src-tauri/src/main.rs`
- The app automatically starts the Python server on launch
- The Python server is gracefully stopped when the app closes

## Features

- Automatic Python server management
- Window size: 1400x900 (resizable)
- Minimum size: 1200x600
- Points to http://localhost:8000
- Graceful shutdown handling

## Customization

### Icons
Replace the placeholder files in `src-tauri/icons/` with your actual app icons:
- 32x32.png
- 128x128.png
- 128x128@2x.png (256x256)
- icon.icns (macOS)
- icon.ico (Windows)

### Window Settings
Edit `src-tauri/tauri.conf.json` to change:
- Window title
- Default size
- Minimum size
- Other window properties

## Troubleshooting

If the Python server doesn't start:
1. Ensure Python is in your PATH
2. Check that all Python dependencies are installed
3. Verify `app.py` can run independently

If Rust isn't installed, Tauri will prompt you to install it automatically.
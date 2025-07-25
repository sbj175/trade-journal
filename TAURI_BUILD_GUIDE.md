# Tauri Build Guide for Trade Journal

This guide explains how to build the Trade Journal as a standalone desktop application using Tauri.

## Prerequisites

### On Linux/Mac:
- Python 3.x with all project dependencies installed
- Node.js and npm
- Rust (will be installed automatically if missing)

### On Windows:
- Python 3.x with all project dependencies installed
- Node.js and npm
- Rust (install from https://rustup.rs/)
- Visual Studio Build Tools (for Windows builds)

## Quick Start

### Development Mode

To run the app in development mode with hot-reload:

```bash
# Linux/Mac
./dev-tauri.sh

# Windows
dev-tauri.bat
```

This will:
1. Start the Python FastAPI server
2. Launch the Tauri development window
3. Enable hot-reload for frontend changes

### Building for Production

To build the standalone desktop application:

```bash
# Linux/Mac
./build-tauri.sh

# Windows
build-tauri.bat
```

Built applications will be in `src-tauri/target/release/bundle/`:
- **Linux**: `.deb` and `.AppImage` files
- **macOS**: `.dmg` file
- **Windows**: `.msi` installer and `.exe` portable

## Cross-Platform Building

### Building Windows App on Linux

1. **On Linux**: Set up and test the Tauri configuration
2. **Copy to Windows**: Transfer the entire project folder
3. **On Windows**: 
   - Install dependencies: `npm install`
   - Run: `build-tauri.bat`

### Important Windows Notes

- Ensure Python is in your PATH
- Install Visual Studio Build Tools for Rust compilation
- The `.msi` installer is recommended for distribution

## Customization

### App Icons

Replace placeholder icons in `src-tauri/icons/`:
- `32x32.png` - Small icon
- `128x128.png` - Medium icon
- `128x128@2x.png` - High DPI (256x256)
- `icon.icns` - macOS icon
- `icon.ico` - Windows icon

### Window Settings

Edit `src-tauri/tauri.conf.json` to modify:
- Window size and position
- App name and version
- Build settings

### Python Server Management

The Rust backend (`src-tauri/src/main.rs`) handles:
- Starting Python server on app launch
- Graceful shutdown on app close
- Server health monitoring

## Troubleshooting

### Python Server Won't Start
- Check Python is installed: `python --version` or `python3 --version`
- Verify all dependencies: `pip install -r requirements.txt`
- Ensure port 8000 is free
- Check `app.py` runs standalone

### Build Fails
- Update Rust: `rustup update`
- Clear build cache: `rm -rf src-tauri/target` (Linux/Mac) or `rmdir /s src-tauri\target` (Windows)
- Check for Rust compilation errors in the output

### App Won't Launch
- Check if Python server starts manually
- Verify localhost:8000 is accessible
- Look for errors in console output

## Development Tips

1. **Manual Testing**: You can run the Python server and Tauri separately:
   ```bash
   # Terminal 1
   python app.py
   
   # Terminal 2
   npm run dev
   ```

2. **Logs**: Check console output for both Python and Rust errors

3. **Database Path**: The app uses the same `trade_journal.db` location as the web version

4. **Credentials**: Encrypted credentials work the same in the desktop app

## Distribution

### For End Users

Provide:
- **Windows**: The `.msi` installer (easiest)
- **macOS**: The `.dmg` file
- **Linux**: The `.AppImage` (most compatible) or `.deb` (for Debian/Ubuntu)

### Important Notes

1. The app bundles its own Python server - users don't need Python installed
2. All data stays local on the user's machine
3. Internet connection required only for Tastytrade API access
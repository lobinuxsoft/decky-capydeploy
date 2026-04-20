#!/bin/bash
# Build script for CapyDeploy Decky Plugin

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Project directories — detect monorepo (submodule) or standalone.
# In standalone mode the plugin output cannot live under ./dist because
# rollup owns that path and wipes it on every build (shx rm -rf dist).
if [ -f "../../../VERSION" ]; then
    ROOT_DIR="$(cd ../../.. && pwd)"
    DIST_DIR="$ROOT_DIR/dist"
else
    ROOT_DIR="$SCRIPT_DIR"
    DIST_DIR="$ROOT_DIR/build"
fi

PLUGIN_NAME="CapyDeploy"
VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*: "\([^"]*\)".*/\1/')
OUTPUT_DIR="$DIST_DIR/decky"
BUILD_DIR="$OUTPUT_DIR/$PLUGIN_NAME"

echo "=== Building $PLUGIN_NAME v$VERSION ==="

# Detect package manager (bun is preferred — matches the monorepo's build_all.sh)
detect_pm() {
    if command -v bun &> /dev/null; then
        echo "bun"
    elif command -v pnpm &> /dev/null; then
        echo "pnpm"
    elif command -v yarn &> /dev/null; then
        echo "yarn"
    elif command -v npm &> /dev/null; then
        echo "npm"
    else
        echo ""
    fi
}

PM=$(detect_pm)

if [ -z "$PM" ]; then
    echo "ERROR: No package manager found (bun, npm, pnpm, or yarn)"
    echo ""
    echo "Install one of the following:"
    echo "  Recommended: curl -fsSL https://bun.sh/install | bash"
    echo "  Alternative: curl -fsSL https://fnm.vercel.app/install | bash  # then: fnm install --lts"
    exit 1
fi

echo "Using package manager: $PM"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    $PM install
fi

# Build frontend — the package.json build script runs `shx rm -rf dist`,
# so any plugin output under $OUTPUT_DIR must be created *after* this step.
echo "Building frontend..."
$PM run build

# Clean previous plugin output and prepare build directory
rm -rf "$OUTPUT_DIR"
mkdir -p "$BUILD_DIR"

# Install Python dependencies into py_modules (bundled with the plugin)
echo "Installing Python dependencies..."
rm -rf py_modules
mkdir -p py_modules
python3 -m pip install --target py_modules -r requirements.txt --no-cache-dir

# Copy files to build directory
echo "Copying files..."
cp plugin.json "$BUILD_DIR/"
cp package.json "$BUILD_DIR/"
for pyfile in main.py steam_utils.py mdns_service.py pairing.py upload.py artwork.py ws_server.py telemetry.py console_log.py game_log.py tcp_server.py; do
    cp "$pyfile" "$BUILD_DIR/"
done

# Copy handler modules
if [ -d "handlers" ]; then
    cp -r handlers "$BUILD_DIR/"
fi

# Copy wrapper scripts
if [ -d "bin" ]; then
    cp -r bin "$BUILD_DIR/"
    chmod +x "$BUILD_DIR/bin/"*.sh
fi
cp requirements.txt "$BUILD_DIR/"
cp -r py_modules "$BUILD_DIR/"

# Copy dist (frontend bundle)
if [ -d "dist" ]; then
    cp -r dist "$BUILD_DIR/"
else
    echo "ERROR: dist/ not found. Frontend build failed?"
    exit 1
fi

# Copy assets
if [ -d "assets" ]; then
    cp -r assets "$BUILD_DIR/"
fi

# Copy LICENSE (local first, then monorepo root)
if [ -f "LICENSE" ]; then
    cp "LICENSE" "$BUILD_DIR/"
elif [ -f "../../../LICENSE" ]; then
    cp "../../../LICENSE" "$BUILD_DIR/"
fi

# Create ZIP
echo "Creating ZIP..."
cd "$OUTPUT_DIR"
zip -r "${PLUGIN_NAME}-v${VERSION}.zip" "$PLUGIN_NAME"

echo ""
echo "=== Build complete! ==="
echo "Output: $OUTPUT_DIR/${PLUGIN_NAME}-v${VERSION}.zip"
echo ""
echo "Installation options:"
echo "  1. Manual: Copy $BUILD_DIR to ~/homebrew/plugins/ on Steam Deck"
echo "  2. URL: Host the ZIP and use Decky Settings > Install from URL"
echo "  3. Dev: Use decky-cli to deploy during development"

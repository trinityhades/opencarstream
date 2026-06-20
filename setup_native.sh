#!/bin/bash
set -e

# Colors for nice output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0;3m' # No Color
NC_BOLD='\033[1m'
CLEAR='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}=== OpenCarStream Native Apple Silicon Setup ===${CLEAR}"

# 1. System check
OS="$(uname -s)"
ARCH="$(uname -m)"
if [ "$OS" != "Darwin" ] || [ "$ARCH" != "arm64" ]; then
    echo -e "${RED}[WARNING] This script is optimized for macOS on Apple Silicon (ARM64).${CLEAR}"
    echo -e "Current OS: $OS, Architecture: $ARCH"
    read -p "Do you want to continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}[OK] Verified macOS Apple Silicon (ARM64) system.${CLEAR}"
fi

# 2. Check Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${RED}[ERROR] Homebrew is not installed.${CLEAR}"
    echo -e "Homebrew is required to install ffmpeg and node."
    echo -e "Please install it from https://brew.sh and re-run this script."
    exit 1
fi
echo -e "${GREEN}[OK] Homebrew is installed.${CLEAR}"

# 3. Install ffmpeg and node via Homebrew
echo -e "${BLUE}Checking system dependencies...${CLEAR}"
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
else
    echo -e "${GREEN}[OK] ffmpeg is already installed.${CLEAR}"
fi

# Verify ffmpeg supports videotoolbox
if ffmpeg -encoders 2>&1 | grep -q "h264_videotoolbox"; then
    echo -e "${GREEN}[OK] Verified ffmpeg supports hardware-accelerated 'h264_videotoolbox'.${CLEAR}"
else
    echo -e "${RED}[WARNING] installed ffmpeg does not seem to support 'h264_videotoolbox'.${CLEAR}"
    echo -e "Hardware acceleration may not function correctly."
fi

if ! command -v node &> /dev/null; then
    echo "Installing node..."
    brew install node
else
    echo -e "${GREEN}[OK] node is already installed.${CLEAR}"
fi

# 3.5. Install ogv-dist
echo -e "${BLUE}Setting up ogv-dist...${CLEAR}"
if ! command -v npm &> /dev/null; then
    echo -e "${RED}[ERROR] npm is not found. Node.js installation may be broken.${CLEAR}"
    exit 1
fi
echo "Installing ogv package locally..."
npm install --prefix "$SCRIPT_DIR" ogv --no-save
echo "Copying distribution files to ogv-dist..."
rm -rf "$SCRIPT_DIR/ogv-dist"
cp -R "$SCRIPT_DIR/node_modules/ogv/dist" "$SCRIPT_DIR/ogv-dist"
rm -rf "$SCRIPT_DIR/node_modules" "$SCRIPT_DIR/package-lock.json"
echo -e "${GREEN}[OK] ogv-dist is set up successfully.${CLEAR}"

# 4. Set up python virtual environment & dependencies
echo -e "${BLUE}Setting up Python virtual environment...${CLEAR}"
if command -v uv &> /dev/null; then
    echo "Found uv. Setting up virtual environment with uv..."
    uv venv --allow-existing "$SCRIPT_DIR/.venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "Installing dependencies with uv..."
    uv pip install --upgrade yt-dlp requests browser-cookie3
else
    echo "uv not found. Falling back to python3 venv..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "Upgrading pip..."
    pip install --upgrade pip
    echo "Installing dependencies..."
    pip install --upgrade yt-dlp requests browser-cookie3
fi

# 5. Create native directories
echo -e "${BLUE}Creating default directories...${CLEAR}"
mkdir -p "$SCRIPT_DIR/config"
mkdir -p "$SCRIPT_DIR/local-media"
mkdir -p "$SCRIPT_DIR/iptv_lists"

echo -e "\n${GREEN}=== Setup Completed Successfully! ===${CLEAR}"
echo -e "To start the server natively, run:"
echo -e "  ${NC_BOLD}./run_native.sh${CLEAR}"
echo -e "To manage OpenCarStream as a background service, run:"
echo -e "  ${NC_BOLD}./manage_service.sh install${CLEAR}"

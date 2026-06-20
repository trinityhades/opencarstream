#!/bin/bash

# Ensure Homebrew and standard paths are in PATH, especially for launchd environment
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Determine directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"


# Verify virtual environment
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "Error: Virtual environment not found at $SCRIPT_DIR/.venv"
    echo "Please run ./setup_native.sh first."
    exit 1
fi

# Load optional .env file if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Loading environment variables from $SCRIPT_DIR/.env"
    # Export variables, ignoring comments and blank lines
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Set native default environment variables pointing inside the project workspace
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-33333}"

export LOCAL_MEDIA_DIR="${LOCAL_MEDIA_DIR:-$SCRIPT_DIR/local-media}"
export IPTV_LISTS_DIR="${IPTV_LISTS_DIR:-$SCRIPT_DIR/iptv_lists}"

export SUBSCRIPTIONS_FILE="${SUBSCRIPTIONS_FILE:-$SCRIPT_DIR/config/subscriptions.json}"
export ACE_STREAMS_FILE="${ACE_STREAMS_FILE:-$SCRIPT_DIR/config/ace_streams.json}"
export FAVORITES_FILE="${FAVORITES_FILE:-$SCRIPT_DIR/config/favorites.json}"
export PROGRESS_FILE="${PROGRESS_FILE:-$SCRIPT_DIR/config/watch_progress.json}"
export HOME_FEED_CACHE_FILE="${HOME_FEED_CACHE_FILE:-$SCRIPT_DIR/config/home_feed_cache.json}"

# Ensure Hardware Acceleration environment variables default to auto-detecting VideoToolbox
export FFMPEG_HWACCEL="${FFMPEG_HWACCEL:-auto}"
export FFMPEG_H264_ENCODER="${FFMPEG_H264_ENCODER:-auto}"

# Display active path configuration for debugging
echo "========================================="
echo "Starting OpenCarStream Natively"
echo "URL: http://$HOST:$PORT"
echo "Local Media: $LOCAL_MEDIA_DIR"
echo "IPTV Lists:  $IPTV_LISTS_DIR"
echo "Configs:     $SCRIPT_DIR/config"
echo "========================================="

# Execute server
exec python3 -u "$SCRIPT_DIR/server.py"

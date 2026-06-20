# OpenCarStream — Native macOS Apple Silicon (ARM64) Version

This guide covers setting up and running OpenCarStream natively on macOS (Apple Silicon). Running natively allows the application to directly interface with Apple's **VideoToolbox** framework, enabling hardware-accelerated H.264 video encoding and decoding. 

Using native hardware encoding drastically reduces CPU load, runs cool and quiet on Apple Silicon Macs, and improves streaming framerate and stability.

---

## Prerequisites

1. **Apple Silicon Mac** (M1, M2, M3, M4, etc.) running macOS.
2. **Homebrew** installed. If you do not have it, install it from [brew.sh](https://brew.sh).
3. **Python 3.12+** (Python 3.13 is fully supported).
4. (Optional but recommended) **`uv`** for lightning-fast virtual environments. Install it via: `brew install uv`.

---

## 1. Setup

Run the native setup script from the root of the repository:

```bash
chmod +x setup_native.sh
./setup_native.sh
```

This script will:
- Check that you are running on macOS Apple Silicon.
- Check and install **`ffmpeg`** and **`node`** via Homebrew (needed by `yt-dlp` for video signatures).
- Set up a python virtual environment (under `.venv/`) and install/upgrade `yt-dlp`.
- Create local folders for configurations (`config/`), media (`local-media/`), and IPTV lists (`iptv_lists/`).

---

## 2. Running OpenCarStream

### Option A: Interactive Mode (Terminal)

To run the server in your active terminal:

```bash
chmod +x run_native.sh
./run_native.sh
```

By default, the server will start on **`http://localhost:33333`**.
Press `Ctrl+C` in your terminal to stop it.

All environment variable configuration defaults to mapping paths directly inside your workspace:
- **Local Media Folder**: `./local-media`
- **IPTV Lists Folder**: `./iptv_lists`
- **Config Folder**: `./config`

If you want to override these, you can create a `.env` file in the root directory (similar to `docker-compose.yml` environment block) or set them directly in your shell environment:

```bash
PORT=8080 LOCAL_MEDIA_DIR=/Users/name/Movies ./run_native.sh
```

### Option B: Background Service (Launchd)

OpenCarStream can run silently in the background as a macOS `launchd` agent, starting automatically whenever you log in.

A helper script is provided to manage the background service:

```bash
chmod +x manage_service.sh

# Install and start the background service
./manage_service.sh install

# Check service status (shows PID and resource utilization)
./manage_service.sh status

# Follow logs in real-time
./manage_service.sh logs

# Restart the service
./manage_service.sh restart

# Stop the service
./manage_service.sh stop

# Uninstall the service
./manage_service.sh uninstall
```

Logs are written directly to `./server.log` inside the repository directory.

---

## 3. Subscriptions Feed

You can sync your YouTube subscriptions to browse them in the car browser:

```bash
# Fetches your subscriptions from Chrome cookies and saves to config/subscriptions.json
uv run sync_subscriptions.py --browser chrome --output config/subscriptions.json
```

If you are using the background launchd service, restart it to load the subscriptions:

```bash
./manage_service.sh restart
```

---

## 4. Verifying Hardware Acceleration

To confirm that your server is successfully using hardware-accelerated transcoding:

1. Open your browser and navigate to `http://localhost:33333`
2. Start streaming any video.
3. Check the logs (`./manage_service.sh logs` if running in the background, or your terminal window).
4. Look for the following lines:
   - `[INFO] Selected encoder: h264_videotoolbox`
   - `[INFO] HW accel args: ['-hwaccel', 'videotoolbox']`

You will also notice that Python/FFmpeg CPU usage in Activity Monitor remains extremely low (typically under 15% even during high-resolution streams) due to the encoding task being offloaded to the Apple Silicon hardware media engines.

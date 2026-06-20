# ── Stage 1: build yt-dlp binary ─────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE} AS base

# System deps: ffmpeg + curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp from PyPI so the image works on both arm64 and amd64.
RUN python3 -m pip install --no-cache-dir --upgrade yt-dlp

# ── Stage 2: app ──────────────────────────────────────────────────────────────
FROM base AS app

WORKDIR /app

COPY server.py .
COPY ogv-dist ./ogv-dist

# Non-root user for security
RUN useradd -m -u 1000 streamer
RUN chown -R streamer:streamer /app \
    && chmod 755 /app \
    && chmod 644 /app/server.py
USER streamer

# ── Runtime config (all overridable via -e / docker-compose env) ──────────────
ENV HOST=0.0.0.0 \
    PORT=8080 \
    MJPEG_FPS=12 \
    FFMPEG_QUALITY=26 \
    STREAM_WIDTH=1920 \
    STREAM_HEIGHT=1080 \
    MP4_WIDTH=1920 \
    MP4_HEIGHT=1080 \
    MP4_VIDEO_BITRATE=2400k \
    MP4_AUDIO_BITRATE=128k \
    FFMPEG_HWACCEL=auto \
    FFMPEG_H264_ENCODER=auto \
    OGV_WIDTH=640 \
    OGV_HEIGHT=360 \
    OGV_FPS=24 \
    OGV_VIDEO_QUALITY=5 \
    OGV_AUDIO_BITRATE=96k \
    OGV_DEFAULT_PROFILE=auto \
    MAX_STREAMS=3

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/health || exit 1

CMD ["python3", "-u", "server.py"]

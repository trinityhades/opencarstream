#!/usr/bin/env python3
"""
OpenCarStream MJPEG Streamer
Usage:
  http://yourserver/stream?url=https://youtube.com/watch?v=xxx
  http://yourserver/             → status page
  http://yourserver/health       → health check
"""

import re
import subprocess
import threading
import time
import sys
import os
import signal
import json
import logging
import select
import secrets
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from urllib.request import Request, urlopen
from socketserver import ThreadingMixIn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("streamer")


def _parse_lang_map(raw: str) -> dict[str, str]:
    """
    Parse env mapping in format: "es:ES,en:US" or "en:8.8.8.8".
    Keys are normalized to lowercase language codes.
    """
    result: dict[str, str] = {}
    for part in (raw or "").split(","):
        item = part.strip()
        if not item or ":" not in item:
            continue
        lang, value = item.split(":", 1)
        lang = lang.strip().lower()
        value = value.strip()
        if lang and value:
            result[lang] = value
    return result


# ── Config (override via env vars) ────────────────────────────────────────────
HOST          = os.environ.get("HOST", "0.0.0.0")
PORT          = int(os.environ.get("PORT", "8080"))
MJPEG_FPS     = int(os.environ.get("MJPEG_FPS", "24"))
FFMPEG_QUALITY= int(os.environ.get("FFMPEG_QUALITY", "3"))   # 1=best, 31=worst
STREAM_WIDTH  = int(os.environ.get("STREAM_WIDTH", "1920"))
STREAM_HEIGHT = int(os.environ.get("STREAM_HEIGHT", "1080"))
MP4_WIDTH     = int(os.environ.get("MP4_WIDTH", "2560"))
MP4_HEIGHT    = int(os.environ.get("MP4_HEIGHT", "1440"))
MP4_VIDEO_BITRATE = os.environ.get("MP4_VIDEO_BITRATE", "2400k")
MP4_AUDIO_BITRATE = os.environ.get("MP4_AUDIO_BITRATE", "128k")
FFMPEG_HWACCEL = os.environ.get("FFMPEG_HWACCEL", "auto").strip().lower()
FFMPEG_H264_ENCODER = os.environ.get("FFMPEG_H264_ENCODER", "auto").strip().lower()
OGV_WIDTH     = int(os.environ.get("OGV_WIDTH", "2560"))
OGV_HEIGHT    = int(os.environ.get("OGV_HEIGHT", "1440"))
OGV_FPS       = int(os.environ.get("OGV_FPS", "24"))
OGV_VIDEO_QUALITY = int(os.environ.get("OGV_VIDEO_QUALITY", "5"))
OGV_AUDIO_BITRATE = os.environ.get("OGV_AUDIO_BITRATE", "96k")
OGV_DEFAULT_PROFILE = os.environ.get("OGV_DEFAULT_PROFILE", "auto").strip().lower()
MAX_STREAMS   = int(os.environ.get("MAX_STREAMS", "3"))       # concurrent stream slots
AUDIO_DELAY_MS= int(os.environ.get("AUDIO_DELAY_MS", "0"))   # ms to delay video start after audio, to keep streams in sync
LOCAL_MEDIA_VIDEO_DELAY_MS = int(
    os.environ.get("LOCAL_MEDIA_VIDEO_DELAY_MS", "1500")
)
SUBSCRIPTIONS_FILE  = os.environ.get("SUBSCRIPTIONS_FILE", "/config/subscriptions.json")
ACE_STREAMS_FILE    = os.environ.get("ACE_STREAMS_FILE", "/config/ace_streams.json")
FAVORITES_FILE      = os.environ.get("FAVORITES_FILE", "/config/favorites.json")
PROGRESS_FILE       = os.environ.get("PROGRESS_FILE", "/config/watch_progress.json")
HOME_FEED_CACHE_FILE = os.environ.get("HOME_FEED_CACHE_FILE", "/config/home_feed_cache.json")
# How many recent videos to fetch per channel for the Home feed
HOME_FEED_PER_CHANNEL = int(os.environ.get("HOME_FEED_PER_CHANNEL", "7"))
# Max concurrent yt-dlp workers when building the Home feed
HOME_FEED_WORKERS     = int(os.environ.get("HOME_FEED_WORKERS", "8"))
# Cache the Home feed for this many seconds (0 = disabled)
HOME_FEED_CACHE_SECS  = int(os.environ.get("HOME_FEED_CACHE_SECS", str(30 * 60)))
# Only show videos uploaded within this many days (0 = no filter; 0 recommended since yt-dlp
# often returns NA for upload_date in flat-playlist mode)
HOME_FEED_MAX_AGE_DAYS = int(os.environ.get("HOME_FEED_MAX_AGE_DAYS", "0"))
# Comma-separated list of Pluto TV language codes to load, e.g. "es,en"
PLUTO_LANGS         = [l.strip() for l in os.environ.get("PLUTO_LANGS", "es,en").split(",") if l.strip()]
PLUTO_REFRESH_SECS  = int(os.environ.get("PLUTO_REFRESH_SECS", str(60 * 60)))  # 1 h
PLUTO_APP_VERSION   = os.environ.get("PLUTO_APP_VERSION", "8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6")
# Maps UI language -> Pluto marketing region (country code).
# Default keeps Spanish in ES and routes English to US lineup.
PLUTO_REGION_MAP    = _parse_lang_map(os.environ.get("PLUTO_REGION_MAP", "es:ES,en:US"))
# Optional language -> X-Forwarded-For IP used for boot/channels requests.
# This helps force region-specific lineups when server IP geo differs.
PLUTO_XFF_MAP       = _parse_lang_map(os.environ.get("PLUTO_XFF_MAP", "en:8.8.8.8"))
LOCAL_MEDIA_DIR     = os.environ.get("LOCAL_MEDIA_DIR", "/media/videos")
IPTV_LISTS_DIR      = os.environ.get("IPTV_LISTS_DIR", "/iptv_lists")
MAX_STREAM_AGE_S    = int(os.environ.get("MAX_STREAM_AGE_S", str(5 * 3600)))  # stop streams older than this
# BCP-47 language tag for YouTube titles/descriptions, e.g. "es", "fr", "de".
# Leave empty ("") to use YouTube's default (usually matches the video's original language).
YT_LANG             = os.environ.get("YT_LANG", "")

# Authentication Password (set empty to disable auth, defaults to "admin" if not configured)
ADMIN_PASSWORD      = os.environ.get("ADMIN_PASSWORD", "admin").strip()
active_sessions     = set()
sessions_lock       = threading.Lock()
LOCAL_MEDIA_EXTS    = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".ts",
}
IPTV_LIST_EXTS      = {".m3u", ".m3u8"}
PROJECT_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OGV_DIST_DIR        = os.environ.get("OGV_DIST_DIR", os.path.join(PROJECT_ROOT, "ogv-dist"))
QUALITY_LEVELS      = {144, 240, 360, 480, 720, 1080, 1440, 2160}
TRANSCODE_PROFILES  = {
    "360":  {"width": 640,  "height": 360,  "fps": 24, "ogv_q": 5, "audio": "96k",  "mp4_bitrate": "1200k"},
    "480":  {"width": 854,  "height": 480,  "fps": 24, "ogv_q": 5, "audio": "112k", "mp4_bitrate": "1600k"},
    "720":  {"width": 1280, "height": 720,  "fps": 24, "ogv_q": 6, "audio": "128k", "mp4_bitrate": "2800k"},
    "1080": {"width": 1920, "height": 1080, "fps": 24, "ogv_q": 6, "audio": "160k", "mp4_bitrate": "5000k"},
    "1440": {"width": 2560, "height": 1440, "fps": 24, "ogv_q": 7, "audio": "192k", "mp4_bitrate": "9000k"},
    "2160": {"width": 3840, "height": 2160, "fps": 24, "ogv_q": 7, "audio": "192k", "mp4_bitrate": "16000k"},
}


_ffmpeg_cap_cache: dict[str, object] = {}
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

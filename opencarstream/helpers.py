import os
import re
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import *
from .config import _ffmpeg_cap_cache
from .state import Stream

def _probe_fps(url: str) -> float | None:
    """Ask ffprobe for the video stream's frame rate. Returns None on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url,
            ],
            capture_output=True, text=True, timeout=10,
        )
        val = r.stdout.strip().splitlines()[0] if r.returncode == 0 else ""
        if not val:
            return None
        if "/" in val:
            num, den = val.split("/", 1)
            den = float(den)
            return round(float(num) / den, 3) if den else None
        return float(val)
    except Exception:
        return None


def _ffmpeg_lines(flag: str) -> list[str]:
    cached = _ffmpeg_cap_cache.get(flag)
    if isinstance(cached, list):
        return cached
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", flag],
            capture_output=True, text=True, timeout=8,
        )
        lines = (r.stdout + "\n" + r.stderr).splitlines()
    except Exception:
        lines = []
    _ffmpeg_cap_cache[flag] = lines
    return lines


def _ffmpeg_encoder_available(name: str) -> bool:
    return any(name in line for line in _ffmpeg_lines("-encoders"))


def _ffmpeg_hwaccel_available(name: str) -> bool:
    return any(line.strip() == name for line in _ffmpeg_lines("-hwaccels"))


def _select_h264_encoder() -> str:
    requested = FFMPEG_H264_ENCODER
    if requested and requested != "auto":
        return requested if _ffmpeg_encoder_available(requested) else "libx264"
    # VideoToolbox is the Apple Silicon path when running natively on macOS.
    # Docker Desktop Linux containers normally cannot see it, so this safely
    # falls back to libx264 there.
    if _ffmpeg_encoder_available("h264_videotoolbox"):
        return "h264_videotoolbox"
    return "libx264"


def _ffmpeg_hwaccel_args() -> list[str]:
    requested = FFMPEG_HWACCEL
    if requested in ("", "none", "off", "0", "false"):
        return []
    if requested == "auto":
        if _ffmpeg_hwaccel_available("videotoolbox"):
            return ["-hwaccel", "videotoolbox"]
        return []
    if _ffmpeg_hwaccel_available(requested):
        return ["-hwaccel", requested]
    return []


def _h264_video_args(width: int, height: int, bitrate: str) -> list[str]:
    encoder = _select_h264_encoder()
    common = [
        "-vf", _scale_pad_filter(width, height),
        "-pix_fmt", "yuv420p",
        "-b:v", bitrate,
        "-maxrate", bitrate,
    ]
    if encoder == "h264_videotoolbox":
        return [
            *common,
            "-c:v", "h264_videotoolbox",
            "-profile:v", "main",
            "-g", "48",
        ]
    return [
        *common,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", "main",
        "-bufsize", "3600k",
        "-g", "48",
        "-keyint_min", "48",
    ]


def _profile_settings(profile: str | None, source_quality: int | None = None) -> dict:
    raw = (profile or OGV_DEFAULT_PROFILE or "auto").strip().lower()
    if raw in ("", "default"):
        return {
            "name": "default",
            "width": OGV_WIDTH,
            "height": OGV_HEIGHT,
            "fps": OGV_FPS,
            "ogv_q": OGV_VIDEO_QUALITY,
            "audio": OGV_AUDIO_BITRATE,
            "mp4_bitrate": MP4_VIDEO_BITRATE,
        }
    if raw == "auto":
        q = source_quality or 720
        if q >= 2160:
            raw = "2160"
        elif q >= 1440:
            raw = "1440"
        elif q >= 1080:
            raw = "1080"
        elif q >= 720:
            raw = "720"
        elif q >= 480:
            raw = "480"
        else:
            raw = "360"
    settings = dict(TRANSCODE_PROFILES.get(raw) or TRANSCODE_PROFILES["720"])
    settings["name"] = raw
    return settings


def _scale_pad_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )


def _yt_lang_args() -> list[str]:
    """Extra yt-dlp flags to request content in the configured YT_LANG."""
    if not YT_LANG:
        return []
    # Pass lang to both extractors: youtubetab (channel/playlist pages) and
    # youtube (individual video pages / search). This sets hl= in InnerTube
    # requests so YouTube returns translated titles when available.
    return [
        "--extractor-args", f"youtube:lang={YT_LANG}",
        "--extractor-args", f"youtubetab:lang={YT_LANG}",
        "--add-header", f"Accept-Language:{YT_LANG}-{YT_LANG.upper()},{YT_LANG};q=0.9,*;q=0.5",
    ]


def fetch_title(stream: Stream):
    if _is_direct_stream(stream.url):
        return  # no yt-dlp for direct streams; title stays empty
    try:
        r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--print", "title", stream.url],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            with stream.lock:
                stream.title = r.stdout.strip()
    except Exception:
        pass


def _fetch_duration_s(url: str) -> int:
    """Return video duration in seconds via yt-dlp, or 0 if live/unknown."""
    if _is_direct_stream(url):
        return 0
    try:
        r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
             "--print", "%(duration)s\t%(is_live)s", "--quiet", url],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return 0
        parts = r.stdout.strip().split("\t")
        is_live = (parts[1].strip().lower() if len(parts) > 1 else "") in ("true", "1")
        if is_live:
            return 0
        try:
            return max(0, int(float(parts[0].strip())))
        except (ValueError, IndexError):
            return 0
    except Exception:
        return 0


def _is_direct_hls(url: str) -> bool:
    """True for raw HLS manifest URLs that ffmpeg can consume directly."""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


def _is_local_media_url(url: str) -> bool:
    """True for local file URLs served by the Local Media tab."""
    return url.startswith("file://")


def _is_acestream(url: str) -> bool:
    """True for acestream-http-proxy URLs (MPEG-TS over HTTP)."""
    return "/ace/getstream" in url or "/ace/manifest.m3u8" in url


def _is_pluto_stream(url: str) -> bool:
    """True for Pluto TV stitched stream URLs."""
    from urllib.parse import urlparse
    return "pluto.tv" in (urlparse(url).netloc or "").lower()


def _is_rtp_stream(url: str) -> bool:
    """True for RTP/UDP multicast streams that ffmpeg can consume directly."""
    return url.startswith(("rtp://", "udp://", "rtsp://", "srt://"))


_PRIVATE_IP_RE = re.compile(
    r"^https?://"
    r"(?:127\.\d+\.\d+\.\d+|"
    r"10\.\d+\.\d+\.\d+|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|"
    r"192\.168\.\d+\.\d+|"
    r"localhost)"
    r"(?::\d+)?/"
)

def _is_local_network_stream(url: str) -> bool:
    """True for HTTP streams served from private/local IPs (e.g. IPTV middleware)."""
    return bool(_PRIVATE_IP_RE.match(url))


def _is_direct_stream(url: str) -> bool:
    """True for any URL ffmpeg can consume directly without yt-dlp."""
    return (_is_direct_hls(url) or _is_acestream(url) or _is_local_media_url(url)
            or _is_rtp_stream(url) or _is_local_network_stream(url))


def _is_youtube_url(url: str) -> bool:
    """True for YouTube watch/channel URLs."""
    return "youtube.com" in url or "youtu.be" in url


def _is_twitch_url(url: str) -> bool:
    """True for Twitch stream URLs."""
    return "twitch.tv" in url


def _default_sync_ms_for_url(url: str) -> int:
    """Return the default sync delay (ms) based on stream source type."""
    if _is_youtube_url(url) or _is_twitch_url(url):
        return 500
    if _is_pluto_stream(url):
        return 500
    if _is_direct_hls(url) or _is_local_network_stream(url):
        # IPTV / HLS streams
        return 1000
    return AUDIO_DELAY_MS


def _ffmpeg_input_target(url: str) -> str:
    """Return ffmpeg-safe input target from stream url."""
    if _is_local_media_url(url):
        parsed = urlparse(url)
        return unquote(parsed.path or "")
    return url


def _has_supported_media_ext(path: str) -> bool:
    """True when path or its symlink target has an allowed video extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in LOCAL_MEDIA_EXTS:
        return True
    if os.path.islink(path):
        target_ext = os.path.splitext(os.path.realpath(path))[1].lower()
        return target_ext in LOCAL_MEDIA_EXTS
    return False


def _has_supported_iptv_list_ext(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in IPTV_LIST_EXTS


def _parse_extinf_name(line: str) -> str:
    # #EXTINF:-1 ... ,Channel Name
    # Prefer the explicit title after the first comma.
    _, _, tail = line.partition(",")
    title = (tail or "").strip()
    if title:
        return title

    # Fallback to tvg-name metadata if present.
    marker = 'tvg-name="'
    pos = line.find(marker)
    if pos != -1:
        rest = line[pos + len(marker):]
        value, _, _ = rest.partition('"')
        return value.strip()
    return ""


def _parse_extinf_logo(line: str) -> str:
    # Look for tvg-logo="..."
    marker = 'tvg-logo="'
    pos = line.find(marker)
    if pos != -1:
        rest = line[pos + len(marker):]
        value, _, _ = rest.partition('"')
        return value.strip()

    # Fallback to logo="..."
    marker2 = 'logo="'
    pos2 = line.find(marker2)
    if pos2 != -1:
        rest = line[pos2 + len(marker2):]
        value, _, _ = rest.partition('"')
        return value.strip()

    return ""


def _parse_iptv_m3u(content: str) -> list[dict[str, str]]:
    streams: list[dict[str, str]] = []
    pending_name = ""
    pending_logo = ""

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending_name = _parse_extinf_name(line)
            pending_logo = _parse_extinf_logo(line)
            continue
        if line.startswith("#"):
            continue

        url = line
        name = pending_name or f"Stream {len(streams) + 1}"
        stream = {"name": name, "url": url}
        if pending_logo:
            stream["logo"] = pending_logo
        streams.append(stream)
        pending_name = ""
        pending_logo = ""

    return streams


__all__ = [name for name in globals() if not name.startswith("__")]


_ace_streams_lock = threading.Lock()

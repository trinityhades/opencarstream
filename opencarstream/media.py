import os
import select
import subprocess
import threading
import time
from urllib.parse import quote

from .config import *
from .helpers import *
from .state import Stream

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _probe_local_codecs(abs_path: str) -> tuple[str, str]:
    """Return (video_codec, audio_codec) for a local file using ffprobe. Empty string if not found."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                abs_path,
            ],
            capture_output=True, text=True, timeout=5,
        )
        vcodec = r.stdout.strip().lower()
        r2 = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0", "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                abs_path,
            ],
            capture_output=True, text=True, timeout=5,
        )
        acodec = r2.stdout.strip().lower()
        return vcodec, acodec
    except Exception:
        return "", ""


def _direct_input_args(url: str, extra_headers: dict[str, str] | None = None) -> list[str]:
    """ffmpeg input flags for a direct stream URL."""
    from urllib.parse import urlparse, parse_qs
    if _is_local_media_url(url) or (os.path.isabs(url) and _has_supported_media_ext(url)):
        return ["-re"]
    if _is_acestream(url):
        return ["-timeout", "10000000"]
    if _is_rtp_stream(url):
        return ["-rtbufsize", "100M"]
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    headers = ""
    args: list[str] = []
    if extra_headers:
        ua = extra_headers.get("User-Agent") or extra_headers.get("user-agent") or _BROWSER_UA
        args = ["-user_agent", ua]
        for key, value in extra_headers.items():
            if key.lower() == "user-agent" or value is None:
                continue
            headers += f"{key}: {value}\r\n"
    elif "pluto.tv" in host:
        country = (parse_qs(parsed.query).get("country", [""])[0] or "").upper()
        xff = ""
        if country:
            for lang_code, region_code in PLUTO_REGION_MAP.items():
                if region_code.upper() == country:
                    xff = PLUTO_XFF_MAP.get(lang_code, "")
                    if xff:
                        break
        headers = (
            "Referer: https://pluto.tv/\r\n"
            "Origin: https://pluto.tv\r\n"
            "Accept-Language: en-US,en;q=0.9\r\n"
        )
        if xff:
            headers += f"X-Forwarded-For: {xff}\r\n"
        args = ["-user_agent", _BROWSER_UA]
    else:
        args = ["-user_agent", _BROWSER_UA]
    if headers:
        args += ["-headers", headers]
    # Don't use -re for Pluto live HLS: let ffmpeg buffer ahead for smoother output.
    if "pluto.tv" not in host:
        args.append("-re")
    return args


def _resolve_mp4_url(url: str, quality: int | None, profile: str | None = None) -> tuple[str, str]:
    """Resolve a direct playable URL for MP4/native mode. Returns (direct_url, error)."""
    transcode_suffix = ""
    if quality:
        transcode_suffix += f"&quality={quality}"
    if profile:
        transcode_suffix += "&profile=" + quote(profile, safe="")

    # Local files: transcode via /stream_fmp4 to ensure H.264+AAC browser compat
    # (handles Xvid, AC3, DTS, MPEG-2, HEVC and any other unsupported codec)
    if _is_local_media_url(url):
        return "/stream_fmp4?url=" + quote(url, safe="") + transcode_suffix, ""

    # Pluto TV live HLS: Chrome/Firefox can't play HLS natively, transcode via /stream_fmp4
    if _is_pluto_stream(url) or _is_direct_hls(url):
        return "/stream_fmp4?url=" + quote(url, safe="") + transcode_suffix, ""

    # Acestream, RTP/UDP/RTSP, LAN MPEG-TS — browser can't play these natively;
    # transcode to fragmented MP4 on the fly via /stream_fmp4
    if _is_acestream(url) or _is_rtp_stream(url) or _is_local_network_stream(url):
        return "/stream_fmp4?url=" + quote(url, safe="") + transcode_suffix, ""

    # YouTube, Twitch, etc: resolve a direct CDN URL via yt-dlp and serve it
    # directly to the browser. Prefer H.264+AAC so no transcoding is needed.
    # However, if quality or profile is above 720p, route to /stream_fmp4 to
    # merge separate video and audio streams.
    q_val = quality or 0
    p_val = 0
    if profile and profile.isdigit():
        p_val = int(profile)

    if q_val > 720 or p_val > 720:
        return "/stream_fmp4?url=" + quote(url, safe="") + transcode_suffix, ""

    fmt = (
        f"best[vcodec^=avc][height<={quality}]/best[vcodec^=avc]/best[height<={quality}]/best"
        if quality
        else "best[vcodec^=avc]/best"
    )
    try:
        r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
             "-f", fmt, "--get-url", "--quiet", url],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            if lines:
                return lines[0], ""
    except Exception as e:
        return "", str(e)
    return "", "Could not resolve a direct playable URL"


def _resolve_ffmpeg_input_url(url: str, quality: int | None) -> tuple[list[dict[str, any]], str]:
    """Return a list of resolved input dicts (each having 'url' and 'headers') that ffmpeg can open directly, plus any error."""
    if _is_direct_stream(url):
        return [{"url": _ffmpeg_input_target(url), "headers": {}}], ""

    q = quality or 720
    # Prefer separate bestvideo and bestaudio so we can get high resolutions (e.g. 1080p, 1440p)
    # If those are not available or not separate, fall back to progressive 'best'.
    fmt = f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best"
    try:
        r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
             "-f", fmt, "--dump-json", "--quiet", url],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return [], r.stderr.strip() or "yt-dlp could not resolve a stream URL"
        try:
            info = json.loads(r.stdout)
        except json.JSONDecodeError:
            lines = [line.strip() for line in r.stdout.splitlines() if line.strip().startswith("{")]
            info = json.loads(lines[-1]) if lines else {}
        if not info:
            return [], "yt-dlp returned empty info"

        headers = info.get("http_headers") if isinstance(info.get("http_headers"), dict) else {}
        headers = {str(k): str(v) for k, v in headers.items() if v is not None}

        # Check if yt-dlp selected separate video and audio formats
        requested_formats = info.get("requested_formats")
        if requested_formats and len(requested_formats) >= 2:
            video_info = requested_formats[0]
            audio_info = requested_formats[1]
            video_url = (video_info.get("url") or "").strip()
            audio_url = (audio_info.get("url") or "").strip()
            v_headers = video_info.get("http_headers") or headers
            v_headers = {str(k): str(v) for k, v in v_headers.items() if v is not None}
            a_headers = audio_info.get("http_headers") or headers
            a_headers = {str(k): str(v) for k, v in a_headers.items() if v is not None}
            if video_url and audio_url:
                return [
                    {"url": video_url, "headers": v_headers},
                    {"url": audio_url, "headers": a_headers}
                ], ""

        direct_url = (info.get("url") or "").strip()
        if direct_url:
            return [{"url": direct_url, "headers": headers}], ""
        return [], "Could not resolve a direct playable URL"
    except Exception as e:
        return [], str(e)


def _short_error(msg: str, max_len: int = 1400) -> str:
    msg = (msg or "").strip()
    if len(msg) <= max_len:
        return msg
    return msg[:max_len - 1].rstrip() + "…"


def _build_ogv_ffmpeg_cmd(
    inputs: list[dict],
    seek_s: float = 0.0,
    output: str = "pipe:1",
    duration_limit_s: float | None = None,
    profile: str | None = None,
    source_quality: int | None = None,
) -> list[str]:
    """Build the Theora/Vorbis Ogg transcode command used by ogv.js playback."""
    seek_args = ["-ss", str(int(seek_s))] if seek_s > 0 else []
    duration_args = ["-t", str(duration_limit_s)] if duration_limit_s else []
    settings = _profile_settings(profile, source_quality)
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        *_ffmpeg_hwaccel_args(),
    ]
    for inp in inputs:
        cmd.extend(_direct_input_args(inp["url"], extra_headers=inp["headers"]))
        if seek_s > 0:
            cmd.extend(seek_args)
        cmd.extend(["-probesize", "10M", "-analyzeduration", "5M"])
        cmd.extend(["-i", inp["url"]])

    cmd.extend(duration_args)
    if len(inputs) >= 2:
        cmd.extend([
            "-map", "0:v:0",
            "-map", "1:a:0?",
        ])
    else:
        cmd.extend([
            "-map", "0:v:0",
            "-map", "0:a:0?",
        ])

    cmd.extend([
        "-vf", _scale_pad_filter(settings["width"], settings["height"]),
        "-r", str(settings["fps"]),
        "-c:v", "libtheora",
        "-q:v", str(settings["ogv_q"]),
        "-c:a", "libvorbis",
        "-b:a", settings["audio"],
        "-f", "ogg",
        output,
    ])
    return cmd


def _start_audio_buffer(stream: Stream):
    """Spawn a dedicated ffmpeg process to fill stream._audio_chunks with MP3.
    Used by the normal MJPEG pipeline for direct HLS streams."""
    extra = []
    if _is_acestream(stream.url) or _is_local_network_stream(stream.url):
        extra = ["-probesize", "20M", "-analyzeduration", "10M"]
    seek_args = ["-ss", str(int(stream.seek_s))] if stream.seek_s > 0 else []
    audio_cmd = [
        "ffmpeg",
        "-loglevel", "error",
        *_direct_input_args(stream.url),
        *seek_args,
        *extra,
        "-i", _ffmpeg_input_target(stream.url),
        "-vn",
        "-af", "aresample=async=1:first_pts=0",
        "-c:a", "mp3",
        "-b:a", "128k",
        "-f", "mp3",
        "pipe:1",
    ]
    audio_proc = subprocess.Popen(
        audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    with stream.lock:
        stream._audio_proc = audio_proc
    with stream._audio_lock:
        stream._audio_chunks.clear()
        stream._audio_done = False
    stream._audio_ready.clear()

    def _drain():
        try:
            while True:
                chunk = audio_proc.stdout.read(8192)
                if not chunk:
                    break
                with stream._audio_lock:
                    stream._audio_chunks.append(chunk)
                stream._audio_ready.set()
        finally:
            with stream._audio_lock:
                stream._audio_done = True
            stream._audio_ready.set()

    threading.Thread(target=_drain, daemon=True).start()


def _start_audio_buffer_any(stream: Stream):
    """Fill stream._audio_chunks with MP3 for any stream type (audio-only mode).
    For direct streams uses ffmpeg directly; for YouTube/Twitch uses yt-dlp first."""
    if _is_direct_stream(stream.url):
        _start_audio_buffer(stream)
        return

    # Non-direct (YouTube, Twitch, etc): resolve audio URL via yt-dlp first
    audio_fmt = "bestaudio[ext=m4a]/bestaudio"
    seek_args: list[str] = ["-ss", str(int(stream.seek_s))] if stream.seek_s > 0 else []
    try:
        url_r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
             "-f", audio_fmt, "--get-url", "--quiet", stream.url],
            capture_output=True, text=True, timeout=30,
        )
        direct_url = url_r.stdout.strip().splitlines()[0] if url_r.returncode == 0 else ""
    except Exception:
        direct_url = ""

    if direct_url:
        ff_cmd = [
            "ffmpeg", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
            *seek_args,
            "-re", "-i", direct_url,
            "-vn", "-af", "aresample=async=1:first_pts=0",
            "-c:a", "mp3", "-b:a", "128k", "-f", "mp3", "pipe:1",
        ]
        ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        yt_proc = None
    else:
        yt_cmd = [
            "yt-dlp", "--js-runtimes", "node", "--no-playlist",
            "-f", audio_fmt, "-o", "-", "--quiet", stream.url,
        ]
        ff_cmd = [
            "ffmpeg", "-loglevel", "error",
            "-i", "pipe:0", "-vn",
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "mp3", "-b:a", "128k", "-f", "mp3", "pipe:1",
        ]
        yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ff_proc = subprocess.Popen(ff_cmd, stdin=yt_proc.stdout,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    with stream.lock:
        stream._audio_proc = ff_proc
    with stream._audio_lock:
        stream._audio_chunks.clear()
        stream._audio_done = False
    stream._audio_ready.clear()

    def _drain():
        try:
            while True:
                chunk = ff_proc.stdout.read(8192)
                if not chunk:
                    break
                with stream._audio_lock:
                    stream._audio_chunks.append(chunk)
                stream._audio_ready.set()
        finally:
            with stream._audio_lock:
                stream._audio_done = True
            stream._audio_ready.set()
            for p in (ff_proc, yt_proc):
                if p and p.poll() is None:
                    try:
                        p.terminate()
                    except Exception:
                        pass

    threading.Thread(target=_drain, daemon=True).start()


def _start_muxed_pipeline(stream: Stream):
    """
    Start a single ffmpeg process for direct streams that outputs:
    - video MJPEG frames on stdout (pipe:1)
    - audio MP3 chunks on fd 3 (pipe:3)
    This avoids a second source connection for audio.
    """
    vf = _scale_pad_filter(STREAM_WIDTH, STREAM_HEIGHT)
    audio_r, audio_w = os.pipe()
    audio_out = [
        "-map", "0:a:0?",
        "-vn",
    ]
    # Local files are stable sources; skip async resampler to avoid periodic
    # audible artifacts on some ffmpeg + browser combinations.
    if not _is_local_media_url(stream.url):
        audio_out += ["-af", "aresample=async=1:first_pts=0"]
    audio_out += [
        "-c:a", "mp3",
        "-b:a", "128k",
        "-ar", "48000",
        "-ac", "2",
        "-f", "mp3",
        f"pipe:{audio_w}",
    ]

    seek_args = ["-ss", str(int(stream.seek_s))] if stream.seek_s > 0 else []
    ff_cmd = [
        "ffmpeg",
        "-loglevel", "error",
        *_direct_input_args(stream.url),
        *seek_args,
        "-probesize", "20M",
        "-analyzeduration", "10M",
        "-i", _ffmpeg_input_target(stream.url),
        # Video output (stdout / pipe:1)
        "-map", "0:v:0",
        "-vf", vf,
        "-vcodec", "mjpeg",
        "-q:v", str(FFMPEG_QUALITY),
        "-r", str(MJPEG_FPS),
        "-f", "image2pipe",
        "-vframes", "99999999",
        "pipe:1",
        # Audio output (extra fd / pipe:3)
        *audio_out,
    ]
    try:
        ff_proc = subprocess.Popen(
            ff_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(audio_w,),
        )
    except Exception:
        os.close(audio_r)
        raise
    finally:
        os.close(audio_w)

    with stream._audio_lock:
        stream._audio_chunks.clear()
        stream._audio_done = False
    stream._audio_ready.clear()

    def _drain():
        try:
            with os.fdopen(audio_r, "rb", buffering=0) as audio_pipe:
                while True:
                    chunk = audio_pipe.read(8192)
                    if not chunk:
                        break
                    with stream._audio_lock:
                        stream._audio_chunks.append(chunk)
                    stream._audio_ready.set()
        finally:
            with stream._audio_lock:
                stream._audio_done = True
            stream._audio_ready.set()

    threading.Thread(target=_drain, daemon=True).start()
    return ff_proc


def _run_hls_pipeline(stream: Stream):
    """Pipeline for direct streams (HLS / MPEG-TS / Acestream) — no yt-dlp."""
    is_ace = _is_acestream(stream.url)
    is_pluto = _is_pluto_stream(stream.url)
    is_local = _is_local_media_url(stream.url)
    is_rtp = _is_rtp_stream(stream.url)
    is_lan = _is_local_network_stream(stream.url)
    log.info(
        f"[{stream.id}] Direct pipeline (ace={is_ace}, pluto={is_pluto}, local={is_local}, rtp={is_rtp}, lan={is_lan}, audio_only={stream.audio_only})"
    )

    if stream.audio_only:
        try:
            _start_audio_buffer(stream)
            with stream.lock:
                stream.status = "streaming"
                if stream.started_at is None:
                    stream.started_at = time.time()
            # Wait for audio to finish
            stream._audio_ready.wait()
            while True:
                stream._audio_ready.clear()
                with stream._audio_lock:
                    if stream._audio_done:
                        break
                stream._audio_ready.wait()
            with stream.lock:
                stream.status = "done"
        except Exception as e:
            with stream.lock:
                stream.status = "error"
                stream.error = str(e)
            log.error(f"[{stream.id}] Audio-only pipeline error: {e}")
        finally:
            stream.stop()
        return

    SOI = b"\xff\xd8"
    EOI = b"\xff\xd9"
    try:
        if is_ace or is_pluto or is_local or is_rtp or is_lan:
            ff_proc = _start_muxed_pipeline(stream)
        else:
            # HLS path still uses a dedicated audio process.
            _start_audio_buffer(stream)
            ff_cmd = [
                "ffmpeg",
                "-loglevel", "error",
                *_direct_input_args(stream.url),
                "-i", _ffmpeg_input_target(stream.url),
                "-vf", _scale_pad_filter(STREAM_WIDTH, STREAM_HEIGHT),
                "-vcodec", "mjpeg",
                "-q:v", str(FFMPEG_QUALITY),
                "-r", str(MJPEG_FPS),
                "-an",
                "-f", "image2pipe",
                "-vframes", "99999999",
                "pipe:1",
            ]
            ff_proc = subprocess.Popen(
                ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        with stream.lock:
            stream._ff_proc = ff_proc
            stream.status = "streaming"
            if stream.started_at is None:
                stream.started_at = time.time()

        buf = b""
        while True:
            chunk = ff_proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(SOI)
                if start == -1:
                    buf = b""
                    break
                end = buf.find(EOI, start + 2)
                if end == -1:
                    buf = buf[start:]
                    break
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                with stream.frame_cond:
                    stream.frame = frame
                    stream._frame_history.append((time.time(), frame))
                    stream.last_used = time.time()
                    if stream.first_frame_at is None:
                        stream.first_frame_at = time.time()
                    stream.frame_cond.notify_all()

        ff_rc = ff_proc.poll()
        produced = stream.frame is not None
        with stream.lock:
            if produced:
                stream.status = "done"
            else:
                ff_err = ff_proc.stderr.read(500).decode("utf-8", errors="replace")
                stream.status = "error"
                stream.error = "No video frames from HLS stream"
                stream.error_detail = f"ff_rc={ff_rc} ff_err={ff_err}"
        log.info(f"[{stream.id}] HLS pipeline finished (rc={ff_rc})")
    except Exception as e:
        with stream.lock:
            stream.status = "error"
            stream.error = str(e)
        log.error(f"[{stream.id}] HLS pipeline error: {e}")
    finally:
        stream.stop()


__all__ = [name for name in globals() if not name.startswith("__")]


def run_pipeline(stream: Stream):
    log.info(f"[{stream.id}] Starting pipeline for: {stream.url}")
    threading.Thread(target=fetch_title, args=(stream,), daemon=True).start()

    if _is_direct_stream(stream.url):
        _run_hls_pipeline(stream)
        return

    if stream.audio_only:
        # Start unified audio buffer (works for all stream types) then return —
        # no MJPEG pipeline is needed. _serve_audio drains from _audio_chunks.
        threading.Thread(target=_start_audio_buffer_any, args=(stream,), daemon=True).start()
        with stream.lock:
            stream.status = "streaming"
            if stream.started_at is None:
                stream.started_at = time.time()
        return

    try:
        def _format_candidates(quality: int | None) -> list[str]:
            if quality:
                q = quality
                return [
                    f"bestvideo[ext=mp4][height<={q}]/best[ext=mp4][height<={q}]",
                    f"bestvideo[height<={q}]/best[height<={q}]",
                    "bestvideo[ext=mp4]/best[ext=mp4]",
                    "bestvideo/best",
                ]
            return [
                "bestvideo[ext=mp4]/best[ext=mp4]",
                "bestvideo/best",
            ]

        def _drain_stderr(pipe, sink: list[str], max_chars: int = 4000):
            try:
                while True:
                    chunk = pipe.read(1024)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    sink.append(text)
                    current = sum(len(x) for x in sink)
                    if current > max_chars:
                        overflow = current - max_chars
                        while overflow > 0 and sink:
                            if len(sink[0]) <= overflow:
                                overflow -= len(sink[0])
                                sink.pop(0)
                            else:
                                sink[0] = sink[0][overflow:]
                                overflow = 0
            except Exception:
                pass

        SOI = b"\xff\xd8"
        EOI = b"\xff\xd9"
        attempt_errors: list[str] = []

        for attempt_idx, fmt in enumerate(_format_candidates(stream.quality), start=1):
            yt_proc = None

            # Always resolve a direct CDN URL first. This lets ffmpeg download
            # at real-time speed (-re) instead of letting yt-dlp race ahead and
            # buffer gigabytes into a pipe — which breaks long videos.
            url_r = subprocess.run(
                ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
                 "-f", fmt, "--get-url", "--quiet", stream.url],
                capture_output=True, text=True, timeout=30,
            )
            direct_url = url_r.stdout.strip().splitlines()[0] if url_r.returncode == 0 else ""

            if direct_url:
                # Detect source FPS so we output at the native rate — no frame
                # duplication/dropping, which is the main cause of A/V drift.
                source_fps = _probe_fps(direct_url)
                output_fps = min(source_fps, MJPEG_FPS) if source_fps else MJPEG_FPS
                stream.fps = output_fps
                log.info(f"[{stream.id}] source_fps={source_fps} → output_fps={output_fps}")

                seek_args = ["-ss", str(int(stream.seek_s))] if stream.seek_s > 0 else []
                ff_cmd = [
                    "ffmpeg",
                    "-loglevel", "error",
                    "-reconnect", "1",
                    "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "10",
                    *seek_args,
                    "-re",
                    "-i", direct_url,
                    "-vf", _scale_pad_filter(STREAM_WIDTH, STREAM_HEIGHT),
                    "-vcodec", "mjpeg",
                    "-q:v", str(FFMPEG_QUALITY),
                    "-r", str(output_fps),
                    "-f", "image2pipe",
                    "-vframes", "99999999",
                    "pipe:1",
                ]
                ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                # Fallback: pipe yt-dlp → ffmpeg (no seek support, may buffer on long videos)
                if stream.seek_s > 0:
                    attempt_errors.append(
                        f"attempt={attempt_idx} fmt={fmt} yt-dlp --get-url failed (seek requires direct URL): {url_r.stderr.strip()}"
                    )
                    continue
                log.warning(f"[{stream.id}] --get-url failed for fmt={fmt}, falling back to pipe")
                yt_cmd = [
                    "yt-dlp",
                    "--js-runtimes", "node",
                    "--no-playlist",
                    "-f", fmt,
                    "-o", "-",
                    "--quiet",
                    stream.url,
                ]
                ff_cmd = [
                    "ffmpeg",
                    "-loglevel", "error",
                    "-re",
                    "-i", "pipe:0",
                    "-vf", _scale_pad_filter(STREAM_WIDTH, STREAM_HEIGHT),
                    "-vcodec", "mjpeg",
                    "-q:v", str(FFMPEG_QUALITY),
                    "-r", str(MJPEG_FPS),
                    "-f", "image2pipe",
                    "-vframes", "99999999",
                    "pipe:1",
                ]
                yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                ff_proc = subprocess.Popen(ff_cmd, stdin=yt_proc.stdout,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            yt_stderr_chunks: list[str] = []
            ff_stderr_chunks: list[str] = []

            with stream.lock:
                stream._yt_proc = yt_proc
                stream._ff_proc = ff_proc
                stream.status = "streaming"
                if stream.started_at is None:
                    stream.started_at = time.time()

            if yt_proc is not None:
                yt_err_t = threading.Thread(
                    target=_drain_stderr,
                    args=(yt_proc.stderr, yt_stderr_chunks),
                    daemon=True,
                )
                yt_err_t.start()
            ff_err_t = threading.Thread(
                target=_drain_stderr,
                args=(ff_proc.stderr, ff_stderr_chunks),
                daemon=True,
            )
            ff_err_t.start()

            log.info(f"[{stream.id}] Pipeline running (attempt {attempt_idx}, fmt={fmt})")

            frame_before = stream.frame
            buf = b""
            while True:
                chunk = ff_proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk

                while True:
                    start = buf.find(SOI)
                    if start == -1:
                        buf = b""
                        break
                    end = buf.find(EOI, start + 2)
                    if end == -1:
                        buf = buf[start:]
                        break
                    frame = buf[start:end + 2]
                    buf = buf[end + 2:]
                    with stream.frame_cond:
                        stream.frame = frame
                        stream._frame_history.append((time.time(), frame))
                        stream.last_used = time.time()
                        if stream.first_frame_at is None:
                            stream.first_frame_at = time.time()
                        stream.frame_cond.notify_all()

            yt_rc = yt_proc.poll() if yt_proc is not None else None
            ff_rc = ff_proc.poll()
            yt_err = "".join(yt_stderr_chunks).strip()
            ff_err = "".join(ff_stderr_chunks).strip()
            if yt_proc is not None:
                yt_err_t.join(timeout=0.2)
            ff_err_t.join(timeout=0.2)

            produced_frames = stream.frame is not None and stream.frame is not frame_before
            if produced_frames:
                with stream.lock:
                    stream.status = "done"
                log.info(f"[{stream.id}] Pipeline finished")
                break

            attempt_errors.append(
                f"attempt={attempt_idx} fmt={fmt} yt_rc={yt_rc} ff_rc={ff_rc} "
                f"yt_err={yt_err[-220:]} ff_err={ff_err[-220:]}"
            )
            for proc in (ff_proc, yt_proc):
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
        else:
            with stream.lock:
                stream.status = "error"
                stream.error = "No video frames were produced"
                stream.error_detail = " || ".join(attempt_errors)[-1800:]
            log.error(f"[{stream.id}] Pipeline failed: {stream.error_detail}")

    except Exception as e:
        with stream.lock:
            stream.status = "error"
            stream.error  = str(e)
            stream.error_detail = ""
        log.error(f"[{stream.id}] Pipeline error: {e}")
    finally:
        stream.stop()


# ── HTML ──────────────────────────────────────────────────────────────────────

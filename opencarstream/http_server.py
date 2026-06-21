import base64
import json
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, quote, unquote, urlparse

from .config import *
from .feeds import *
from .helpers import *
from .media import *
from .pluto import pluto_cache
from .state import Stream, active_sessions, registry, sessions_lock
from .storage import *
from .views import *


def _is_tesla_user_agent(user_agent: str | None) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return False
    if "tesla" in ua or "qtcarbrowser" in ua or "qtwebengine" in ua:
        return True

    # Newer Tesla browser builds often present as a plain Linux Chromium UA
    # without an explicit Tesla token.
    if (
        "x11; linux x86_64" in ua
        and "applewebkit/" in ua
        and "chrome/" in ua
        and "safari/" in ua
        and "edg/" not in ua
        and "opr/" not in ua
        and "opera" not in ua
        and "vivaldi" not in ua
        and "brave" not in ua
        and "chromium" not in ua
        and "firefox/" not in ua
    ):
        return True

    return False


class Handler(BaseHTTPRequestHandler):
    disable_nagle_algorithm = True  # TCP_NODELAY — eliminates inter-frame buffering delay

    def log_message(self, fmt, *args):
        log.debug(fmt % args)

    @staticmethod
    def _safe_header_value(value: str) -> str:
        # http.server writes headers as latin-1; replace unsupported chars so
        # titles with unicode punctuation/emojis do not crash the request.
        cleaned = (value or "").replace("\r", " ").replace("\n", " ")
        return cleaned.encode("latin-1", "replace").decode("latin-1")

    @staticmethod
    def _parse_quality(raw_quality: str | None) -> int | None:
        if raw_quality is None or raw_quality == "" or raw_quality == "auto":
            return None
        try:
            quality = int(raw_quality)
        except ValueError:
            raise ValueError("quality must be one of: auto,144,240,360,480,720,1080,1440,2160")
        if quality not in QUALITY_LEVELS:
            raise ValueError("quality must be one of: auto,144,240,360,480,720,1080,1440,2160")
        return quality

    @staticmethod
    def _parse_profile(raw_profile: str | None) -> str:
        profile = (raw_profile or OGV_DEFAULT_PROFILE or "auto").strip().lower()
        if profile in ("", "auto", "default"):
            return profile or "auto"
        if profile not in TRANSCODE_PROFILES:
            raise ValueError("profile must be one of: auto,default,360,480,720,1080,1440,2160")
        return profile

    @staticmethod
    def _parse_sync_ms(raw_sync: str | None, default_ms: int | None = None) -> int:
        if raw_sync is None or raw_sync == "":
            return AUDIO_DELAY_MS if default_ms is None else default_ms
        try:
            sync_ms = int(raw_sync)
        except ValueError:
            raise ValueError("sync must be an integer milliseconds value")
        if sync_ms < 0 or sync_ms > 10000:
            raise ValueError("sync must be between 0 and 10000 milliseconds")
        return sync_ms

    @staticmethod
    def _resolve_local_media_path(rel_path: str | None) -> tuple[str | None, str]:
        if not rel_path:
            return None, "Missing ?file= parameter"
        # Keep path traversal protections (`..`) while allowing symlink targets
        # outside the base directory when they are reachable via entries inside
        # the mounted media tree.
        base = os.path.abspath(LOCAL_MEDIA_DIR)
        target = os.path.abspath(os.path.normpath(os.path.join(base, rel_path)))
        if not (target == base or target.startswith(base + os.sep)):
            return None, "Invalid local media path"
        if not os.path.isfile(target):
            return None, "Local media file not found"
        if not _has_supported_media_ext(target):
            return None, "Unsupported local media extension"
        return target, ""

    @staticmethod
    def _resolve_iptv_list_path(raw_list: str | None) -> tuple[str | None, str]:
        if not raw_list:
            return None, "Missing ?list= parameter"

        requested = raw_list.strip()
        if not requested:
            return None, "Missing ?list= parameter"

        base, lists, err = _scan_iptv_lists()
        if err:
            return None, err

        request_lower = requested.lower()
        for entry in lists:
            if entry["id"].lower() == request_lower:
                return os.path.join(base, entry["id"].replace("/", os.sep)), ""

        # Allow resolving by friendly name (filename without extension).
        by_name = [entry for entry in lists if entry["name"].lower() == request_lower]
        if len(by_name) == 1:
            return os.path.join(base, by_name[0]["id"].replace("/", os.sep)), ""
        if len(by_name) > 1:
            return None, (
                f"Ambiguous IPTV list name '{requested}'. "
                "Use the full list id/path from /iptv_lists."
            )

        return None, f"IPTV list not found: {requested}"

    def _is_authenticated(self) -> bool:
        if not ADMIN_PASSWORD:
            return True

        # 1. Check Cookie
        cookie_header = self.headers.get("Cookie", "")
        if "session=" in cookie_header:
            for cookie in cookie_header.split(";"):
                cookie = cookie.strip()
                if cookie.startswith("session="):
                    session_id = cookie.split("=", 1)[1]
                    with sessions_lock:
                        if session_id in active_sessions:
                            return True

        # 2. Check Query parameter: auth=... or token=...
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        auth_param = qs.get("auth", [None])[0] or qs.get("token", [None])[0]
        if auth_param:
            if auth_param == ADMIN_PASSWORD:
                return True
            with sessions_lock:
                if auth_param in active_sessions:
                    return True

        # 3. Check Authorization header
        auth_header = self.headers.get("Authorization", "")
        if auth_header:
            if auth_header.lower().startswith("basic "):
                try:
                    auth_type, encoded = auth_header.split(" ", 1)
                    decoded = base64.b64decode(encoded).decode("utf-8")
                    if ":" in decoded:
                        user, pwd = decoded.split(":", 1)
                        if pwd == ADMIN_PASSWORD:
                            return True
                    else:
                        if decoded == ADMIN_PASSWORD:
                            return True
                except Exception:
                    pass
            elif auth_header.lower().startswith("bearer ") or auth_header.lower().startswith("token "):
                try:
                    token = auth_header.split(" ", 1)[1].strip()
                    with sessions_lock:
                        if token in active_sessions:
                            return True
                except Exception:
                    pass

        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/login":
            next_url = qs.get("next", ["/"])[0]
            next_query = f"?next={quote(next_url)}" if next_url != "/" else ""
            html = LOGIN_HTML.replace("{{error_msg}}", "").replace("{{next_query}}", next_query)
            self._html(html)
            return

        if path == "/logout":
            cookie_header = self.headers.get("Cookie", "")
            if "session=" in cookie_header:
                for cookie in cookie_header.split(";"):
                    cookie = cookie.strip()
                    if cookie.startswith("session="):
                        session_id = cookie.split("=", 1)[1]
                        with sessions_lock:
                            active_sessions.discard(session_id)
            self.send_response(303)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.end_headers()
            return

        if path != "/health" and not self._is_authenticated():
            self.send_response(303)
            self.send_header("Location", f"/login?next={quote(self.path)}")
            self.end_headers()
            return

        if path.startswith("/ogv-dist/"):
            self._serve_ogv_asset(path)

        elif path == "/":
            html = render_status_page()
            self._html(html)

        elif path == "/health":
            self._json({"ok": True, "streams": len(registry.all_streams())})

        elif path == "/status":
            data = [s.to_dict() for s in registry.all_streams()]
            self._json({"streams": data})

        elif path == "/feed":
            channel = qs.get("channel", [None])[0]
            if not channel:
                self._error(400, "Missing ?channel= parameter")
                return
            limit = 12
            try:
                raw_limit = qs.get("limit", [None])[0]
                if raw_limit:
                    limit = max(1, min(int(raw_limit), 50))
            except (ValueError, TypeError):
                pass
            self._serve_feed(channel.strip(), limit)

        elif path == "/ytsearch":
            q = qs.get("q", [None])[0]
            if not q:
                self._error(400, "Missing ?q= parameter")
                return
            limit = 12
            try:
                raw_limit = qs.get("limit", [None])[0]
                if raw_limit:
                    limit = max(1, min(int(raw_limit), 50))
            except (ValueError, TypeError):
                pass
            self._serve_ytsearch(q.strip(), limit)

        elif path == "/subscriptions":
            self._serve_subscriptions()

        elif path == "/iptv_lists":
            self._serve_iptv_lists()

        elif path == "/iptv_streams":
            list_name = qs.get("list", [None])[0]
            self._serve_iptv_streams(list_name)

        elif path == "/stream_fmp4":
            raw_url = qs.get("url", [None])[0]
            if not raw_url:
                self._error(400, "Missing ?url= parameter")
                return
            raw_quality = qs.get("quality", [None])[0]
            try:
                quality = self._parse_quality(raw_quality)
                profile = self._parse_profile(qs.get("profile", [None])[0])
            except ValueError as e:
                self._error(400, str(e))
                return
            stream_url = unquote(raw_url)
            self._serve_fmp4_direct(stream_url, profile=profile, quality=quality)

        elif path == "/stream_ogv":
            raw_url = qs.get("url", [None])[0]
            if not raw_url:
                self._error(400, "Missing ?url= parameter")
                return
            raw_quality = qs.get("quality", [None])[0]
            try:
                quality = self._parse_quality(raw_quality)
                profile = self._parse_profile(qs.get("profile", [None])[0])
            except ValueError as e:
                self._error(400, str(e))
                return
            try:
                seek_s = max(0.0, float(qs.get("seek", [0])[0] or 0))
            except (ValueError, TypeError):
                seek_s = 0.0
            stream_url = unquote(raw_url)
            if qs.get("diagnostic", ["0"])[0] == "1":
                self._serve_ogv_diagnostic(stream_url, quality=quality, seek_s=seek_s, profile=profile)
                return
            self._serve_ogv_direct(stream_url, quality=quality, seek_s=seek_s, profile=profile)

        elif path == "/file_serve":
            raw_path = qs.get("path", [None])[0]
            if not raw_path:
                self._error(400, "Missing ?path= parameter")
                return
            req_path = unquote(raw_path)
            local_file, err = self._resolve_local_media_path(
                os.path.relpath(req_path, os.path.abspath(LOCAL_MEDIA_DIR))
            )
            if not local_file:
                self._error(400, err)
                return
            self._serve_file_bytes(local_file)

        elif path == "/local_media":
            raw_dir = qs.get("dir", [None])[0]
            self._serve_local_media(raw_dir)

        elif path == "/local_watch":
            raw_file = qs.get("file", [None])[0]
            raw_sync = qs.get("sync", [None])[0]
            raw_seek = qs.get("seek", [None])[0]
            if raw_sync is None or raw_sync == "":
                sync_ms = LOCAL_MEDIA_VIDEO_DELAY_MS
            else:
                try:
                    sync_ms = self._parse_sync_ms(raw_sync)
                except ValueError as e:
                    self._error(400, str(e))
                    return
            seek_s = 0
            if raw_seek:
                try:
                    seek_s = max(0, int(raw_seek))
                except ValueError:
                    pass
            local_file, err = self._resolve_local_media_path(raw_file)
            if not local_file:
                self._error(400, err)
                return
            file_url = "file://" + quote(local_file, safe="/")
            registry.cleanup_done()
            stream = registry.get_or_create(
                file_url,
                quality=None,
                reuse_existing=False,
            )
            if not stream.title:
                stream.title = os.path.splitext(os.path.basename(local_file))[0]
            if seek_s > 0:
                stream.seek_s = float(seek_s)
            user_agent = self.headers.get("User-Agent", "")
            default_mode = "ogv" if _is_tesla_user_agent(user_agent) else "mp4"
            local_mode = (qs.get("mode", [default_mode])[0] or default_mode).lower()
            if local_mode not in ("mjpeg", "mp4", "ogv", "audio"):
                local_mode = default_mode
            try:
                profile = self._parse_profile(qs.get("profile", [None])[0])
            except ValueError as e:
                self._error(400, str(e))
                return

            if local_mode == "mp4":
                vcodec, acodec = _probe_local_codecs(local_file)
                fname = os.path.basename(local_file)
                # Browsers support H.264/H.265 video and AAC/MP3 audio natively in MP4
                video_ok = vcodec in ("h264", "hevc")
                audio_ok = acodec in ("aac", "mp3", "")
                if video_ok and audio_ok:
                    log.info(f"MP4 {fname}: video:{vcodec}→copy, audio:{acodec or 'none'}→copy (direct)")
                    mp4_url = "/file_serve?path=" + quote(local_file, safe="")
                else:
                    vlog = f"video:{vcodec or '?'}→{'copy' if video_ok else 'h264'}"
                    alog = f"audio:{acodec or '?'}→{'copy' if audio_ok else 'aac'}"
                    log.info(f"MP4 {fname}: {vlog}, {alog} (transcoding)")
                    mp4_url = "/stream_fmp4?url=" + quote(file_url, safe="") + "&profile=" + quote(profile, safe="")
                self._html(render_mp4_page(mp4_url))
                return

            if local_mode == "ogv":
                ogv_url = "/stream_ogv?url=" + quote(file_url, safe="") + f"&seek={int(seek_s)}&profile=" + quote(profile, safe="")
                self._html(render_ogv_page(ogv_url, original_url=file_url, stream_title=stream.title, seek_s=int(seek_s), profile=profile))
                return

            if local_mode == "audio":
                stream.audio_only = True
                self._html(render_audio_page(stream.id, sync_ms))
                return

            # Warm local playback so configured sync delay reflects timeline
            # delay rather than ffmpeg startup overhead.
            if stream.status == "starting" and stream._ff_proc is None:
                threading.Thread(target=run_pipeline, args=(stream,), daemon=True).start()
            warm_deadline = time.time() + 8.0
            while (
                stream.frame is None
                and stream.status not in ("error", "done")
                and time.time() < warm_deadline
            ):
                time.sleep(0.05)
            self._html(render_watch_page(stream.id, sync_ms, local_file=raw_file or "", seek_s=seek_s))

        elif path == "/pluto_channels":
            lang = qs.get("lang", [PLUTO_LANGS[0]])[0]
            self._serve_pluto_channels(lang)

        elif path == "/pluto_watch":
            lang = (qs.get("lang", [PLUTO_LANGS[0]])[0] or "").strip().lower()
            channel_id = qs.get("id", [None])[0]
            if not channel_id:
                self._error(400, "Missing ?id= parameter")
                return
            raw_sync = qs.get("sync", [None])[0]
            try:
                sync_ms = self._parse_sync_ms(raw_sync, 500)
            except ValueError as e:
                self._error(400, str(e))
                return
            if lang not in PLUTO_LANGS:
                self._error(400, f"Unsupported Pluto lang '{lang}'")
                return

            # Refresh Pluto session tokens per playback launch to avoid stale
            # signed URLs being rejected with fallback "unsupported device" streams.
            pluto_url, err = pluto_cache.build_channel_url(
                lang, channel_id, force_refresh=True
            )
            if not pluto_url:
                self._error(502, f"Pluto TV stream unavailable: {err}")
                return
            registry.cleanup_done()
            stream = registry.get_or_create(
                pluto_url,
                quality=None,
                reuse_existing=False,
            )
            if not stream.title:
                with pluto_cache._lock:
                    ch = next((c for c in pluto_cache._by_lang.get(lang, []) if c.get("id") == channel_id), None)
                if ch:
                    stream.title = ch["name"]
            user_agent = self.headers.get("User-Agent", "")
            default_mode = "ogv" if _is_tesla_user_agent(user_agent) else "mp4"
            pluto_mode = (qs.get("mode", [default_mode])[0] or default_mode).lower()
            if pluto_mode not in ("mjpeg", "mp4", "ogv", "audio"):
                pluto_mode = default_mode
            try:
                profile = self._parse_profile(qs.get("profile", [None])[0])
            except ValueError as e:
                self._error(400, str(e))
                return
            if pluto_mode == "mp4":
                direct_url, err = _resolve_mp4_url(pluto_url, None, profile=profile)
                self._html(render_mp4_page(direct_url, error_msg=err, stream_title=stream.title))
            elif pluto_mode == "ogv":
                ogv_url = "/stream_ogv?url=" + quote(pluto_url, safe="") + "&profile=" + quote(profile, safe="")
                self._html(render_ogv_page(ogv_url, original_url=pluto_url, stream_title=stream.title, profile=profile))
            elif pluto_mode == "audio":
                stream.audio_only = True
                self._html(render_audio_page(stream.id, sync_ms))
            else:
                self._html(render_watch_page(stream.id, sync_ms))

        elif path == "/stop_stream":
            sid = qs.get("sid", [None])[0]
            if not sid:
                self._error(400, "Missing ?sid= parameter")
                return
            stream = registry.get(sid)
            if stream:
                stream.stop()
                stream.status = "done"
            self._json({"ok": True})

        elif path == "/stream_status":
            sid = qs.get("sid", [None])[0]
            if not sid:
                self._error(400, "Missing ?sid= parameter")
                return
            stream = registry.get(sid)
            if stream is None:
                self._error(404, "Stream session not found")
                return
            self._json(stream.to_dict())

        elif path == "/watch":
            raw_url = qs.get("url", [None])[0]
            if not raw_url:
                self._error(400, "Missing ?url= parameter")
                return
            raw_quality = qs.get("quality", [None])[0]
            try:
                quality = self._parse_quality(raw_quality)
            except ValueError as e:
                self._error(400, str(e))
                return
            raw_sync = qs.get("sync", [None])[0]
            video_url = unquote(raw_url)
            try:
                sync_ms = self._parse_sync_ms(raw_sync, _default_sync_ms_for_url(video_url))
            except ValueError as e:
                self._error(400, str(e))
                return
            user_agent = self.headers.get("User-Agent", "")
            default_mode = "ogv" if _is_tesla_user_agent(user_agent) else "mp4"
            mode = (qs.get("mode", [default_mode])[0] or default_mode).lower()
            if mode not in ("mjpeg", "mp4", "ogv", "audio"):
                mode = default_mode
            try:
                profile = self._parse_profile(qs.get("profile", [None])[0])
            except ValueError as e:
                self._error(400, str(e))
                return

            if mode == "mp4":
                direct_url, err = _resolve_mp4_url(video_url, quality, profile=profile)
                self._html(render_mp4_page(direct_url, error_msg=err))
                return

            try:
                seek_s = max(0.0, float(qs.get("seek", [0])[0] or 0))
            except (ValueError, TypeError):
                seek_s = 0.0

            if mode == "ogv":
                ogv_url = "/stream_ogv?url=" + quote(video_url, safe="") + f"&seek={int(seek_s)}"
                if quality:
                    ogv_url += f"&quality={quality}"
                if profile:
                    ogv_url += "&profile=" + quote(profile, safe="")
                self._html(render_ogv_page(
                    ogv_url,
                    original_url=video_url,
                    quality=quality,
                    seek_s=int(seek_s),
                    profile=profile,
                ))
                return

            registry.cleanup_done()
            stream = registry.get_or_create(
                video_url,
                quality=quality,
                reuse_existing=False,
            )
            stream.seek_s = seek_s
            if mode == "audio":
                stream.audio_only = True
                duration_s = _fetch_duration_s(video_url)
                self._html(render_audio_page(stream.id, sync_ms, video_url, int(seek_s), duration_s))
            else:
                self._html(render_watch_page(stream.id, sync_ms, video_url, quality))

        elif path == "/stream":
            raw_sync = qs.get("sync", [None])[0]
            try:
                sync_ms = self._parse_sync_ms(raw_sync)
            except ValueError as e:
                self._error(400, str(e))
                return
            sid = qs.get("sid", [None])[0]
            stream = None
            if sid:
                stream = registry.get(sid)
                if stream is None:
                    self._error(404, "Stream session not found")
                    return
            else:
                raw_url = qs.get("url", [None])[0]
                if not raw_url:
                    self._error(400, "Missing ?url= parameter")
                    return
                raw_quality = qs.get("quality", [None])[0]
                try:
                    quality = self._parse_quality(raw_quality)
                except ValueError as e:
                    self._error(400, str(e))
                    return
                video_url = unquote(raw_url)
                stream = registry.get_or_create(video_url, quality=quality)
            self._serve_mjpeg(stream, sync_ms=sync_ms)

        elif path == "/audio":
            raw_sync = qs.get("sync", [None])[0]
            try:
                sync_ms = self._parse_sync_ms(raw_sync)
            except ValueError as e:
                self._error(400, str(e))
                return
            sid = qs.get("sid", [None])[0]
            stream = None
            if sid:
                stream = registry.get(sid)
                if stream is None:
                    self._error(404, "Stream session not found")
                    return
            else:
                raw_url = qs.get("url", [None])[0]
                if not raw_url:
                    self._error(400, "Missing ?url= parameter")
                    return
                raw_quality = qs.get("quality", [None])[0]
                try:
                    quality = self._parse_quality(raw_quality)
                except ValueError as e:
                    self._error(400, str(e))
                    return
                video_url = unquote(raw_url)
                stream = registry.get_or_create(video_url, quality=quality)
            self._serve_audio(stream, sync_ms=sync_ms)

        elif path == "/ace_streams":
            self._serve_ace_streams()

        elif path == "/favorites":
            self._json({"favorites": _load_favorites()})

        elif path == "/progress":
            url = (qs.get("url", [None])[0] or "").strip()
            data = _load_progress()
            if url:
                self._json(data.get(url) or {})
            else:
                self._json(data)

        elif path == "/subscriptions_feed":
            force = qs.get("force", [None])[0] == "1"
            self._serve_subscriptions_feed(force)

        else:
            self._error(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length).decode("utf-8", "ignore")
            params = parse_qs(body)
            password = params.get("password", [""])[0]
            next_url = qs.get("next", ["/"])[0]
            
            if password == ADMIN_PASSWORD:
                session_id = secrets.token_hex(16)
                with sessions_lock:
                    active_sessions.add(session_id)
                self.send_response(303)
                self.send_header("Location", next_url)
                self.send_header("Set-Cookie", f"session={session_id}; Path=/; HttpOnly; SameSite=Lax")
                self.end_headers()
                return
            else:
                next_query = f"?next={quote(next_url)}" if next_url != "/" else ""
                html = LOGIN_HTML.replace("{{error_msg}}", "Incorrect password").replace("{{next_query}}", next_query)
                self._html(html, 401)
                return

        if path != "/health" and not self._is_authenticated():
            self._error(401, "Unauthorized")
            return

        if path == "/ace_streams":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                item = json.loads(body)
            except Exception:
                self._error(400, "Invalid JSON")
                return
            name = (item.get("name") or "").strip()
            cid  = (item.get("id")   or "").strip()
            if not name or not cid:
                self._error(400, "Missing name or id")
                return
            streams = _load_ace_streams()
            streams.append({"name": name, "id": cid})
            _save_ace_streams(streams)
            self._json({"ok": True, "streams": streams})

        elif path == "/favorites":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                item = json.loads(body)
            except Exception:
                self._error(400, "Invalid JSON")
                return
            url = (item.get("url") or "").strip()
            if not url:
                self._error(400, "Missing url")
                return
            favs = _load_favorites()
            if url not in favs:
                favs.append(url)
                _save_favorites(favs)
            self._json({"ok": True, "favorites": favs})

        elif path == "/progress":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                item = json.loads(body)
            except Exception:
                self._error(400, "Invalid JSON")
                return
            url   = (item.get("url") or "").strip()
            pos_s = item.get("pos_s")
            if not url or pos_s is None:
                self._error(400, "Missing url or pos_s")
                return
            data = _load_progress()
            data[url] = {"pos_s": int(pos_s), "saved_at": int(time.time())}
            _save_progress(data)
            self._json({"ok": True})

        else:
            self._error(404, "Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path != "/health" and not self._is_authenticated():
            self._error(401, "Unauthorized")
            return

        if path == "/ace_streams":
            qs  = parse_qs(parsed.query)
            idx_raw = qs.get("idx", [None])[0]
            try:
                idx = int(idx_raw)
            except (TypeError, ValueError):
                self._error(400, "Missing or invalid ?idx= parameter")
                return
            streams = _load_ace_streams()
            if idx < 0 or idx >= len(streams):
                self._error(404, "Index out of range")
                return
            streams.pop(idx)
            _save_ace_streams(streams)
            self._json({"ok": True, "streams": streams})

        elif path == "/favorites":
            qs  = parse_qs(parsed.query)
            url = (qs.get("url", [None])[0] or "").strip()
            if not url:
                self._error(400, "Missing ?url= parameter")
                return
            favs = _load_favorites()
            favs = [f for f in favs if f != url]
            _save_favorites(favs)
            self._json({"ok": True, "favorites": favs})

        elif path == "/progress":
            qs  = parse_qs(parsed.query)
            url = (qs.get("url", [None])[0] or "").strip()
            if not url:
                self._error(400, "Missing ?url= parameter")
                return
            data = _load_progress()
            data.pop(url, None)
            _save_progress(data)
            self._json({"ok": True})

        else:
            self._error(404, "Not found")

    # ── Ace streams ───────────────────────────────────────────────────────────
    def _serve_ace_streams(self):
        self._json({"streams": _load_ace_streams()})

    # ── Subscriptions ─────────────────────────────────────────────────────────
    def _serve_subscriptions(self):
        if not os.path.isfile(SUBSCRIPTIONS_FILE):
            self._error(503, f"Subscriptions file not found at {SUBSCRIPTIONS_FILE}. "
                            "Run sync_subscriptions.py and mount the resulting JSON.")
            return
        try:
            with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self._error(500, f"Failed to read subscriptions file: {e}")
            return
        self._json({
            "synced_at": data.get("synced_at", ""),
            "channels":  data.get("channels", []),
        })

    def _serve_subscriptions_feed(self, force: bool = False):
        if not os.path.isfile(SUBSCRIPTIONS_FILE):
            self._error(503, "Subscriptions file not found")
            return
        try:
            with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self._error(500, f"Failed to read subscriptions file: {e}")
            return

        channels = data.get("channels", [])
        if not channels:
            self._json({"videos": [], "built_at": 0, "cached": False})
            return

        with _home_feed_lock:
            age = time.time() - _home_feed_cache["built_at"]
            if not force and HOME_FEED_CACHE_SECS > 0 and age < HOME_FEED_CACHE_SECS and _home_feed_cache["videos"]:
                self._json({
                    "videos":   _home_feed_cache["videos"],
                    "built_at": int(_home_feed_cache["built_at"]),
                    "cached":   True,
                })
                return

        log.info(f"Building home feed from {len(channels)} channels ({HOME_FEED_WORKERS} workers)…")
        t0 = time.time()
        videos = _build_home_feed(channels)

        # Filter by age only when upload_date is reliably present (>50% of videos have a date).
        # yt-dlp flat-playlist often returns NA, making the age filter delete everything.
        dated = sum(1 for v in videos if v.get("upload_date") and v["upload_date"] != "NA")
        if HOME_FEED_MAX_AGE_DAYS > 0 and dated > len(videos) * 0.5:
            cutoff = time.strftime("%Y%m%d", time.gmtime(time.time() - HOME_FEED_MAX_AGE_DAYS * 86400))
            before = len(videos)
            videos = [v for v in videos if (v.get("upload_date") or "99991231") >= cutoff]
            log.info(f"Home feed: {before} raw → {len(videos)} within {HOME_FEED_MAX_AGE_DAYS}d in {time.time()-t0:.1f}s")
        else:
            log.info(f"Home feed built: {len(videos)} videos ({dated} dated) in {time.time()-t0:.1f}s")

        built_at = time.time()
        with _home_feed_lock:
            _home_feed_cache["videos"]   = videos
            _home_feed_cache["built_at"] = built_at

        _save_home_feed_disk_cache(videos, built_at)
        self._json({"videos": videos, "built_at": int(built_at), "cached": False})

    # ── IPTV lists ────────────────────────────────────────────────────────────
    def _serve_iptv_lists(self):
        base, lists, err = _scan_iptv_lists()
        if err:
            self._error(503, err)
            return
        self._json({"base_dir": base, "lists": lists})

    def _serve_iptv_streams(self, raw_list: str | None):
        target, err = self._resolve_iptv_list_path(raw_list)
        if not target:
            code = 503 if "directory not found" in err.lower() else 400
            self._error(code, err)
            return
        if not _has_supported_iptv_list_ext(target):
            self._error(400, "Unsupported IPTV list extension (use .m3u or .m3u8)")
            return
        try:
            with open(target, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            self._error(500, f"Failed to read IPTV list: {e}")
            return

        streams = _parse_iptv_m3u(content)
        self._json({
            "list": {
                "name": os.path.splitext(os.path.basename(target))[0],
                "path": os.path.relpath(target, os.path.abspath(IPTV_LISTS_DIR)).replace(os.sep, "/"),
            },
            "stream_count": len(streams),
            "streams": streams,
        })

    def _serve_ogv_asset(self, request_path: str):
        name = os.path.basename(unquote(request_path))
        if not name:
            self._error(404, "Not found")
            return
        asset_path = os.path.abspath(os.path.join(OGV_DIST_DIR, name))
        if not asset_path.startswith(os.path.abspath(OGV_DIST_DIR) + os.sep):
            self._error(403, "Forbidden")
            return
        if not os.path.isfile(asset_path):
            self._error(404, "Not found")
            return
        if name.endswith(".wasm"):
            mime = "application/wasm"
        elif name.endswith(".js"):
            mime = "application/javascript"
        elif name.endswith(".txt") or name in {"COPYING", "README.md"}:
            mime = "text/plain; charset=utf-8"
        else:
            mime = "application/octet-stream"
        try:
            size = os.path.getsize(asset_path)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            with open(asset_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_fmp4_direct(self, url: str, profile: str | None = None, quality: int | None = None):
        """Remux/transcode a live stream to fragmented MP4 for native browser <video> playback."""
        settings = _profile_settings(profile, quality)
        mp4_width = settings["width"] if profile else MP4_WIDTH
        mp4_height = settings["height"] if profile else MP4_HEIGHT
        mp4_bitrate = settings.get("mp4_bitrate", MP4_VIDEO_BITRATE) if profile else MP4_VIDEO_BITRATE
        # For local files, probe codecs to skip unnecessary transcoding
        video_args: list[str]
        audio_args: list[str]
        inputs: list[dict] = []
        if _is_local_media_url(url):
            vcodec, acodec = _probe_local_codecs(_ffmpeg_input_target(url))
            fname = os.path.basename(_ffmpeg_input_target(url))
            if vcodec in ("h264", "hevc"):
                video_args = ["-c:v", "copy"]
                vlog = f"video:{vcodec}→copy"
            else:
                video_args = _h264_video_args(mp4_width, mp4_height, mp4_bitrate)
                vlog = f"video:{vcodec or '?'}→{_select_h264_encoder()} {mp4_width}x{mp4_height}"
            if acodec in ("aac", "mp3", ""):
                audio_args = ["-c:a", "copy"] if acodec else []
                alog = f"audio:{acodec or 'none'}→copy"
            else:
                audio_args = ["-c:a", "aac", "-b:a", MP4_AUDIO_BITRATE, "-ar", "48000", "-ac", "2"]
                alog = f"audio:{acodec}→aac"
            log.info(f"fMP4 {fname}: {vlog}, {alog}")
        else:
            var_inputs, err = _resolve_ffmpeg_input_url(url, quality)
            if not var_inputs:
                self._error(502, f"Could not resolve stream: {err}")
                return
            inputs = var_inputs
            video_args = _h264_video_args(mp4_width, mp4_height, mp4_bitrate)
            audio_args = ["-c:a", "aac", "-b:a", MP4_AUDIO_BITRATE, "-ar", "48000", "-ac", "2"]

        if _is_local_media_url(url):
            ff_cmd = [
                "ffmpeg",
                "-loglevel", "error",
                *_ffmpeg_hwaccel_args(),
                *_direct_input_args(url),
                "-i", _ffmpeg_input_target(url),
                *video_args,
                *audio_args,
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-frag_duration", "1000000",
                "-f", "mp4",
                "pipe:1",
            ]
        else:
            ff_cmd = [
                "ffmpeg",
                "-loglevel", "error",
                *_ffmpeg_hwaccel_args(),
            ]
            for inp in inputs:
                ff_cmd.extend(_direct_input_args(inp["url"], extra_headers=inp["headers"]))
                ff_cmd.extend(["-i", inp["url"]])

            if len(inputs) >= 2:
                ff_cmd.extend([
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                ])
            else:
                ff_cmd.extend([
                    "-map", "0:v:0",
                    "-map", "0:a:0?",
                ])

            ff_cmd.extend([
                *video_args,
                *audio_args,
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-frag_duration", "1000000",
                "-f", "mp4",
                "pipe:1",
            ])

        range_header = self.headers.get("Range", "")
        is_range = range_header.startswith("bytes=")
        start_byte = 0
        end_byte = None
        if is_range:
            parts = range_header[6:].split("-")
            try:
                start_byte = int(parts[0]) if parts[0] else 0
                end_byte = int(parts[1]) if len(parts) > 1 and parts[1] else None
            except ValueError:
                pass

        dummy_total_size = 100 * 1024 * 1024 * 1024  # 100 GB

        ff_proc = None
        try:
            ff_proc = subprocess.Popen(
                ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )

            if is_range:
                if start_byte == 0 and end_byte == 1:
                    first_two_bytes = ff_proc.stdout.read(2)
                    self.send_response(206)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Range", f"bytes 0-1/{dummy_total_size}")
                    self.send_header("Content-Length", "2")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-cache, no-store")
                    self.end_headers()
                    self.wfile.write(first_two_bytes)
                    self.wfile.flush()
                    return

                target_end = end_byte if end_byte is not None else dummy_total_size - 1
                length = target_end - start_byte + 1
                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Range", f"bytes {start_byte}-{target_end}/{dummy_total_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

            if start_byte > 0:
                discarded = 0
                while discarded < start_byte:
                    to_read = min(65536, start_byte - discarded)
                    buf = ff_proc.stdout.read(to_read)
                    if not buf:
                        break
                    discarded += len(buf)

            while True:
                chunk = ff_proc.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if ff_proc and ff_proc.poll() is None:
                try:
                    ff_proc.terminate()
                except Exception:
                    pass

    @staticmethod
    def _read_process_startup(proc: subprocess.Popen, timeout_s: float = 15.0) -> tuple[bytes, str]:
        """Return the first stdout chunk plus any early stderr, without hanging forever."""
        if proc.stdout is None:
            return b"", "process has no stdout pipe"

        stdout_fd = proc.stdout.fileno()
        stderr_fd = proc.stderr.fileno() if proc.stderr is not None else None
        fds = [stdout_fd]
        if stderr_fd is not None:
            fds.append(stderr_fd)

        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        try:
            os.set_blocking(stdout_fd, False)
            if stderr_fd is not None:
                os.set_blocking(stderr_fd, False)
            deadline = time.time() + timeout_s
            while time.time() < deadline and fds:
                wait_s = max(0.05, min(0.25, deadline - time.time()))
                ready, _, _ = select.select(fds, [], [], wait_s)
                if not ready:
                    if proc.poll() is not None:
                        break
                    continue
                for fd in ready:
                    try:
                        data = os.read(fd, 65536)
                    except BlockingIOError:
                        continue
                    except OSError:
                        if fd in fds:
                            fds.remove(fd)
                        continue
                    if not data:
                        if fd in fds:
                            fds.remove(fd)
                        continue
                    if fd == stdout_fd:
                        out_chunks.append(data)
                    else:
                        err_chunks.append(data)
                if out_chunks:
                    break
                if proc.poll() is not None and stdout_fd not in fds:
                    break
        finally:
            try:
                os.set_blocking(stdout_fd, True)
            except Exception:
                pass
            if stderr_fd is not None:
                try:
                    os.set_blocking(stderr_fd, True)
                except Exception:
                    pass

        err_text = b"".join(err_chunks).decode("utf-8", errors="replace")
        return b"".join(out_chunks), err_text

    @staticmethod
    def _drain_pipe(pipe):
        try:
            while pipe.read(4096):
                pass
        except Exception:
            pass

    def _serve_ogv_diagnostic(self, url: str, quality: int | None = None, seek_s: float = 0.0, profile: str | None = None):
        """Run the OGV resolver/transcoder briefly and return a JSON diagnosis."""
        inputs, err = _resolve_ffmpeg_input_url(url, quality)
        if not inputs:
            err = _short_error(err or "yt-dlp could not resolve a stream URL")
            log.warning("OGV resolve failed url=%s quality=%s err=%s", url[:180], quality, err)
            self._json({"ok": False, "stage": "resolve", "error": err, "http_status": 502})
            return

        ff_cmd = _build_ogv_ffmpeg_cmd(
            inputs,
            seek_s=seek_s,
            output="pipe:1",
            duration_limit_s=2,
            profile=profile,
            source_quality=quality,
        )
        try:
            r = subprocess.run(
                ff_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=18,
            )
        except subprocess.TimeoutExpired as e:
            err = _short_error((e.stderr or b"").decode("utf-8", errors="replace") or "ffmpeg timed out during OGV diagnostic")
            log.warning("OGV diagnostic timed out url=%s err=%s", url[:180], err)
            self._json({"ok": False, "stage": "ffmpeg", "error": err, "http_status": 502})
            return
        except Exception as e:
            err = _short_error(str(e))
            log.warning("OGV diagnostic failed url=%s err=%s", url[:180], err)
            self._json({"ok": False, "stage": "ffmpeg", "error": err, "http_status": 502})
            return

        has_ogg_header = r.stdout.startswith(b"OggS")
        if r.returncode != 0 or not has_ogg_header:
            err = _short_error(
                r.stderr.decode("utf-8", errors="replace")
                or f"ffmpeg produced {len(r.stdout)} bytes but no Ogg stream header"
            )
            log.warning(
                "OGV diagnostic failed rc=%s ogg=%s url=%s err=%s",
                r.returncode,
                has_ogg_header,
                url[:180],
                err,
            )
            self._json({
                "ok": False,
                "stage": "ffmpeg",
                "returncode": r.returncode,
                "bytes": len(r.stdout),
                "error": err,
                "http_status": 502,
            })
            return

        settings = _profile_settings(profile, quality)
        self._json({
            "ok": True,
            "stage": "ready",
            "bytes": len(r.stdout),
            "settings": {
                "profile": settings["name"],
                "width": settings["width"],
                "height": settings["height"],
                "fps": settings["fps"],
                "video_quality": settings["ogv_q"],
                "audio_bitrate": settings["audio"],
            },
        })

    def _serve_ogv_direct(self, url: str, quality: int | None = None, seek_s: float = 0.0, profile: str | None = None):
        """Transcode a source to Ogg/Theora/Vorbis for ogv.js playback."""
        ff_proc: subprocess.Popen | None = None
        first_chunk = b""
        last_err = ""
        try:
            for attempt in range(1, 3):
                inputs, err = _resolve_ffmpeg_input_url(url, quality)
                if not inputs:
                    last_err = _short_error(err or "yt-dlp could not resolve a stream URL")
                    log.warning("OGV resolve failed attempt=%s url=%s quality=%s err=%s", attempt, url[:180], quality, last_err)
                    time.sleep(0.4)
                    continue

                ff_cmd = _build_ogv_ffmpeg_cmd(
                    inputs,
                    seek_s=seek_s,
                    profile=profile,
                    source_quality=quality,
                )
                ff_proc = subprocess.Popen(
                    ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                first_chunk, startup_err = self._read_process_startup(ff_proc, timeout_s=15.0)
                if first_chunk:
                    if not first_chunk.startswith(b"OggS"):
                        log.warning("OGV ffmpeg first bytes did not start with OggS url=%s", url[:180])
                    break

                if ff_proc.poll() is None:
                    try:
                        ff_proc.terminate()
                        ff_proc.wait(timeout=3)
                    except Exception:
                        pass
                rc = ff_proc.poll()
                last_err = _short_error(startup_err or f"ffmpeg produced no Ogg data before startup timeout (rc={rc})")
                log.warning("OGV ffmpeg startup failed attempt=%s rc=%s url=%s err=%s", attempt, rc, url[:180], last_err)
                ff_proc = None
                time.sleep(0.5)

            if not first_chunk or ff_proc is None:
                self._error(502, f"OGV ffmpeg startup failed: {last_err or 'no Ogg data produced'}")
                return

            if ff_proc.stderr is not None:
                threading.Thread(target=self._drain_pipe, args=(ff_proc.stderr,), daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "video/ogg")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            duration_s = _fetch_duration_s(url)
            if duration_s:
                self.send_header("X-Content-Duration", str(duration_s))
            self.end_headers()
            self.wfile.write(first_chunk)
            self.wfile.flush()
            while True:
                chunk = ff_proc.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if ff_proc and ff_proc.poll() is None:
                try:
                    ff_proc.terminate()
                except Exception:
                    pass

    def _serve_file_bytes(self, abs_path: str):
        """Serve a local media file directly over HTTP for native browser playback."""
        import mimetypes
        ext = os.path.splitext(abs_path)[1].lower()
        mime = mimetypes.types_map.get(ext, "video/mp4")
        try:
            size = os.path.getsize(abs_path)
        except OSError as e:
            self._error(500, str(e))
            return

        try:
            range_header = self.headers.get("Range", "")
            if range_header.startswith("bytes="):
                parts = range_header[6:].split("-")
                start = int(parts[0]) if parts[0] else 0
                end   = int(parts[1]) if len(parts) > 1 and parts[1] else size - 1
                end   = min(end, size - 1)
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(abs_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            else:
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(abs_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_local_media(self, rel_dir: str | None = None):
        base = os.path.abspath(LOCAL_MEDIA_DIR)
        if not os.path.isdir(base):
            self._error(503, f"Local media directory not found: {base}")
            return
        # Resolve the requested sub-directory (default: root)
        if rel_dir:
            target_dir = os.path.abspath(os.path.normpath(os.path.join(base, rel_dir)))
            if not (target_dir == base or target_dir.startswith(base + os.sep)):
                self._error(400, "Invalid directory path")
                return
        else:
            target_dir = base
        if not os.path.isdir(target_dir):
            self._error(404, "Directory not found")
            return
        current_rel = os.path.relpath(target_dir, base)
        if current_rel == ".":
            current_rel = ""
        folders = []
        files = []
        try:
            for name in sorted(os.listdir(target_dir), key=str.lower):
                full = os.path.join(target_dir, name)
                if os.path.islink(full):
                    full = os.path.realpath(full)
                rel = os.path.relpath(os.path.join(target_dir, name), base)
                if os.path.isdir(full):
                    folders.append({"name": name, "path": rel.replace(os.sep, "/")})
                elif os.path.isfile(full) and _has_supported_media_ext(full):
                    files.append({"name": name, "path": rel.replace(os.sep, "/")})
        except Exception as e:
            self._error(500, f"Failed to scan local media folder: {e}")
            return
        self._json({
            "base_dir": base,
            "current_dir": current_rel.replace(os.sep, "/"),
            "folders": folders,
            "files": files,
        })

    # ── Pluto TV channels ─────────────────────────────────────────────────────
    def _serve_pluto_channels(self, lang: str):
        channels, err = pluto_cache.get(lang)
        if not channels:
            if err:
                self._error(502, f"Pluto TV [{lang}] unavailable: {err}")
            else:
                self._error(503, "Pluto TV channel list not loaded yet, try again shortly")
            return
        meta = pluto_cache.get_meta(lang)
        self._json({
            "lang": lang,
            "country": meta.get("country", ""),
            "region": meta.get("region", ""),
            "xff": meta.get("xff", ""),
            "refresh_at": meta.get("refresh_at", 0),
            "channels": channels,
        })

    # ── Feed ──────────────────────────────────────────────────────────────────
    def _serve_feed(self, channel: str, limit: int):
        # Normalise: bare handle (@channel), channel URL, or plain name
        if channel.startswith("http://") or channel.startswith("https://"):
            url = channel
        elif channel.startswith("@"):
            url = f"https://www.youtube.com/{channel}/videos"
        else:
            url = f"https://www.youtube.com/@{channel}/videos"

        try:
            r = subprocess.run(
                [
                    "yt-dlp",
                    "--js-runtimes", "node",
                    "--flat-playlist",
                    "--playlist-end", str(limit),
                    "--print", "%(id)s\t%(title)s\t%(duration)s\t%(thumbnail)s\t%(webpage_url)s",
                    "--no-warnings",
                    "--quiet",
                    *_yt_lang_args(),
                    url,
                ],
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired:
            self._error(504, "yt-dlp timed out fetching feed")
            return
        except Exception as e:
            self._error(500, f"Feed fetch failed: {e}")
            return

        if r.returncode != 0:
            err = r.stderr.strip() or "yt-dlp returned non-zero exit code"
            self._error(502, f"Could not fetch channel feed: {err}")
            return

        videos = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t", 4)
            if len(parts) < 2:
                continue
            vid_id   = parts[0].strip()
            title    = parts[1].strip()
            duration = parts[2].strip() if len(parts) > 2 else ""
            thumb    = parts[3].strip() if len(parts) > 3 else ""
            webpage  = parts[4].strip() if len(parts) > 4 else ""
            if not vid_id or vid_id == "NA":
                continue
            # Use the canonical webpage URL when available; fall back to
            # building a YouTube URL from the ID for backwards compatibility.
            if webpage and webpage != "NA":
                video_url = webpage
            else:
                video_url = f"https://www.youtube.com/watch?v={vid_id}"
            # yt-dlp returns NA for thumbnails in flat-playlist mode on YouTube.
            # The thumbnail URL is deterministic from the video ID.
            if (not thumb or thumb == "NA") and "youtube.com" in video_url:
                thumb = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
            videos.append({
                "id":       vid_id,
                "title":    title,
                "duration": duration,
                "thumb":    thumb,
                "url":      video_url,
            })

        self._json({"channel": url, "videos": videos})

    def _serve_ytsearch(self, query: str, limit: int = 12):
        search_url = f"ytsearch{limit}:{query}"
        try:
            r = subprocess.run(
                [
                    "yt-dlp",
                    "--js-runtimes", "node",
                    "--flat-playlist",
                    "--print", "%(id)s\t%(title)s\t%(duration)s\t%(thumbnail)s\t%(webpage_url)s",
                    "--no-warnings",
                    "--quiet",
                    *_yt_lang_args(),
                    search_url,
                ],
                capture_output=True, text=True, timeout=25,
            )
        except subprocess.TimeoutExpired:
            self._error(504, "yt-dlp timed out during search")
            return
        except Exception as e:
            self._error(500, f"Search failed: {e}")
            return

        if r.returncode != 0:
            err = r.stderr.strip() or "yt-dlp returned non-zero exit code"
            self._error(502, f"Search failed: {err}")
            return

        videos = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t", 4)
            if len(parts) < 2:
                continue
            vid_id   = parts[0].strip()
            title    = parts[1].strip()
            duration = parts[2].strip() if len(parts) > 2 else ""
            thumb    = parts[3].strip() if len(parts) > 3 else ""
            webpage  = parts[4].strip() if len(parts) > 4 else ""
            if not vid_id or vid_id == "NA":
                continue
            if webpage and webpage != "NA":
                video_url = webpage
            else:
                video_url = f"https://www.youtube.com/watch?v={vid_id}"
            if (not thumb or thumb == "NA"):
                thumb = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
            videos.append({
                "id":       vid_id,
                "title":    title,
                "duration": duration,
                "thumb":    thumb,
                "url":      video_url,
            })

        self._json({"videos": videos})

    # ── MJPEG ─────────────────────────────────────────────────────────────────
    def _serve_mjpeg(self, stream: Stream, sync_ms: int = 0):
        registry.cleanup_done()
        delay_s = max(0.0, sync_ms / 1000.0)

        # Start pipeline if not already running
        if stream.status == "starting" and stream._ff_proc is None:
            threading.Thread(target=run_pipeline,
                             args=(stream,), daemon=True).start()

        # Wait up to 20s for first frame
        deadline = time.time() + 20
        with stream.frame_cond:
            while stream.frame is None and stream.status not in ("error", "done"):
                if time.time() > deadline:
                    self._error(504, "Timed out waiting for first frame")
                    return
                stream.frame_cond.wait(timeout=0.5)
        if delay_s > 0:
            # Let delayed playback have enough buffered frames so the first
            # shown frame starts near content time 0.
            with stream.frame_cond:
                while stream.status not in ("error", "done"):
                    if stream._frame_history:
                        oldest_ts = stream._frame_history[0][0]
                        newest_ts = stream._frame_history[-1][0]
                        if newest_ts - oldest_ts >= delay_s:
                            break
                    if time.time() > deadline:
                        break
                    stream.frame_cond.wait(timeout=0.5)

        if stream.status == "error":
            detail = f" ({stream.error_detail})" if stream.error_detail else ""
            self._error(502, f"Pipeline error: {stream.error}{detail}")
            return
        if stream.status == "done" and stream.frame is None:
            detail = f" ({stream.error_detail})" if stream.error_detail else ""
            self._error(502, f"Video ended before first frame was produced{detail}")
            return

        self.send_response(200)
        self.send_header("Content-Type",  "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection",    "keep-alive")
        self.send_header("X-Stream-Id",   stream.id)
        self.send_header("X-Stream-Title", self._safe_header_value(stream.title or ""))
        self.end_headers()

        log.info(f"[{stream.id}] Client connected: {self.client_address[0]}")
        last_frame = None

        try:
            while True:
                # Wait for FFmpeg to produce a new frame (wakes all clients immediately).
                with stream.frame_cond:
                    stream.frame_cond.wait(timeout=5.0)
                    if delay_s <= 0:
                        frame = stream.frame
                    else:
                        cutoff = time.time() - delay_s
                        frame = None
                        for ts, candidate in reversed(stream._frame_history):
                            if ts <= cutoff:
                                frame = candidate
                                break
                    status = stream.status

                if frame and frame is not last_frame:
                    last_frame = frame
                    boundary = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                    )
                    self.wfile.write(boundary + frame + b"\r\n")

                if status in ("error", "done"):
                    break

        except (BrokenPipeError, ConnectionResetError):
            log.info(f"[{stream.id}] Client disconnected: {self.client_address[0]}")

    @staticmethod
    def _launch_audio_pipeline(url: str, seek_s: float):
        """Spawn ffmpeg for audio starting at seek_s seconds.
        Always resolves a direct CDN URL first so ffmpeg reads at real-time
        pace and never buffers a whole long video into a pipe."""
        audio_fmt = "bestaudio[ext=m4a]/bestaudio"
        url_r = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--no-playlist",
             "-f", audio_fmt, "--get-url", "--quiet", url],
            capture_output=True, text=True, timeout=30,
        )
        direct_url = url_r.stdout.strip().splitlines()[0] if url_r.returncode == 0 else ""

        if direct_url:
            seek_args = ["-ss", str(int(seek_s))] if seek_s > 0 else []
            ff_cmd = [
                "ffmpeg", "-loglevel", "error",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "10",
                *seek_args,
                "-i", direct_url,
                "-vn",
                "-af", "aresample=async=1:first_pts=0",
                "-c:a", "mp3", "-b:a", "128k", "-f", "mp3", "pipe:1",
            ]
            ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            return None, ff_proc

        # Fallback: pipe yt-dlp → ffmpeg
        yt_cmd = [
            "yt-dlp", "--js-runtimes", "node", "--no-playlist",
            "-f", audio_fmt, "-o", "-", "--quiet", url,
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
        return yt_proc, ff_proc

    def _serve_audio(self, stream: Stream, sync_ms: int = AUDIO_DELAY_MS):
        log.info(f"[{stream.id}] Audio starting (audio_only={stream.audio_only})")

        # audio_only mode: pipeline uses _start_audio_buffer_any which always
        # fills _audio_chunks regardless of stream type. Start pipeline if needed.
        if stream.audio_only:
            if stream.status == "starting" and stream._audio_proc is None:
                threading.Thread(target=run_pipeline,
                                 args=(stream,), daemon=True).start()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                cursor = 0
                sent_bytes = 0
                while True:
                    stream._audio_ready.wait(timeout=5)
                    stream._audio_ready.clear()
                    with stream._audio_lock:
                        new_chunks = stream._audio_chunks[cursor:]
                        cursor += len(new_chunks)
                        done = stream._audio_done
                    for ch in new_chunks:
                        self.wfile.write(ch)
                        sent_bytes += len(ch)
                    self.wfile.flush()
                    if done and not new_chunks:
                        break
                log.info(f"[{stream.id}] Audio-only stream ended (bytes={sent_bytes})")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if _is_direct_stream(stream.url):
            # MJPEG mode: audio is captured into _audio_chunks by the muxed pipeline.
            # Start the pipeline here if /audio is requested before /stream.
            if stream.status == "starting" and stream._ff_proc is None:
                threading.Thread(target=run_pipeline,
                                 args=(stream,), daemon=True).start()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                cursor = 0
                sent_bytes = 0
                while True:
                    stream._audio_ready.wait(timeout=5)
                    stream._audio_ready.clear()
                    with stream._audio_lock:
                        new_chunks = stream._audio_chunks[cursor:]
                        cursor += len(new_chunks)
                        done = stream._audio_done
                    for ch in new_chunks:
                        self.wfile.write(ch)
                        sent_bytes += len(ch)
                    self.wfile.flush()
                    if done and not new_chunks:
                        break
                log.info(f"[{stream.id}] Direct audio ended (bytes={sent_bytes})")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # MJPEG mode, non-direct (YouTube/Twitch): independent audio pipeline
        yt_proc = None
        ff_proc = None
        try:
            yt_proc, ff_proc = self._launch_audio_pipeline(stream.url, seek_s=stream.seek_s)

            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            while True:
                chunk = ff_proc.stdout.read(16384)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            for proc in (ff_proc, yt_proc):
                if proc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _html(self, body: str, code: int = 200):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code: int = 200):
        data = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, msg: str):
        self._json({"error": msg, "code": code}, code)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Each request handled in its own thread (needed for concurrent MJPEG streams)."""
    daemon_threads = True
    allow_reuse_address = True


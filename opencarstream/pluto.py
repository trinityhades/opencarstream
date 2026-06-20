import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import *
from .config import _BROWSER_UA

class PlutoCache:
    def __init__(self):
        self._lock  = threading.Lock()
        self._by_lang: dict[str, list[dict]] = {}
        self._errors:  dict[str, str]        = {}
        # { lang: (device_id, session_token, stitcher_params, refresh_at) }
        self._sessions: dict[str, tuple[str, str, str, float]] = {}

    def get(self, lang: str) -> tuple[list[dict], str]:
        with self._lock:
            return list(self._by_lang.get(lang, [])), self._errors.get(lang, "")

    def get_meta(self, lang: str) -> dict[str, str | int]:
        """Return metadata for a language cache entry."""
        from urllib.parse import parse_qsl
        region, xff = self._lang_context(lang)
        with self._lock:
            sess = self._sessions.get(lang)
        if not sess:
            return {"country": "", "refresh_at": 0, "region": region, "xff": xff}
        _, _token, stitcher_params, refresh_at = sess
        country = ""
        for key, val in parse_qsl(stitcher_params, keep_blank_values=True):
            if key == "country":
                country = val
                break
        return {
            "country": country,
            "refresh_at": int(refresh_at),
            "region": region,
            "xff": xff,
        }

    def langs(self) -> list[str]:
        with self._lock:
            return list(self._by_lang.keys())

    @staticmethod
    def _lang_context(lang: str) -> tuple[str, str]:
        lang_key = (lang or "").strip().lower()
        region = PLUTO_REGION_MAP.get(lang_key, lang_key.upper() or "US")
        xff = PLUTO_XFF_MAP.get(lang_key, "")
        return region, xff

    @staticmethod
    def _apply_stitcher_params(hls_url: str, stitcher_params: str, session_token: str = "") -> str:
        """Merge Pluto stitcher query params into the channel HLS URL."""
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(hls_url)
        # Ensure /v2 prefix on path (Pluto requires /v2/stitch/hls/...)
        path = parts.path
        if path.startswith("/stitch/") and not path.startswith("/v2/"):
            path = "/v2" + path
        merged = dict(parse_qsl(parts.query, keep_blank_values=True))
        for k, v in parse_qsl(stitcher_params, keep_blank_values=True):
            merged[k] = v
        if session_token:
            merged["jwt"] = session_token
        merged["includeExtendedEvents"] = "true"
        merged["masterJWTPassthrough"] = "true"
        query = urlencode(merged, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, path, query, ""))

    def build_channel_url(
        self, lang: str, channel_id: str, force_refresh: bool = False
    ) -> tuple[str | None, str]:
        """
        Build a fresh Pluto playback URL for channel_id in lang.
        Returns (url, err). When url is None, err describes the failure.
        """
        if not channel_id:
            return None, "missing channel id"

        if force_refresh:
            self._fetch_lang(lang)

        with self._lock:
            channels = self._by_lang.get(lang, [])
            sess = self._sessions.get(lang)
            channel = next((c for c in channels if c.get("id") == channel_id), None)

        if channel is None:
            return None, f"channel '{channel_id}' not found for lang '{lang}'"
        if not sess:
            return None, f"Pluto TV [{lang}] session unavailable"

        _, session_token, stitcher_params, _ = sess
        hls_url = channel.get("hls_url", "")
        if not hls_url:
            return None, "channel has no HLS URL"
        return self._apply_stitcher_params(hls_url, stitcher_params, session_token), ""

    def _boot(self, lang: str) -> tuple[str, str, str, int] | None:
        """Call Pluto boot API and return (device_id, session_token, stitcher_params, refresh_in_sec)."""
        import urllib.request, uuid
        region, xff = self._lang_context(lang)
        device_id = str(uuid.uuid4())
        url = (
            f"https://boot.pluto.tv/v4/start"
            f"?appName=web&appVersion={PLUTO_APP_VERSION}"
            f"&deviceDNT=0&deviceId={device_id}&deviceMake=chrome"
            f"&deviceModel=web&deviceType=web&deviceVersion=122.0.0"
            f"&clientModelNumber=1.0.0&serverSideAds=false"
            f"&drmCapabilities=widevine%3AL3&blockingMode="
            f"&marketingRegion={region}&clientID={device_id}"
        )
        try:
            headers = {
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json",
                "Referer": "https://pluto.tv/",
                "Origin": "https://pluto.tv",
            }
            if xff:
                headers["X-Forwarded-For"] = xff
            req = urllib.request.Request(
                url, headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            log.warning(f"Pluto TV [{lang}] boot HTTP {e.code}: {body[:500]}")
            return None
        except Exception as e:
            log.warning(f"Pluto TV [{lang}] boot failed: {e}")
            return None
        log.info(f"Pluto TV [{lang}] boot response keys: {list(data.keys())}")
        session_token = data.get("sessionToken", "")
        params = data.get("stitcherParams", "")
        refresh = int(data.get("refreshInSec", 28800))
        if not params:
            log.warning(f"Pluto TV [{lang}] boot returned no stitcherParams. Full response: {raw[:1000]}")
            return None
        return device_id, session_token, params, refresh

    def _fetch_lang(self, lang: str):
        import urllib.request
        boot = self._boot(lang)
        if boot is None:
            with self._lock:
                self._errors[lang] = "boot API failed"
            return
        device_id, session_token, stitcher_params, refresh_in = boot

        _, xff = self._lang_context(lang)
        api_url = (
            f"https://api.pluto.tv/v2/channels"
            f"?lang={lang}&deviceType=web&deviceId={device_id}"
            f"&appName=web&appVersion={PLUTO_APP_VERSION}&clientTime=0"
        )
        try:
            headers = {
                "User-Agent": _BROWSER_UA,
                "Referer": "https://pluto.tv/",
                "Origin": "https://pluto.tv",
            }
            if session_token:
                headers["Authorization"] = f"Bearer {session_token}"
            if xff:
                headers["X-Forwarded-For"] = xff
            req = urllib.request.Request(
                api_url, headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                raw = json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            with self._lock:
                self._errors[lang] = f"HTTP {e.code}"
            log.warning(f"Pluto TV [{lang}] channels HTTP {e.code}: {body[:500]}")
            return
        except Exception as e:
            with self._lock:
                self._errors[lang] = str(e)
            log.warning(f"Pluto TV [{lang}] channels fetch failed: {e}")
            return
        log.info(f"Pluto TV [{lang}] channels response: {len(raw) if isinstance(raw, list) else type(raw).__name__}")

        channels = []
        for ch in raw:
            if not ch.get("isStitched"):
                continue
            urls = ch.get("stitched", {}).get("urls", [])
            hls_url = next(
                (u.get("url", "") for u in urls if u.get("type") == "hls"),
                None,
            )
            if not hls_url:
                continue
            # Keep the original URL template and inject fresh stitcher params.
            stitched_url = self._apply_stitcher_params(hls_url, stitcher_params, session_token)
            channels.append({
                "id":       ch.get("_id", ""),
                "name":     ch.get("name", ""),
                "category": ch.get("category", ""),
                "hls_url":  hls_url,
                "url":      stitched_url,
            })
        channels.sort(key=lambda c: (c["category"], c["name"]))

        with self._lock:
            self._by_lang[lang] = channels
            self._errors.pop(lang, None)
            self._sessions[lang] = (device_id, session_token, stitcher_params,
                                    time.time() + refresh_in)
        meta = self.get_meta(lang)
        log.info(
            f"Pluto TV [{lang}] region={meta.get('region')} country={meta.get('country')} "
            f"xff={meta.get('xff') or '-'}: loaded {len(channels)} channels "
            f"(refresh in {refresh_in//3600}h)"
        )

    def refresh_all(self):
        for lang in PLUTO_LANGS:
            self._fetch_lang(lang)

    def start_background_refresh(self):
        def _loop():
            while True:
                now = time.time()
                for lang in PLUTO_LANGS:
                    with self._lock:
                        _, _, _, refresh_at = self._sessions.get(lang, ("", "", "", 0))
                    if now >= refresh_at:
                        self._fetch_lang(lang)
                time.sleep(300)  # check every 5 min
        threading.Thread(target=_loop, daemon=True).start()


pluto_cache = PlutoCache()

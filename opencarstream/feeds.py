from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import subprocess
import threading
import time
from urllib.request import Request, urlopen

from .config import *
from .helpers import _has_supported_iptv_list_ext, _yt_lang_args

_home_feed_cache: dict = {"videos": [], "built_at": 0.0}
_home_feed_lock  = threading.Lock()


def _load_home_feed_disk_cache() -> None:
    """Load persisted home feed cache from disk on startup."""
    try:
        if os.path.isfile(HOME_FEED_CACHE_FILE):
            with open(HOME_FEED_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            videos = data.get("videos") or []
            if videos and data.get("built_at"):
                ts_dated = [v for v in videos if v.get("published_ts")]
                ts_dated.sort(key=lambda v: v["published_ts"], reverse=True)
                remaining = [v for v in videos if not v.get("published_ts")]
                dated   = [v for v in remaining if v.get("upload_date")]
                undated = [v for v in remaining if not v.get("upload_date")]
                dated.sort(key=lambda v: v["upload_date"], reverse=True)
                undated.sort(key=lambda v: v.get("fetch_idx", 0))
                videos = ts_dated + dated + undated
                _home_feed_cache["videos"]   = videos
                _home_feed_cache["built_at"] = float(data["built_at"])
                log.info(f"Loaded home feed cache from disk: {len(videos)} videos ({len(dated)} dated)")
    except Exception as e:
        log.warning(f"Could not load home feed disk cache: {e}")


def _save_home_feed_disk_cache(videos: list[dict], built_at: float) -> None:
    """Persist home feed cache to disk so it survives container restarts."""
    try:
        os.makedirs(os.path.dirname(HOME_FEED_CACHE_FILE), exist_ok=True)
        tmp = HOME_FEED_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"videos": videos, "built_at": built_at}, f)
        os.replace(tmp, HOME_FEED_CACHE_FILE)
    except Exception as e:
        log.warning(f"Could not save home feed disk cache: {e}")


_CHANNEL_ID_CACHE: dict[str, str] = {}
_CHANNEL_ID_LOCK = threading.Lock()
_UC_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")
_YT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _resolve_channel_id(channel_url: str) -> str:
    """Return the UC... channel ID for a YouTube channel URL, or '' on failure. Cached."""
    if not channel_url:
        return ""
    with _CHANNEL_ID_LOCK:
        if channel_url in _CHANNEL_ID_CACHE:
            return _CHANNEL_ID_CACHE[channel_url]
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", channel_url)
    cid = m.group(1) if m else ""
    if not cid:
        try:
            req = Request(channel_url, headers={"User-Agent": _YT_UA, "Accept-Language": "en-US,en;q=0.9"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read(400_000).decode("utf-8", errors="replace")
            m = _UC_RE.search(html)
            cid = m.group(0) if m else ""
        except Exception:
            cid = ""
    with _CHANNEL_ID_LOCK:
        _CHANNEL_ID_CACHE[channel_url] = cid
    return cid


def _fetch_rss_published(channel_id: str) -> dict[str, str]:
    """Return {video_id: ISO-8601 published} for a channel via YouTube's Atom feed."""
    if not channel_id:
        return {}
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = Request(url, headers={"User-Agent": _YT_UA})
        with urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return {}
    out: dict[str, str] = {}
    # Atom entries are small enough to parse with a regex pair.
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, flags=re.DOTALL):
        vid_m = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", entry)
        pub_m = re.search(r"<published>([^<]+)</published>", entry)
        if vid_m and pub_m:
            out[vid_m.group(1).strip()] = pub_m.group(1).strip()
    return out


def _fetch_channel_videos(channel_url: str, channel_name: str, n: int) -> list[dict]:
    """Fetch the n most recent videos for one channel. Returns [] on any failure."""
    try:
        r = subprocess.run(
            [
                "yt-dlp",
                "--js-runtimes", "node",
                "--flat-playlist",
                "--playlist-end", str(n),
                "--print", "%(id)s\t%(title)s\t%(duration)s\t%(thumbnail)s\t%(webpage_url)s\t%(upload_date)s",
                "--no-warnings",
                "--quiet",
                *_yt_lang_args(),
                channel_url,
            ],
            capture_output=True, text=True, timeout=25,
        )
    except Exception:
        return []

    if r.returncode != 0:
        return []

    videos = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t", 5)
        if len(parts) < 2:
            continue
        vid_id      = parts[0].strip()
        title       = parts[1].strip()
        duration    = parts[2].strip() if len(parts) > 2 else ""
        thumb       = parts[3].strip() if len(parts) > 3 else ""
        webpage     = parts[4].strip() if len(parts) > 4 else ""
        upload_date = parts[5].strip() if len(parts) > 5 else ""
        if not vid_id or vid_id == "NA":
            continue
        # Skip Shorts: duration <= 60s, or webpage URL is a /shorts/ link.
        try:
            if duration and duration != "NA" and float(duration) <= 60:
                continue
        except ValueError:
            pass
        if webpage and "/shorts/" in webpage:
            continue
        video_url = webpage if (webpage and webpage != "NA") else f"https://www.youtube.com/watch?v={vid_id}"
        if not thumb or thumb == "NA":
            thumb = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
        videos.append({
            "id":          vid_id,
            "title":       title,
            "duration":    duration,
            "thumb":       thumb,
            "url":         video_url,
            "upload_date": upload_date if upload_date and upload_date != "NA" else "",
            "channel":     channel_name,
            "channel_url": channel_url,
            "fetch_idx":   len(videos),  # position within channel (0 = newest)
        })

    # Enrich with precise publish timestamps from the channel's Atom feed.
    # This is how we get a reliable cross-channel sort order for the Home feed,
    # since --flat-playlist almost never returns upload_date for YouTube tabs.
    if videos:
        cid = _resolve_channel_id(channel_url)
        rss = _fetch_rss_published(cid) if cid else {}
        if rss:
            for v in videos:
                ts = rss.get(v["id"])
                if ts:
                    v["published_ts"] = ts            # ISO-8601, sortable as string
                    if not v.get("upload_date"):
                        v["upload_date"] = ts[:10].replace("-", "")  # YYYYMMDD
    return videos


def _build_home_feed(channels: list[dict]) -> list[dict]:
    """Fetch recent videos from all channels concurrently and return sorted list."""
    all_videos: list[dict] = []
    with ThreadPoolExecutor(max_workers=HOME_FEED_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_channel_videos, ch["url"], ch["name"], HOME_FEED_PER_CHANNEL): ch
            for ch in channels
        }
        for future in as_completed(futures):
            try:
                all_videos.extend(future.result())
            except Exception:
                pass

    # Prefer precise RSS publish timestamps when available so videos from
    # different channels interleave by true recency, like YouTube's home feed.
    ts_dated = [v for v in all_videos if v.get("published_ts")]
    ts_dated.sort(key=lambda v: v["published_ts"], reverse=True)
    remaining = [v for v in all_videos if not v.get("published_ts")]
    dated   = [v for v in remaining if v.get("upload_date")]
    undated = [v for v in remaining if not v.get("upload_date")]
    dated.sort(key=lambda v: v["upload_date"], reverse=True)  # newest first

    # True round-robin interleave for undated videos: group by channel_url,
    # sort each group by fetch_idx (0=newest), then zip across channels so
    # position 0 is newest from every channel before showing position 1, etc.
    by_channel: dict[str, list] = {}
    for v in undated:
        key = v.get("channel_url") or v.get("channel") or ""
        by_channel.setdefault(key, []).append(v)
    for lst in by_channel.values():
        lst.sort(key=lambda v: v.get("fetch_idx", 0))
    interleaved: list[dict] = []
    channels_lists = list(by_channel.values())
    max_len = max((len(l) for l in channels_lists), default=0)
    for i in range(max_len):
        for lst in channels_lists:
            if i < len(lst):
                interleaved.append(lst[i])

    return ts_dated + dated + interleaved


def _scan_iptv_lists() -> tuple[str, list[dict[str, str]], str]:
    base = os.path.abspath(IPTV_LISTS_DIR)
    if not os.path.isdir(base):
        return base, [], f"IPTV lists directory not found: {base}"

    lists: list[dict[str, str]] = []
    try:
        for root, _, names in os.walk(base, followlinks=True):
            for filename in names:
                full = os.path.join(root, filename)
                if not os.path.isfile(full):
                    continue
                if not _has_supported_iptv_list_ext(full):
                    continue
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                name = os.path.splitext(os.path.basename(rel))[0]
                lists.append({"id": rel, "name": name, "path": rel})
    except Exception as e:
        return base, [], f"Failed to scan IPTV lists folder: {e}"

    lists.sort(key=lambda x: x["path"].lower())
    return base, lists, ""


__all__ = [name for name in globals() if not name.startswith("__")]

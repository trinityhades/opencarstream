import json
import os
import signal
import sys
import threading
import time

from .config import *
from .feeds import (
    _build_home_feed,
    _home_feed_cache,
    _home_feed_lock,
    _load_home_feed_disk_cache,
    _save_home_feed_disk_cache,
)
from .http_server import Handler, ThreadedHTTPServer
from .media import _ffmpeg_hwaccel_args, _select_h264_encoder
from .pluto import pluto_cache
from .state import registry

def main():
    log.info("═" * 52)
    log.info("  OpenCarStream MJPEG Streamer")
    log.info(f"  Listening on http://{HOST}:{PORT}")
    log.info(f"  FPS={MJPEG_FPS}  Quality={FFMPEG_QUALITY}  "
             f"Res={STREAM_WIDTH}×{STREAM_HEIGHT}  MaxStreams={MAX_STREAMS}")
    log.info(f"  MP4 encoder={_select_h264_encoder()}  HW accel={' '.join(_ffmpeg_hwaccel_args()) or 'none'}")
    log.info(f"  OGV default profile={OGV_DEFAULT_PROFILE}  base={OGV_WIDTH}×{OGV_HEIGHT}@{OGV_FPS}")
    log.info("═" * 52)

    pluto_cache.start_background_refresh()
    _load_home_feed_disk_cache()

    def _stream_reaper():
        while True:
            time.sleep(10)
            registry.cleanup_inactive()
            registry.cleanup_old()
    threading.Thread(target=_stream_reaper, daemon=True).start()

    def _home_feed_refresher():
        """Build home feed on startup then refresh every 6 hours."""
        # Small delay so the server is ready before the first fetch
        time.sleep(5)
        while True:
            if not os.path.isfile(SUBSCRIPTIONS_FILE):
                time.sleep(300)
                continue
            try:
                with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                channels = data.get("channels", [])
            except Exception:
                channels = []
            if channels:
                log.info(f"Background home feed refresh ({len(channels)} channels)…")
                t0 = time.time()
                videos = _build_home_feed(channels)
                built_at = time.time()
                with _home_feed_lock:
                    _home_feed_cache["videos"]   = videos
                    _home_feed_cache["built_at"] = built_at
                _save_home_feed_disk_cache(videos, built_at)
                log.info(f"Background home feed done: {len(videos)} videos in {built_at-t0:.1f}s")
            time.sleep(6 * 3600)
    threading.Thread(target=_home_feed_refresher, daemon=True).start()

    server = ThreadedHTTPServer((HOST, PORT), Handler)

    def _stop(sig, frame):
        log.info("Shutting down…")
        for s in registry.all_streams():
            s.stop()
        try:
            server.server_close()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)
    server.serve_forever()


if __name__ == "__main__":
    main()

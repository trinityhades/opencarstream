from collections import deque
import threading
import time

from .config import *

class Stream:
    def __init__(self, stream_id: str, url: str, quality: int | None = None):
        self.id         = stream_id
        self.url        = url
        self.quality    = quality
        self.lock       = threading.Lock()
        self.frame      : bytes | None = None
        self.status     = "starting"   # starting | streaming | error | done
        self.title      = ""
        self.error      = ""
        self.error_detail = ""
        self.created_at = time.time()
        self.last_used  = time.time()
        self._yt_proc   = None
        self._ff_proc   = None
        self._audio_proc: object | None = None   # separate audio ffmpeg for direct streams
        self.seek_s     : float = 0.0
        self.fps        : float = float(MJPEG_FPS)
        self.started_at : float | None = None
        self.first_frame_at: float | None = None
        # Audio ring-buffer for direct streams (HLS/MPEG-TS) where a second
        # connection to the source is not viable.
        self._audio_lock   = threading.Lock()
        self._audio_chunks : list[bytes] = []
        self._audio_ready  = threading.Event()
        self._audio_done   = False
        self._frame_history = deque(maxlen=max(MJPEG_FPS * 12, 120))
        self.frame_cond     = threading.Condition(self.lock)  # notified whenever a new frame arrives
        self.audio_only     = False  # when True, skip MJPEG pipeline and run audio only

    def stop(self):
        procs = [p for p in [self._ff_proc, self._yt_proc, self._audio_proc] if p]
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        for proc in procs:
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
        self._ff_proc     = None
        self._yt_proc     = None
        self._audio_proc  = None
        with self._audio_lock:
            self._audio_done = True
        self._audio_ready.set()
        with self.frame_cond:
            self.frame_cond.notify_all()
        with self.lock:
            self._frame_history.clear()

    def to_dict(self):
        return {
            "id":     self.id,
            "url":    self.url,
            "quality": self.quality,
            "started_at": self.started_at,
            "status": self.status,
            "title":  self.title,
            "error":  self.error,
            "error_detail": self.error_detail,
            "age_s":  round(time.time() - self.created_at),
            "fps":    self.fps,
            "seek_s": self.seek_s,
        }


# ── Stream registry ───────────────────────────────────────────────────────────
class Registry:
    def __init__(self):
        self._lock    = threading.Lock()
        self._streams : dict[str, Stream] = {}
        self._counter = 0

    def _make_id(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    def get_or_create(
        self,
        url: str,
        quality: int | None = None,
        reuse_existing: bool = True,
    ) -> Stream:
        with self._lock:
            if reuse_existing:
                # Return existing live stream for same URL + quality profile
                for s in self._streams.values():
                    if (
                        s.url == url
                        and s.quality == quality
                        and s.status in ("starting", "streaming")
                    ):
                        s.last_used = time.time()
                        return s

            # Evict oldest if at capacity
            if len(self._streams) >= MAX_STREAMS:
                oldest = min(self._streams.values(), key=lambda s: s.last_used)
                log.info(f"Evicting stream {oldest.id} ({oldest.url[:60]})")
                oldest.stop()
                del self._streams[oldest.id]

            sid    = self._make_id()
            stream = Stream(sid, url, quality=quality)
            self._streams[sid] = stream
            return stream

    def get(self, sid: str) -> Stream | None:
        with self._lock:
            return self._streams.get(sid)

    def all_streams(self) -> list[Stream]:
        with self._lock:
            return list(self._streams.values())

    def cleanup_done(self):
        with self._lock:
            dead = [sid for sid, s in self._streams.items()
                    if s.status in ("error", "done")
                    and time.time() - s.last_used > 60]
            for sid in dead:
                self._streams[sid].stop()
                del self._streams[sid]
                log.info(f"Cleaned up stream {sid}")

    def cleanup_old(self):
        """Stop and remove streams that have been active longer than MAX_STREAM_AGE_S."""
        cutoff = time.time() - MAX_STREAM_AGE_S
        with self._lock:
            old = [sid for sid, s in self._streams.items()
                   if s.created_at < cutoff and s.status in ("starting", "streaming")]
            for sid in old:
                log.info(f"Auto-stopping stream {sid} (age limit reached)")
                self._streams[sid].stop()
                self._streams[sid].status = "done"
                del self._streams[sid]


registry = Registry()

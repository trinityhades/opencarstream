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
        self.active_clients = 0
        self.last_client_at = time.time()
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
            self.active_clients = 0

    def add_client(self):
        with self.lock:
            self.active_clients += 1
            now = time.time()
            self.last_client_at = now
            self.last_used = now

    def remove_client(self):
        with self.lock:
            if self.active_clients > 0:
                self.active_clients -= 1
            now = time.time()
            self.last_client_at = now
            self.last_used = now

    def touch(self):
        with self.lock:
            now = time.time()
            self.last_used = now
            if self.active_clients > 0:
                self.last_client_at = now

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
            "clients": self.active_clients,
        }


# ── Stream registry ───────────────────────────────────────────────────────────
class Registry:
    def __init__(self):
        self._lock    = threading.Lock()
        self._streams : dict[str, Stream] = {}
        self._viewer_streams: dict[str, str] = {}
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

    def bind_viewer(self, viewer_id: str | None, stream: Stream | None):
        if not viewer_id:
            return
        old_stream = None
        with self._lock:
            old_sid = self._viewer_streams.get(viewer_id)
            new_sid = stream.id if stream is not None else None
            if old_sid and old_sid != new_sid:
                old_stream = self._streams.get(old_sid)
            if stream is None:
                self._viewer_streams.pop(viewer_id, None)
            else:
                self._viewer_streams[viewer_id] = stream.id
                stream.last_used = time.time()
        if old_stream is not None:
            log.info(f"Replacing viewer stream {old_stream.id} for viewer={viewer_id[:12]}")
            old_stream.stop()
            with self._lock:
                if self._streams.get(old_stream.id) is old_stream:
                    old_stream.status = "done"
                    del self._streams[old_stream.id]

    def touch_stream(self, stream: Stream):
        stream.touch()

    def release_stream_if_inactive(self, stream: Stream, idle_timeout_s: int = STREAM_IDLE_TIMEOUT_S):
        if stream.active_clients > 0:
            return
        now = time.time()
        if now - stream.last_client_at < idle_timeout_s:
            return
        with self._lock:
            current = self._streams.get(stream.id)
            if current is not stream:
                return
            if stream.active_clients > 0 or now - stream.last_client_at < idle_timeout_s:
                return
            viewer_ids = [vid for vid, sid in self._viewer_streams.items() if sid == stream.id]
            for vid in viewer_ids:
                self._viewer_streams.pop(vid, None)
            log.info(f"Auto-stopping inactive stream {stream.id}")
            stream.stop()
            stream.status = "done"
            del self._streams[stream.id]

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
                for viewer_id, mapped_sid in list(self._viewer_streams.items()):
                    if mapped_sid == sid:
                        del self._viewer_streams[viewer_id]
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
                for viewer_id, mapped_sid in list(self._viewer_streams.items()):
                    if mapped_sid == sid:
                        del self._viewer_streams[viewer_id]
                del self._streams[sid]

    def cleanup_inactive(self, idle_timeout_s: int = STREAM_IDLE_TIMEOUT_S):
        stale: list[Stream] = []
        now = time.time()
        with self._lock:
            for stream in self._streams.values():
                if stream.status not in ("starting", "streaming"):
                    continue
                if stream.active_clients > 0:
                    continue
                if now - stream.last_client_at >= idle_timeout_s:
                    stale.append(stream)
        for stream in stale:
            self.release_stream_if_inactive(stream, idle_timeout_s=idle_timeout_s)


registry = Registry()

import json
import os
import threading

from .config import *

_ace_streams_lock = threading.Lock()

def _load_ace_streams() -> list[dict]:
    if not os.path.isfile(ACE_STREAMS_FILE):
        return []
    try:
        with open(ACE_STREAMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_ace_streams(streams: list[dict]) -> None:
    os.makedirs(os.path.dirname(ACE_STREAMS_FILE) or ".", exist_ok=True)
    with _ace_streams_lock:
        with open(ACE_STREAMS_FILE, "w", encoding="utf-8") as f:
            json.dump(streams, f, indent=2)


_favorites_lock = threading.Lock()

def _load_favorites() -> list[str]:
    """Return list of favorited channel URLs."""
    if not os.path.isfile(FAVORITES_FILE):
        return []
    try:
        with open(FAVORITES_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_favorites(urls: list[str]) -> None:
    os.makedirs(os.path.dirname(FAVORITES_FILE) or ".", exist_ok=True)
    with _favorites_lock:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(urls, f, indent=2)


_progress_lock = threading.Lock()

def _load_progress() -> dict:
    """Return {url: {pos_s, saved_at}} dict."""
    if not os.path.isfile(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_progress(data: dict) -> None:
    os.makedirs(os.path.dirname(PROGRESS_FILE) or ".", exist_ok=True)
    with _progress_lock:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


__all__ = [name for name in globals() if not name.startswith("__")]

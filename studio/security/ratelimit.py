"""Small in-process token buckets (single server process — see DEPLOY.md)."""
import threading
import time

from fastapi import HTTPException

_buckets: dict = {}
_lock = threading.Lock()


def hit(key: str, capacity: int, per_second: float, what: str = 'requests'):
    """Allow bursts of ``capacity`` and a sustained ``per_second``; 429 otherwise."""
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (float(capacity), now))
        tokens = min(float(capacity), tokens + (now - last) * per_second)
        if tokens < 1:
            _buckets[key] = (tokens, now)
            raise HTTPException(429, f'Too many {what} — slow down a little.')
        _buckets[key] = (tokens - 1, now)
        if len(_buckets) > 20000:
            for k in list(_buckets)[:10000]: _buckets.pop(k, None)


def user_key(prefix: str) -> str:
    from .context import current_user
    u = current_user.get()
    return f"{prefix}:{u['id'] if u else 'anon'}"

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from threading import BoundedSemaphore
from time import time

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.observability import event


def init_usage():
    path = get_settings().usage_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=2)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS usage (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        con.commit()


def reserve_request(request, kind):
    settings = get_settings()
    minute = int(time() // 60)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    # Use the ASGI peer; forwarded headers must be verified by the deployment proxy.
    peer = request.client.host if request.client else "unknown"
    client = sha256(peer.encode()).hexdigest()
    buckets = [(f"minute:{minute}:{kind}:{client}",
                settings.chat_requests_per_minute if kind == "chat" else 3)]
    if kind == "chat":
        buckets.append((f"day:{day}", settings.daily_chat_limit))
        buckets.append((f"month:{month}:chat", settings.monthly_chat_limit))
    elif kind == "pdf":
        buckets.extend([(f"pdf-day:{day}", 20), (f"month:{month}:pdf", 100)])
    try:
        with closing(sqlite3.connect(settings.usage_db_path, timeout=2)) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM usage WHERE bucket LIKE 'minute:%' AND bucket < ?", (f"minute:{minute}:",))
            con.execute("DELETE FROM usage WHERE bucket LIKE 'day:%' AND bucket < ?", (f"day:{day}",))
            con.execute("DELETE FROM usage WHERE bucket LIKE 'pdf-day:%' AND bucket < ?", (f"pdf-day:{day}",))
            con.execute("DELETE FROM usage WHERE bucket LIKE 'month:%' AND bucket < ?", (f"month:{month}:",))
            for bucket, limit in buckets:
                row = con.execute("SELECT count FROM usage WHERE bucket = ?", (bucket,)).fetchone()
                if row and row[0] >= limit:
                    if bucket.startswith("month:"):
                        next_month = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1,
                                              tzinfo=timezone.utc)
                        scope, seconds = "monthly", int((next_month - now).total_seconds()) + 1
                    elif bucket.startswith(("day:", "pdf-day:")):
                        scope, seconds = "daily", int(86400 - time() % 86400) + 1
                    else:
                        scope, seconds = "minute", int((minute + 1) * 60 - time()) + 1
                    seconds = max(1, seconds)
                    event("request_rate_limited", kind=kind, scope=scope, retry_after=seconds)
                    message = (f"The demo's {scope} limit has been reached."
                               if scope != "minute" else "Too many requests. Please try again shortly.")
                    raise HTTPException(429, message, headers={"Retry-After": str(seconds)})
            for bucket, limit in buckets:
                con.execute("INSERT INTO usage VALUES (?, 1) ON CONFLICT(bucket) DO UPDATE SET count=count+1",
                            (bucket,))
            con.commit()
    except sqlite3.Error as exc:
        raise HTTPException(503, "The demo is temporarily unavailable. Please try again.") from exc


@lru_cache(maxsize=2)
def slots(kind):
    return BoundedSemaphore(get_settings().max_concurrent_chats if kind == "chat" else 1)


@contextmanager
def request_slot(kind):
    semaphore = slots(kind)
    if not semaphore.acquire(blocking=False):
        event("request_busy", kind=kind)
        raise HTTPException(503, "The demo is busy. Please try again shortly.", headers={"Retry-After": "5"})
    try:
        yield
    finally:
        semaphore.release()

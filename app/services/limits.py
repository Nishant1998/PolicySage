from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from time import time

import psycopg
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.observability import event
from app.db.connection import connect


def init_usage():
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("policysage:usage-schema",))
        conn.execute("CREATE TABLE IF NOT EXISTS policysage_usage (bucket text PRIMARY KEY, count integer NOT NULL)")


def reserve_request(request, kind):
    settings = get_settings()
    minute = int(time() // 60)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    peer = request.client.host if request.client else "unknown"
    client = sha256(peer.encode()).hexdigest()
    buckets = [(f"minute:{minute}:{kind}:{client}",
                settings.chat_requests_per_minute if kind == "chat" else 3)]
    if kind == "chat":
        buckets.extend([(f"day:{day}", settings.daily_chat_limit),
                        (f"month:{month}:chat", settings.monthly_chat_limit)])
    elif kind == "pdf":
        buckets.extend([(f"pdf-day:{day}", 20), (f"month:{month}:pdf", 100)])
    try:
        with connect() as conn:
            # Serialize quota reservations, including missing rows, across all containers.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("policysage:usage",))
            for prefix, cutoff in (("minute:", f"minute:{minute}:"), ("day:", f"day:{day}"),
                                   ("pdf-day:", f"pdf-day:{day}"), ("month:", f"month:{month}:")):
                conn.execute("DELETE FROM policysage_usage WHERE bucket LIKE %s AND bucket < %s", (prefix + "%", cutoff))
            for bucket, limit in buckets:
                row = conn.execute("SELECT count FROM policysage_usage WHERE bucket = %s", (bucket,)).fetchone()
                if row and row["count"] >= limit:
                    if bucket.startswith("month:"):
                        next_month = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)
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
            for bucket, _ in buckets:
                conn.execute("INSERT INTO policysage_usage VALUES (%s, 1) ON CONFLICT (bucket) DO UPDATE SET count=policysage_usage.count+1", (bucket,))
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "The demo is temporarily unavailable. Please try again.") from exc


@contextmanager
def request_slot(kind):
    count = get_settings().max_concurrent_chats if kind == "chat" else 1
    try:
        conn = connect(autocommit=True)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "The demo is temporarily unavailable. Please try again.") from exc
    try:
        acquired = False
        for slot in range(count):
            key = f"policysage:slot:{kind}:{slot}"
            if conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked", (key,)).fetchone()["locked"]:
                acquired = True
                break
        if not acquired:
            event("request_busy", kind=kind)
            raise HTTPException(503, "The demo is busy. Please try again shortly.", headers={"Retry-After": "5"})
        yield
    finally:
        conn.close()

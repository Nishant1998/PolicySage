import json
import sqlite3
from hashlib import sha256
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings


def init_db() -> None:
    path = get_settings().audit_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS query_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                source_used TEXT NOT NULL,
                trace_json TEXT NOT NULL
            )"""
        )
        con.commit()


def write_audit(question: str, source_used: str, trace: list[str]) -> None:
    with closing(sqlite3.connect(get_settings().audit_db_path)) as con:
        con.execute(
            "INSERT INTO query_audit(created_at, question, source_used, trace_json) VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "sha256:" + sha256(question.encode()).hexdigest(),
                source_used,
                json.dumps(trace, ensure_ascii=False),
            ),
        )
        con.commit()

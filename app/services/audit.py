import json
from datetime import datetime, timezone
from hashlib import sha256

from app.db.connection import connect


def init_db() -> None:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("policysage:audit-schema",))
        conn.execute("""CREATE TABLE IF NOT EXISTS policysage_query_audit (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at timestamptz NOT NULL,
            question_hash text NOT NULL,
            source_used text NOT NULL,
            trace_json jsonb NOT NULL
        )""")


def write_audit(question: str, source_used: str, trace: list[str]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO policysage_query_audit(created_at, question_hash, source_used, trace_json) VALUES (%s, %s, %s, %s::jsonb)",
            (datetime.now(timezone.utc), "sha256:" + sha256(question.encode()).hexdigest(),
             source_used, json.dumps(trace, ensure_ascii=False)),
        )

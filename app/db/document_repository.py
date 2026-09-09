from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from app.core.config import get_settings
from app.core.observability import traced_operation
from app.db.connection import connect

PROCESSING = ("parsing", "chunking", "indexing", "verifying")
CATALOGUE_FIELDS = ("source_url", "insurer", "category", "product_name", "document_type",
                    "uins", "effective_from")
_snapshot = ContextVar("kb_snapshot", default=None)


@traced_operation("postgres_active_revisions")
def active_revisions():
    with connect() as conn:
        rows = conn.execute(
            """SELECT id::text AS id, document_id::text AS document_id, id::text AS document_revision, sha256, chunk_count, embedding_model, name AS document_title,
                      insurer, product_name, uins AS uin, category, document_type, source_url,
                      effective_from::text AS effective_from
               FROM documents WHERE status='active' AND NOT review_required
                 AND withdrawn_at IS NULL ORDER BY id"""
        ).fetchall()
    model = get_settings().embedding_model
    if any(row["embedding_model"] not in (None, model) for row in rows):
        raise RuntimeError("Published KB vectors use a different embedding model.")
    return {row["id"]: row for row in rows}


@contextmanager
def retrieval_snapshot():
    # Keep one snapshot per chat, loaded only if the router chooses KB search.
    token = _snapshot.set(lru_cache(maxsize=1)(active_revisions))
    try:
        yield
    finally:
        _snapshot.reset(token)


def current_revisions():
    load_snapshot = _snapshot.get()
    return active_revisions() if load_snapshot is None else load_snapshot()


def document_for_source(conn, source):
    return conn.execute('SELECT document_id FROM documents WHERE source_path=%s LIMIT 1', (source,)).fetchone()


def latest_revision(conn, document_id):
    return conn.execute(
        """SELECT *, updated_at < now() - interval '10 minutes' AS upload_stale
            FROM documents WHERE document_id=%s
            ORDER BY version DESC LIMIT 1""",
        (document_id,),
    ).fetchone()


def retire_pending(conn, revision_id):
    conn.execute(
        """UPDATE documents SET status='cleanup_pending', last_error=NULL,
                updated_at=statement_timestamp()
            WHERE id=%s AND status IN
                ('staged', 'queued', 'parsing', 'chunking', 'indexing', 'verifying', 'failed')
                AND withdrawn_at IS NULL""",
        (revision_id,),
    )


def insert_revision(conn, version, document_id, name, source, key, digest,
                    status, filename, review_required, values):
    return conn.execute(
        """INSERT INTO documents (
                version, document_id, name, source_path, object_key, sha256, status, filename, review_required,
                source_url, insurer, category, product_name, document_type, uins, effective_from
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (version, document_id, name, source, key, digest, status, filename,
             review_required, *(values[field] for field in CATALOGUE_FIELDS)),
    ).fetchone()["id"]


def mark_withdrawn(conn, document_id):
    return conn.execute(
        """UPDATE documents
            SET withdrawn_at=statement_timestamp(),
                updated_at=statement_timestamp(), last_error=NULL,
                status=CASE WHEN status='archived' THEN 'archived' ELSE 'cleanup_pending' END
            WHERE document_id=%s AND withdrawn_at IS NULL""",
        (document_id,),
    ).rowcount


def document_exists(conn, document_id):
    return conn.execute('SELECT 1 FROM documents WHERE document_id=%s', (document_id,)).fetchone()


def set_stage(conn, revision_id, stage):
    return conn.execute(
        """UPDATE documents SET status=%s, updated_at=now()
            WHERE id=%s AND status=ANY(%s)""",
        (stage, revision_id, list(PROCESSING)),
    ).rowcount


def save_index_manifest(conn, revision_id, count, model, total_pages):
    return conn.execute(
        """UPDATE documents SET chunk_count=%s, embedding_model=%s, total_pages=%s,
                parser='docling', chunking_method='semantic', updated_at=now()
            WHERE id=%s AND status='indexing'""",
        (count, model, total_pages, revision_id),
    ).rowcount


def ready_revision(conn, revision_id):
    return conn.execute(
        """SELECT chunk_count FROM documents WHERE id=%s AND status='verifying'
            AND NOT review_required AND withdrawn_at IS NULL""",
        (revision_id,),
    ).fetchone()


def retire_active(conn, document_id):
    conn.execute(
        """UPDATE documents SET status='cleanup_pending', updated_at=statement_timestamp()
            WHERE document_id=%s AND status='active'""",
        (document_id,),
    )


def mark_published(conn, revision_id):
    conn.execute(
        """UPDATE documents SET status='active', published_at=statement_timestamp(),
                updated_at=statement_timestamp()
            WHERE id=%s""",
        (revision_id,),
    )


def claim_job(conn):
    return conn.execute(
        """UPDATE documents AS r
            SET status=CASE WHEN r.status='queued' THEN 'parsing'
                            WHEN r.status='cleanup_pending' THEN 'cleaning' ELSE r.status END,
                attempts=r.attempts + CASE WHEN r.status='queued' THEN 1 ELSE 0 END,
                last_error=NULL, updated_at=now()
            WHERE r.id=(SELECT id FROM documents
                        WHERE status='queued' OR (status='verifying' AND NOT review_required) OR
                            (status='cleanup_pending' AND updated_at <= now() - interval '6 minutes')
                        ORDER BY updated_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING r.*""",
    ).fetchone()


def archive_revision(conn, revision_id):
    conn.execute(
        """UPDATE documents SET status='archived', updated_at=now()
            WHERE id=%s AND status='cleaning'""",
        (revision_id,),
    )


def fail_job(conn, revision_id, cleaning, error):
    conn.execute(
        """UPDATE documents SET status=%s, last_error=%s, updated_at=now()
            WHERE id=%s AND status=ANY(%s)""",
        ("cleanup_failed" if cleaning else "failed", error[:500], revision_id,
             ["cleaning"] if cleaning else list(PROCESSING)),
    )


def staged_revisions(conn, sources):
    return conn.execute(
        """SELECT id, source_path FROM documents WHERE status='staged'
            AND withdrawn_at IS NULL AND source_path=ANY(%s) FOR UPDATE""",
        (sorted(sources),),
    ).fetchall()


def enqueue_revisions(conn, revision_ids):
    conn.execute("UPDATE documents SET status='queued', updated_at=now() WHERE id=ANY(%s)", (revision_ids,))


def try_worker_lock(conn, lock_id):
    return conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (lock_id,)).fetchone()["locked"]


def recover_interrupted_jobs(conn):
    conn.execute(
        """UPDATE documents SET status=CASE
                WHEN status='cleaning' THEN 'cleanup_pending' ELSE 'queued' END
            WHERE status='cleaning' OR status=ANY(%s)""",
        ([status for status in PROCESSING if status != "verifying"],),
    )


def has_failed_jobs(conn):
    return conn.execute("SELECT 1 FROM documents WHERE status IN ('failed', 'cleanup_failed') LIMIT 1").fetchone()


def list_documents():
    with connect() as conn:
        return conn.execute(
            """SELECT latest.document_id AS id, latest.name AS title, latest.source_path AS source,
                       latest.source_url, latest.status AS index_status, latest.withdrawn_at,
                       latest.updated_at, latest.filename, latest.review_required, active.id AS active_revision
                FROM (SELECT DISTINCT ON (document_id) * FROM documents
                      ORDER BY document_id, created_at DESC, id DESC) latest
                LEFT JOIN documents active
                    ON active.document_id=latest.document_id AND active.status='active'
                ORDER BY latest.withdrawn_at NULLS FIRST, latest.name, latest.document_id""",
        ).fetchall()


def list_jobs():
    with connect() as conn:
        return conn.execute(
            """SELECT id, name, status, review_required, attempts, last_error, updated_at
                FROM documents
                ORDER BY CASE WHEN status IN ('failed','cleanup_failed') THEN 0 ELSE 1 END,
                         updated_at DESC LIMIT 100""",
        ).fetchall()


def approve_revision(revision_id):
    with connect() as conn:
        return conn.execute(
            """UPDATE documents SET review_required=false, updated_at=now()
                WHERE id=%s AND status='verifying' AND review_required
                  AND withdrawn_at IS NULL RETURNING id""",
            (revision_id,),
        ).fetchone()


def preview_object(revision_id):
    with connect() as conn:
        return conn.execute('SELECT object_key FROM documents WHERE id=%s AND withdrawn_at IS NULL', (revision_id,)).fetchone()


def retry_job(job_id):
    with connect() as conn:
        return conn.execute(
            """UPDATE documents
                SET status=CASE WHEN status='cleanup_failed' THEN 'cleanup_pending' ELSE 'queued' END,
                    last_error=NULL, updated_at=now()
                WHERE id=%s AND status IN ('failed', 'cleanup_failed')
                  AND (last_error IS NULL OR last_error NOT LIKE 'Upload %') RETURNING id""",
            (job_id,),
        ).fetchone()


def published_object(revision_id):
    with connect() as conn:
        return conn.execute(
            """SELECT object_key FROM documents
                WHERE id::text=%s AND published_at IS NOT NULL AND withdrawn_at IS NULL
                LIMIT 1""",
            (str(revision_id),),
        ).fetchone()


def revision_exists(conn, revision_id):
    return conn.execute("SELECT 1 FROM documents WHERE id=%s", (revision_id,)).fetchone()

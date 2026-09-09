from app.db.connection import connect, lock_document


SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS documents_document_id_seq AS bigint;
CREATE TABLE IF NOT EXISTS documents (
    document_id bigint NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL CHECK (status IN (
        'staged', 'queued', 'parsing', 'chunking', 'indexing', 'verifying', 'active',
        'failed', 'cleanup_pending', 'cleaning', 'cleanup_failed', 'archived'
    )),
    category text,
    insurer text,
    product_name text,
    document_type text,
    filename text NOT NULL,
    source_path text,
    object_key text NOT NULL UNIQUE,
    source_url text,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-fA-F]{64}$'),
    total_pages integer CHECK (total_pages > 0),
    chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    review_required boolean NOT NULL DEFAULT false,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error text,
    uins text[] NOT NULL DEFAULT '{}',
    effective_from date,
    parser text,
    chunking_method text,
    embedding_model text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    withdrawn_at timestamptz,
    UNIQUE (document_id, version),
    CHECK (status <> 'active' OR
           (published_at IS NOT NULL AND withdrawn_at IS NULL AND chunk_count > 0 AND NOT review_required))
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_active
    ON documents (document_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS documents_history
    ON documents (document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS documents_source
    ON documents (source_path) WHERE source_path IS NOT NULL;
"""


def initialize():
    with connect() as conn:
        lock_document(conn, "schema:documents")
        existing = conn.execute("SELECT to_regclass('documents') IS NOT NULL AS present").fetchone()
        if existing["present"]:
            columns = conn.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema=current_schema() AND table_name='documents'"""
            ).fetchall()
            names = {row["column_name"] for row in columns}
            if "version" not in names or "document_revision" in names or "is_active" in names:
                raise RuntimeError("The existing documents table uses the old schema; reset it manually first.")
        conn.execute(SCHEMA)

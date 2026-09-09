from app.core.config import get_settings


def connect(*, autocommit=False):
    import psycopg
    from psycopg.rows import dict_row

    settings = get_settings()
    url = settings.kb_database_url.get_secret_value()
    if not settings.kb_managed or not url:
        raise RuntimeError("Configure managed KB and KB_DATABASE_URL.")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10, autocommit=autocommit)


def lock_document(conn, document_id):
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(document_id),))

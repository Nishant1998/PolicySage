import hashlib
import re
from pathlib import PurePosixPath

from app.core.observability import traced_operation
from app.db import document_repository as repository
from app.db.connection import connect, lock_document
from app.infrastructure.object_storage import upload_pdf

MAX_PDF_BYTES = 20 * 1024 * 1024


def object_key_for_pdf(filename, document_id, version, *, source=None, category=None, insurer=None):
    def safe(value, fallback):
        value = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "")).strip("_.-").lower()
        return value[:120] or fallback

    parts = PurePosixPath((source or "").replace("\\", "/")).parts
    category = parts[0] if len(parts) >= 3 else category
    insurer = parts[1] if len(parts) >= 3 else insurer
    stem = PurePosixPath(filename.replace("\\", "/")).stem
    return (f"{safe(category, 'uncategorized')}/{safe(insurer, 'unknown_insurer')}/"
            f"{safe(stem, 'document')}__d{document_id}_v{version}.pdf")


@traced_operation("register_pdf")
def register_document(content, filename, metadata, *, source=None, document_id=None, hold=False):
    if not content.startswith(b"%PDF-") or len(content) > MAX_PDF_BYTES:
        raise ValueError("Upload a PDF no larger than 20 MB.")
    filename = PurePosixPath(filename.replace("\\", "/")).name
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Upload a PDF with a valid filename.")
    digest = hashlib.sha256(content).hexdigest()
    if metadata.get("sha256") and metadata["sha256"] != digest:
        raise ValueError("PDF checksum does not match its catalogue entry.")

    with connect() as conn:
        if source:
            lock_document(conn, f"source:{source}")
            existing = repository.document_for_source(conn, source)
            document_id = existing["document_id"] if existing else None
        replacing = document_id is not None
        if replacing:
            try:
                document_id = int(document_id)
            except (TypeError, ValueError):
                raise ValueError("Invalid document ID.") from None
        else:
            document_id = conn.execute("SELECT nextval('documents_document_id_seq') AS id").fetchone()["id"]
        lock_document(conn, document_id)
        previous = repository.latest_revision(conn, document_id)
        if replacing and not previous:
            raise ValueError("Document not found.")
        if previous and previous["withdrawn_at"]:
            if source or hold:
                return {"document_id": document_id, "status": "withdrawn"}
            raise ValueError("This document was withdrawn.")
        if previous and previous["last_error"] == "Upload pending":
            if not previous["upload_stale"]:
                raise ValueError("Another upload for this document is in progress.")
            conn.execute("UPDATE documents SET last_error='Upload failed; register the PDF again' WHERE id=%s",
                         (previous["id"],))
            previous["last_error"] = "Upload failed; register the PDF again"
        if (previous and previous["sha256"] == digest and previous["status"] != "archived"
                and not (previous["last_error"] or "").startswith("Upload failed")):
            return {"document_id": document_id, "revision_id": previous["id"], "status": "unchanged"}
        if hold and previous and previous["status"] in ("verifying", "failed"):
            if not (previous["last_error"] or "").startswith("Upload failed"):
                raise ValueError("Resolve the previous indexing job before staging a replacement.")

        version = previous["version"] + 1 if previous else 1
        name = metadata.get("document_title") or (previous and previous["name"]) or filename
        values = {field: (previous or {}).get(field) for field in repository.CATALOGUE_FIELDS}
        values.update({field: metadata[field] for field in repository.CATALOGUE_FIELDS if metadata.get(field)})
        parts = PurePosixPath(source or "").parts
        if len(parts) >= 3:
            values["category"] = values["category"] or parts[0]
            values["insurer"] = values["insurer"] or parts[1]
        values["uins"] = metadata.get("uin") or values["uins"] or []
        key = object_key_for_pdf(filename, document_id, version, source=source,
                                 category=values["category"], insurer=values["insurer"])
        revision_id = repository.insert_revision(
            conn, version, document_id, name, source or (previous and previous["source_path"]),
            key, digest, "failed", filename, metadata.get("review_required") is True, values,
        )
        conn.execute("UPDATE documents SET last_error='Upload pending' WHERE id=%s", (revision_id,))

    try:
        upload_pdf(key, content)
    except Exception:
        with connect() as conn:
            conn.execute("UPDATE documents SET last_error='Upload failed; register the PDF again', updated_at=now() WHERE id=%s",
                         (revision_id,))
        raise

    status = "staged" if hold else "queued"
    with connect() as conn:
        lock_document(conn, document_id)
        row = repository.latest_revision(conn, document_id)
        if row["id"] != revision_id or row["withdrawn_at"]:
            raise ValueError("Document changed during upload; register it again.")
        if (previous and previous["status"] in (*repository.PROCESSING, "staged", "queued", "failed")
                and not (previous["last_error"] or "").startswith("Upload failed")):
            repository.retire_pending(conn, previous["id"])
        conn.execute("UPDATE documents SET status=%s, last_error=NULL, updated_at=now() WHERE id=%s",
                     (status, revision_id))
    return {"document_id": document_id, "revision_id": revision_id, "status": status}


def withdraw(document_id):
    with connect() as conn:
        lock_document(conn, document_id)
        if not repository.mark_withdrawn(conn, document_id) and not repository.document_exists(conn, document_id):
            raise ValueError("Document not found.")

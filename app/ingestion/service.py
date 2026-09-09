import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import get_settings
from app.core.observability import span, traced_operation
from app.core.revisions import revision_record_ids
from app.db import document_repository as repository
from app.db.connection import lock_document
from app.infrastructure.object_storage import download_pdf
from app.infrastructure.qdrant_store import chunk_vector_metadata, wait_for_records
from app.ingestion.chunking import chunk_documents
from app.ingestion.indexer import delete_records, write_chunks
from app.ingestion.pdf_parser import parse_pdf
from app.services.document_service import MAX_PDF_BYTES


def index_revision(conn, revision):
    revision_id = revision["id"]
    settings = get_settings()
    if revision["embedding_model"] not in (None, settings.embedding_model):
        raise ValueError("Use the original embedding model to retry this revision.")
    content = download_pdf(revision["object_key"], MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES or hashlib.sha256(content).hexdigest() != revision["sha256"]:
        raise ValueError("Stored PDF does not match the registered checksum.")

    with TemporaryDirectory() as temp:
        path = Path(temp) / "source.pdf"
        path.write_bytes(content)
        documents, total_pages = parse_pdf(path, revision_id)
    if not repository.set_stage(conn, revision_id, "chunking"):
        return
    with span("chunk_document") as trace:
        chunks = chunk_documents(documents)
        trace.update(pages=total_pages, chunks=len(chunks))
    if not chunks:
        raise ValueError("No searchable chunks were created.")
    policy_metadata = {
        key: revision[key] for key in ("insurer", "category", "product_name", "document_type", "source_url")
        if revision[key]
    }
    if revision["uins"]:
        policy_metadata["uin"] = revision["uins"]
    for position, chunk in enumerate(chunks):
        chunk.metadata = chunk_vector_metadata({
            **chunk.metadata,
            "document_id": str(revision["document_id"]),
            "document_revision": str(revision["id"]),
            "is_active": False,
            **policy_metadata,
            "document_title": revision["name"],
            "chunk_index": position,
            "embedding_model": settings.embedding_model,
        })

    ids = revision_record_ids(revision_id, len(chunks))
    expected = {key: {**chunk.metadata, "text": chunk.page_content} for key, chunk in zip(ids, chunks)}
    if not repository.set_stage(conn, revision_id, "indexing"):
        return
    # Trim any extra records left by a previous, partially completed attempt.
    delete_records(revision_record_ids(revision_id, revision["chunk_count"])[len(chunks):])
    if not repository.save_index_manifest(conn, revision_id, len(chunks), settings.embedding_model, total_pages):
        return

    write_chunks(chunks, record_ids=ids)
    with span("qdrant_verify") as trace:
        wait_for_records(ids, expected=expected)
        trace["verified_chunks"] = len(ids)
    if repository.set_stage(conn, revision_id, "verifying"):
        publish_revision(conn, revision)


@traced_operation("publish_revision")
def publish_revision(conn, revision):
    revision_id = revision["id"]
    document_id = revision["document_id"]
    with conn.transaction():
        lock_document(conn, document_id)
        ready = repository.ready_revision(conn, revision_id)
        if not ready:
            return
        if not ready["chunk_count"]:
            raise ValueError("This revision has no verified chunks.")
        # A review or restart may have separated verification from publication.
        wait_for_records(revision_record_ids(revision_id, ready["chunk_count"]))
        repository.retire_active(conn, document_id)
        repository.mark_published(conn, revision_id)

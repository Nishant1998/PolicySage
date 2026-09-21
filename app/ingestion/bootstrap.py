import logging
import hashlib
from collections import Counter

from botocore.exceptions import ClientError
from tqdm.auto import tqdm

from app.core.config import get_settings
from app.core.revisions import revision_record_ids
from app.db import document_repository as repository
from app.db.connection import connect
from app.infrastructure.object_storage import object_store, upload_pdf
from app.infrastructure.qdrant_store import point_id, records
from app.ingestion.catalogue import selected_pdfs
from app.ingestion.wakeup import signal_worker
from app.services.document_service import MAX_PDF_BYTES, register_document


logger = logging.getLogger(__name__)


def inspect_existing(source, digest, content):
    with connect() as conn:
        existing = repository.document_for_source(conn, source)
        if not existing:
            matches = conn.execute(
                """SELECT DISTINCT document_id FROM documents
                   WHERE sha256=%s AND withdrawn_at IS NULL
                     AND status NOT IN ('archived', 'cleanup_pending', 'cleaning', 'cleanup_failed')""",
                (digest,),
            ).fetchall()
            if matches:
                raise ValueError("This PDF is already registered under another source; inspect it before importing.")
        revision = repository.latest_revision(conn, existing["document_id"]) if existing else None
    if not revision or revision["sha256"] != digest or revision["withdrawn_at"]:
        return None

    try:
        info = object_store().head_object(Bucket=get_settings().kb_s3_bucket, Key=revision["object_key"])
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchKey", "NotFound"}:
            raise
        upload_pdf(revision["object_key"], content)
        logger.info("%s: restored missing object", source)
    else:
        if info["ContentLength"] != len(content):
            raise ValueError("Stored object size differs from the local PDF; manual inspection required.")

    if revision["status"] == "staged":
        with connect() as conn:
            row = conn.execute(
                """UPDATE documents SET status='queued', updated_at=now()
                   WHERE id=%s AND status='staged' AND withdrawn_at IS NULL RETURNING id""",
                (revision["id"],),
            ).fetchone()
        if not row:
            raise ValueError("Revision changed during inspection; run the command again.")
        signal_worker()
        logger.info("%s: queued staged revision", source)
        return "queued"

    if revision["status"] != "active":
        logger.info("%s: existing revision status is %s", source, revision["status"])
        return revision["status"]

    ids = revision_record_ids(revision["id"], revision["chunk_count"])
    missing = not ids
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        found = records(batch)
        for key in batch:
            payload = found.get(point_id(key))
            if (not payload or payload.get("document_revision") != str(revision["id"])
                    or payload.get("document_id") != str(revision["document_id"])
                    or payload.get("embedding_model") != get_settings().embedding_model
                    or not payload.get("text")):
                missing = True
                break
        if missing:
            break
    if missing:
        logger.warning("%s: published vectors are incomplete; creating a replacement revision", source)
        return ("repair", revision["id"])
    logger.info("%s: stored PDF and indexed chunks are present", source)
    return "unchanged"


def bootstrap(*, stage_only=False, sources=None):
    root = get_settings().kb_dir
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
             if p.is_file() and p.suffix.lower() == ".pdf"}
    selected = selected_pdfs(root, files)
    if sources:
        requested = set(sources)
        if requested - selected.keys():
            raise ValueError("Each --source must match a PDF enabled in metadata.csv.")
        selected = {source: selected[source] for source in requested}
    if not selected:
        raise ValueError("No PDFs selected for bulk ingestion.")

    action = "Staging" if stage_only else "Registering"
    failures = []
    counts = Counter()
    for source, row in tqdm(sorted(selected.items()), desc=f"{action} PDFs", unit="pdf", disable=None):
        try:
            path = files[source]
            with path.open("rb") as stream:
                content = stream.read(MAX_PDF_BYTES + 1)
            if len(content) > MAX_PDF_BYTES:
                raise ValueError("PDF is larger than 20 MB.")
            metadata = {**row, "document_title": row.get("document_title") or path.stem}
            digest = hashlib.sha256(content).hexdigest()
            if metadata.get("sha256") and metadata["sha256"].lower() != digest:
                raise ValueError("PDF checksum does not match its catalogue entry.")
            metadata["uin"] = [value.strip() for value in (row.get("uin") or "").split(";") if value.strip()]
            metadata["review_required"] = (row.get("review_required") or "").strip().lower() == "true"
            repair = None
            if not stage_only:
                state = inspect_existing(source, digest, content)
                if isinstance(state, tuple):
                    repair = state[1]
                elif state:
                    counts[state] += 1
                    continue
            result = register_document(content, path.name, metadata, source=source, hold=stage_only,
                                       **({"repair_revision": repair} if repair is not None else {}))
            counts[result["status"]] += 1
            logger.info("%s: %s", source, result["status"])
        except Exception as exc:
            failures.append(source)
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            logger.error("Could not register %s (%s)", source, type(exc).__name__)
    logger.info("Bootstrap: %d queued, %d staged, %d unchanged, %d withdrawn, %d failed",
                counts["queued"], counts["staged"], counts["unchanged"], counts["withdrawn"], len(failures))
    if failures:
        raise SystemExit("Bootstrap incomplete. Resolve and rerun: " + ", ".join(failures))


def queue_staged(conn, sources):
    sources = set(sources)
    with conn.transaction():
        rows = repository.staged_revisions(conn, sources)
        if {row["source_path"] for row in rows} != sources or len(rows) != len(sources):
            raise SystemExit("Each --source must match exactly one staged revision. No revisions were queued.")
        repository.enqueue_revisions(conn, [row["id"] for row in rows])
    signal_worker()
    logger.info("Queued %d explicitly selected staged PDFs", len(rows))

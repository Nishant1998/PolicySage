import logging
from collections import Counter

from tqdm.auto import tqdm

from app.core.config import get_settings
from app.db import document_repository as repository
from app.ingestion.catalogue import selected_pdfs
from app.services.document_service import MAX_PDF_BYTES, register_document


logger = logging.getLogger(__name__)


def bootstrap(*, stage_only=False):
    root = get_settings().kb_dir
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
             if p.is_file() and p.suffix.lower() == ".pdf"}
    selected = selected_pdfs(root, files)
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
            metadata["uin"] = [value.strip() for value in (row.get("uin") or "").split(";") if value.strip()]
            metadata["review_required"] = (row.get("review_required") or "").strip().lower() == "true"
            result = register_document(content, path.name, metadata, source=source, hold=stage_only)
            counts[result["status"]] += 1
            logger.info("%s: %s", source, result["status"])
        except Exception as exc:
            failures.append(source)
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            logger.error("Could not register %s (%s)", source, error)
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
    logger.info("Queued %d explicitly selected staged PDFs", len(rows))

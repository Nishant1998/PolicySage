import hashlib
import logging
import time

from tqdm.auto import tqdm

from app.core.observability import observe_request, span
from app.core.revisions import revision_record_ids
from app.db import document_repository as repository
from app.ingestion.indexer import delete_records
from app.ingestion.service import index_revision, publish_revision


logger = logging.getLogger(__name__)


WORKER_LOCK = 828142157


def drain(conn, watch):
    failures = 0
    with tqdm(desc="Processing PDF revisions", unit="revision", disable=None) as progress:
        while True:
            revision = repository.claim_job(conn)
            if revision is None:
                if not watch:
                    return failures
                time.sleep(5)
                continue
            revision_id = revision["id"]
            cleaning = revision["status"] == "cleaning"
            try:
                with observe_request("kb_worker", "WORKER") as observation:
                    observation["revision_ref"] = hashlib.sha256(str(revision_id).encode()).hexdigest()[:16]
                    with span("process_revision") as trace:
                        trace["starting_status"] = revision["status"]
                        if cleaning:
                            delete_records(revision_record_ids(revision_id, revision["chunk_count"]))
                            repository.archive_revision(conn, revision_id)
                        elif revision["status"] == "verifying":
                            publish_revision(conn, revision)
                        else:
                            index_revision(conn, revision)
            except Exception as exc:
                failures += 1
                error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                repository.fail_job(conn, revision_id, cleaning, error)
                logger.error("Revision %s failed (%s)", revision_id, error)
            progress.update(1)

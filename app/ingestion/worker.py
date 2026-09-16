import hashlib
import logging
import time

from tqdm.auto import tqdm

from app.core.observability import observe_request, span
from app.core.revisions import revision_record_ids
from app.db import document_repository as repository
from app.db.connection import connect
from app.ingestion.indexer import delete_records
from app.ingestion.service import index_revision, publish_revision
from app.ingestion.wakeup import signal_version


logger = logging.getLogger(__name__)


WORKER_LOCK = 828142157
RECOVERY_INTERVAL_SECONDS = 900
SIGNAL_CHECK_SECONDS = 2
ERROR_RETRY_SECONDS = 60


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


def watch_worker():
    logger.info("Ingestion worker watching for jobs; database connection closes when idle")
    while True:
        seen = signal_version()
        delay = RECOVERY_INTERVAL_SECONDS
        try:
            with connect(autocommit=True) as conn:
                if not repository.try_worker_lock(conn, WORKER_LOCK):
                    logger.info("Another worker is processing jobs")
                    delay = ERROR_RETRY_SECONDS
                else:
                    repository.recover_interrupted_jobs(conn)
                    drain(conn, watch=False)
                    cleanup_delay = repository.next_cleanup_delay(conn)
                    if cleanup_delay is not None:
                        delay = min(delay, max(1, cleanup_delay))
        except Exception:
            logger.exception("Ingestion worker could not process the queue; retrying")
            delay = ERROR_RETRY_SECONDS

        deadline = time.monotonic() + delay
        while signal_version() == seen:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(SIGNAL_CHECK_SECONDS, remaining))

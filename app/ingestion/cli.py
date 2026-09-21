import argparse
import logging

from tqdm.contrib.logging import logging_redirect_tqdm

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import observe_request, trace_client
from app.db import document_repository as repository
from app.db.connection import connect
from app.db.schema import initialize
from app.ingestion.bootstrap import bootstrap, queue_staged
from app.ingestion.worker import WORKER_LOCK, drain, watch_worker

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Register and process PolicySage documents.")
    parser.add_argument("command", nargs="?",
                        choices=("init", "bootstrap", "index-staged", "worker"))
    parser.add_argument("--stage-only", action="store_true", help="Register new bootstrap PDFs without queueing.")
    parser.add_argument("--watch", action="store_true", help="Keep processing newly queued jobs.")
    parser.add_argument("--source", action="append",
                        help="Relative KB path to process. Repeat to select multiple PDFs.")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    if args.command == "index-staged" and not args.source:
        parser.error("index-staged requires at least one --source confirmed missing from Qdrant.")
    if args.source and args.command not in ("index-staged", "bootstrap"):
        parser.error("--source is only valid with bootstrap or index-staged.")
    if args.watch and args.command not in ("worker", "index-staged"):
        parser.error("--watch requires worker or index-staged.")
    if args.stage_only and args.command != "bootstrap":
        parser.error("--stage-only requires bootstrap.")

    settings = get_settings()
    configure_logging(settings.log_level, structured=settings.app_env == "production")
    if args.command in ("init", "bootstrap"):
        with observe_request("kb_init", "WORKER"):
            initialize()
        if args.command == "init":
            return
        # The source and document locks in registration also protect a live worker.
        with logging_redirect_tqdm(), observe_request("kb_bulk", "WORKER"):
            bootstrap(stage_only=args.stage_only, sources=args.source)
        return

    if args.command == "worker" and args.watch:
        with logging_redirect_tqdm():
            watch_worker()
        return

    with connect(autocommit=True) as conn, logging_redirect_tqdm():
        if not repository.try_worker_lock(conn, WORKER_LOCK):
            raise SystemExit("A KB worker is already running. Stop it before starting this command.")
        if args.command == "index-staged":
            queue_staged(conn, args.source)
        repository.recover_interrupted_jobs(conn)
        failed = drain(conn, watch=False)
        if failed or repository.has_failed_jobs(conn):
            raise SystemExit("Some jobs failed. Review and retry them in the admin panel.")
    if args.watch:
        with logging_redirect_tqdm():
            watch_worker()


def run():
    try:
        main()
    finally:
        if trace_client.cache_info().currsize:
            try:
                trace_client().flush(timeout=2)
            except Exception:
                logger.warning("LangSmith flush failed")

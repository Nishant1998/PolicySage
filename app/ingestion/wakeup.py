import logging
from uuid import uuid4

from app.core.config import BASE_DIR

logger = logging.getLogger(__name__)
SIGNAL_PATH = BASE_DIR / "data" / "ingestion-wakeup"


def signal_worker():
    try:
        SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SIGNAL_PATH.write_text(uuid4().hex, encoding="ascii")
    except OSError:
        logger.exception("Could not signal ingestion worker; recovery polling will find queued jobs")


def signal_version():
    try:
        return SIGNAL_PATH.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None

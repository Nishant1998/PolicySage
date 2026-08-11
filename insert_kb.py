import csv
import logging
from pathlib import Path

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from app.core.config import BASE_DIR
from app.core.logging import configure_logging
from app.rag.vectorstore import index_document_chunks
from app.services.ingestion import chunk_documents, load_file, load_metadata

logger = logging.getLogger(__name__)


def insert_kb(kb_dir: Path) -> None:
    metadata_path = kb_dir / "metadata.csv"
    # Use only files selected in the catalogue, including nested folders.
    with metadata_path.open(encoding="utf-8-sig", newline="") as file:
        rows = [row for row in csv.DictReader(file) if row["include_in_index"].strip().lower() == "true"]
    if not rows:
        raise ValueError("No documents are selected for indexing.")

    total_chunks = 0
    # Keep log messages from breaking the progress bar.
    with logging_redirect_tqdm(), tqdm(rows, desc="Indexing KB", unit="file") as progress:
        for row in progress:
            progress.set_postfix_str(row["file_path"])
            file_path = kb_dir / row["file_path"]
            metadata = load_metadata(file_path, metadata_path)
            documents = load_file(file_path)
            for document in documents:
                document.metadata.update(metadata)

            # Finish one file before loading the next to keep memory use small.
            chunks = chunk_documents(documents)
            chunk_ids = index_document_chunks(chunks)
            total_chunks += len(chunk_ids)

    logger.info("Indexed %d files -> %d chunks (includes unchanged chunks)", len(rows), total_chunks)


if __name__ == "__main__":
    configure_logging()
    insert_kb(BASE_DIR / "data" / "kb")

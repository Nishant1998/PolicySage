import csv
from bisect import bisect_right
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


def clean_text(text: str) -> str:
    # Normalize line endings and remove null characters.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def load_file(path: str | Path) -> list[Document]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    metadata = {"source": str(path)}
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported.")
        # Keep PDF page numbers for answer citations.
        documents = [
            Document(
                page_content=clean_text(page.extract_text() or ""),
                metadata={**metadata, "page": number, "total_pages": len(reader.pages)},
            )
            for number, page in enumerate(reader.pages, start=1)
        ]
    elif path.suffix.lower() == ".docx":
        parts = []
        # Read paragraphs and tables in their original order.
        for block in DocxDocument(path).iter_inner_content():
            if isinstance(block, Table):
                parts.append("\n".join("\t".join(cell.text for cell in row.cells) for row in block.rows))
            else:
                parts.append(block.text)
        documents = [Document(page_content=clean_text("\n\n".join(parts)), metadata=metadata)]
    else:
        text = path.read_text(encoding="utf-8-sig")
        documents = [Document(page_content=clean_text(text), metadata=metadata)]

    documents = [document for document in documents if document.page_content]
    if not documents:
        message = "No readable text found."
        if path.suffix.lower() == ".pdf":
            message += " Scanned PDFs require OCR."
        raise ValueError(f"{path.name}: {message}")
    return documents


def chunk_documents(
    documents: Iterable[Document],
    chunk_size: int = 900,
    chunk_overlap: int = 120,
) -> list[Document]:
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )
    # Keep chunks from different files separate.
    groups = {}
    for index, document in enumerate(documents):
        if document.page_content.strip():
            key = document.metadata.get("source", index)
            groups.setdefault(key, []).append(document)

    chunks = []
    for group in groups.values():
        # Track page boundaries in the joined text, including two newline separators.
        offsets = []
        position = 0
        for document in group:
            offsets.append(position)
            position += len(document.page_content) + 2
        text = "\n\n".join(document.page_content for document in group)
        metadata = {key: value for key, value in group[0].metadata.items() if key != "page"}
        # Split joined pages into overlapping chunks with character offsets.
        file_chunks = splitter.create_documents([text], [metadata])
        for index, chunk in enumerate(file_chunks):
            chunk.metadata["chunk_index"] = index
            if all("page" in document.metadata for document in group):
                # Map each chunk back to its first and last PDF pages.
                start = chunk.metadata["start_index"]
                end = start + len(chunk.page_content) - 1
                chunk.metadata["page_start"] = group[bisect_right(offsets, start) - 1].metadata["page"]
                chunk.metadata["page_end"] = group[bisect_right(offsets, end) - 1].metadata["page"]
        chunks.extend(file_chunks)
    return chunks


def load_metadata(file_path: str | Path, metadata_path: str | Path) -> dict:
    file_path = Path(file_path).resolve()
    metadata_path = Path(metadata_path).resolve()
    # Match the file to its entry in the local CSV catalogue.
    relative_path = file_path.relative_to(metadata_path.parent).as_posix()
    with metadata_path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if row["file_path"] != relative_path:
                continue
            if row["include_in_index"].strip().lower() != "true":
                raise ValueError(f"Document is excluded from indexing: {relative_path}")
            # Reject files that changed after the catalogue was created.
            if sha256(file_path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"Document checksum does not match metadata: {relative_path}")
            # Keep non-empty metadata; use source instead of a duplicate file_path.
            metadata = {key: value for key, value in row.items() if value and key not in {"include_in_index", "file_path"}}
            metadata["source"] = relative_path
            if "uin" in metadata:
                metadata["uin"] = [uin.strip() for uin in metadata["uin"].split(";") if uin.strip()]
            return metadata
    raise ValueError(f"Document is missing from metadata: {relative_path}")

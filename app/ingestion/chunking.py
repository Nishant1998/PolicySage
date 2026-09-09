from bisect import bisect_right
from collections.abc import Iterable

import tiktoken
from langchain_core.documents import Document

from app.core.config import get_settings
from app.ingestion.semantic import semantic_spans


def chunk_documents(
    documents: Iterable[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    settings = get_settings()
    chunk_size = settings.chunk_tokens if chunk_size is None else chunk_size
    chunk_overlap = settings.chunk_overlap_tokens if chunk_overlap is None else chunk_overlap
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size.")

    maximum = settings.chunk_max_tokens
    minimum = settings.chunk_min_tokens
    if not chunk_overlap < chunk_size <= maximum or not 0 < minimum <= chunk_size:
        raise ValueError("Require overlap < target <= maximum and 0 < minimum <= target.")
    encoder = tiktoken.get_encoding("cl100k_base")
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
        spans = semantic_spans(text, encoder, chunk_size, maximum, minimum, chunk_overlap)
        file_chunks = []
        for start, end in spans:
            passage = text[start:end]
            token_count = len(encoder.encode(passage))
            if token_count > maximum:
                raise ValueError("Semantic chunk exceeds the hard token limit")
            chunk_metadata = {**metadata, "start_index": start, "end_index": end,
                              "chunking_method": "semantic", "token_count": token_count}
            if token_count < minimum:
                chunk_metadata["size_exception"] = "short_document_or_fragment"
            file_chunks.append(Document(page_content=passage, metadata=chunk_metadata))
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



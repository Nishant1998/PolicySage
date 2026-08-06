import logging
import time
from functools import lru_cache
from hashlib import sha256

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from app.core.config import get_settings

logger = logging.getLogger(__name__)
BATCH_SIZE = 64
# Default vector sizes for the supported embedding models.
EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def get_embedding_dimension(model_name: str | None = None) -> int:
    model_name = model_name or get_settings().embedding_model
    if model_name not in EMBEDDING_DIMENSIONS:
        raise ValueError(f"Unsupported embedding model: {model_name}")
    return EMBEDDING_DIMENSIONS[model_name]


@lru_cache(maxsize=1)
def get_embedding_client() -> OpenAIEmbeddings:
    # Reuse this client; creating it does not generate embeddings.
    settings = get_settings()
    get_embedding_dimension(settings.embedding_model)
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        chunk_size=BATCH_SIZE,
    )


def get_pinecone_index():
    settings = get_settings()
    dimension = get_embedding_dimension(settings.embedding_model)
    client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
    name = settings.pinecone_index_name
    # Create the index only when it does not exist.
    if name not in client.list_indexes().names():
        client.create_index(
            name=name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            timeout=max(1, int(settings.request_timeout)),
        )

    # Check compatibility before writing any vectors.
    description = client.describe_index(name)
    if description.dimension != dimension or description.metric != "cosine":
        raise ValueError(f"Index '{name}' must use dimension {dimension} and cosine similarity.")

    # Wait for the index to be ready, up to the configured timeout.
    deadline = time.monotonic() + settings.request_timeout
    while not description.status["ready"]:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Index '{name}' did not become ready in time.")
        time.sleep(1)
        description = client.describe_index(name)
    return client.Index(name)


@lru_cache(maxsize=1)
def get_pinecone_vector_store() -> PineconeVectorStore:
    settings = get_settings()
    # Connect the index, embedding client and KB namespace.
    return PineconeVectorStore(
        index=get_pinecone_index(),
        embedding=get_embedding_client(),
        namespace=settings.pinecone_namespace,
    )


def get_kb_retriever():
    # Configure the retriever to return up to top_k matching chunks per query.
    return get_pinecone_vector_store().as_retriever(search_kwargs={"k": get_settings().top_k})


def index_document_chunks(chunks: list[Document]) -> list[str]:
    if not chunks:
        return []
    settings = get_settings()
    records = {}
    for index, chunk in enumerate(chunks):
        source = chunk.metadata.get("sha256") or chunk.metadata.get("source")
        if not source or not chunk.page_content.strip():
            raise ValueError("Each chunk must have a source and non-empty text.")
        chunk_index = chunk.metadata.get("chunk_index", index)
        # Reuse the same record ID when the model, source and chunk are unchanged.
        identity = f"{settings.embedding_model}:{source}:{chunk_index}:{chunk.page_content}"
        record_id = sha256(identity.encode("utf-8")).hexdigest()
        records[record_id] = Document(
            page_content=chunk.page_content,
            metadata={**chunk.metadata, "embedding_model": settings.embedding_model},
        )

    vector_store = get_pinecone_vector_store()
    ids = list(records)
    uploaded = 0
    for start in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[start:start + BATCH_SIZE]
        # Skip stored chunks only when both text and metadata match.
        existing = vector_store.index.fetch(ids=batch_ids, namespace=settings.pinecone_namespace).vectors
        pending = []
        for record_id in batch_ids:
            document = records[record_id]
            expected = {**document.metadata, "text": document.page_content}
            if record_id not in existing or existing[record_id].metadata != expected:
                pending.append(record_id)
        if pending:
            # Generate embeddings and upload only new or changed chunks.
            vector_store.add_documents(
                [records[record_id] for record_id in pending],
                ids=pending,
                batch_size=BATCH_SIZE,
                embedding_chunk_size=BATCH_SIZE,
                async_req=False,
            )
            uploaded += len(pending)
    logger.info("Chunks: %d indexed, %d uploaded, %d unchanged", len(ids), uploaded, len(ids) - uploaded)
    return ids

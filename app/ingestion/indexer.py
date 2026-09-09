from qdrant_client import models

from app.core.config import get_settings
from app.core.observability import traced_operation
from app.infrastructure.embeddings import get_embedding_client
from app.infrastructure.qdrant_store import client, point_id, records, wait_for_records


@traced_operation("qdrant_write_chunks")
def write_chunks(chunks, *, record_ids):
    pairs = list(zip(record_ids, chunks, strict=True))
    for start in range(0, len(pairs), 25):
        batch = pairs[start:start + 25]
        existing = records([key for key, _ in batch])
        pending = []
        for key, chunk in batch:
            payload = {**chunk.metadata, "text": chunk.page_content}
            if existing.get(point_id(key)) != payload:
                pending.append((point_id(key), payload))
        if pending:
            vectors = get_embedding_client().embed_documents([payload["text"] for _, payload in pending])
            client().upsert(get_settings().qdrant_collection, [
                models.PointStruct(id=key, payload=payload, vector=vector)
                for (key, payload), vector in zip(pending, vectors, strict=True)
            ], wait=True)
    return record_ids


@traced_operation("qdrant_cleanup")
def delete_records(ids):
    for start in range(0, len(ids), 100):
        client().delete(get_settings().qdrant_collection,
                        models.PointIdsList(points=[point_id(key) for key in ids[start:start + 100]]),
                        wait=True)
    if ids:
        wait_for_records(ids, absent=True)

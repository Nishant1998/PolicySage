import time
from functools import lru_cache
from threading import RLock
from uuid import NAMESPACE_URL, uuid5

import httpx
from qdrant_client import QdrantClient

from app.core.config import get_settings

INDEX_LOCK = RLock()
CHUNK_METADATA_KEYS = (
    "document_id", "document_revision", "is_active",
    "insurer", "category", "product_name", "document_type", "uin",
    "document_title", "source_url",
    "chunk_index", "page_start", "page_end", "start_index", "end_index",
    "embedding_model", "token_count",
)


def point_id(record_id):
    return str(uuid5(NAMESPACE_URL, f"policysage/{record_id}"))


@lru_cache(maxsize=1)
def client():
    settings = get_settings()
    if not settings.qdrant_url:
        raise RuntimeError("Configure QDRANT_URL.")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key.get_secret_value(),
                        timeout=settings.request_timeout, check_compatibility=False)


def records(ids):
    return {point.id: point.payload or {} for point in client().retrieve(
        get_settings().qdrant_collection, [point_id(key) for key in ids], with_vectors=False)}


def wait_for_records(ids, *, absent=False, expected=None):
    deadline = time.monotonic() + get_settings().request_timeout
    while True:
        found = {}
        for start in range(0, len(ids), 100):
            found.update(records(ids[start:start + 100]))
        if absent and not found:
            return
        if not absent and all(point_id(key) in found and
                              (expected is None or found[point_id(key)] == expected[key])
                              for key in ids):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Qdrant records did not reach the expected state.")
        time.sleep(1)


def chunk_vector_metadata(metadata):
    return {key: metadata.get(key) for key in CHUNK_METADATA_KEYS}


def query_points(query, revision_ids, *, using=None):
    settings = get_settings()
    body = {
        "query": query, "limit": 20, "with_payload": True,
        "filter": {"must": [
            {"key": "document_revision", "match": {"any": revision_ids}},
            {"key": "embedding_model", "match": {"value": settings.embedding_model}},
        ]},
    }
    if using is not None:
        body["using"] = using
    response = httpx.post(
        f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}/points/query",
        json=body, headers={"api-key": settings.qdrant_api_key.get_secret_value()},
        timeout=settings.request_timeout,
    )
    response.raise_for_status()
    return response.json()["result"]["points"]

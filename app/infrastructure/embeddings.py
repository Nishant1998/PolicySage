from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from threading import RLock
from time import monotonic

from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.core.observability import span


class TTLCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = RLock()
        self.generation = 0

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.generation += 1

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            expires, value = entry
            if monotonic() >= expires:
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
            return deepcopy(value)

    def put(self, key, value, generation, ttl, capacity):
        with self.lock:
            if generation != self.generation:
                return
            self.entries[key] = (monotonic() + ttl, deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > capacity:
                self.entries.popitem(last=False)


BATCH_SIZE = 64
QUERY_EMBEDDING_CACHE = TTLCache()
QUERY_EMBEDDING_TTL_SECONDS = 300
QUERY_EMBEDDING_MAX_ENTRIES = 128
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


class CachedQueryEmbeddings(OpenAIEmbeddings):
    def embed_query(self, text, **kwargs):
        if kwargs:
            return super().embed_query(text, **kwargs)
        key = sha256(f"{self.model}\0{self.dimensions}\0{text}".encode()).hexdigest()
        cached = QUERY_EMBEDDING_CACHE.get(key)
        if cached is not None:
            with span("query_embedding") as trace:
                trace["cache_hit"] = True
            return cached
        with span("query_embedding") as trace:
            trace["cache_hit"] = False
            trace["embedding_model"] = self.model
            vector = super().embed_query(text)
        QUERY_EMBEDDING_CACHE.put(
            key, vector, QUERY_EMBEDDING_CACHE.generation,
            QUERY_EMBEDDING_TTL_SECONDS, QUERY_EMBEDDING_MAX_ENTRIES,
        )
        return vector


@lru_cache(maxsize=1)
def get_embedding_client() -> OpenAIEmbeddings:
    # Reuse this client; creating it does not generate embeddings.
    settings = get_settings()
    get_embedding_dimension(settings.embedding_model)
    return CachedQueryEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        chunk_size=BATCH_SIZE,
    )

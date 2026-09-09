import logging
import re
import sqlite3
from contextlib import closing
from hashlib import sha256

import numpy as np
from tqdm.auto import tqdm

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def sentence_spans(text, encoder, limit=180):
    ends = [match.end() for match in re.finditer(r"(?<=[.!?])\s+|\n[ \t]*\n", text)]
    ends.append(len(text))
    spans, start = [], 0
    for end in ends:
        while start < end:
            stop = end
            if len(encoder.encode(text[start:end])) > limit:
                low, high = start + 1, min(end, start + limit * 12)
                while low < high:
                    middle = (low + high + 1) // 2
                    if len(encoder.encode(text[start:middle])) <= limit:
                        low = middle
                    else:
                        high = middle - 1
                stop = low
                boundary = max(text.rfind("\n", start, stop), text.rfind(" ", start, stop))
                if boundary > start + (stop - start) // 2:
                    stop = boundary + 1
            spans.append((start, stop))
            start = stop
    return spans


def embed_windows(texts, encoder):
    from app.infrastructure.embeddings import get_embedding_client

    settings = get_settings()
    path = settings.semantic_cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = [sha256((settings.embedding_model + "\0" + text).encode()).hexdigest() for text in texts]
    with closing(sqlite3.connect(path, timeout=30)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")
        cached = {}
        for key in set(keys):
            row = con.execute("SELECT vector FROM embeddings WHERE key=?", (key,)).fetchone()
            if row:
                cached[key] = np.frombuffer(row[0], dtype=np.float32)
        pending = list(dict.fromkeys(key for key in keys if key not in cached))
        by_key = dict(zip(keys, texts))
        input_tokens = 0
        for start in tqdm(range(0, len(pending), 64), desc="Semantic embeddings",
                          unit="batch", leave=False, disable=None):
            batch_keys = pending[start:start + 64]
            batch = [by_key[key] for key in batch_keys]
            vectors = get_embedding_client().embed_documents(batch)
            if len(vectors) != len(batch):
                raise ValueError("Incomplete semantic embedding response")
            input_tokens += sum(len(encoder.encode(text)) for text in batch)
            for key, vector in zip(batch_keys, vectors):
                cached[key] = vector
                con.execute("INSERT OR REPLACE INTO embeddings VALUES (?, ?)",
                            (key, np.asarray(vector, dtype=np.float32).tobytes()))
            con.commit()
    logger.info("Semantic boundaries: %d windows, %d cached, %d estimated embedding input tokens",
                len(texts), len(set(keys)) - len(pending), input_tokens)
    return np.asarray([cached[key] for key in keys], dtype=np.float32)


def semantic_spans(text, encoder, target, maximum, minimum, overlap):
    units = sentence_spans(text, encoder, limit=min(180, maximum))
    if not units:
        return []
    if len(units) == 1:
        return units
    # Neighbouring sentences give each boundary enough context for comparison.
    windows = [text[units[max(0, i - 1)][0]:units[min(len(units) - 1, i + 1)][1]]
               for i in range(len(units))]
    vectors = embed_windows(windows, encoder)
    if vectors.ndim != 2 or len(vectors) != len(units) or not np.isfinite(vectors).all():
        raise ValueError("Invalid semantic embeddings")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Zero-length semantic embedding")
    vectors = vectors / norms
    distances = 1 - np.sum(vectors[:-1] * vectors[1:], axis=1)
    threshold = float(np.percentile(distances, 90))
    def count(start, end):
        return len(encoder.encode(text[start:end]))

    cores, first = [], 0
    while first < len(units):
        candidates = []
        for last in range(first, len(units)):
            size = count(units[first][0], units[last][1])
            if size > maximum:
                break
            candidates.append((last, size))
        if not candidates:
            raise ValueError("A semantic unit exceeds the token limit")
        if candidates[-1][0] == len(units) - 1:
            last = candidates[-1][0]
        else:
            eligible = [(i, size) for i, size in candidates if size >= minimum]
            breaks = [(i, size) for i, size in eligible if distances[i] >= threshold and distances[i] > 1e-8]
            last, _ = min(breaks or eligible or candidates, key=lambda item: abs(item[1] - (target - overlap)))
        cores.append((units[first][0], units[last][1]))
        first = last + 1

    # Absorb or rebalance a small final fragment using existing sentence boundaries.
    if len(cores) > 1 and count(*cores[-1]) < minimum:
        start, end = cores[-2][0], cores[-1][1]
        if count(start, end) <= maximum:
            cores[-2:] = [(start, end)]
        else:
            splits = [b for a, b in units if start < b < end
                      and minimum <= count(start, b) <= maximum
                      and minimum <= count(b, end) <= maximum]
            if splits:
                middle = min(splits, key=lambda b: abs(count(start, b) - count(b, end)))
                cores[-2:] = [(start, middle), (middle, end)]

    spans = []
    for start, end in cores:
        expanded = start
        # Overlap is sentence-aligned and may be less than the configured maximum.
        for a, b in reversed(units):
            if b > start:
                continue
            if count(a, start) > overlap or count(a, end) > maximum:
                break
            expanded = a
        spans.append((expanded, end))
    return spans

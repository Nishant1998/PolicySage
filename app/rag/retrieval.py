from functools import lru_cache

from langchain_core.documents import Document

from app.core.budget import reserve_external_call
from app.core.config import get_settings
from app.core.observability import evidence_refs, exporting_trace, span, trace_content, trace_details, traced_operation
from app.db.document_repository import current_revisions
from app.infrastructure.qdrant_store import INDEX_LOCK, query_points
from app.infrastructure.embeddings import get_embedding_client

_lock = INDEX_LOCK
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"


def matches(metadata, filters):
    for key, expected in filters.items():
        actual = metadata.get(key)
        if expected not in (actual if isinstance(actual, list) else [actual]):
            return False
    return True


@lru_cache(maxsize=1)
def reranker():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    name = RERANKER_MODEL
    return AutoTokenizer.from_pretrained(name), AutoModelForSequenceClassification.from_pretrained(name).to("cpu").eval()


@traced_operation("rerank")
def rerank_documents(question, documents, limit=10):
    import torch
    unique = {(doc.metadata.get("document_id") or doc.metadata.get("source"), doc.page_content): doc
              for doc in documents}
    trace_details(model=RERANKER_MODEL, candidates=evidence_refs(documents),
                  duplicates_removed=len(documents) - len(unique), top_k=limit)
    documents = list(unique.values())
    if not documents:
        return []
    with _lock:
        tokenizer, model = reranker()
        scores = []
        for start in range(0, len(documents), 8):
            batch = documents[start:start + 8]
            inputs = tokenizer([question] * len(batch), [doc.page_content for doc in batch],
                               padding=True, truncation=True, max_length=512, return_tensors="pt")
            with torch.inference_mode():
                scores.extend(model(**inputs).logits.reshape(-1).tolist())
        ranked = sorted(zip(documents, scores), key=lambda item: -item[1])
        trace_details(ranking=[
            {**reference, "reranker_score": score}
            for reference, (_, score) in zip(evidence_refs([doc for doc, _ in ranked]), ranked)
        ], selected=evidence_refs([doc for doc, _ in ranked[:limit]]),
            discarded_count=max(0, len(ranked) - limit))
        return [doc for doc, score in ranked[:limit]]


@traced_operation("fuse_candidates")
def fuse_candidates(rankings, limit=20):
    scores, documents = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, doc in enumerate(ranking, 1):
            key = (doc.metadata.get("document_id") or doc.metadata.get("source"), doc.page_content)
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            documents[key] = doc
    ranked_keys = sorted(scores, key=lambda key: -scores[key])[:limit]
    selected = [documents[key] for key in ranked_keys]
    trace_details(method="reciprocal_rank_fusion", rank_constant=60,
                  input_counts=[len(ranking) for ranking in rankings],
                  duplicates_removed=sum(map(len, rankings)) - len(documents),
                  ranking=[{**ref, "rrf_score": scores[key]}
                           for ref, key in zip(evidence_refs(selected), ranked_keys)])
    return selected


def with_catalogue(doc, revisions):
    row = revisions[doc.metadata["document_revision"]]
    keys = ("document_title", "insurer", "product_name", "uin", "category",
            "document_type", "effective_from", "source_url")
    metadata = {
        **doc.metadata,
        **{key: row[key] for key in keys if row.get(key) is not None},
        "document_id": row["document_id"],
        "embedding_model": row["embedding_model"] or doc.metadata.get("embedding_model"),
    }
    return Document(id=doc.id, page_content=doc.page_content, metadata=metadata)


def candidates(question, eligible, *, lexical):
    method = "bm25" if lexical else "dense"
    with span(f"qdrant_{method}", run_type="retriever", inputs={
        "query": trace_content(question), "top_k": 20,
    }) as trace:
        query = {"text": question} if lexical else get_embedding_client().embed_query(question)
        points = query_points(query, list(eligible), using="text" if lexical else None)
        documents = []
        scores = []
        for point in points:
            metadata = dict(point["payload"])
            text = metadata.pop("text", "")
            if text and metadata.get("document_revision") in eligible:
                documents.append(with_catalogue(Document(id=str(point["id"]), page_content=text,
                                                          metadata=metadata), eligible))
                scores.append(point["score"])
        trace["matches"] = len(documents)
        if exporting_trace():
            trace_details(results=[{**ref, f"{method}_score": score}
                                   for ref, score in zip(evidence_refs(documents), scores)])
        return documents


@traced_operation("kb_search")
def search_kb(question, filters=None, *, rerank=True):
    eligible = {row["document_revision"]: row for row in current_revisions().values()
                if matches(row, filters or {})}
    if not eligible:
        return []
    reserve_external_call("search")
    dense = candidates(question, eligible, lexical=False)
    lexical = candidates(question, eligible, lexical=True)
    selected = fuse_candidates([dense, lexical])
    return rerank_documents(question, selected, get_settings().top_k) if rerank else selected


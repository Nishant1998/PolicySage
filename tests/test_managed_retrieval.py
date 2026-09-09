import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.documents import Document

from app.rag import retrieval


PUBLISHED_REVISION = "1" * 32


def published_row(**updates):
    return {
        "id": PUBLISHED_REVISION,
        "document_id": "policy-id",
        "document_revision": PUBLISHED_REVISION,
        "document_title": "Published policy",
        "insurer": "Published insurer",
        "product_name": "Health plan",
        "uin": ["U1"],
        "category": "health",
        "document_type": "wording",
        "effective_from": "2026-01-15",
        "source_url": "https://example.org/published.pdf",
        "embedding_model": "test-model",
        "chunk_count": 2,
        **updates,
    }


def vector_chunk(text, revision=PUBLISHED_REVISION, *, active=False, page=3, uin="stale-uin"):
    return Document(page_content=text, metadata={
        "document_id": "stale-vector-id",
        "document_revision": revision,
        "document_title": "Stale title",
        "uin": [uin],
        "embedding_model": "test-model",
        "is_active": active,
        "source_url": "https://example.org/stale.pdf",
        "page_start": page,
        "page_end": page + 1,
    })


class ManagedRetrievalTests(unittest.TestCase):
    def test_hybrid_search_uses_published_revisions_for_both_branches(self):
        dense = vector_chunk("Waiting period of thirty days")
        lexical = vector_chunk("Waiting period for surgery", page=8)
        unpublished = vector_chunk("Pending approval", revision="2")
        def point(doc):
            return {"id": doc.page_content, "score": 1.0,
                    "payload": {**doc.metadata, "text": doc.page_content}}
        with (
            patch.object(retrieval, "current_revisions", return_value={PUBLISHED_REVISION: published_row()}),
            patch.object(retrieval, "get_embedding_client") as embeddings,
            patch.object(retrieval, "query_points", side_effect=[
                [point(dense), point(unpublished)], [point(lexical)],
            ]) as query,
        ):
            embeddings.return_value.embed_query.return_value = [0.1]
            result = retrieval.search_kb("surgery", {"uin": "U1"}, rerank=False)
        self.assertEqual([call.args[1] for call in query.call_args_list], [[PUBLISHED_REVISION]] * 2)
        self.assertEqual(query.call_args_list[1].kwargs["using"], "text")
        self.assertEqual({doc.page_content for doc in result}, {dense.page_content, lexical.page_content})
        for doc in result:
            self.assert_catalogue_metadata(doc, page=3 if doc.page_content == dense.page_content else 8)

    def test_empty_registry_skips_qdrant(self):
        with patch.object(retrieval, "current_revisions", return_value={}), \
             patch.object(retrieval, "query_points") as query:
            self.assertEqual(retrieval.search_kb("coverage"), [])
        query.assert_not_called()

    def assert_catalogue_metadata(self, document, *, page):
        self.assertEqual(
            {key: document.metadata.get(key) for key in (
                "document_id", "document_revision", "document_title", "insurer", "product_name",
                "uin", "category", "document_type", "effective_from", "source_url", "page_start", "page_end",
            )},
            {
                "document_id": "policy-id",
                "document_revision": PUBLISHED_REVISION,
                "document_title": "Published policy",
                "insurer": "Published insurer",
                "product_name": "Health plan",
                "uin": ["U1"],
                "category": "health",
                "document_type": "wording",
                "effective_from": "2026-01-15",
                "source_url": "https://example.org/published.pdf",
                "page_start": page,
                "page_end": page + 1,
            },
        )

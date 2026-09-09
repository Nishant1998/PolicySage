import unittest
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.documents import Document

from app.rag import workflow
from app.ingestion import chunking as ingestion
from app.ingestion.chunking import chunk_documents
from app.rag import retrieval
from app.infrastructure import embeddings
from app.api import chat
from app.services import limits
from app.ingestion import semantic as semantic_chunking
import numpy as np
from fastapi import HTTPException


class RetrievalTests(unittest.TestCase):
    def test_query_embeddings_cache_reuses_vector_for_same_model_and_text(self):
        client = embeddings.CachedQueryEmbeddings.model_construct(model="test", dimensions=2)
        other_model = embeddings.CachedQueryEmbeddings.model_construct(model="other", dimensions=2)
        with patch.object(embeddings, "QUERY_EMBEDDING_CACHE", embeddings.TTLCache()), \
             patch.object(embeddings.OpenAIEmbeddings, "embed_query", return_value=[1.0, 2.0]) as embed:
            first = client.embed_query("coverage")
            first[0] = 0.0
            self.assertEqual(client.embed_query("coverage"), [1.0, 2.0])
            other_model.embed_query("coverage")
        self.assertEqual(embed.call_count, 2)

    def test_retry_can_replace_a_full_pool(self):
        old = [Document(page_content=f"old {i}", metadata={"source": "a"}) for i in range(10)]
        fresh = Document(page_content="needed clause", metadata={"source": "b"})
        state = dict(question="question", current_query="rewritten", retry_count=1,
                     subqueries=[], filters={}, limitations=[], trace=[], kb_pool=old)
        with patch.object(workflow, "get_settings", return_value=SimpleNamespace(top_k=10)), \
             patch.object(workflow, "search_kb", return_value=[fresh]), \
             patch.object(workflow, "rerank_documents", side_effect=lambda q, docs, k: [fresh, *old[:9]]):
            result = workflow.retrieve_kb(state)
        self.assertIn("needed clause", [doc.page_content for doc in result["kb_docs"]])
        self.assertEqual(len(result["kb_docs"]), 10)
        self.assertEqual(len({doc.metadata["evidence_id"] for doc in result["kb_docs"]}), 10)

    def test_citations_include_the_actual_source_excerpt(self):
        doc = Document(page_content="The waiting period is 30 days.", metadata={
            "source": "policy.pdf", "evidence_id": "K1", "page_start": 4,
            "page_end": 4, "source_url": "https://example.org/policy.pdf"})
        answer = SimpleNamespace(answer="30 days. [K1]", citation_ids=["K1"])
        with patch.object(workflow, "invoke_structured", return_value=answer), \
             patch.object(workflow, "bounded_evidence", side_effect=lambda docs: docs):
            result = workflow.generate_answer({"question": "Waiting period?", "trace": []}, [doc])
        self.assertEqual(result["citations"][0]["excerpt"], doc.page_content)
        self.assertEqual(result["citations"][0]["page_start"], 4)

    def test_managed_citation_uses_authorized_revision_or_publisher_url(self):
        revision = "a" * 32
        metadata = {"document_revision": revision, "document_id": "logical-doc",
                    "evidence_id": "K1", "page_start": 4, "page_end": 5}
        answer = SimpleNamespace(answer="Coverage. [K1]", citation_ids=["K1"])
        settings = SimpleNamespace(kb_managed=True,
                                   public_pdf_downloads_enabled=False)
        for enabled, source, expected in (
            (False, "", ""),
            (False, f"/api/kb/revisions/{revision}.pdf", ""),
            (False, f"https://policysage.example/api/kb/revisions/{revision}.pdf", ""),
            (False, "https://publisher.example/policy.pdf", "https://publisher.example/policy.pdf"),
            (True, "https://publisher.example/policy.pdf", f"/api/kb/revisions/{revision}.pdf"),
        ):
            settings.public_pdf_downloads_enabled = enabled
            with self.subTest(enabled=enabled, source=source), \
                 patch.object(workflow, "get_settings", return_value=settings), \
                 patch.object(workflow, "invoke_structured", return_value=answer), \
                 patch.object(workflow, "bounded_evidence", side_effect=lambda docs: docs):
                doc = Document(page_content="Covered.", metadata={**metadata, "source_url": source})
                citation, = workflow.generate_answer({"question": "Covered?", "trace": []}, [doc])["citations"]
                self.assertEqual(citation["url"], expected)
                self.assertEqual((citation["page_start"], citation["page_end"]), (4, 5))
                self.assertEqual(citation["source_id"], "logical-doc")


class IngestionTests(unittest.TestCase):
    def test_chunks_retain_pdf_page_locations(self):
        docs = [Document(page_content="Clause A. " * 30, metadata={"source": "p", "page": 2}),
                Document(page_content="Clause B. " * 30, metadata={"source": "p", "page": 3})]
        with patch.object(ingestion, "get_settings", return_value=SimpleNamespace(
                chunk_tokens=128, chunk_overlap_tokens=20, chunk_min_tokens=40, chunk_max_tokens=180)), \
             patch.object(ingestion.tiktoken, "get_encoding", return_value=CharacterEncoder()), \
             patch.object(semantic_chunking, "embed_windows", side_effect=lambda texts, encoder: np.ones((len(texts), 2))):
            chunks = chunk_documents(docs)
        self.assertTrue(chunks)
        self.assertTrue(all(2 <= c.metadata["page_start"] <= c.metadata["page_end"] <= 3 for c in chunks))
        text = "\n\n".join(doc.page_content for doc in docs)
        for chunk in chunks:
            start = chunk.metadata["start_index"]
            self.assertGreaterEqual(start, 0)
            self.assertEqual(text[start:start + len(chunk.page_content)], chunk.page_content)
            self.assertEqual(chunk.metadata["chunking_method"], "semantic")


class CharacterEncoder:
    def encode(self, text):
        return list(text)


class SemanticChunkingTests(unittest.TestCase):
    def test_topic_change_is_selected_as_boundary(self):
        sentences = [f"Policy sentence {i:02d}." for i in range(8)]
        text = " ".join(sentences)
        def vectors(texts, encoder):
            return np.asarray([[1, 0]] * 4 + [[0, 1]] * 4)
        with patch.object(semantic_chunking, "embed_windows", side_effect=vectors):
            spans = semantic_chunking.semantic_spans(text, CharacterEncoder(), 60, 100, 25, 0)
        self.assertEqual(spans[0][1], len(" ".join(sentences[:4])) + 1)
        self.assertEqual("".join(text[a:b] for a, b in spans), text)

    def test_oversized_sentence_is_split_without_losing_text(self):
        text = "word " * 200
        with patch.object(semantic_chunking, "embed_windows", side_effect=lambda texts, encoder: np.ones((len(texts), 2))):
            spans = semantic_chunking.semantic_spans(text, CharacterEncoder(), 80, 128, 25, 0)
        self.assertTrue(all(b - a <= 128 for a, b in spans))
        self.assertEqual("".join(text[a:b] for a, b in spans), text)

    def test_cached_boundary_vectors_are_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(embedding_model="test", semantic_cache_path=Path(folder) / "cache.db")
            with patch.object(semantic_chunking, "get_settings", return_value=settings), \
                 patch.object(embeddings, "get_embedding_client") as client:
                client.return_value.embed_documents.return_value = [[1., 0.], [0., 1.]]
                first = semantic_chunking.embed_windows(["one", "two"], CharacterEncoder())
                second = semantic_chunking.embed_windows(["one", "two"], CharacterEncoder())
                self.assertEqual(client.return_value.embed_documents.call_count, 1)
                self.assertTrue(np.allclose(first, second))

    def test_boundary_embedding_failure_does_not_silently_use_another_method(self):
        with patch.object(semantic_chunking, "embed_windows", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError):
                semantic_chunking.semantic_spans("First sentence. Second sentence.", CharacterEncoder(), 30, 60, 10, 0)


class ApiTests(unittest.TestCase):
    def test_audit_failure_does_not_discard_answer(self):
        result = dict(answer="Answer", status="answered", source_used="kb", trace=[])
        with patch.object(chat, "get_settings", return_value=SimpleNamespace(kb_managed=False)), \
             patch.object(chat, "ask", return_value=result), \
             patch.object(chat, "retrieval_snapshot", return_value=__import__("contextlib").nullcontext()), \
             patch.object(chat, "write_audit", side_effect=sqlite3.OperationalError("locked")), \
             self.assertLogs("app.api.chat", level="ERROR"):
            response = chat.chat(chat.ChatRequest(question="What is covered?"))
        self.assertEqual(response["answer"], "Answer")

    def test_daily_request_budget_is_shared_between_visitors(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(usage_db_path=Path(folder) / "usage.db",
                                       daily_chat_limit=1, chat_requests_per_minute=6, monthly_chat_limit=300)
            with patch.object(limits, "get_settings", return_value=settings):
                limits.init_usage()
                limits.reserve_request(SimpleNamespace(client=SimpleNamespace(host="one")), "chat")
                with self.assertRaises(HTTPException) as caught:
                    limits.reserve_request(SimpleNamespace(client=SimpleNamespace(host="two")), "chat")
        self.assertEqual(caught.exception.status_code, 429)

    def test_monthly_request_budget_survives_new_visitors(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(usage_db_path=Path(folder) / "usage.db",
                                       daily_chat_limit=30, chat_requests_per_minute=6, monthly_chat_limit=1)
            with patch.object(limits, "get_settings", return_value=settings):
                limits.init_usage()
                limits.reserve_request(SimpleNamespace(client=SimpleNamespace(host="one")), "chat")
                with self.assertRaises(HTTPException) as caught:
                    limits.reserve_request(SimpleNamespace(client=SimpleNamespace(host="two")), "chat")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn("monthly", caught.exception.detail)
        self.assertGreater(int(caught.exception.headers["Retry-After"]), 0)


if __name__ == "__main__":
    unittest.main()

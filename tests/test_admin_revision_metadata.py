import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api import admin_documents
from app.main import app
from app.services import document_service


class AdminRevisionMetadataTests(unittest.TestCase):
    def test_revision_form_passes_source_and_review(self):
        client = TestClient(app)
        app.dependency_overrides[admin_documents.require_admin] = lambda: None
        self.addCleanup(app.dependency_overrides.pop, admin_documents.require_admin, None)
        with patch.object(admin_documents, "receive_pdf", return_value={"status": "queued"}) as receive:
            response = client.post(
                "/api/admin/kb/documents/17/revisions",
                files={"file": ("revision.pdf", b"%PDF-1.7", "application/pdf")},
                data={"source_url": "https://example.com/new.pdf", "review_required": "true",
                      "clear_source_url": "true"},
            )
        self.assertEqual(response.status_code, 202)
        metadata = receive.call_args.args[2]
        self.assertEqual(metadata["source_url"], "https://example.com/new.pdf")
        self.assertTrue(metadata["review_required"])
        self.assertTrue(metadata["clear_source_url"])

    def test_revision_clears_or_replaces_old_source_without_changing_default_api_behavior(self):
        previous = {"id": 1, "document_id": 17, "version": 1, "name": "Policy",
                    "sha256": "old", "status": "active", "withdrawn_at": None,
                    "last_error": None, "source_path": None, "source_url": "https://old.test/a.pdf",
                    "insurer": "Insurer", "category": "travel", "product_name": "Policy",
                    "document_type": "wording", "uins": [], "effective_from": None}
        for metadata, expected in [
            ({"clear_source_url": True}, None),
            ({"clear_source_url": True, "source_url": "https://new.test/b.pdf"}, "https://new.test/b.pdf"),
            ({}, "https://old.test/a.pdf"),
        ]:
            with self.subTest(metadata=metadata):
                conn = MagicMock()
                with patch.object(document_service, "connect", side_effect=lambda: nullcontext(conn)), \
                     patch.object(document_service, "lock_document"), \
                     patch.object(document_service.repository, "latest_revision",
                                  side_effect=[previous, {"id": 2, "withdrawn_at": None}]), \
                     patch.object(document_service.repository, "insert_revision", return_value=2) as insert, \
                     patch.object(document_service, "upload_pdf"):
                    document_service.register_document(b"%PDF-1.7 new", "new.pdf", metadata, document_id=17)
                self.assertEqual(insert.call_args.args[-1]["source_url"], expected)

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import admin_documents
from app.main import app


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

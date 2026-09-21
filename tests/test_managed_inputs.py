import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ingestion import pdf_parser
from app.services import document_service


class ManagedInputTests(unittest.TestCase):
    def test_non_pdf_is_rejected_before_opening_registry(self):
        for content in (b"", b"plain text"):
            with self.subTest(content=content), patch.object(document_service, "connect") as connect:
                with self.assertRaisesRegex(ValueError, "Upload a PDF"):
                    document_service.register_document(content, "policy.pdf", {})
                connect.assert_not_called()

    def test_corrupt_pdf_reports_actionable_error_before_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"%PDF-1.7\ncorrupt")
            with patch.object(pdf_parser, "converter") as converter:
                with self.assertRaisesRegex(ValueError, "Could not open the PDF"):
                    pdf_parser.parse_pdf(path, "test-revision")
                converter.assert_not_called()

    def test_storage_failure_marks_upload_failed_and_does_not_signal_worker(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"id": 1}
        with (
            patch.object(document_service, "connect", side_effect=lambda: nullcontext(conn)),
            patch.object(document_service, "lock_document"),
            patch.object(document_service.repository, "latest_revision", return_value=None),
            patch.object(document_service.repository, "insert_revision", return_value=1) as insert,
            patch.object(document_service, "upload_pdf", side_effect=TimeoutError),
            patch.object(document_service, "signal_worker") as signal,
        ):
            with self.assertRaises(TimeoutError):
                document_service.register_document(b"%PDF-1.7", "policy.pdf", {})
        insert.assert_called_once()
        signal.assert_not_called()
        self.assertTrue(any("Upload failed" in call.args[0] for call in conn.execute.call_args_list))

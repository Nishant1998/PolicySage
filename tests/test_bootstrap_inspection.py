import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from app.ingestion import bootstrap


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.revision = {"id": 7, "document_id": 4, "sha256": "abc", "withdrawn_at": None,
                         "object_key": "test.pdf", "status": "active", "chunk_count": 1}
        self.stack = [
            patch.object(bootstrap, "connect", side_effect=lambda: nullcontext(MagicMock())),
            patch.object(bootstrap.repository, "document_for_source", return_value={"document_id": 4}),
            patch.object(bootstrap.repository, "latest_revision", return_value=self.revision),
            patch.object(bootstrap, "get_settings", return_value=SimpleNamespace(kb_s3_bucket="test",embedding_model="model")),
            patch.object(bootstrap, "object_store"),
            patch.object(bootstrap, "records"),
            patch.object(bootstrap, "upload_pdf"),
        ]
        self.mocks = [p.start() for p in self.stack]
        for p in self.stack: self.addCleanup(p.stop)
        self.store, self.records, self.upload = self.mocks[-3:]
        self.store.return_value.head_object.return_value = {"ContentLength": 3}
        self.records.return_value = {bootstrap.point_id("7-000000"): {
            "document_revision":"7", "document_id":"4", "embedding_model":"model", "text":"sample"}}

    def test_existing_complete(self):
        self.assertEqual(bootstrap.inspect_existing("home/a.pdf", "abc", b"pdf"), "unchanged")
        self.upload.assert_not_called()

    def test_missing_object_is_restored_only_on_not_found(self):
        self.store.return_value.head_object.side_effect = ClientError({"Error":{"Code":"404"}}, "HeadObject")
        self.assertEqual(bootstrap.inspect_existing("home/a.pdf", "abc", b"pdf"), "unchanged")
        self.upload.assert_called_once_with("test.pdf", b"pdf")

    def test_missing_vectors_request_safe_new_revision(self):
        self.records.return_value = {}
        self.assertEqual(bootstrap.inspect_existing("home/a.pdf", "abc", b"pdf"), ("repair", 7))

    def test_denied_object_access_stops(self):
        self.store.return_value.head_object.side_effect = ClientError({"Error":{"Code":"403"}}, "HeadObject")
        with self.assertRaises(ClientError):
            bootstrap.inspect_existing("home/a.pdf", "abc", b"pdf")
        self.upload.assert_not_called()

    def test_changed_file_is_not_mistaken_for_existing(self):
        self.assertIsNone(bootstrap.inspect_existing("home/a.pdf", "different", b"pdf"))
        self.store.return_value.head_object.assert_not_called()

    def test_bootstrap_without_source_inspects_all_selected_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.pdf").write_bytes(b"%PDF-a")
            (root / "b.pdf").write_bytes(b"%PDF-b")
            settings = SimpleNamespace(kb_dir=root)
            with patch.object(bootstrap, "get_settings", return_value=settings), \
                 patch.object(bootstrap, "inspect_existing", side_effect=["unchanged", None]) as inspect, \
                 patch.object(bootstrap, "register_document", return_value={"status": "queued"}) as register:
                bootstrap.bootstrap()
            self.assertEqual(inspect.call_count, 2)
            register.assert_called_once()
            self.assertEqual(register.call_args.kwargs["source"], "b.pdf")

    def test_checksum_mismatch_stops_before_inspection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.pdf").write_bytes(b"%PDF-a")
            with patch.object(bootstrap, "get_settings", return_value=SimpleNamespace(kb_dir=root)), \
                 patch.object(bootstrap, "selected_pdfs", return_value={"a.pdf": {"sha256": "wrong"}}), \
                 patch.object(bootstrap, "inspect_existing") as inspect, \
                 patch.object(bootstrap, "register_document") as register:
                with self.assertRaises(SystemExit):
                    bootstrap.bootstrap()
            inspect.assert_not_called()
            register.assert_not_called()

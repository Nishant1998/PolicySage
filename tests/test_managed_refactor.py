import hashlib
import tempfile
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pydantic import SecretStr

from app.api import admin_documents, document_sources
from app.core.revisions import revision_record_ids
from app.infrastructure import qdrant_store
from app.ingestion import bootstrap, cli, indexer, service, worker
from app import main
from app.main import app
from app.services import document_service


PDF = b"%PDF-1.7 test"
REVISION_ID = "1" * 32
REPLACEMENT_ID = "2" * 32
DIGEST = hashlib.sha256(PDF).hexdigest()


class RegistrationTests(unittest.TestCase):
    def test_bootstrap_queues_new_pdf_and_skips_unchanged_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "policy.pdf").write_bytes(PDF)
            with patch.object(bootstrap, "get_settings", return_value=SimpleNamespace(kb_dir=root)), \
                 patch.object(bootstrap, "inspect_existing", side_effect=[None, "unchanged"]), \
                 patch.object(bootstrap, "register_document", return_value={"status": "queued"}) as register:
                bootstrap.bootstrap()
                bootstrap.bootstrap()
            register.assert_called_once()
            self.assertEqual(register.call_args.kwargs["source"], "policy.pdf")

    def test_cli_bootstrap_supports_optional_staging(self):
        with patch.object(cli, "get_settings", return_value=SimpleNamespace(log_level="INFO", app_env="test")), \
             patch.object(cli, "configure_logging"), patch.object(cli, "initialize"), \
             patch.object(cli, "bootstrap") as register:
            cli.main(["bootstrap"])
            cli.main(["bootstrap", "--stage-only"])
        self.assertEqual(register.call_args_list, [call(stage_only=False, sources=None),
                                                  call(stage_only=True, sources=None)])

    def test_upload_is_not_attempted_if_registration_fails(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"id": 1}
        with patch.object(document_service, "connect", return_value=nullcontext(conn)), \
             patch.object(document_service, "lock_document"), \
             patch.object(document_service.repository, "latest_revision", return_value=None), \
             patch.object(document_service.repository, "insert_revision", side_effect=OSError), \
             patch.object(document_service, "upload_pdf") as upload:
            with self.assertRaises(OSError):
                document_service.register_document(PDF, "policy.pdf", {})
        upload.assert_not_called()

    def test_duplicate_pdf_returns_existing_revision_without_upload(self):
        previous = {"id": 1, "version": 1, "status": "active", "withdrawn_at": None,
                    "sha256": DIGEST, "last_error": None}
        with patch.object(document_service, "connect", return_value=nullcontext(MagicMock())), \
             patch.object(document_service, "lock_document"), \
             patch.object(document_service.repository, "latest_revision", return_value=previous), \
             patch.object(document_service, "upload_pdf") as upload:
            result = document_service.register_document(PDF, "policy.pdf", {}, document_id=1)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["revision_id"], 1)
        upload.assert_not_called()


class WorkerTests(unittest.TestCase):
    def test_indexing_retries_same_ids_after_embedding_or_verification_failure(self):
        for failure_stage in ("embedding", "verification"):
            with self.subTest(failure_stage=failure_stage):
                self.check_indexing_retry(failure_stage)

    def check_indexing_retry(self, failure_stage):
        write_results = [ConnectionError, None] if failure_stage == "embedding" else [None, None]
        verify_results = [{}] if failure_stage == "embedding" else [TimeoutError, {}]
        revision = {
            "id": REPLACEMENT_ID, "document_id": REVISION_ID, "document_revision": REPLACEMENT_ID,
            "embedding_model": "test", "object_key": "pdf-key", "sha256": DIGEST, "chunk_count": 0,
            "insurer": "Insurer", "category": None, "product_name": None, "document_type": None,
            "source_url": None, "uins": ["U1"], "name": "Policy", "status": "parsing",
        }
        conn = MagicMock()
        record_ids = revision_record_ids(REPLACEMENT_ID, 1)
        chunks = [Document(page_content="Policy clause", metadata={"page_start": 3, "page_end": 4})]
        with patch.object(service, "get_settings", return_value=SimpleNamespace(embedding_model="test")), \
             patch.object(service, "download_pdf", return_value=PDF), \
             patch.object(service, "parse_pdf", return_value=([], 4)), \
             patch.object(service, "chunk_documents", return_value=chunks), \
             patch.object(service.repository, "claim_job", side_effect=[revision, None, revision, None]), \
             patch.object(service.repository, "set_stage", return_value=1), \
             patch.object(service.repository, "save_index_manifest", return_value=1), \
             patch.object(service.repository, "fail_job") as fail, \
             patch.object(service, "delete_records"), \
             patch.object(service, "write_chunks", side_effect=write_results) as write, \
             patch.object(service, "wait_for_records", side_effect=verify_results) as verify, \
             patch.object(service, "publish_revision") as publish, \
             self.assertLogs(worker.logger, level="ERROR"):
            self.assertEqual(worker.drain(conn, False), 1)
            publish.assert_not_called()
            if failure_stage == "embedding":
                verify.assert_not_called()
            self.assertEqual(worker.drain(conn, False), 0)
        self.assertEqual([entry.kwargs["record_ids"] for entry in write.call_args_list], [record_ids, record_ids])
        expected = verify.call_args.kwargs["expected"][record_ids[0]]
        self.assertEqual(expected["document_revision"], REPLACEMENT_ID)
        self.assertEqual((expected["page_start"], expected["page_end"]), (3, 4))
        self.assertFalse(expected["is_active"])
        error_type = "ConnectionError" if failure_stage == "embedding" else "TimeoutError"
        fail.assert_called_once_with(conn, REPLACEMENT_ID, False, error_type)
        publish.assert_called_once_with(conn, revision)

    def test_partial_vector_write_retries_only_missing_record_ids(self):
        ids = revision_record_ids(REPLACEMENT_ID, 2)
        chunks = [
            Document(page_content=text, metadata={"document_revision": REPLACEMENT_ID, "is_active": False})
            for text in ("First clause.", "Second clause.")
        ]
        records = {}
        store = MagicMock()
        def write(collection, points, wait):
            records[points[0].id] = points[0].payload
            if len(points) > 1:
                raise ConnectionError("Partial write")
        store.upsert.side_effect = write
        with patch.object(indexer, "get_settings", return_value=SimpleNamespace(qdrant_collection="test")), \
             patch.object(indexer, "client", return_value=store), \
             patch.object(indexer, "records", side_effect=lambda keys: dict(records)), \
             patch.object(indexer, "get_embedding_client") as embeddings:
            embeddings.return_value.embed_documents.side_effect = lambda texts: [[0.1]] * len(texts)
            with self.assertRaises(ConnectionError):
                indexer.write_chunks(chunks, record_ids=ids)
            self.assertEqual(set(records), {qdrant_store.point_id(ids[0])})
            indexer.write_chunks(chunks, record_ids=ids)
            indexer.write_chunks(chunks, record_ids=ids)
            self.assertEqual(store.upsert.call_count, 2)

    def test_interrupted_publication_keeps_previous_revision_until_retry(self):
        revision = {"id": REPLACEMENT_ID, "document_id": REVISION_ID}
        committed = {REVISION_ID: "active", REPLACEMENT_ID: "verifying"}

        pending = {}

        @contextmanager
        def transaction():
            pending.clear()
            pending.update(committed)
            yield
            committed.update(pending)

        conn = SimpleNamespace(transaction=transaction)

        def retire(conn, document_id):
            pending[REVISION_ID] = "cleanup_pending"

        def publish(conn, revision_id):
            pending[revision_id] = "active"
            raise KeyboardInterrupt()

        with patch.object(service, "lock_document"), \
             patch.object(service.repository, "ready_revision", return_value={"chunk_count": 1}), \
             patch.object(service.repository, "retire_active", side_effect=retire), \
             patch.object(service.repository, "mark_published", side_effect=publish) as mark, \
             patch.object(service, "wait_for_records", side_effect=[TimeoutError, {}, {}]) as verify, \
             patch.object(qdrant_store, "client") as vector_store:
            with self.assertRaises(TimeoutError):
                service.publish_revision(conn, revision)
            self.assertEqual(committed, {REVISION_ID: "active", REPLACEMENT_ID: "verifying"})
            mark.assert_not_called()

            with self.assertRaises(KeyboardInterrupt):
                service.publish_revision(conn, revision)
            self.assertEqual(committed, {REVISION_ID: "active", REPLACEMENT_ID: "verifying"})

            mark.side_effect = lambda conn, revision_id: pending.update({revision_id: "active"})
            service.publish_revision(conn, revision)

        self.assertEqual(committed, {REVISION_ID: "cleanup_pending", REPLACEMENT_ID: "active"})
        self.assertEqual(verify.call_args_list, [call(revision_record_ids(REPLACEMENT_ID, 1))] * 3)
        vector_store.assert_not_called()

    def test_review_pending_revision_waits_for_approval(self):
        conn = MagicMock()
        revision = {"id": REPLACEMENT_ID, "document_id": REVISION_ID}
        with patch.object(service, "lock_document"), \
             patch.object(service.repository, "ready_revision", side_effect=[None, {"chunk_count": 1}]), \
             patch.object(service.repository, "retire_active"), \
             patch.object(service.repository, "mark_published") as publish, \
             patch.object(service, "wait_for_records") as verify:
            service.publish_revision(conn, revision)
            publish.assert_not_called()
            verify.assert_not_called()

            service.publish_revision(conn, revision)
            verify.assert_called_once_with(revision_record_ids(REPLACEMENT_ID, 1))
            publish.assert_called_once_with(conn, REPLACEMENT_ID)

    def test_watch_cli_starts_persistent_worker(self):
        settings = SimpleNamespace(log_level="INFO", app_env="test")
        with patch.object(cli, "get_settings", return_value=settings), \
             patch.object(cli, "configure_logging"), \
             patch.object(cli, "watch_worker") as watch:
            cli.main(["worker", "--watch"])
        watch.assert_called_once()

    def test_staged_enqueue_is_all_or_nothing(self):
        conn = MagicMock()
        rows = [{"id": REVISION_ID, "source_path": "staged.pdf"}]
        with patch.object(bootstrap.repository, "staged_revisions", return_value=rows), \
             patch.object(bootstrap.repository, "enqueue_revisions") as enqueue:
            with self.assertRaises(SystemExit):
                bootstrap.queue_staged(conn, ["staged.pdf", "missing.pdf"])
            enqueue.assert_not_called()
            bootstrap.queue_staged(conn, ["staged.pdf"])
        enqueue.assert_called_once_with(conn, [REVISION_ID])


class WithdrawalTests(unittest.TestCase):
    def test_withdrawal_updates_the_registry_and_is_idempotent(self):
        conn = MagicMock()
        with patch.object(document_service, "connect", return_value=nullcontext(conn)), \
             patch.object(document_service, "lock_document") as lock, \
             patch.object(document_service.repository, "mark_withdrawn", side_effect=[1, 0, 0]) as withdraw, \
             patch.object(document_service.repository, "document_exists", side_effect=[True, False]):
            document_service.withdraw(REVISION_ID)
            document_service.withdraw(REVISION_ID)
            with self.assertRaisesRegex(ValueError, "Document not found"):
                document_service.withdraw("missing")
        self.assertEqual(withdraw.call_args_list, [call(conn, REVISION_ID), call(conn, REVISION_ID), call(conn, "missing")])
        self.assertEqual(lock.call_args_list, withdraw.call_args_list)


class HttpContractTests(unittest.TestCase):
    def test_admin_upload_and_citation_access_contracts(self):
        settings = SimpleNamespace(
            kb_managed=True, app_env="test", admin_api_key=SecretStr("example-key"),
            kb_admin_username="admin", public_pdf_downloads_enabled=False,
        )
        result = {"document_id": REVISION_ID, "revision_id": REVISION_ID, "status": "queued"}
        # A client without lifespan can exercise real routers without loading the reranker.
        client = TestClient(app, base_url="https://testserver")
        with patch.object(admin_documents, "get_settings", return_value=settings), \
             patch.object(admin_documents, "reserve_request"), \
             patch.object(admin_documents, "request_slot", return_value=nullcontext()), \
             patch.object(admin_documents, "register_document", return_value=result) as register:
            upload = {"file": ("policy.pdf", PDF, "application/pdf")}
            self.assertEqual(client.post("/api/admin/kb/documents", files=upload).status_code, 401)
            response = client.post("/api/admin/kb/documents", files=upload, auth=("admin", "example-key"))
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), result)
            register.assert_called_once()
            self.assertEqual(register.call_args.args[:2], (PDF, "policy.pdf"))

        url = "/api/kb/revisions/1.pdf"
        with patch.object(document_sources, "get_settings", return_value=settings), \
             patch.object(document_sources, "reserve_request"), \
             patch.object(document_sources.repository, "published_object", return_value={"object_key": "pdf-key"}) as lookup, \
             patch.object(document_sources, "signed_pdf_url", return_value="https://example.test/signed"):
            self.assertEqual(client.get(url).status_code, 404)
            lookup.assert_not_called()
            settings.public_pdf_downloads_enabled = True
            response = client.get(url, follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["location"], "https://example.test/signed")
            # Global middleware applies the same policy as before the router split.
            self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")

    def test_web_startup_serves_health_without_running_ingestion(self):
        settings = SimpleNamespace(log_level="INFO", app_name="PolicySage", app_env="test")
        with patch.object(main, "get_settings", return_value=settings), \
             patch("app.api.health.get_settings", return_value=settings), \
             patch.object(main, "configure_logging"), \
             patch.object(main, "init_db"), patch.object(main, "init_usage"), \
             patch.object(main, "reranker"), \
             patch.object(bootstrap, "bootstrap") as register, \
             patch.object(cli, "drain") as process, TestClient(app) as client:
            self.assertEqual(client.get("/api/health").json(), {"status": "ok", "service": "PolicySage"})
        register.assert_not_called()
        process.assert_not_called()

    def test_admin_preview_approval_and_retry_require_authentication(self):
        settings = SimpleNamespace(
            kb_managed=True, app_env="production", admin_api_key=SecretStr("example-key"),
            kb_admin_username="admin", public_pdf_downloads_enabled=False,
        )
        client = TestClient(app, base_url="https://testserver")
        auth = ("admin", "example-key")
        preview = f"/api/admin/kb/revisions/{REVISION_ID}/preview"
        approval = f"/api/admin/kb/revisions/{REVISION_ID}/approve"
        retry = f"/api/admin/kb/jobs/{REVISION_ID}/retry"

        with patch.object(admin_documents, "get_settings", return_value=settings), \
             patch.object(admin_documents, "reserve_request"), \
             patch.object(document_sources.repository, "preview_object", return_value={"object_key": "private-key"}) as lookup, \
             patch.object(document_sources, "signed_pdf_url", return_value="https://storage.example/signed") as sign, \
             patch.object(admin_documents.repository, "approve_revision", side_effect=[{"id": REVISION_ID}, None]) as approve, \
             patch.object(admin_documents.repository, "retry_job", side_effect=[{"id": REVISION_ID}, None]) as requeue:
            self.assertEqual(client.get(preview).status_code, 401)
            self.assertEqual(client.post(approval).status_code, 401)
            self.assertEqual(client.post(retry).status_code, 401)
            for action in (lookup, sign, approve, requeue):
                action.assert_not_called()

            self.assertEqual(client.get(preview, auth=auth).json(), {"url": "https://storage.example/signed"})
            lookup.assert_called_once_with(REVISION_ID)
            sign.assert_called_once_with("private-key")
            self.assertEqual(client.post(approval, auth=auth).json(), {"status": "approved"})
            self.assertEqual(client.post(approval, auth=auth).status_code, 409)
            self.assertEqual(client.post(retry, auth=auth).json(), {"status": "queued"})
            self.assertEqual(client.post(retry, auth=auth).status_code, 409)

    def test_document_and_job_lists_preserve_frontend_fields_and_require_auth(self):
        settings = SimpleNamespace(
            kb_managed=True, app_env="production", admin_api_key=SecretStr("example-key"),
            kb_admin_username="admin",
        )
        client = TestClient(app, base_url="https://testserver")
        documents = [{"id": REVISION_ID, "title": "Policy", "active_revision": REVISION_ID,
                      "withdrawn_at": None}]
        jobs = [{"id": REPLACEMENT_ID, "status": "failed", "last_error": "TimeoutError"}]
        with (
            patch.object(admin_documents, "get_settings", return_value=settings),
            patch.object(admin_documents, "reserve_request"),
            patch.object(admin_documents.repository, "list_documents", return_value=documents) as list_docs,
            patch.object(admin_documents.repository, "list_jobs", return_value=jobs) as list_jobs,
        ):
            for endpoint, rows, query in (("documents", documents, list_docs), ("jobs", jobs, list_jobs)):
                with self.subTest(endpoint=endpoint):
                    url = f"/api/admin/kb/{endpoint}"
                    self.assertEqual(client.get(url).status_code, 401)
                    query.assert_not_called()
                    response = client.get(url, auth=("admin", "example-key"))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), rows)
                    query.assert_called_once()

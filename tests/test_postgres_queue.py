import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.db import document_repository as repository
from app.db.schema import SCHEMA
from app.services import limits
from fastapi import HTTPException


@unittest.skipUnless(os.getenv("POLICYSAGE_TEST_POSTGRES"), "Requires a disposable local PostgreSQL database")
class PostgreSQLQueueTests(unittest.TestCase):
    def test_concurrent_quota_reservations_and_slots_use_shared_database(self):
        config = conninfo_to_dict(os.environ["POLICYSAGE_TEST_POSTGRES"])
        self.assertIn(config.get("host"), ("127.0.0.1", "::1"))
        self.assertEqual(config.get("hostaddr", config["host"]), config["host"])
        self.assertEqual(config.get("dbname"), "policysage_test")
        schema_name = f"limits_test_{uuid4().hex}"
        schema = sql.Identifier(schema_name)
        config.update(connect_timeout=5, options=f"-c search_path={schema_name} -c statement_timeout=5000")
        settings = SimpleNamespace(chat_requests_per_minute=1, daily_chat_limit=100,
                                   monthly_chat_limit=100, max_concurrent_chats=1)

        def connect(*, autocommit=False):
            return psycopg.connect(**config, autocommit=autocommit, row_factory=dict_row)

        def reserve():
            request = SimpleNamespace(client=SimpleNamespace(host="same-client"))
            try:
                limits.reserve_request(request, "chat")
                return 200
            except HTTPException as exc:
                return exc.status_code

        with psycopg.connect(**{**config, "options": "-c statement_timeout=5000"}, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
            try:
                with patch.object(limits, "connect", side_effect=connect), \
                     patch.object(limits, "get_settings", return_value=settings):
                    limits.init_usage()
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        self.assertEqual(sorted(executor.map(lambda _: reserve(), range(2))), [200, 429])
                    with limits.request_slot("chat"):
                        with self.assertRaises(HTTPException) as caught:
                            with limits.request_slot("chat"):
                                self.fail("A second slot must not be available")
                        self.assertEqual(caught.exception.status_code, 503)
                    with limits.request_slot("chat"):
                        pass
            finally:
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))

    def test_claim_skips_locked_revision_and_recovery_requeues_interrupted_jobs(self):
        config = conninfo_to_dict(os.environ["POLICYSAGE_TEST_POSTGRES"])
        self.assertIn(config.get("host"), ("127.0.0.1", "::1"))
        self.assertEqual(config.get("hostaddr", config["host"]), config["host"])
        self.assertEqual(config.get("dbname"), "policysage_test")
        config.update(connect_timeout=5, options="-c statement_timeout=5000")
        schema = sql.Identifier(f"queue_test_{uuid4().hex}")

        with (
            psycopg.connect(**config, autocommit=True, row_factory=dict_row) as first,
            psycopg.connect(**config, autocommit=True, row_factory=dict_row) as second,
        ):
            first.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
            try:
                for conn in (first, second):
                    conn.execute(sql.SQL("SET search_path TO {}").format(schema))
                first.execute(SCHEMA)
                first.execute("""
                    INSERT INTO documents (document_id, version, name, filename, status, object_key, sha256)
                    VALUES (1, 1, 'First', 'a.pdf', 'queued', 'a.pdf', repeat('a', 64)),
                           (2, 1, 'Second', 'b.pdf', 'queued', 'b.pdf', repeat('b', 64)),
                           (3, 1, 'Review', 'c.pdf', 'verifying', 'c.pdf', repeat('c', 64))
                """)
                first.execute("UPDATE documents SET review_required=true WHERE document_id=3")

                with first.transaction():
                    self.assertEqual(repository.claim_job(first)["document_id"], 1)
                    self.assertEqual(repository.claim_job(second)["document_id"], 2)
                    self.assertIsNone(repository.claim_job(second))

                repository.recover_interrupted_jobs(first)
                recovered = first.execute("SELECT id, status, attempts FROM documents ORDER BY id").fetchall()
                self.assertEqual([(row["status"], row["attempts"]) for row in recovered],
                                 [("queued", 1), ("queued", 1), ("verifying", 0)])
                self.assertEqual(repository.claim_job(second)["attempts"], 2)
            finally:
                first.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))

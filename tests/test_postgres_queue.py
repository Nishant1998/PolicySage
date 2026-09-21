import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.db import document_repository as repository
from app.db.schema import SCHEMA


@unittest.skipUnless(os.getenv("POLICYSAGE_TEST_POSTGRES"), "Requires a disposable local PostgreSQL database")
class PostgreSQLQueueTests(unittest.TestCase):
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

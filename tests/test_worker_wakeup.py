import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.ingestion import worker


class WorkerWakeTests(unittest.TestCase):
    def test_scheduled_worker_recovers_and_drains_only_after_acquiring_lock(self):
        conn = MagicMock()
        with patch.object(worker, "connect") as connect, \
             patch.object(worker.repository, "try_worker_lock", return_value=True), \
             patch.object(worker.repository, "recover_interrupted_jobs") as recover, \
             patch.object(worker, "drain", return_value=0) as drain:
            connect.return_value.__enter__.return_value = conn
            worker.process_queued_jobs()
        recover.assert_called_once_with(conn)
        drain.assert_called_once_with(conn, watch=False)

    def test_scheduled_worker_leaves_queue_to_existing_worker(self):
        with patch.object(worker, "connect"), \
             patch.object(worker.repository, "try_worker_lock", return_value=False), \
             patch.object(worker.repository, "recover_interrupted_jobs") as recover, \
             patch.object(worker, "drain") as drain:
            worker.process_queued_jobs()
        recover.assert_not_called()
        drain.assert_not_called()

    def test_worker_closes_database_before_waiting_and_wakes_on_signal(self):
        state = {"connected": False, "version": "before", "connects": 0}

        @contextmanager
        def connection(**kwargs):
            state["connected"] = True
            state["connects"] += 1
            try:
                yield MagicMock()
            finally:
                state["connected"] = False

        def sleep(seconds):
            self.assertFalse(state["connected"])
            state["version"] = "new job"

        def version():
            if state["connects"] == 2:
                raise KeyboardInterrupt()
            return state["version"]

        with patch.object(worker, "connect", side_effect=connection), \
             patch.object(worker, "signal_version", side_effect=version), \
             patch.object(worker.time, "sleep", side_effect=sleep), \
             patch.object(worker.repository, "try_worker_lock", return_value=True), \
             patch.object(worker.repository, "recover_interrupted_jobs"), \
             patch.object(worker.repository, "next_cleanup_delay", return_value=None), \
             patch.object(worker, "drain") as drain:
            with self.assertRaises(KeyboardInterrupt):
                worker.watch_worker()
        self.assertEqual(state["connects"], 2)
        self.assertEqual(drain.call_count, 2)

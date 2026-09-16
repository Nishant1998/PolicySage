import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ingestion import worker, wakeup


class WorkerWakeTests(unittest.TestCase):
    def test_signal_file_changes_each_time(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(wakeup, "SIGNAL_PATH", Path(directory) / "wake"):
            self.assertIsNone(wakeup.signal_version())
            wakeup.signal_worker()
            first = wakeup.signal_version()
            wakeup.signal_worker()
            self.assertIsNotNone(first)
            self.assertNotEqual(first, wakeup.signal_version())

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

    def test_cleanup_schedules_earlier_wakeup(self):
        clock = [0]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 6:
                raise KeyboardInterrupt()
        conn = MagicMock()
        with patch.object(worker, "connect", return_value=conn), \
             patch.object(worker, "signal_version", return_value=None), \
             patch.object(worker.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(worker.time, "sleep", side_effect=sleep), \
             patch.object(worker.repository, "try_worker_lock", return_value=True), \
             patch.object(worker.repository, "recover_interrupted_jobs"), \
             patch.object(worker.repository, "next_cleanup_delay", return_value=6), \
             patch.object(worker, "drain"):
            with self.assertRaises(KeyboardInterrupt):
                worker.watch_worker()
        self.assertEqual(clock[0], 6)
        conn.__exit__.assert_called_once()

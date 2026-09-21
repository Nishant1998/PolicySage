import json
import logging
import unittest
from unittest.mock import patch

from app.core.logging import ConsoleFormatter, JsonFormatter
from app.core.observability import event, span


class ConsoleLoggingTests(unittest.TestCase):
    def test_request_summary_is_short_and_informative(self):
        record = logging.LogRecord("app.core.observability", logging.INFO, "", 0, "request_finished", (), None)
        record.fields = {"path": "/api/chat", "duration_ms": 1250, "llm_calls": 2, "total_tokens": 450}
        message = ConsoleFormatter().format(record)
        self.assertIn("Request completed", message)
        self.assertIn("duration_ms=1250", message)
        self.assertIn("llm_calls=2", message)
        self.assertNotIn("{", message)

    def test_detailed_events_are_debug_and_errors_stay_visible(self):
        with self.assertLogs("app.core.observability", level="DEBUG") as logs:
            event("stage_finished", stage="qdrant_dense", duration_ms=10, error_type=None)
            event("stage_finished", stage="qdrant_dense", error_type="TimeoutError")
            event("request_finished", path="/api/chat", duration_ms=100)
        self.assertEqual([record.levelno for record in logs.records], [logging.DEBUG, logging.WARNING, logging.INFO])
        self.assertIn("stage=qdrant_dense", ConsoleFormatter().format(logs.records[1]))
        self.assertIn("error_type=TimeoutError", ConsoleFormatter().format(logs.records[1]))

    def test_structured_logs_remain_available(self):
        record = logging.LogRecord("app.core.observability", logging.INFO, "", 0, "request_finished", (), None)
        record.fields = {"path": "/api/chat", "duration_ms": 300}
        self.assertEqual(json.loads(JsonFormatter().format(record))["duration_ms"], 300)

    def test_span_still_exports_detail(self):
        parent = unittest.mock.MagicMock()
        child = parent.create_child.return_value
        from app.core.observability import current_span
        token = current_span.set(parent)
        try:
            with span("example") as fields:
                fields["matches"] = 5
        finally:
            current_span.reset(token)
        self.assertEqual(child.end.call_args.kwargs["outputs"]["matches"], 5)

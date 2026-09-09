import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from app.core import observability as obs
from app.core.logging import JsonFormatter


def settings(**changes):
    return SimpleNamespace(langsmith_enabled=False, openai_model="test-model",
                           llm_input_usd_per_million=1.0, llm_output_usd_per_million=2.0,
                           llm_cached_input_usd_per_million=0.5, **changes)


class ObservabilityTests(unittest.TestCase):
    def test_usage_is_accumulated_and_request_state_is_cleared(self):
        response = SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 20})
        with patch.object(obs, "get_settings", return_value=settings()):
            with obs.observe_request("/api/chat", "POST") as request:
                obs.record_usage(response, "test")
                obs.record_usage(response, "test")
                self.assertEqual(request["input_tokens"], 200)
                self.assertEqual(request["llm_calls"], 2)
                self.assertAlmostEqual(request["estimated_cost_usd"], 0.00028)
            self.assertIsNone(obs.current_request.get())
            with obs.observe_request("/api/chat", "POST") as another:
                self.assertNotEqual(request["id"], another["id"])
                self.assertEqual(another["input_tokens"], 0)

    def test_missing_usage_does_not_claim_zero_cost(self):
        with patch.object(obs, "get_settings", return_value=settings()):
            with obs.observe_request("/api/chat", "POST") as request:
                obs.record_usage(SimpleNamespace(), "test")
                self.assertFalse(request["cost_complete"])
                self.assertEqual(request["usage_missing"], 1)

    def test_tracing_failure_does_not_break_the_request(self):
        config = settings(langsmith_api_key=SimpleNamespace(get_secret_value=lambda: "fake"))
        config.langsmith_enabled = True
        config.langsmith_agent_id = "policysage"
        config.langsmith_agent_environment = "local"
        with patch.object(obs, "get_settings", return_value=config), \
             patch.object(obs, "trace_client", side_effect=RuntimeError("unavailable")):
            with obs.observe_request("/api/chat", "POST") as request:
                self.assertTrue(request["id"])

    def test_traces_target_the_registered_agent_environment(self):
        config = settings(langsmith_api_key=SimpleNamespace(get_secret_value=lambda: "fake"))
        config.langsmith_enabled = True
        config.langsmith_agent_id = "policysage"
        config.langsmith_agent_environment = "local"
        with patch.object(obs, "get_settings", return_value=config), \
             patch.object(obs, "trace_client"), patch.object(obs, "RunTree") as root, \
             patch.object(obs, "agent_address", return_value="destination") as address:
            with obs.observe_request("/api/chat", "POST"):
                pass
        address.assert_called_once_with("policysage", "local")
        self.assertEqual(root.call_args.kwargs["address"], "destination")
        self.assertNotIn("project_name", root.call_args.kwargs)

    def test_export_starts_only_after_request_is_admitted(self):
        config = settings(langsmith_api_key=SimpleNamespace(get_secret_value=lambda: "fake"))
        config.langsmith_enabled = True
        config.langsmith_agent_id = "policysage"
        config.langsmith_agent_environment = "local"
        with patch.object(obs, "get_settings", return_value=config), \
             patch.object(obs, "trace_client"), patch.object(obs, "RunTree") as root:
            with obs.observe_request("/api/chat", "POST", export=False):
                pass
            root.assert_not_called()
            with obs.observe_request("/api/chat", "POST", export=False) as request:
                obs.start_request_trace()
                obs.start_request_trace()
                request["http_status"] = 200
            root.assert_called_once()
            outputs = root.return_value.end.call_args.kwargs["outputs"]
            self.assertEqual(outputs["http_status"], 200)
            self.assertNotIn("_root", outputs)

    def test_node_trace_excludes_questions_answers_and_documents(self):
        parent = MagicMock()
        token = obs.current_span.set(parent)
        try:
            function = obs.observed_node(lambda state: {"answer": "private answer", "route": "kb"})
            self.assertEqual(function({"question": "private question"})["answer"], "private answer")
            payload = parent.create_child.return_value.end.call_args.kwargs["outputs"]
            self.assertNotIn("answer", payload)
            self.assertNotIn("question", payload)
            self.assertEqual(payload["route"], "kb")
        finally:
            obs.current_span.reset(token)

    def test_json_logs_omit_exception_message(self):
        try:
            raise ValueError("sensitive content")
        except ValueError:
            import sys
            record = logging.LogRecord("test", logging.ERROR, "", 0, "operation_failed", (), sys.exc_info())
        result = JsonFormatter().format(record)
        self.assertNotIn("sensitive content", result)
        self.assertEqual(json.loads(result)["error_type"], "ValueError")

    def test_debug_content_is_redacted_and_excluded_from_application_logs(self):
        config = settings(langsmith_debug_content=True)
        parent = MagicMock()
        with patch.object(obs, "get_settings", return_value=config), \
             patch.object(obs, "event") as event, \
             obs.observe_request("/api/chat", "POST", export=False):
            token = obs.current_span.set(parent)
            try:
                with obs.span("debug"):
                    obs.trace_details(answer=obs.trace_content("hello example@example.org token=secret-value"))
            finally:
                obs.current_span.reset(token)
        output = parent.create_child.return_value.end.call_args.kwargs["outputs"]
        self.assertEqual(output["answer"], "hello [redacted] [redacted]")
        self.assertNotIn("answer", event.call_args_list[1].kwargs)

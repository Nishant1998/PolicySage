import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core import token_budget as tokens
from app.rag import workflow


class TokenBudgetTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(max_request_tokens=5000, max_prompt_tokens=1000,
                                 max_answer_tokens=200, max_history_tokens=100)
        settings = patch.object(tokens, "get_settings", return_value=config)
        settings.start()
        self.addCleanup(settings.stop)
        counter = patch.object(tokens, "token_count", side_effect=len)
        counter.start()
        self.addCleanup(counter.stop)
        workflow_counter = patch.object(workflow, "token_count", side_effect=len)
        workflow_counter.start()
        self.addCleanup(workflow_counter.stop)

    def test_complete_prompt_is_checked_before_model_call(self):
        with tokens.token_budget(), patch.object(workflow, "get_llm_client") as client:
            with self.assertRaises(tokens.TokenBudgetExceeded):
                workflow.invoke_text([("system", "x" * 1001), ("human", "short")], "test")
            client.assert_not_called()

    def test_actual_usage_replaces_reservation(self):
        with tokens.token_budget():
            reserved = tokens.reserve_call([("human", "question")])
            tokens.settle_call(reserved, SimpleNamespace(usage_metadata={"input_tokens": 90, "output_tokens": 10}))
            self.assertEqual(tokens._current.get()["used"], 100)

    def test_missing_usage_keeps_full_reservation(self):
        with tokens.token_budget():
            reserved = tokens.reserve_call([("human", "question")])
            tokens.settle_call(reserved, SimpleNamespace())
            self.assertEqual(tokens._current.get()["used"], reserved)

    def test_research_cannot_spend_the_final_response_reserve(self):
        with tokens.token_budget():
            tokens._current.get()["used"] = 3800
            with self.assertRaises(tokens.TokenBudgetExceeded):
                tokens.reserve_call([("human", "question")])
            tokens.reserve_call([("human", "question")], final=True)

    def test_oldest_history_is_removed_as_complete_turns(self):
        history = [{"question": "old", "answer": "x" * 100}, {"question": "new", "answer": "short"}]
        self.assertEqual(tokens.trim_history(history), history[-1:])
        self.assertEqual(len(history), 2)

    def test_request_state_is_reset(self):
        with tokens.token_budget():
            tokens.reserve_call([("human", "question")])
        self.assertIsNone(tokens._current.get())
        with tokens.token_budget():
            self.assertEqual(tokens._current.get()["used"], 0)

    def test_exhaustion_returns_a_limitation_without_another_call(self):
        class Graph:
            def stream(self, *args, **kwargs):
                raise tokens.TokenBudgetExceeded()
        with patch.object(workflow, "get_settings", return_value=SimpleNamespace(web_search_enabled=True, max_question_tokens=1024)), \
             patch.object(workflow, "build_graph", return_value=Graph()), \
             patch.object(workflow, "get_llm_client") as client:
            result = workflow.ask("What is covered?")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["citations"], [])
        client.assert_not_called()

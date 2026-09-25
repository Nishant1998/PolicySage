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

    def test_research_cannot_spend_the_final_response_reserve(self):
        with tokens.token_budget():
            tokens._current.get()["used"] = 3800
            with self.assertRaises(tokens.TokenBudgetExceeded):
                tokens.reserve_call([("human", "question")])
            tokens.reserve_call([("human", "question")], final=True)

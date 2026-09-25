from unittest import TestCase
from unittest.mock import Mock, patch

from app.rag import answer_cache


class AnswerCacheTests(TestCase):
    def setUp(self):
        self.addCleanup(answer_cache._entries.clear)
        answer_cache._entries.clear()
        self.revisions = {"1": {"sha256": "first"}}
        self.result = {"answer": "Grounded answer", "status": "answered", "citations": [{"id": "W1"}]}
        self.generate = Mock(return_value=self.result)
        for name, args in (
            ("current_revisions", {"side_effect": lambda: self.revisions}),
            ("loaded_revisions", {"side_effect": lambda: self.revisions}),
            ("unit_vector", {"return_value": (1.0,)}),
            ("equivalent", {"return_value": True}),
        ):
            patcher = patch.object(answer_cache, name, **args)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def ask(self, question, *, history=None, allow_web=True):
        return answer_cache.get_answer(
            question, history=history or [], filters=None, allow_web=allow_web, generate=self.generate
        )

    def test_repeat_and_rephrasing_skip_generation(self):
        q = "Which delayed baggage purchases are covered?"
        self.ask(q)
        history = [{"question": q, "answer": self.result["answer"]}]
        self.assertIn("exact question", self.ask(q, history=history)["trace"][0])
        self.assertIn("equivalent question", self.ask("What can I buy if my baggage is late?")["trace"][0])
        self.generate.assert_called_once()
        self.equivalent.assert_called_once()

    def test_rejects_similar_but_different_questions_and_changed_revisions(self):
        q = "Which delayed baggage purchases are covered?"
        self.ask(q)
        self.equivalent.return_value = False
        self.ask("Which lost baggage purchases are covered?")
        self.revisions.clear()
        self.ask(q)
        self.assertEqual(self.generate.call_count, 3)

import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pydantic import ValidationError

from app.api.chat import ChatRequest
from app.rag import workflow
from app.rag.state import RouteDecision
from app.core import token_budget


class ConversationTests(unittest.TestCase):
    def setUp(self):
        counter = patch.object(token_budget, "token_count", side_effect=lambda text: len(text) // 4)
        counter.start()
        self.addCleanup(counter.stop)
        workflow_counter = patch.object(workflow, "token_count", side_effect=lambda text: len(text) // 4)
        workflow_counter.start()
        self.addCleanup(workflow_counter.stop)

    def test_direct_answer_receives_name_and_original_question(self):
        state = {"question": "What name did the user share?", "original_question": "what is my name",
                 "history": [{"question": "my name is nishant", "answer": "Nice to meet you, Nishant."}],
                 "needs_details": False, "route": "direct", "trace": []}
        with patch.object(workflow, "get_llm_client") as client, \
             patch.object(workflow, "remaining_timeout", return_value=30):
            client.return_value.invoke.return_value = SimpleNamespace(content="Your name is Nishant.")
            result = workflow.general_answer(state)
        sent = json.loads(client.return_value.invoke.call_args.args[0][-1][1])
        self.assertEqual(sent["recent_chat"], state["history"])
        self.assertEqual(sent["current_question"], "what is my name")
        self.assertEqual(result["answer"], "Your name is Nishant.")
        self.assertEqual(result["status"], "answered")

    def test_grounded_answer_receives_history_without_using_it_as_evidence(self):
        from langchain_core.documents import Document

        history = [{"question": "Explain waiting periods", "answer": "Let's look at the policy."}]
        state = {"question": "Explain the waiting-period exceptions", "original_question": "Any exceptions?",
                 "history": history, "trace": []}
        doc = Document(page_content="Accidents are exempt.", metadata={"evidence_id": "K1"})
        answer = SimpleNamespace(answer="Accidents are exempt. [K1]", citation_ids=["K1"])
        with patch.object(workflow, "invoke_structured", return_value=answer) as invoke, \
             patch.object(workflow, "bounded_evidence", side_effect=lambda docs: docs):
            result = workflow.generate_answer(state, [doc])
        prompt = invoke.call_args.args[1][-1][1]
        self.assertIn('"current_question": "Any exceptions?"', prompt)
        self.assertIn('"recent_chat":', prompt)
        self.assertEqual(result["citations"][0]["excerpt"], "Accidents are exempt.")

    def test_history_is_bounded(self):
        turn = {"question": "Waiting period?", "answer": "It depends on the policy."}
        with self.assertRaises(ValidationError):
            ChatRequest(question="Tell me more", history=[turn] * 5)
        with self.assertRaises(ValidationError):
            ChatRequest(question="Tell me more", history=[{**turn, "answer": "x" * 4001}])

    def test_router_resolves_context_in_one_call(self):
        history = [{"question": "What is a waiting period?", "answer": "A period before coverage applies."}]
        resolved = "Give general examples of health conditions with waiting periods longer than a month."
        decision = RouteDecision(route="kb", standalone_question=resolved, web_query=resolved,
                                 needs_details=False, needs_decomposition=False)
        with patch.object(workflow, "invoke_structured", return_value=decision) as invoke:
            result = workflow.route_question({"question": "Tell me in general", "history": history, "trace": []})
        invoke.assert_called_once()
        sent = json.loads(invoke.call_args.args[1][-1][1])
        self.assertEqual(sent["recent_chat"], history)
        self.assertEqual(result["question"], resolved)
        self.assertEqual(result["current_query"], resolved)
        self.assertEqual(result["route"], "kb")

    def test_new_request_does_not_reuse_previous_history(self):
        states = []

        class Graph:
            def stream(self, state, **kwargs):
                states.append(state.copy())
                return iter([])

        turn = {"question": "Waiting period?", "answer": "It depends on the policy."}
        with patch.object(workflow, "get_settings", return_value=SimpleNamespace(web_search_enabled=True, max_question_tokens=1024)), patch.object(workflow, "build_graph", return_value=Graph()):
            workflow.ask("Tell me more", history=[turn])
            workflow.ask("What is motor insurance?")
        self.assertEqual(states[0]["history"], [turn])
        self.assertEqual(states[1]["history"], [])
        self.assertEqual(states[0]["original_question"], "Tell me more")
        self.assertEqual(states[1]["kb_pool"], [])

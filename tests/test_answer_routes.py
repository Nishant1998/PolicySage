import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api.chat import chat_access
from app.main import app
from app.rag import workflow
from app.rag.state import EvidenceGrade, RouteDecision


class AnswerRouteTests(unittest.TestCase):
    def test_first_web_search_is_attempted_with_low_research_budget(self):
        state = {"needs_details": False, "kb_grade": "weak", "allow_web": True, "retry_count": 0}
        with patch.object(workflow, "research_budget_available", return_value=False):
            self.assertEqual(workflow.after_kb(state)[0], "search_web")
            step, reason = workflow.after_kb({**state, "retry_count": 1})
        self.assertEqual(step, "general_answer")
        self.assertIn("token budget", reason)

    def test_disabled_web_search_reports_reason(self):
        step, reason = workflow.after_kb({
            "needs_details": False, "kb_grade": "weak", "allow_web": False,
            "web_disabled_reason": "disabled in server settings",
        })
        self.assertEqual(step, "general_answer")
        self.assertEqual(reason, "Web search skipped: disabled in server settings")

    def test_insurance_questions_through_chat_api(self):
        cases = [
            ("How do cashless and reimbursement claims differ?", "kb"),
            ("What is a waiting period in health insurance?", "kb"),
            ("What does room rent capping mean?", "web"),
            ("What is a no-claim bonus in Indian motor insurance?", "web"),
            ("How does third-party motor cover differ from comprehensive cover?", "kb"),
        ]
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[chat_access] = lambda: None
        self.addCleanup(app.dependency_overrides.update, previous)
        self.addCleanup(app.dependency_overrides.pop, chat_access, None)
        self.addCleanup(workflow.build_graph.cache_clear)
        for question, expected in cases:
            with self.subTest(question=question), ExitStack() as stack:
                evidence_id = "K1" if expected == "kb" else "W1"
                chunk = Document(page_content="Fixture passage for " + question,
                                 metadata={"evidence_id": "K1", "page_start": 2})

                def model(schema, messages, **kwargs):
                    if schema is RouteDecision:
                        return RouteDecision(route="kb", standalone_question=question,
                                             web_query=question, needs_details=False,
                                             needs_decomposition=False)
                    if schema is EvidenceGrade:
                        return EvidenceGrade(grade="good", supporting_evidence_ids=[evidence_id],
                                             missing_aspects=[], needs_details=False)
                    return schema(answer=f"Fixture answer [{evidence_id}]", citation_ids=[evidence_id])

                settings = workflow.get_settings().model_copy(update={"web_search_enabled": True})
                mocks = {
                    "app.rag.workflow.get_settings": {"return_value": settings},
                    "app.api.chat.write_audit": {},
                    "app.api.chat.start_request_trace": {},
                    "app.core.token_budget.token_count": {"return_value": 20},
                    "app.rag.workflow.token_count": {"return_value": 20},
                    "app.rag.workflow.call_fits": {"return_value": True},
                    "app.rag.workflow.research_budget_available": {"return_value": True},
                    "app.rag.workflow.invoke_structured": {"side_effect": model},
                    "app.rag.workflow.retrieve_kb": {"new": lambda state: {"kb_docs": [chunk] if expected == "kb" else []}},
                }
                for name, kwargs in mocks.items():
                    stack.enter_context(patch(name, **kwargs))
                search = stack.enter_context(patch.object(
                    workflow, "search_official_web", return_value={"results": [{
                        "url": "https://irdai.gov.in/fixture", "content": "Fixture official source."
                    }]}
                ))
                workflow.build_graph.cache_clear()
                response = TestClient(app).post("/api/chat", json={"question": question, "allow_web": True})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result["status"], "answered", result)
                self.assertEqual(result["source_used"], expected)
                self.assertEqual(result["citations"][0]["id"], evidence_id)
                self.assertIn("Router: kb", result["trace"])
                if expected == "web":
                    self.assertIn("Web search selected: policy evidence is insufficient", result["trace"])
                    self.assertIn("Web research complete: supporting evidence found", result["trace"])
                    search.assert_called_once_with(question, workflow.OFFICIAL_DOMAINS)
                else:
                    self.assertIn("Web search skipped: policy evidence is sufficient", result["trace"])
                    search.assert_not_called()

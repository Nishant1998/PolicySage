import json
import logging
import re
from hashlib import sha256
from time import monotonic
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import unquote, urlparse

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.budget import remaining_timeout
from app.core.observability import (
    evidence_refs, event, observed_node, record_usage, span, trace_content,
    trace_details, traced_operation,
)
from app.core.token_budget import (TokenBudgetExceeded, token_limited, trim_history,
                                   reserve_call, settle_call, research_budget_available, token_count, call_fits)
from app.rag.state import AgentState, ChatTurn, EvidenceGrade, GroundedAnswer, PolicyFilters, QueryDecomposition, RouteDecision
from app.rag.retrieval import fuse_candidates, rerank_documents, search_kb
from app.rag.web_search import search_official_web

logger = logging.getLogger(__name__)
OFFICIAL_DOMAINS = (
    "irdai.gov.in",
    "financialservices.gov.in",
    "gstcouncil.gov.in",
    "pmfby.gov.in",
    "cioins.co.in",
    "starhealth.in",
    "hdfcergo.com",
    "hdfclife.com",
    "sbigeneral.in",
    "sbilife.co.in",
    "licindia.in",
    "axismaxlife.com",
    "bajajgeneralinsurance.com",
    "newindia.co.in",
    "tataaig.com",
    "tataaia.com",
)
from app.rag.prompts import (
    SYSTEM_PROMPT,
    ROUTER_PROMPT,
    DECOMPOSITION_PROMPT,
    GRADING_PROMPT,
    WEB_GRADING_PROMPT,
    REWRITE_PROMPT,
    ANSWER_PROMPT,
    WEB_ANSWER_PROMPT,
    GENERAL_PROMPTS,
)


@lru_cache(maxsize=1)
def get_llm_client():
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.request_timeout,
        max_retries=0,
        max_tokens=settings.max_answer_tokens,
    )


def add_trace(state: AgentState, message: str):
    return [*state["trace"], message]


@traced_operation("openai_generate")
def invoke_text(messages, operation, *, final=False):
    reservation = reserve_call(messages, final=final)
    trace_details(provider="openai", model=get_settings().openai_model, prompt_name=operation,
                  prompt_version=sha256(messages[0][1].encode()).hexdigest()[:12],
                  prompt=trace_content(messages), reserved_tokens=reservation,
                  max_output_tokens=get_settings().max_answer_tokens)
    response = get_llm_client().invoke(messages, timeout=remaining_timeout())
    settle_call(reservation, response)
    record_usage(response, operation)
    trace_details(response=trace_content(response.content))
    return response.content


def structured_messages(schema, messages):
    # Required schema fields stop incomplete JSON becoming a default decision.
    role, instruction = messages[0]
    return [(role, instruction + "\nReturn only JSON matching this schema:\n" +
                 json.dumps(schema.model_json_schema())), *messages[1:]]


@traced_operation("openai_structured")
def invoke_structured(schema, messages, *, client=None):
    messages = structured_messages(schema, messages)
    reservation = reserve_call(messages, schema=schema, final=schema is GroundedAnswer)
    trace_details(provider="openai", model=get_settings().openai_model, prompt_name=schema.__name__,
                  prompt_version=sha256(messages[0][1].encode()).hexdigest()[:12],
                  prompt=trace_content(messages), reserved_tokens=reservation,
                  max_output_tokens=get_settings().max_answer_tokens, response_format="json_schema")
    response = (client or get_llm_client()).with_structured_output(
        schema, method="json_schema", include_raw=True
    ).invoke(messages, timeout=remaining_timeout())
    settle_call(reservation, response.get("raw"))
    record_usage(response.get("raw"), schema.__name__)
    if response["parsing_error"] is not None or response["parsed"] is None:
        raise ValueError(f"Invalid structured output: {schema.__name__}")
    parsed = schema.model_validate(response["parsed"])
    trace_details(**{
        key: value if key in {"route", "needs_details", "needs_decomposition", "grade"} else
        [item for item in value if re.fullmatch(r"[KW][0-9]{1,6}", item)]
        if key in {"supporting_evidence_ids", "citation_ids"} else trace_content(value)
        for key, value in parsed.model_dump().items()
    })
    return parsed


def route_question(state: AgentState):
    decision = invoke_structured(RouteDecision,
        [
            (
                "system",
                SYSTEM_PROMPT + "\n" + ROUTER_PROMPT + "\nSet needs_decomposition true only for multiple distinct facts or sections that benefit from separate searches; false for a single fact or direct response.",
            ),
            ("human", json.dumps({"recent_chat": state.get("history", []),
                                  "current_question": state["question"]}, ensure_ascii=False)),
        ]
    )
    route = "direct" if decision.needs_details else decision.route
    trace_details(decision_reason="requires clarification" if decision.needs_details else
                  "search policy evidence" if route == "kb" else "direct response")
    if token_count(decision.standalone_question) > get_settings().max_question_tokens:
        raise TokenBudgetExceeded()
    return {
        "question": decision.standalone_question.strip(),
        "current_query": decision.standalone_question.strip(),
        "route": route,
        "decompose": route == "kb" and decision.needs_decomposition,
        "web_query": decision.web_query,
        "needs_details": decision.needs_details,
        "trace": add_trace(state, f"Router: {route}"),
    }


def route_after_router(state: AgentState):
    return "retrieve_kb" if state["route"] == "kb" else "general_answer"


def prepare_search_queries(question: str, *, client=None):
    messages = [
        ("system", DECOMPOSITION_PROMPT),
        ("human", question),
    ]
    result = (invoke_structured(QueryDecomposition, messages, client=client) if client is not None
              else invoke_structured(QueryDecomposition, messages))
    queries = list(dict.fromkeys(query.strip() for query in result.queries if query.strip()))
    if not queries:
        raise ValueError("Decomposition returned no search queries")
    return queries


def decompose_question(state: AgentState):
    if not state["decompose"] or not research_budget_available():
        return {"subqueries": [], "trace": add_trace(state, "Decomposition skipped")}
    queries = prepare_search_queries(state["question"])
    return {"subqueries": queries[:3], "trace": add_trace(state, f"Decomposed into {len(queries[:3])} queries")}


def retrieve_kb(state: AgentState):
    queries = state["subqueries"] if state["retry_count"] == 0 and state["subqueries"] else [state["current_query"]]
    rankings, hits = [], []
    limitations = list(state["limitations"])
    for query in queries:
        try:
            docs = search_kb(query, state["filters"], rerank=False)
            hits.append({"query": query, "status": "completed"})
        except Exception as exc:
            logger.warning("KB search failed (%s)", type(exc).__name__)
            docs = []
            hits.append({"query": query, "status": "error"})
            limitations.append("A knowledge base search could not be completed.")
        rankings.append(docs)
    limit = get_settings().top_k
    documents = fuse_candidates([state["kb_pool"], *rankings], limit=20)
    # Re-select across retries and subqueries so stale results cannot fill the pool.
    documents = rerank_documents(state["question"], documents, limit)
    documents = [Document(page_content=doc.page_content,
                          id=doc.id,
                          metadata={**doc.metadata, "evidence_id": f"K{number}"})
                 for number, doc in enumerate(documents, 1)]
    return {"kb_docs": documents, "kb_pool": documents, "subquery_hits": hits,
            "web_results": [], "kb_grade": "weak", "web_grade": "weak", "web_unavailable": False,
            "limitations": limitations, "trace": add_trace(state, f"KB retrieval: {len(documents)} chunks")}


def format_evidence(documents: list[Document]):
    keys = ("document_title", "title", "url", "insurer", "product_name", "category", "document_type",
            "uin", "effective_from", "page_start", "page_end")
    return "\n\n".join(
        f"[{doc.metadata['evidence_id']}] {json.dumps({key: doc.metadata[key] for key in keys if doc.metadata.get(key)}, ensure_ascii=False)}\n{doc.page_content}"
        for doc in documents
    )


def bounded_evidence(documents):
    remaining = get_settings().max_evidence_tokens
    selected = []
    for doc in documents:
        count = token_count(format_evidence([doc]))
        if count <= remaining:
            selected.append(doc)
            remaining -= count
    return selected


def fit_evidence(documents, make_messages, schema, *, final=False):
    selected = bounded_evidence(documents)
    before = len(selected)
    while selected and not call_fits(structured_messages(schema, make_messages(selected)), schema=schema, final=final):
        selected.pop()
    if len(selected) < before:
        event("evidence_trimmed_to_prompt", retained_chunks=len(selected), removed_chunks=before - len(selected))
    return selected


def grade_evidence(state: AgentState, documents: list[Document]):
    def messages(selected):
        return [
            (
                "system",
                SYSTEM_PROMPT + "\n" + GRADING_PROMPT + (
                    "\n" + WEB_GRADING_PROMPT
                    if any(doc.metadata["evidence_id"].startswith("W") for doc in selected)
                    else ""
                ),
            ),
            ("human", f"Question: {state['question']}\nEvidence:\n{format_evidence(selected)}"),
        ]
    documents = fit_evidence(documents, messages, EvidenceGrade)
    if not documents:
        return EvidenceGrade(grade="weak", supporting_evidence_ids=[], missing_aspects=["Relevant evidence"], needs_details=False)
    grade = invoke_structured(EvidenceGrade, messages(documents))
    known = {doc.metadata["evidence_id"] for doc in documents}
    trace_details(assessed_evidence=evidence_refs(documents),
                  supporting_evidence_ids=[item for item in grade.supporting_evidence_ids if item in known],
                  unknown_evidence_count=len(set(grade.supporting_evidence_ids) - known),
                  missing_aspect_count=len(grade.missing_aspects))
    if not set(grade.supporting_evidence_ids) <= known:
        raise ValueError("Grader returned unknown evidence IDs")
    if grade.grade == "good" and not grade.supporting_evidence_ids:
        raise ValueError("Good grade requires supporting evidence IDs")
    if grade.needs_details or grade.missing_aspects:
        grade.grade = "weak"
    trace_details(evidence_sufficient=grade.grade == "good")
    return grade


def grade_kb(state: AgentState):
    grade = grade_evidence(state, state["kb_docs"])
    # Pass only accepted chunks to answer generation or web research.
    docs = [
        doc
        for doc in state["kb_docs"]
        if doc.metadata["evidence_id"] in grade.supporting_evidence_ids
    ]
    return {
        "kb_docs": docs,
        "needs_details": grade.needs_details,
        "kb_grade": grade.grade,
        "missing_aspects": grade.missing_aspects[:3],
        "trace": add_trace(state, f"KB grade: {grade.grade}"),
    }


def after_kb(state: AgentState):
    if state["needs_details"]:
        return "general_answer"
    if state["kb_grade"] == "good":
        return "generate_from_kb"
    return "search_web" if state["allow_web"] and research_budget_available() else "general_answer"


def search_web(state: AgentState):
    trace_details(fallback_reason="knowledge-base evidence was insufficient")
    try:
        if not state["web_query"].strip():
            raise ValueError("No public search query")
        result = search_official_web(state["web_query"], OFFICIAL_DOMAINS)
        documents, seen = [], set()
        for item in result.get("results", []):
            url, content = item.get("url", ""), item.get("content", "")
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            official = any(
                host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS
            )
            if (
                parsed.scheme != "https"
                or parsed.username
                or not official
                or not content
                or url in seen
            ):
                continue
            seen.add(url)
            documents.append(
                Document(
                    page_content=content[:6000],
                    metadata={
                        "evidence_id": f"W{len(documents) + 1}",
                        "title": item.get("title") or url,
                        "url": url,
                        "published_date": item.get("published_date", ""),
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )
        return {
            "web_results": documents,
            "trace": add_trace(state, f"Web search: {len(documents)} sources"),
        }
    except Exception as exc:
        logger.warning("Web search failed (%s)", type(exc).__name__)
        return {
            "web_results": [],
            "web_unavailable": True,
            "limitations": [*state["limitations"], "Official web search is unavailable."],
            "trace": add_trace(state, "Web search unavailable"),
        }


def grade_web(state: AgentState):
    # Relevant KB passages may complete an answer that web evidence alone cannot.
    if not state["web_results"]:
        return {
            "web_grade": "weak",
            "trace": add_trace(state, "Web and KB grade: weak"),
        }
    grade = grade_evidence(state, [*state["kb_docs"], *state["web_results"]])
    return {
        "kb_docs": [
            doc
            for doc in state["kb_docs"]
            if doc.metadata["evidence_id"] in grade.supporting_evidence_ids
        ],
        "web_results": [
            doc
            for doc in state["web_results"]
            if doc.metadata["evidence_id"] in grade.supporting_evidence_ids
        ],
        "web_grade": grade.grade,
        "needs_details": grade.needs_details,
        "missing_aspects": grade.missing_aspects[:3],
        "trace": add_trace(state, f"Web and KB grade: {grade.grade}"),
    }


def after_web(state: AgentState):
    if state["needs_details"]:
        return "general_answer"
    if state["web_grade"] == "good":
        return "generate_from_web"
    if not state["web_unavailable"] and state["retry_count"] < get_settings().max_retries and research_budget_available():
        return "rewrite_query"
    return "general_answer"


def rewrite_query(state: AgentState):
    trace_details(retry_reason="combined evidence was insufficient", next_attempt=state["retry_count"] + 1)
    rewritten = invoke_text([
        ("system", REWRITE_PROMPT),
        ("human", f"Public query: {state['web_query']}\nMissing aspects: {json.dumps(state['missing_aspects'], ensure_ascii=False)}"),
    ], "rewrite_query")
    if not isinstance(rewritten, str) or not rewritten.strip():
        raise ValueError("Empty rewritten query")
    return {
        "current_query": rewritten.strip(),
        "web_query": rewritten.strip(),
        "retry_count": state["retry_count"] + 1,
        "trace": add_trace(state, "Query rewritten"),
    }


def conversation_context(state: AgentState):
    return json.dumps({
        "recent_chat": state.get("history", []),
        "current_question": state.get("original_question", state["question"]),
        "resolved_question": state["question"],
    }, ensure_ascii=False)


def citation_url(evidence_id, metadata):
    url = metadata.get("source_url") or metadata.get("url", "")
    revision_id = metadata.get("document_revision")
    if not evidence_id.startswith("K") or not revision_id:
        return url
    settings = get_settings()
    if not settings.kb_managed:
        return url
    if settings.public_pdf_downloads_enabled:
        return f"/api/kb/revisions/{revision_id}.pdf"

    if not isinstance(url, str):
        return ""
    try:
        source = urlparse(url)
    except ValueError:
        return ""
    if (source.scheme not in ("https", "http") or not source.hostname
            or source.username is not None or source.password is not None):
        return ""
    if unquote(source.path).startswith(("/api/kb/revisions/", "/api/admin/kb/")):
        return ""
    return url


def generate_answer(state: AgentState, documents: list[Document]):
    original_count = len(documents)
    def messages(selected):
        return [
            (
                "system",
                SYSTEM_PROMPT + "\n" + ANSWER_PROMPT + (
                    "\n" + WEB_ANSWER_PROMPT
                    if any(doc.metadata["evidence_id"].startswith("W") for doc in selected)
                    else ""
                ),
            ),
            ("human", f"Conversation:\n{conversation_context(state)}\nEvidence:\n{format_evidence(selected)}"),
        ]
    documents = fit_evidence(documents, messages, GroundedAnswer, final=True)
    if not documents:
        raise TokenBudgetExceeded()
    result = invoke_structured(GroundedAnswer, messages(documents))
    trace_details(generation_evidence=evidence_refs(documents), evidence_count=len(documents),
                  omitted_evidence_count=original_count - len(documents))
    available = {doc.metadata["evidence_id"]: doc.metadata for doc in documents}
    cited = set(result.citation_ids)
    # Accept grouped references and add missing markers from validated source IDs.
    answer = re.sub(
        r"\[([KW]\d+(?:\s*[,;]\s*[KW]\d+)+)\]",
        lambda match: " ".join(f"[{item}]" for item in re.findall(r"[KW]\d+", match[1])),
        result.answer,
    )
    inline_ids = set(re.findall(r"\[([KW]\d+)\]", answer))
    with span("verify_citations"):
        trace_details(
            returned_ids=sorted(item for item in cited if re.fullmatch(r"[KW][0-9]{1,6}", item)),
            unsupported_count=len(cited - available.keys()),
            unexpected_inline_ids=sorted(inline_ids - cited),
            missing_inline_count=len(cited - inline_ids),
            references=evidence_refs([doc for doc in documents if doc.metadata["evidence_id"] in cited]),
            accessibility="not_checked",
            semantic_support="not_evaluated",
        )
        if not cited or not cited <= available.keys() or not inline_ids <= cited:
            raise ValueError("Invalid answer citations")
    missing_ids = [item for item in dict.fromkeys(result.citation_ids) if item not in inline_ids]
    if missing_ids:
        answer += "\n\nSources: " + " ".join(f"[{item}]" for item in missing_ids)
    citations = []
    for evidence_id in dict.fromkeys(result.citation_ids):
        metadata = available[evidence_id]
        citations.append(
            {
                "id": evidence_id,
                "title": metadata.get("document_title")
                or metadata.get("title")
                or metadata.get("source", "Policy document"),
                "url": citation_url(evidence_id, metadata),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "excerpt": next(doc.page_content for doc in documents
                                if doc.metadata["evidence_id"] == evidence_id),
                "source_id": metadata.get("document_id") or metadata.get("source", ""),
                "type": "kb" if evidence_id.startswith("K") else "web",
            }
        )
    sources = {citation["type"] for citation in citations}
    source_used = "kb_and_web" if len(sources) == 2 else next(iter(sources))
    return {
        "answer": answer,
        "status": "answered",
        "source_used": source_used,
        "citations": citations,
        "limitations": [*state.get("limitations", []), *(
            ["Some retrieved passages could not be included; the answer may be partial."]
            if len(documents) < original_count else [])],
        "trace": add_trace(state, f"Answer: {source_used}"),
    }


def generate_from_kb(state: AgentState):
    return generate_answer(state, state["kb_docs"])


def generate_from_web(state: AgentState):
    return generate_answer(state, [*state["kb_docs"], *state["web_results"]])


def general_answer(state: AgentState):
    status = "insufficient_evidence"
    if state["needs_details"]:
        status = "clarification_required"
    elif state["route"] == "direct":
        status = "answered"
    question = conversation_context(state)
    if status == "insufficient_evidence":
        question += (f"\nMissing aspects: {json.dumps(state['missing_aspects'], ensure_ascii=False)}"
                     f"\nKnown limitations: {json.dumps(state['limitations'], ensure_ascii=False)}")
    answer = invoke_text([
        ("system", SYSTEM_PROMPT + "\n" + GENERAL_PROMPTS[status] + "\nReturn only a brief user-facing response. Do not invent citations or insurance facts."),
        ("human", question),
    ], "general_answer", final=True)
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Empty general answer")
    return {
        "answer": answer,
        "status": status,
        "source_used": "direct" if status == "answered" else "none",
        "citations": [],
        "trace": add_trace(state, f"General answer: {status}"),
    }


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(AgentState)
    for name, function in {
        "route_question": route_question, "decompose_question": decompose_question,
        "retrieve_kb": retrieve_kb, "grade_kb": grade_kb,
        "search_web": search_web, "grade_web": grade_web,
        "rewrite_query": rewrite_query, "generate_from_kb": generate_from_kb,
        "generate_from_web": generate_from_web, "general_answer": general_answer,
    }.items():
        graph.add_node(name, observed_node(function))
    graph.add_edge(START, "route_question")
    graph.add_conditional_edges("route_question", route_after_router,
                                {"retrieve_kb": "decompose_question", "general_answer": "general_answer"})
    graph.add_edge("decompose_question", "retrieve_kb")
    graph.add_edge("retrieve_kb", "grade_kb")
    graph.add_conditional_edges(
        "grade_kb", after_kb, ["generate_from_kb", "search_web", "general_answer"]
    )
    graph.add_edge("search_web", "grade_web")
    graph.add_conditional_edges(
        "grade_web", after_web, ["generate_from_web", "rewrite_query", "general_answer"]
    )
    graph.add_edge("rewrite_query", "retrieve_kb")
    graph.add_edge("generate_from_kb", END)
    graph.add_edge("generate_from_web", END)
    graph.add_edge("general_answer", END)
    return graph.compile()


@token_limited
def ask(question: str, *, filters: dict | None = None, allow_web: bool = True,
        history: list[dict] | None = None, on_step=None):
    initial: AgentState = {
        "original_question": question,
        "history": [],
        "question": question,
        "current_query": question,
        "decompose": False,
        "subqueries": [],
        "subquery_hits": [],
        "web_query": "",
        "route": "kb",
        "filters": {},
        "kb_docs": [],
        "kb_pool": [],
        "web_results": [],
        "kb_grade": "weak",
        "web_grade": "weak",
        "missing_aspects": [],
        "needs_details": False,
        "retry_count": 0,
        "allow_web": allow_web and getattr(get_settings(), "web_search_enabled", True),
        "web_unavailable": False,
        "answer": "",
        "status": "insufficient_evidence",
        "source_used": "none",
        "citations": [],
        "limitations": [],
        "trace": [],
    }
    stage = "input validation"
    try:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Empty question")
        if token_count(question) > get_settings().max_question_tokens:
            raise TokenBudgetExceeded()
        if history is not None and (not isinstance(history, list) or len(history) > 4):
            raise ValueError("History must contain at most four turns")
        validated_history = [ChatTurn.model_validate(turn).model_dump() for turn in (history or [])]
        initial["history"] = trim_history(validated_history)
        if len(initial["history"]) < len(validated_history):
            event("chat_history_trimmed", retained_turns=len(initial["history"]))
        initial["filters"] = PolicyFilters.model_validate(
            filters if filters is not None else {}
        ).model_dump(exclude_none=True)
        # Keep completed steps available when a later node fails.
        stage = "graph startup"
        step_started = monotonic()
        for update in build_graph().stream(
            initial, config={"recursion_limit": 40}, stream_mode="updates"
        ):
            for node, values in update.items():
                remaining_timeout()
                initial.update(values)
                stage = node
                logger.info("RAG step completed: %s (%.2fs)", node, monotonic() - step_started)
                step_started = monotonic()
                if on_step is not None:
                    on_step(node, initial)
        return initial
    except TokenBudgetExceeded:
        return {**initial, "answer": "I could not complete the research within this request's limit. Please ask a narrower question.",
                "status": "insufficient_evidence", "source_used": "none", "citations": [],
                "limitations": ["The request's token allowance was reached."],
                "trace": add_trace(initial, "Token budget reached")}
    except Exception as exc:
        event("workflow_failed", stage=stage, error_type=type(exc).__name__)
        logger.warning("RAG workflow failed after %s (%s)", stage, type(exc).__name__)
        return {
            **initial,
            "answer": "I could not complete the request. Please try again.",
            "status": "error",
            "source_used": "none",
            "citations": [],
            "trace": add_trace(initial, "Workflow error"),
        }

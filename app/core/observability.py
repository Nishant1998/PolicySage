import logging
import re
from random import random
from hashlib import sha256
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
from time import monotonic
from uuid import uuid4

from langsmith import Client, agent_address, tracing_context
from langsmith.run_trees import RunTree

from app.core.config import get_settings

logger = logging.getLogger(__name__)
current_request = ContextVar("observation", default=None)
current_span = ContextVar("observation_span", default=None)
trace_fields = ContextVar("trace_fields", default=None)
APP_VERSION = "0.1.0"


def trace_details(**fields):
    active = trace_fields.get()
    if active is not None:
        active.update(fields)


def exporting_trace():
    return trace_fields.get() is not None


def trace_content(value):
    request = current_request.get()
    if request is None or request.get("_path") != "/api/chat":
        return None
    settings = get_settings()
    if not getattr(settings, "langsmith_debug_content", False):
        return None
    from app.core.privacy import SEARCH_REDACTIONS

    if isinstance(value, str):
        for name in ("openai_api_key", "qdrant_api_key", "tavily_api_key", "brave_api_key",
                     "langsmith_api_key", "admin_api_key", "kb_admin_password", "kb_database_url",
                     "kb_s3_access_key_id", "kb_s3_secret_access_key"):
            secret = getattr(settings, name, None)
            if secret and (secret_value := secret.get_secret_value()):
                value = value.replace(secret_value, "[redacted]")
        for _, pattern in SEARCH_REDACTIONS:
            value = re.sub(pattern, "[redacted]", value, flags=re.IGNORECASE)
        value = re.sub(r"(?i)\b(?:bearer\s+|(?:password|secret|token|api[_ -]?key)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]+",
                       "[redacted]", value)
        value = re.sub(r"https?://[^\s\"<>]+", "[url redacted]", value)
        return value[:12000]
    if isinstance(value, (list, tuple)):
        return [trace_content(item) for item in value]
    return None


def evidence_refs(documents):
    keys = ("document_id", "document_revision", "chunk_id", "chunk_index",
            "page_start", "page_end", "evidence_id")
    return [
        {"rank": rank, **{key: doc.metadata[key] for key in keys if key in doc.metadata},
         "record_id": doc.id, "title": trace_content(doc.metadata.get("document_title") or doc.metadata.get("title"))}
        for rank, doc in enumerate(documents, 1)
    ]


def event(name, **fields):
    request = current_request.get()
    if name == "stage_finished" and fields.get("error_type"):
        level = logging.WARNING
    elif name in {"stage_finished", "request_started", "llm_tokens_reserved", "llm_usage", "token_budget_finished"}:
        level = logging.DEBUG
    elif name == "request_finished" and fields.get("error_type"):
        level = logging.ERROR
    elif name == "request_finished" and (fields.get("http_status") or 0) >= 400:
        level = logging.WARNING
    elif name == "request_finished" and (fields.get("routine") and (fields.get("http_status") or 500) < 400):
        level = logging.DEBUG
    else:
        level = logging.INFO
    if logger.isEnabledFor(level):
        logger.log(level, name, extra={"fields": {"request_id": request["id"] if request else None, **fields}})


@lru_cache(maxsize=1)
def trace_client():
    settings = get_settings()
    return Client(api_key=settings.langsmith_api_key.get_secret_value(),
                  api_url=settings.langsmith_endpoint, timeout_ms=1000)


def start_request_trace(*, question=None, **inputs):
    request = current_request.get()
    if request is None or request.get("_trace_attempted"):
        return
    request["_trace_attempted"] = True
    settings = get_settings()
    if not settings.langsmith_enabled:
        return
    rate = getattr(settings, "langsmith_trace_sample_rate", 1.0)
    if rate < 1 and random() >= rate:
        return
    if not settings.langsmith_api_key.get_secret_value():
        event("tracing_disabled_missing_key")
        return
    try:
        if question is not None:
            inputs["question"] = trace_content(question)
        root = RunTree(id=request["id"], name="policysage_request", run_type="chain",
                       inputs={"path": request["_path"], "method": request["_method"],
                               "request_id": request["id"], "trace_id": request["id"],
                               "environment": settings.langsmith_agent_environment,
                               "app_version": APP_VERSION, **inputs},
                       address=agent_address(settings.langsmith_agent_id, settings.langsmith_agent_environment),
                       client=trace_client())
        root.post()
        request["_root"] = root
        current_span.set(root)
    except Exception:
        event("tracing_unavailable")


def traced_operation(name, *, start_trace=False):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if start_trace:
                start_request_trace()
            with span(name) as fields:
                result = function(*args, **kwargs)
                if isinstance(result, dict):
                    for key in ("status", "source_used"):
                        if isinstance(result.get(key), str):
                            fields[key] = result[key]
                return result
        return wrapped
    return decorate


@contextmanager
def span(name, *, inputs=None, run_type="chain"):
    started = monotonic()
    parent = current_span.get()
    run = None
    if parent is not None:
        try:
            run = parent.create_child(name=name, run_type=run_type, inputs=inputs or {})
            run.post()
        except Exception:
            event("tracing_unavailable")
            run = None
    token = current_span.set(run)
    error = None
    fields = {}
    details = {}
    details_token = trace_fields.set(details if run is not None else None)
    request = current_request.get()
    before = (request["input_tokens"], request["output_tokens"]) if request else (0, 0)
    try:
        yield fields
    except Exception as exc:
        error = type(exc).__name__
        if request is not None:
            request["cost_complete"] = False
        raise
    finally:
        fields.update(duration_ms=round((monotonic() - started) * 1000, 2), error_type=error)
        if request is not None:
            fields.update(input_tokens=request["input_tokens"] - before[0],
                          output_tokens=request["output_tokens"] - before[1])
        event("stage_finished", stage=name, **fields)
        if run is not None:
            try:
                run.end(outputs={**fields, **details}, error=error)
                run.patch()
            except Exception:
                event("tracing_unavailable")
        trace_fields.reset(details_token)
        current_span.reset(token)


@contextmanager
def observe_request(path, method, *, export=True):
    request = {"id": uuid4().hex, "input_tokens": 0, "output_tokens": 0,
               "llm_calls": 0, "usage_missing": 0, "estimated_cost_usd": 0.0,
               "cost_complete": True, "_path": path, "_method": method}
    token = current_request.set(request)
    started = monotonic()
    parent = current_span.set(None)
    if export:
        start_request_trace()
    event("request_started", path=path, method=method)
    try:
        # Only our metadata-only spans are exported; disable automatic prompt capture.
        with tracing_context(enabled=False):
            yield request
    except BaseException as exc:
        request["error_type"] = type(exc).__name__
        request["cost_complete"] = False
        raise
    finally:
        summary = {key: value for key, value in request.items()
                   if not key.startswith("_") and key not in {"id", "cost_complete"}}
        summary["estimated_cost_usd"] = round(request["estimated_cost_usd"], 8) if request["cost_complete"] else None
        summary["total_tokens"] = request["input_tokens"] + request["output_tokens"]
        summary["duration_ms"] = round((monotonic() - started) * 1000, 2)
        log_summary = dict(summary, method=method, routine=request.get("_routine", False))
        if method != "WORKER":
            log_summary.setdefault("http_status", None)
        if not request["llm_calls"]:
            for key in ("llm_calls", "input_tokens", "output_tokens", "total_tokens", "usage_missing", "estimated_cost_usd"):
                log_summary.pop(key, None)
        elif request["usage_missing"]:
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                log_summary[key] = None
        event("request_finished", path=path, **log_summary)
        root = request.get("_root")
        if root is not None:
            try:
                root.end(outputs={**summary, **request.get("_result", {})}, error=request.get("error_type"))
                root.patch()
            except Exception:
                event("tracing_unavailable")
        current_span.reset(parent)
        current_request.reset(token)


def record_usage(response, operation):
    usage = getattr(response, "usage_metadata", None)
    request = current_request.get()
    if not isinstance(usage, dict) or not all(isinstance(usage.get(key), int) for key in ("input_tokens", "output_tokens")):
        if request is not None:
            request["llm_calls"] += 1
            request["usage_missing"] += 1
            request["cost_complete"] = False
        event("llm_usage_missing", operation=operation)
        trace_details(usage_available=False, estimated_cost_usd=None)
        return
    inputs = usage.get("input_tokens", 0)
    outputs = usage.get("output_tokens", 0)
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    settings = get_settings()
    rates = (settings.llm_input_usd_per_million, settings.llm_output_usd_per_million,
             settings.llm_cached_input_usd_per_million)
    cost = None
    if rates[0] is not None and rates[1] is not None and (not cached or rates[2] is not None):
        cost = ((inputs - cached) * rates[0] + outputs * rates[1] + cached * (rates[2] or 0)) / 1_000_000
    if request is not None:
        request["llm_calls"] += 1
        request["input_tokens"] += inputs
        request["output_tokens"] += outputs
        request["cost_complete"] &= cost is not None
        request["estimated_cost_usd"] += cost or 0
    trace_details(usage_available=True, input_tokens=inputs, output_tokens=outputs, total_tokens=inputs + outputs,
                  estimated_cost_usd=cost)
    event("llm_usage", operation=operation, input_tokens=inputs, output_tokens=outputs,
          model=settings.openai_model, cached_input_tokens=cached, estimated_cost_usd=cost)


def observed_node(function):
    @wraps(function)
    def wrapped(state):
        if function.__name__ == "decompose_question" and not state.get("decompose"):
            return function(state)
        with span(function.__name__, inputs={
            "retry_count": state.get("retry_count"),
            "history_used": bool(state.get("history")),
            "question": trace_content(state.get("question")),
            "query": trace_content(state.get("current_query")),
        }) as fields:
            result = function(state)
            for key in ("route", "kb_grade", "web_grade", "retry_count", "status", "source_used", "web_unavailable"):
                if key in result:
                    fields[key] = result[key]
            for key in ("kb_docs", "web_results", "citations"):
                if key in result:
                    fields[key + "_count"] = len(result[key])
            if "kb_docs" in result:
                trace_details(selected_evidence=evidence_refs(result["kb_docs"]))
                fields["chunk_refs"] = [sha256(str((doc.metadata.get("document_id") or doc.metadata.get("source"),
                    doc.metadata.get("document_revision"), doc.metadata.get("chunk_index"),
                    doc.metadata.get("start_index"))).encode()).hexdigest()[:16]
                    for doc in result["kb_docs"]]
            trace_details(
                **{key: trace_content(result[key]) for key in
                   ("question", "current_query", "web_query", "subqueries", "missing_aspects")
                   if key in result},
                **({"web_sources": evidence_refs(result["web_results"])} if "web_results" in result else {}),
            )
            return result
    return wrapped

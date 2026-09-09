import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps

import tiktoken

from app.core.config import get_settings
from app.core.observability import event

_current = ContextVar("token_budget", default=None)
TOKEN_SAFETY_BUFFER = 512


class TokenBudgetExceeded(Exception):
    pass


@lru_cache(maxsize=4)
def tokenizer(model):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def token_count(text):
    return len(tokenizer(get_settings().openai_model).encode(text, disallowed_special=()))


@contextmanager
def token_budget():
    if _current.get() is not None:
        yield
        return
    settings = get_settings()
    budget = {"used": 0, "limit": settings.max_request_tokens,
              "prompt_limit": settings.max_prompt_tokens, "output_limit": settings.max_answer_tokens,
              "final_reserve": settings.max_prompt_tokens + settings.max_answer_tokens}
    if budget["limit"] <= budget["final_reserve"]:
        raise ValueError("MAX_REQUEST_TOKENS must exceed MAX_PROMPT_TOKENS + MAX_ANSWER_TOKENS")
    token = _current.set(budget)
    try:
        yield
    finally:
        event("token_budget_finished", accounted_tokens=budget["used"], limit=budget["limit"])
        _current.reset(token)


def token_limited(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with token_budget():
            return function(*args, **kwargs)
    return wrapped


def trim_history(history):
    history = list(history)
    while history and token_count(json.dumps(history, ensure_ascii=False)) > get_settings().max_history_tokens:
        history.pop(0)
    return history


def input_tokens(messages, schema=None):
    text = json.dumps(messages, ensure_ascii=False)
    if schema is not None:
        text += json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return token_count(text) + TOKEN_SAFETY_BUFFER


def call_fits(messages, *, schema=None, final=False):
    budget = _current.get()
    if budget is None:
        return True
    inputs = input_tokens(messages, schema)
    available = budget["limit"] - budget["used"] - (0 if final else budget["final_reserve"])
    return inputs <= budget["prompt_limit"] and inputs + budget["output_limit"] <= available


def reserve_call(messages, *, schema=None, final=False):
    budget = _current.get()
    if budget is None:
        return None
    inputs = input_tokens(messages, schema)
    reserved = inputs + budget["output_limit"]
    available = budget["limit"] - budget["used"] - (0 if final else budget["final_reserve"])
    if not call_fits(messages, schema=schema, final=final):
        event("token_budget_exceeded", estimated_input_tokens=inputs, remaining_tokens=max(0, available))
        raise TokenBudgetExceeded()
    budget["used"] += reserved
    event("llm_tokens_reserved", estimated_input_tokens=inputs, reserved_output_tokens=budget["output_limit"])
    return reserved


def settle_call(reserved, response):
    budget = _current.get()
    usage = getattr(response, "usage_metadata", None)
    if budget is None or reserved is None:
        return
    # Missing usage or a failed call keeps the full reservation charged locally.
    if isinstance(usage, dict) and all(isinstance(usage.get(key), int) for key in ("input_tokens", "output_tokens")):
        budget["used"] += usage["input_tokens"] + usage["output_tokens"] - reserved


def research_budget_available():
    budget = _current.get()
    return budget is None or budget["limit"] - budget["used"] - budget["final_reserve"] >= budget["output_limit"] + 1024

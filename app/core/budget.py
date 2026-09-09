from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from app.core.config import get_settings

_deadline = ContextVar("request_deadline", default=None)
_external_calls = ContextVar("request_external_calls", default=None)


@contextmanager
def request_budget():
    settings = get_settings()
    token = _deadline.set(monotonic() + settings.chat_timeout)
    calls_token = _external_calls.set({
        "search": settings.max_searches_per_chat,
        "web": settings.max_web_attempts_per_chat,
    })
    try:
        yield
    finally:
        _external_calls.reset(calls_token)
        _deadline.reset(token)


def remaining_timeout():
    seconds = get_settings().request_timeout
    deadline = _deadline.get()
    if deadline is not None:
        seconds = min(seconds, deadline - monotonic())
    if seconds <= 0:
        raise TimeoutError("The request time budget was exhausted")
    return seconds


def reserve_external_call(kind):
    calls = _external_calls.get()
    if calls is not None:
        remaining_timeout()
        if calls[kind] <= 0:
            raise RuntimeError(f"The request {kind} budget was exhausted")
        calls[kind] -= 1

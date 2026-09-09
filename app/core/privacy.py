import re

from app.core.observability import event

# Best-effort patterns, not a guarantee that arbitrary private text is detected.
SEARCH_REDACTIONS = (
    ("email", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ("private_id", r"\b(?:policy|claim|account|member)\s*(?:number|no\.?|id)\s*[:#=-]?\s*(?=[A-Z0-9/-]*\d)[A-Z0-9][A-Z0-9/-]*\b"),
    ("aadhaar", r"(?<!\w)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\w)"),
    ("phone", r"(?<!\w)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\w)"),
    ("api_key", r"\b(?:sk-|lsv2_|tvly-)[A-Z0-9_-]{12,}\b"),
)


def public_search_query(query):
    redactions = {}
    for category, pattern in SEARCH_REDACTIONS:
        query, count = re.subn(pattern, " ", query, flags=re.IGNORECASE)
        if count:
            redactions[category] = count
    query = " ".join(query.split())
    if redactions:
        event("web_query_redacted", categories=redactions)
    if not re.search(r"[A-Za-z\u0900-\u097f]", query):
        raise ValueError("No public search topic remains")
    return query

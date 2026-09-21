import json
import logging
import re
import sys
import traceback
from datetime import datetime, timezone


# Only operational metadata belongs in application logs, not prompts or documents.
SAFE_FIELDS = {
    "request_id", "trace_id", "document_id", "revision_id", "revision_ref", "job_id",
    "duration_ms", "status", "http_status", "method", "path", "stage", "attempt",
    "error_type", "model", "llm_calls", "total_tokens", "input_tokens", "output_tokens",
    "usage_missing", "estimated_cost_usd", "chunk_count", "pages", "kind", "scope",
    "retry_after", "retained_chunks", "removed_chunks", "retained_turns",
}


def _safe(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if not isinstance(value, str):
        return None
    value = re.sub(r"[a-z][a-z0-9+.-]*://\S+", "[url redacted]", value, flags=re.IGNORECASE)
    value = re.sub(r"(?i)(bearer\s+|(?:password|secret|token|api[_-]?key)\s*[:=]\s*)\S+", r"\1[redacted]", value)
    return value.replace("\n", "\\n").replace("\r", "\\r")[:250]


def _details(record):
    from app.core.observability import current_request

    request = current_request.get()
    fields = {key: _safe(value) for key, value in getattr(record, "fields", {}).items()
              if key in SAFE_FIELDS and (value is None or isinstance(value, (str, int, float, bool)))}
    if request and "request_id" not in fields:
        fields["request_id"] = request["id"]
    if record.exc_info:
        fields["error_type"] = record.exc_info[0].__name__
    return fields


def _message(record):
    message = record.getMessage()
    if record.name == "app.core.observability":
        if message == "request_finished":
            fields = getattr(record, "fields", {})
            if fields.get("path") == "kb_worker":
                return "Document processing failed" if fields.get("error_type") else "Document processing completed"
            return "Request failed" if fields.get("error_type") or (fields.get("http_status") or 0) >= 400 else "Request completed"
        if message == "stage_finished" and getattr(record, "fields", {}).get("error_type"):
            return "Processing stage failed"
        message = message.replace("_", " ").capitalize()
    return _safe(message)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname, "logger": record.name, "message": _message(record),
                **_details(record)}
        return json.dumps(data, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self, *, color=False):
        super().__init__()
        self.color = color

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).strftime("%H:%M:%S")
        level = f"{record.levelname:<8}"
        colors = {logging.DEBUG: "\033[90m", logging.WARNING: "\033[33m",
                  logging.ERROR: "\033[31m", logging.CRITICAL: "\033[31m"}
        if self.color and record.levelno in colors:
            level = f"{colors[record.levelno]}{level}\033[0m"
        fields = _details(record)
        metadata = " ".join(f"{key}={value if value is not None else 'unavailable'}" for key, value in fields.items())
        line = f"{timestamp} | {level} | {record.name} | {_message(record)}"
        if metadata:
            line += f" | {metadata}"
        if record.exc_info:
            line += "\n" + "".join(traceback.format_list(traceback.extract_tb(record.exc_info[2])))
            line += record.exc_info[0].__name__
        return line


def configure_logging(level: str = "INFO", *, structured: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if structured else ConsoleFormatter(color=sys.stderr.isatty()))
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpx2", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

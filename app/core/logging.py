import logging
import json
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from app.core.observability import current_request
        request = current_request.get()
        fields = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                  "logger": record.name, "event": record.getMessage(),
                  "request_id": request["id"] if request else None,
                  **getattr(record, "fields", {})}
        if record.exc_info:
            fields["error_type"] = record.exc_info[0].__name__
        return json.dumps(fields, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)

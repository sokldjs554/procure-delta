from __future__ import annotations

import json
import logging
from typing import Any


class JsonFormatter(logging.Formatter):
    """Small dependency-free formatter for request and worker event fields."""

    _fields = (
        "request_id",
        "job_id",
        "job_key",
        "source",
        "source_record_id",
        "stage",
        "attempt",
        "duration_ms",
        "result",
        "status",
    )

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {"event": record.getMessage(), "level": record.levelname}
        event.update(
            {field: getattr(record, field) for field in self._fields if hasattr(record, field)}
        )
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arq_logger = logging.getLogger("arq")
    arq_logger.handlers.clear()
    arq_logger.propagate = True

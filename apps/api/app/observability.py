from __future__ import annotations

import json
import logging
import os
from typing import Any

import sentry_sdk
from sentry_sdk.types import Event, Hint

from app.config import Settings, get_settings

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "recipient",
    "destination",
    "email",
)
_error_tracking_enabled = False


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


def _sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _sensitive_key(key) else _scrub_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000] + "...[TRUNCATED]"
    return value


def scrub_sentry_event(event: Event, hint: Hint) -> Event | None:
    """Remove request/user/exception text and secret-shaped extras before transport."""
    del hint
    event.pop("request", None)
    event.pop("user", None)

    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and "value" in value:
                    value["value"] = "[REDACTED_EXCEPTION_DETAIL]"

    if "message" in event:
        event["message"] = "application_error"
    if "logentry" in event:
        event["logentry"] = {"message": "application_error"}

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _scrub_value(extra)

    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = _scrub_value(tags)

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and isinstance(breadcrumbs.get("values"), list):
        safe_breadcrumbs = []
        for crumb in breadcrumbs["values"]:
            if not isinstance(crumb, dict):
                continue
            safe_breadcrumbs.append(
                {
                    key: crumb[key]
                    for key in ("timestamp", "type", "category", "level")
                    if key in crumb
                }
            )
        event["breadcrumbs"] = {"values": safe_breadcrumbs}
    return event


def error_tracking_release(settings: Settings) -> str:
    if settings.release_revision != "development":
        return settings.release_revision
    render_commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    return render_commit or settings.release_revision


def configure_error_tracking(
    settings: Settings | None = None,
    *,
    init: Any | None = None,
) -> bool:
    """Enable error tracking only when explicitly opted in with a DSN."""
    global _error_tracking_enabled
    active = settings or get_settings()
    _error_tracking_enabled = False
    if not active.sentry_enabled:
        return False
    if active.sentry_dsn is None or not active.sentry_dsn.get_secret_value().strip():
        raise ValueError("SENTRY_DSN is required when SENTRY_ENABLED=true")

    initializer = init or sentry_sdk.init
    initializer(
        dsn=active.sentry_dsn.get_secret_value(),
        environment=active.sentry_environment,
        release=error_tracking_release(active),
        send_default_pii=False,
        traces_sample_rate=active.sentry_traces_sample_rate,
        before_send=scrub_sentry_event,
    )
    _error_tracking_enabled = True
    return True


def capture_tracked_exception(error: Exception) -> None:
    if _error_tracking_enabled:
        sentry_sdk.capture_exception(error)

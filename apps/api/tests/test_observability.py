from __future__ import annotations

import pytest

from app.config import Settings
from app.observability import (
    capture_tracked_exception,
    configure_error_tracking,
    scrub_sentry_event,
)


def test_error_tracking_is_disabled_without_explicit_opt_in() -> None:
    calls = []

    def init(**kwargs):
        calls.append(kwargs)

    assert configure_error_tracking(Settings(_env_file=None), init=init) is False
    assert calls == []


def test_error_tracking_requires_dsn_when_enabled() -> None:
    with pytest.raises(ValueError, match="SENTRY_DSN"):
        configure_error_tracking(
            Settings(_env_file=None, sentry_enabled=True),
            init=lambda **_: None,
        )


def test_error_tracking_uses_privacy_safe_sdk_options() -> None:
    calls = []

    def init(**kwargs):
        calls.append(kwargs)

    settings = Settings(
        _env_file=None,
        sentry_enabled=True,
        sentry_dsn="https://public@example.invalid/1",
        sentry_environment="ci",
        sentry_traces_sample_rate=0.25,
        release_revision="revision-123",
    )
    assert configure_error_tracking(settings, init=init) is True
    assert len(calls) == 1
    options = calls[0]
    assert options["dsn"] == "https://public@example.invalid/1"
    assert options["environment"] == "ci"
    assert options["release"] == "revision-123"
    assert options["send_default_pii"] is False
    assert options["traces_sample_rate"] == 0.25
    assert options["before_send"] is scrub_sentry_event
    assert configure_error_tracking(Settings(_env_file=None), init=init) is False


def test_sentry_scrubber_removes_request_user_and_sensitive_details() -> None:
    event = {
        "request": {
            "headers": {"Authorization": "Bearer secret"},
            "cookies": {"session": "secret"},
        },
        "user": {"email": "person@example.invalid"},
        "message": "token=secret",
        "logentry": {"message": "password=secret"},
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "recipient@example.invalid token=secret",
                    "stacktrace": {"frames": [{"filename": "app.py", "lineno": 1}]},
                }
            ]
        },
        "extra": {
            "token": "secret",
            "safe_counter": 3,
            "nested": {"password": "secret", "stage": "documents"},
        },
        "tags": {"environment": "test", "api_key": "secret"},
        "breadcrumbs": {
            "values": [
                {
                    "timestamp": 1.0,
                    "category": "http",
                    "level": "info",
                    "message": "https://example.invalid/?token=secret",
                    "data": {"authorization": "secret"},
                }
            ]
        },
    }

    scrubbed = scrub_sentry_event(event, {})
    assert scrubbed is not None
    assert "request" not in scrubbed
    assert "user" not in scrubbed
    assert scrubbed["message"] == "application_error"
    assert scrubbed["logentry"] == {"message": "application_error"}
    assert scrubbed["exception"]["values"][0]["value"] == "[REDACTED_EXCEPTION_DETAIL]"
    assert scrubbed["extra"]["token"] == "[REDACTED]"
    assert scrubbed["extra"]["nested"]["password"] == "[REDACTED]"
    assert scrubbed["extra"]["nested"]["stage"] == "documents"
    assert scrubbed["tags"]["api_key"] == "[REDACTED]"
    assert scrubbed["breadcrumbs"]["values"] == [
        {"timestamp": 1.0, "category": "http", "level": "info"}
    ]


def test_capture_is_noop_when_disabled_and_uses_sdk_when_enabled(monkeypatch) -> None:
    import app.observability as observability

    seen = []
    monkeypatch.setattr(observability, "_error_tracking_enabled", False)
    monkeypatch.setattr(observability.sentry_sdk, "capture_exception", seen.append)
    error = RuntimeError("secret detail")
    capture_tracked_exception(error)
    assert seen == []

    monkeypatch.setattr(observability, "_error_tracking_enabled", True)
    capture_tracked_exception(error)
    assert seen == [error]

from __future__ import annotations

import pytest

from app.ops.wait_for_schema import wait_for_schema


def test_wait_for_schema_retries_until_ready() -> None:
    attempts = 0

    def checker() -> bool:
        nonlocal attempts
        attempts += 1
        return attempts == 3

    wait_for_schema(timeout_seconds=1, interval_seconds=0, checker=checker)
    assert attempts == 3


def test_wait_for_schema_times_out_without_exposing_connection_details() -> None:
    with pytest.raises(RuntimeError, match="database schema did not become ready"):
        wait_for_schema(timeout_seconds=0, interval_seconds=0, checker=lambda: False)

from __future__ import annotations

from typing import Any

import httpx

from app.sources.http import ResilientHttpClient


async def http_drills() -> dict[str, Any]:
    cases = []
    for name, statuses, expected_attempts, succeeds in [
        ('timeout-recovery', [0, 0, 200], 3, True),
        ('rate-limit-recovery', [429, 200], 2, True),
        ('server-error-terminal', [500, 500, 500], 3, False),
        ('forbidden-not-retried', [403], 1, False),
    ]:
        attempts = 0
        delays: list[float] = []

        async def sleep(delay: float, bound_delays: list[float] = delays) -> None:
            bound_delays.append(delay)

        def handle(
            request: httpx.Request,
            bound_statuses: list[int] = statuses,
        ) -> httpx.Response:
            nonlocal attempts
            status = bound_statuses[min(attempts, len(bound_statuses) - 1)]
            attempts += 1
            if status == 0:
                raise httpx.ReadTimeout('synthetic timeout', request=request)
            return httpx.Response(status, json={'synthetic': True})

        succeeded = False
        async with ResilientHttpClient(transport=httpx.MockTransport(handle), sleeper=sleep,
                                       jitter=lambda _: 0, max_attempts=3) as client:
            try:
                await client.request('GET', 'https://example.invalid/source')
                succeeded = True
            except httpx.HTTPError:
                pass
        expected_delays = [0.25 * 2**i for i in range(expected_attempts - 1)]
        passed = (
            attempts == expected_attempts and succeeded == succeeds
            and delays == expected_delays
        )
        cases.append({'name': name, 'attempts': attempts, 'backoff_seconds': delays,
                      'succeeded': succeeded, 'passed': passed})
    return {'scope': 'http_transport_injection', 'cases': cases,
            'database_outage_verified': False, 'redis_restart_verified': False,
            'limitation': (
                'Synthetic HTTP failures; sleepers recorded, not actual network/DB outages.'
            )}

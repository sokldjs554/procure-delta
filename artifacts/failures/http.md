# ProcureDelta failure drills

기계 판독용 원본: `http.json`.

합성 회귀 실험이며 운영 성능/실제 조달 적합도 평가가 아니다. 미실행 지표는 null 또는 not_run이다.

```json
{
  "scope": "http_transport_injection",
  "cases": [
    {
      "name": "timeout-recovery",
      "attempts": 3,
      "backoff_seconds": [
        0.25,
        0.5
      ],
      "succeeded": true,
      "passed": true
    },
    {
      "name": "rate-limit-recovery",
      "attempts": 2,
      "backoff_seconds": [
        0.25
      ],
      "succeeded": true,
      "passed": true
    },
    {
      "name": "server-error-terminal",
      "attempts": 3,
      "backoff_seconds": [
        0.25,
        0.5
      ],
      "succeeded": false,
      "passed": true
    },
    {
      "name": "forbidden-not-retried",
      "attempts": 1,
      "backoff_seconds": [],
      "succeeded": false,
      "passed": true
    }
  ],
  "database_outage_verified": false,
  "redis_restart_verified": false,
  "limitation": "Synthetic HTTP failures; sleepers recorded, not actual network/DB outages.",
  "environment": {
    "python": "3.13.5",
    "os": "Linux-6.18.44-x86_64-with-glibc2.41",
    "cpu_logical_count": 5,
    "machine": "x86_64",
    "cpu_model": "not exposed",
    "shared_sandbox": true
  }
}
```

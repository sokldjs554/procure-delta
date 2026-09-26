# 부하·장애·쿼리 검증

## 공개 reference measurement

CPU·queue·HTTP·query-plan의 기존 공개 측정값은 **GitHub Actions run 35565162198의 격리 Docker 실행**을 reference snapshot으로 고정했다.  
paginated backfill checkpoint/resume 측정은 **GitHub Actions run 35810323430**에서 별도로 추가했다. 입력은 모두 합성 데이터이며, 운영 트래픽·고객 데이터·실제 나라장터 부하가 아니다.

공개 snapshot은 다음 파일에 저장한다.

- `artifacts/performance/cpu.json`
- `artifacts/performance/queue.json`
- `artifacts/performance/backfill.json`
- `artifacts/performance/http.json`
- `artifacts/performance/query-plans.json`
- `artifacts/failures/http.json`
- `apps/api/app/evaluation/results/engineering.json`

API는 저장소 checkout에서는 원본 artifact를 우선 읽고, Docker 이미지처럼 저장소 루트의 `artifacts/`가 없는 환경에서는 packaged `engineering.json`으로 fallback한다. public static demo도 같은 핵심 값을 사용하며 테스트에서 snapshot과의 일치를 확인한다.

## CPU production-function benchmark

`artifacts/performance/cpu.json`:

- 합성 레코드 50,000건을 실제 normalizer와 eligibility/ranker 함수에 통과
- 50,000건 ranking
- 5,000쌍 Delta 비교
- 약 6.995초
- 약 7,148 records/s

이 값은 **CPU-only production-function loop**다. DB INSERT, Redis/ARQ, HTTP, OCR, 외부 LLM, 실제 수집을 포함하지 않으므로 서비스 처리량으로 해석하지 않는다.

## Redis · ARQ · PostgreSQL queue

`artifacts/performance/queue.json`:

- scope: `real_redis_arq_postgresql`
- 합성 입력: 1,000건
- DB에서 확인된 normalized 완료: 1,000건
- worker elapsed: 약 46.59초
- 약 21.46 records/s
- successful: `true`

이 측정은 격리 Docker의 실제 Redis, ARQ worker, PostgreSQL ingest 경로를 사용했다. 문서 다운로드, OCR, 외부 LLM, attachment processing은 제외한다.

## Paginated backfill · checkpoint/resume

`artifacts/performance/backfill.json`은 **GitHub Actions run 35810323430**의 격리 PostgreSQL 측정이다.

- scope: `real_postgresql_paginated_backfill`
- 합성 입력: 2,000건
- page size: 100건
- 총 20페이지 / 성공 IngestRun 20개
- 첫 batch: 5페이지 · 500건
- 저장된 resume cursor: `500`
- 재개 batch: 15페이지 · 1,500건
- DB normalized 완료: 2,000/2,000
- checkpoint에서 재개 확인: `true`
- elapsed: 약 17.46초
- 약 114.55 records/s
- successful: `true`

측정은 production `poll_source_pages()`와 실제 PostgreSQL ingest/normalize/checkpoint 경로를 사용한다. 첫 5페이지 처리 후 의도적으로 호출을 끝내고, 다음 호출이 DB에 남은 cursor에서 나머지 15페이지를 이어 처리하는지 확인한다.

이 benchmark는 최초 호출과 재개 호출 두 번을 측정한다. 각 호출은 production과 동일하게 최대 100페이지이며, 최초 batch와 남은 페이지가 각각 100페이지 이하여야 한다. 이 범위를 벗어나는 조합은 DB 접근 전에 거절한다. 예를 들어 `--records 2000 --page-size 10 --first-batch-pages 5`는 재개할 195페이지가 한도를 넘으므로 허용하지 않는다. 이 제한은 두 호출을 비교하는 benchmark의 입력 계약이며 전체 수집기의 누적 처리 한도가 아니다.

현재 도구는 페이지 크기가 `NORMALIZATION_BATCH_SIZE`보다 커서 남은 정규화가 있으면,
두 discovery 호출 뒤 해당 benchmark 소스만 같은 제한 크기로 복구한다. 다른 소스의 pending
원본은 처리하지 않는다. 각 호출 후 PostgreSQL 완료 건수를 다시 읽고, 진전이 없거나 예상
건수가 완료되면 멈춘다. 추가 호출 수도 처음 남은 레코드 수 이하로 제한한다.
`elapsed_seconds`에는 이 복구 시간이 포함되며, 원본 결과의 `normalized_during_discovery`,
`normalized_during_reconciliation`, `normalization_reconciliation_batches`,
`normalization_reconciliation_seconds`, `normalization_reconciliation_stop`으로 구간을 구분한다.
처리가 남으면 `successful=false`, `records_per_second=null`을 반환한다. 위의 과거 reference
측정값은 이 변경으로 다시 측정하거나 덮어쓰지 않았다.

기존 release snapshot의 gate 목록에는 이후 backfill gate를 소급해서 넣지 않는다. 공개 UI의 별도 Backfill 카드와 이 절의 실행 번호로 후속 측정을 확인한다.

이 값은 **합성 local PostgreSQL backfill** 측정이다. 실제 나라장터 HTTP 응답 지연·rate limit·실문서 다운로드·OCR·hosted LLM은 포함하지 않으므로 운영 수집 처리량으로 일반화하지 않는다.

## 실제 로컬 HTTP 부하

`artifacts/performance/http.json`은 격리된 실제 FastAPI 서비스에 총 200요청을 보냈다. endpoint별 50요청, concurrency 5이며 오류는 0건이었다.

| Endpoint | Requests | p50 | p95 | 범위 |
|---|---:|---:|---:|---|
| inbox | 50 | 1,159.6 ms | 1,219.2 ms | 합성 공고 목록 |
| search | 50 | 1,154.9 ms | 1,210.4 ms | 합성 검색 |
| detail | 50 | 165.5 ms | 195.7 ms | 공고 상세 |
| admin | 50 | 25.3 ms | 71.6 ms | 운영 집계 |

이 지연은 **client-observed local container measurement**다. 인터넷 RTT, 실제 나라장터, 외부 LLM, 실제 사용자 동시성은 포함하지 않는다.

## PostgreSQL query-plan experiment

`artifacts/performance/query-plans.json`:

- 합성 row: 1,007
- 후보 인덱스 전 median execution: 0.331 ms
- 후보 인덱스 후 median execution: 0.041 ms
- 이번 실행의 비율: 약 8.07×
- candidate_adopted: `false`
- candidate_rolled_back: `true`

`query_plans.py`는 실제 keyset 정렬 쿼리에 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`을 실행한다. 후보 인덱스는 rollback 트랜잭션 안에서만 만들었다.

**8.07×를 일반적인 개선률로 주장하지 않는다.** 고정 실행 순서와 warmed cache 영향이 있으므로, 이 한 번의 실험만으로 migration에 인덱스를 채택하지 않았다.

## 실패 주입

`artifacts/failures/http.json`은 실제 `ResilientHttpClient`에 합성 transport 오류를 주입한 결과다.

- timeout: 3번째 시도에서 회복
- 429: 2번째 시도에서 회복
- 반복 5xx: 3회 후 terminal
- 403: 재시도하지 않음

backoff는 기록용 sleeper를 사용했다. 실제 공공 API 장애, 실제 네트워크 단절, 실제 Redis 재시작을 실행한 결과가 아니다.

## 실행

전체 격리 검증:

```sh
python scripts/verify_containers.py --scale-records 1000
```

개별 도구:

```sh
python scripts/seed_scale.py --records 5000
python scripts/backfill_benchmark.py --records 2000 --page-size 100 --first-batch-pages 5
python scripts/load_test.py --mode service --base-url http://localhost:8000 --output artifacts/performance/http.json
python scripts/load_test.py --mode queue --records 5000 --output artifacts/performance/queue.json
python scripts/query_plans.py
python scripts/failure_drill.py --integration
```

`BENCH_DATABASE_URL`은 로컬 `_test` 또는 `_bench` 전용 DB만 허용하고, `BENCH_REDIS_URL`은 로컬 Redis DB 15만 허용한다. 검증 runner는 원본 `.env`와 기존 볼륨을 사용하지 않는다.

## 남은 병목과 한계

- 목록/search는 현재 합성 1천 건 수준에서도 detail/admin보다 비용이 크므로 실제 규모에서 추가 프로파일링이 필요하다.
- graph reconciliation은 더 큰 lifecycle graph에서 별도 측정이 필요하다.
- backfill 2,000건 측정은 cursor/checkpoint/resume 경로의 재현성 증거이며 실제 나라장터 네트워크 처리량은 아니다.
- 본 결과만으로 5만 실문서 수집, 운영 SaaS 동시 사용자 수, OCR/LLM throughput을 입증하지 못한다.
- 하드웨어와 cache 상태가 다른 실행의 절대 지연을 직접 비교하지 않는다.

# 부하·장애·쿼리 검증

## 공개 reference measurement

공개 UI와 README에 표시하는 서비스 측정값은 **GitHub Actions run 35565162198의 격리 Docker 실행**을 reference snapshot으로 고정했다.  
입력은 모두 합성 데이터이며, 운영 트래픽·고객 데이터·실제 나라장터 부하가 아니다.

공개 snapshot은 다음 파일에 저장한다.

- `artifacts/performance/cpu.json`
- `artifacts/performance/queue.json`
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

## Paginated source backfill

`scripts/source_backfill_benchmark.py`는 실제 `poll_source_pages()` 경로를 사용해
합성 paginated source를 PostgreSQL raw 저장과 normalization까지 통과시킨다.

- 페이지마다 성공 cursor를 `IngestRun`에 커밋
- 한 scheduler batch의 page budget을 제한
- budget을 넘는 backlog는 다음 batch에서 재개
- 실제 worker의 source poll 코드와 동일한 DB transaction 경계를 사용
- release gate에서는 `--scale-records`와 같은 합성 레코드 수를 대상으로 측정

결과는 `artifacts/performance/source-backfill.json`에 공개 요약으로 남긴다.
이 값은 **실제 나라장터 네트워크 처리량이 아니다.** public API latency·quota·OCR·hosted LLM·첨부
다운로드는 제외하며, collector의 pagination/cursor/raw-ingest/normalize 경로만 검증한다.

## Redis · ARQ · PostgreSQL queue

`artifacts/performance/queue.json`:

- scope: `real_redis_arq_postgresql`
- 합성 입력: 1,000건
- DB에서 확인된 normalized 완료: 1,000건
- worker elapsed: 약 46.59초
- 약 21.46 records/s
- successful: `true`

이 측정은 격리 Docker의 실제 Redis, ARQ worker, PostgreSQL ingest 경로를 사용했다. 문서 다운로드, OCR, 외부 LLM, attachment processing은 제외한다.

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
python scripts/load_test.py --mode service --base-url http://localhost:8000 --output artifacts/performance/http.json
python scripts/load_test.py --mode queue --records 5000 --output artifacts/performance/queue.json
python scripts/query_plans.py
python scripts/failure_drill.py --integration
```

`BENCH_DATABASE_URL`은 로컬 `_test` 또는 `_bench` 전용 DB만 허용하고, `BENCH_REDIS_URL`은 로컬 Redis DB 15만 허용한다. 검증 runner는 원본 `.env`와 기존 볼륨을 사용하지 않는다.

## 남은 병목과 한계

- 목록/search는 현재 합성 1천 건 수준에서도 detail/admin보다 비용이 크므로 실제 규모에서 추가 프로파일링이 필요하다.
- graph reconciliation은 더 큰 lifecycle graph에서 별도 측정이 필요하다.
- 본 결과만으로 5만 실문서 수집, 운영 SaaS 동시 사용자 수, OCR/LLM throughput을 입증하지 못한다.
- 하드웨어와 cache 상태가 다른 실행의 절대 지연을 직접 비교하지 않는다.

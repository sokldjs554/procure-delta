# 부하·장애·쿼리 검증

## 실제 실행된 범위

`artifacts/performance/cpu.json`: 50,000개 합성 레코드를 실제 normalizer 및 eligibility/ranker 함수에 통과시켰다.
매 10건마다 Delta 비교를 해 총 5,000쌍을 실행했다. 약 6.995초, 약 7,148건/초는 이 CPU 루프의 처리량이다.
논리 CPU 5개로 노출된 Python 3.13.5 공유 Linux 컨테이너에서 측정했다. 전용 서버 성능이 아니다.
이 명령은 DB INSERT, Redis 큐, HTTP 사용자 요청, 실제 수집·OCR·외부 LLM을 수행하지 않는다.

`artifacts/failures/http.json`: 실제 ResilientHttpClient에 합성 HTTP transport 오류를 주입했다.
timeout 2회 후 회복, 429 후 회복, 반복 500의 최종 실패, 403 비재시도를 확인했다.
backoff는 기록용 sleeper를 사용했다. 실제 공공 API 장애나 실제 Redis 재시작을 실행한 결과는 아니다.

## 실제 서비스 측정 도구 (이번 환경 미실행)

```sh
# 전용 로컬 *_bench DB와 Redis DB 15가 필요하다. 운영 주소를 지정하지 않는다.
python scripts/seed_scale.py --records 5000
python scripts/load_test.py --mode service --base-url http://localhost:8000 --output artifacts/performance/http.json
python scripts/load_test.py --mode queue --records 5000 --output artifacts/performance/queue.json
python scripts/query_plans.py
python scripts/failure_drill.py --integration
```

`BENCH_DATABASE_URL`은 로컬 PostgreSQL의 `_test` 또는 `_bench` 전용 DB만 허용한다.
`BENCH_REDIS_URL`은 로컬 Redis DB 15만 허용한다. 실제 ARQ worker가 운영 ingest_record 함수를 실행하고,
job 결과뿐 아니라 DB에서 normalized 상태 건수를 확인한다. 모든 레코드가 정상 처리되지 않으면 성공 처리량을 반환하지 않는다.
`seed_scale`은 부하 실행과 문서 없는 합성 레코드의 읽기 준비 처리를 구분한다. 모든 데이터는 합성이다.
HTTP 측정은 준비된 실제 API에서 로그인·목록·검색·상세·운영자 집계를 호출한다. 실패 응답도 p95와 오류 건수에 포함한다.
운영자 비밀값이 없으면 admin은 not_run이다. 빈 공고함을 유효한 성능 측정으로 취급하지 않는다.

## 인덱스는 아직 채택하지 않았다

`query_plans.py`는 실제 keyset 정렬 쿼리의 EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON)을 후보 인덱스 전후 각 5회 수집한다.
최소 1,000건을 요구하고, 인덱스 생성은 ROLLBACK 트랜잭션 안에서 끝난다. 쿼리 자체를 더 쉬운 것으로 바꾸지 않는다.
고정 실행 순서와 warm-cache 영향을 기록한다. 실제 계획/지연 데이터를 얻기 전에는 개선률이나 인덱스 채택을 주장하지 않는다.
현재 전달본에는 실제 PostgreSQL 계획 산출물이 없다. migration에 근거 없는 인덱스를 추가하지 않았다.

## 남은 병목

실제 API는 항목별 판단 생성과 DB 접근 비용이 있다. graph reconciliation도 큰 데이터셋에서 측정해야 한다.
본 테스트만으로 5만 실문서 수집, 서비스 동시 사용자 수, 크레딧/결제 부하를 입증하지 못한다.
전체 검증은 `python scripts/verify_containers.py`로 격리된 환경에서 실행하고 JSON/로그를 남긴다.

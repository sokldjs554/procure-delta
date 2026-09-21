# 구조와 판단 근거

## 실행 단위

Next.js 사용자/운영자 웹은 FastAPI의 `/api/v1`을 호출한다. FastAPI는 PostgreSQL에서 원본·정규화 버전·문서·판단·outbox를 읽는다.
Redis는 세션과 ARQ 큐에 쓰고, 별도 worker/scheduler 프로세스가 주기 수집과 재처리를 담당한다.
첨부파일은 원본 SHA-256으로 로컬 공유 볼륨에 보관한다. Docker의 API/worker/scheduler가 같은 볼륨을 사용한다.

```text
공개 소스 / 합성 소스
  → raw_records (먼저 commit)
  → opportunities + opportunity_versions (버전별 원본 연결)
  → attachments → native parse / OCR 분기
  → structured_extractions → 근거·필드 검증
  → lifecycle_links / opportunity_deltas
  → company_profile → eligibility → ranking
  → watched events → notification_events(outbox) → delivery receipt / job_failures
```

## 중요한 경계

버전 채택은 effective_at 순서와 DB 직렬화 잠금으로 보호한다. 늦게 온 과거 자료는 이력에 남지만 최신 포인터를 덮지 않는다.
문서 처리 generation은 이전 OCR 작업이 새 처리 상태를 덮지 못하게 한다. 원본과 검증된 추출이 충돌하면 별도 충돌로 기록한다.
공식 연결 근거가 모호하면 미해결로 둔다. 공개 API에는 내부 비밀값이나 임의 원문 오류를 노출하지 않는 projection을 적용한다.

추출은 기본 결정론적 라벨 추출이다. hosted 어댑터가 있어도 키 없이 모델이 실행됐다고 표시하지 않는다.
역사 재생은 실시간 테이블의 current 포인터를 재사용하지 않고, effective_at/observed_at/created_at 모두 당시 이용 가능했는지 확인한다.
평가의 결과 라벨은 ranking 입력에서 제외한다. 이 평가가 실제 수주 확률을 의미하지 않는다.

## 선택하지 않은 것

현재 문제에 필요가 증명되지 않은 별도 벡터 DB, Kafka, Kubernetes는 도입하지 않았다.
PostgreSQL keyset 정렬의 표현식 인덱스는 측정용 후보만 제공한다. 격리 EXPLAIN 실험에서는 실행시간 감소가 관측됐지만 fixed-order/warm-cache 단일 실행이라 후보 인덱스를 rollback했고 배포 마이그레이션에는 넣지 않았다.
대부분의 조회는 기존 모듈의 쿼리를 그대로 사용한다. 목록 조회의 항목별 판단 생성 비용과 큰 그래프 재계산 비용은 측정 후 개선해야 한다.

## 검증 원칙

실행 계약은 `scripts/verify_containers.py`로 격리 검증한다. 원본 `.env`와 기존 DB/Redis 볼륨을 사용하지 않고, backend·frontend·브라우저 E2E·queue/query/load gate를 한 번에 확인한다. 검증 결과는 `artifacts/verification/release-gate.json`에 보존한다.

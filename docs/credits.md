# Credit ledger

ProcureDelta의 크레딧 도메인은 외부 결제사를 흉내 내지 않고, 사용량 차감에서 가장 문제가 되기 쉬운 **중복 차감·동시성·실패 복구**를 다루는 내부 원장으로 구현합니다.

## 상태 전이

```text
grant
  ↓
available
  ├─ reserve → reserved ── commit → spent
  └─ reserve → reserved ── refund ─→ available
```

- `grant`: 구매·프로모션·관리자 지급 등 상위 결제 시스템이 확정한 크레딧을 계정에 반영하는 경계입니다.
- `reserve`: LLM/OCR처럼 비용이 발생할 작업을 시작하기 전에 크레딧을 잠급니다.
- `commit`: 작업이 실제로 사용량을 발생시키면 예약분을 확정 차감합니다.
- `refund`: provider 호출 전 실패하거나 과금하지 않아야 하는 실패면 예약분을 반환합니다.

현재 프로젝트는 **외부 PG·정기결제 webhook·구독 갱신을 구현했다고 주장하지 않습니다.** 이 원장은 그런 상위 시스템이 확정한 결과를 안전하게 반영할 backend boundary입니다.

## 동시성과 중복 방지

계정 갱신은 PostgreSQL `SELECT ... FOR UPDATE`로 직렬화합니다. 두 요청이 남은 5 credits에 각각 4 credits를 동시에 예약해도 하나만 성공하고 다른 하나는 잔액 부족으로 실패해야 합니다.

모든 변경 요청은 계정 범위의 `idempotency_key`를 요구합니다. 같은 키와 같은 입력의 재시도는 기존 ledger entry를 반환하고 잔액을 다시 바꾸지 않습니다. 같은 키를 다른 금액이나 다른 reference에 재사용하면 conflict로 거절합니다.

예약은 별도 `reservation_key`와 상태를 갖습니다. 이미 committed/refunded 된 예약은 다른 요청 ID로 다시 정산할 수 없습니다.

## 저장 구조

- `credit_accounts`: 현재 available/reserved balance
- `credit_reservations`: 예약 금액과 terminal state
- `credit_ledger_entries`: grant/reserve/commit/refund의 append-only 감사 원장

원장 테이블에는 PostgreSQL `BEFORE UPDATE OR DELETE` trigger를 두어 애플리케이션 실수나 직접 SQL에서도 기존 row 변경·삭제를 거절합니다. 정정이 필요하면 기존 row를 고치지 않고 새로운 보정 이벤트를 추가하는 방식으로 확장해야 합니다.

각 ledger row에는 mutation 직후 `available_after`, `reserved_after`를 저장해 운영 시점의 판단을 재구성할 수 있습니다.

## 검증

테스트는 다음을 확인합니다.

- grant → reserve → commit/refund 잔액 보존
- 같은 idempotency key 재실행 시 중복 반영 없음
- 부족한 잔액의 reserve 거절
- terminal reservation 재정산 거절
- 독립 DB session 두 개의 동시 reserve에서 초과 사용 방지
- 직접 UPDATE/DELETE 시 PostgreSQL이 원장 변경을 거절하는지

이 범위는 **크레딧 원장 설계·트랜잭션 안전성 증거**이며 실제 결제사 운영 증거는 아닙니다.


## release evidence

격리 컨테이너 release gate는 실제 PostgreSQL benchmark DB에서 별도 `credit-ledger` drill을 실행합니다.
이 drill은 동일 idempotency key 재요청, 두 독립 session의 동시 reserve, refund/commit 정산,
그리고 직접 UPDATE/DELETE 차단을 다시 실행하고 `artifacts/performance/credit.json` 공개 요약을 만듭니다.
공개 화면은 이 artifact가 없으면 0이나 PASS를 만들어내지 않고 `미측정`으로 표시합니다.


### 저장된 측정 결과

2026-09-22 격리 release-contract에서 credit drill은 동시 reserve 요청 2건 중 1건만 승인하고
1건을 잔액 부족으로 거절했습니다. 같은 idempotency key 재요청은 중복 반영하지 않았고,
refund와 commit 경로가 모두 통과했습니다. PostgreSQL trigger는 직접 UPDATE와 DELETE를 모두
거절했습니다. 최종 잔액은 available 3 / reserved 0, ledger entry 5건, reservation 2건입니다.

이 값은 합성 격리 PostgreSQL 검증이며 외부 PG·정기결제·실제 고객 과금 처리량을 의미하지 않습니다.

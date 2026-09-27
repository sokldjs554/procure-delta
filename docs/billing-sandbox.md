# 합성 webhook과 격리된 크레딧 원장

이 모듈은 **합성 서명 webhook과 실제 PostgreSQL 원장을 연결하는 sandbox 계약**이다.
Stripe에 요청을 보내거나 결제·Checkout·구독을 생성하지 않는다. 실제 Stripe 수신,
현금 결제, 운영 고객 인증, 정기 갱신 운영의 증거로 사용할 수 없다.

## 지원 범위

| 입력 | 처리 |
| --- | --- |
| 서명된 `2025-03-31.basil` snapshot, `livemode=false` | 제한된 필드 검사 후 처리 |
| `invoice.paid`, 단일 고정 금액·수량 1의 구독 최초/주기 청구 | 사전에 등록한 가격 정책과 일치할 때 sandbox 크레딧 지급 |
| 같은 event 재전송 | 기존 관찰 결과 반환, 지급 없음 |
| 다른 event의 같은 invoice | 정규화 지급 사실이 같으면 중복 반환, 지급 없음 |
| 같은 event/invoice의 상충하는 사실 | 409, 전체 트랜잭션 rollback |
| 결제 실패·구독 생성/수정/삭제 | 관찰만 저장; 현재 구독 상태나 이용 권한을 산출하지 않음 |
| 세금·할인·proration·조정·부분 줄 목록·미등록 고객/가격 | `review`, 지급 없음 |
| 환불·분쟁 등 미지원 이벤트 | `review`, 지급 없음; 크레딧 예약 반환을 현금 환불로 취급하지 않음 |
| live, Connect/context, 다른 API 버전, malformed 입력 | 거부; 외부 API 조회로 보완하지 않음 |

지급 가능 청구서는 `status=paid`, 양수의 정확한 정책 금액, 잔액 0,
`subscription_create` 또는 `subscription_cycle`, 완전한 단일 줄, 동일 구독 ID,
동일 통화, 비-proration, 유효한 기간이 필요하다. 청구서·줄의 할인/세금 배열은
비어 있어야 하며 크레딧 노트와 전후 잔액 조정도 없어야 한다. 범위를 넓혀
정책을 추정하지 않는다. `invoice.paid` 자체가 현금 수납 증명이라는 의미도 아니다.

## 설정과 운영자 경계

기본 `BILLING_SANDBOX_ENABLED=false`에서 `POST /api/v1/billing/stripe`는 404다.
활성화하려면 아래 두 값을 모두 지정한다. 빈 Compose 값은 `None`으로 처리한다.

- `BILLING_SANDBOX_SCOPE`: 이 sandbox 판매자/데이터셋의 **영속 namespace**.
  서명 secret, API 버전, 배포 버전 변경 때 바꾸지 않는다. 요청이 선택할 수 없다.
- `BILLING_STRIPE_WEBHOOK_SECRET`: 서명 검증용 `SecretStr`. API에만 전달한다.

고객과 가격은 서버 운영자 CLI로만 등록한다. 요청 metadata, 데모 로그인,
고객 ID 이외의 입력으로 기존 내부 예산 계정을 선택할 수 없다. 고객 등록은
새 `billing_sandbox` 계정을 생성한다. 가격·통화·minor-unit 금액·지급량은 명시적
운영자 입력이며 제품의 기본 가격이나 상용 플랜을 가정하지 않는다.

아래 값은 저장소의 합성 fixture 전용 예시이다. API 디렉터리에서, 마이그레이션을
적용한 로컬 개발 PostgreSQL의 `DATABASE_URL`을 설정한 뒤 실행한다.

```sh
alembic upgrade head
python -m app.ops.billing_sandbox customer \
  --scope synthetic-merchant-stable --customer cus_synthetic
python -m app.ops.billing_sandbox price \
  --scope synthetic-merchant-stable --price price_synthetic \
  --currency usd --amount 1000 --units 10
```

별도 터미널에서 같은 DB로 로컬 API를 시작한다.

```sh
BILLING_SANDBOX_ENABLED=true \
BILLING_SANDBOX_SCOPE=synthetic-merchant-stable \
BILLING_STRIPE_WEBHOOK_SECRET=whsec_local_synthetic_only \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

합성 요청은 외부 Stripe 주소를 사용하지 않는다. API 디렉터리에서 다음을 두 번
실행하면 첫 요청의 `credited=true`, 두 번째의 `credited=false, duplicate=true`를
확인할 수 있다. 첫 번째 `status`는 저장된 관찰 결과이며 재전송에서도 유지된다.

```python
import hashlib
import hmac
import time
import urllib.request
from pathlib import Path

body = Path("tests/billing/fixtures/basil_paid.json").read_bytes()
timestamp = str(int(time.time()))
digest = hmac.new(
    b"whsec_local_synthetic_only", timestamp.encode() + b"." + body, hashlib.sha256
).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/billing/stripe", data=body,
    headers={"Content-Type": "application/json", "Stripe-Signature": f"t={timestamp},v1={digest}"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.read().decode())
```

```sh
python -m app.ops.billing_sandbox status --scope synthetic-merchant-stable
```

가격/고객 바인딩을 같은 값으로 다시 등록하면 기존 값을 반환한다. 다른 값으로
변경할 수 없으며 DB에서 update/delete도 차단한다. `review` 관찰 역시 불변이다.
나중에 바인딩을 추가해도 같은 event는 자동 재처리되지 않는다. 재처리·정합성
복구와 운영자 승인 흐름은 별도 미구현 범위다. 200 `review`를 결제 완료나 지급
완료로 해석하지 않는다.

## 무결성, 격리, 개인정보

HMAC-SHA256은 JSON decode 전 원본 bytes에 적용한다. timestamp는 과거/미래 모두
300초 오차만 허용한다. 복수 `v1` 서명은 지원하며 timestamp 중복, 중복 헤더,
JSON 중복 key를 거절한다. body는 256 KiB, 서명 헤더는 4,096자로 제한한다.
ID·정수·배열을 제한하고 `bool`을 금액으로 허용하지 않는다. 입력/secret/서명이나
개인정보 원문을 응답 또는 로그에 담지 않는다.

event 재전송 fingerprint는 원문 bytes가 아닌 canonical JSON의 SHA-256이다.
공백/키 순서만 바뀐 재전송은 같지만, 같은 event의 내용 변경은 충돌이다.
다른 event에서 동일 invoice를 재전송할 때는 별도 정규화 지급 facts digest로
비교한다. 고객·구독·가격·금액·통화·수량·기간·청구 사유만 관찰/지급 기록에
저장하며 raw payload, 이메일, metadata, 카드 정보는 저장하지 않는다.

한 요청은 하나의 트랜잭션에서 `event → invoice → account` 순서로 잠근다.
없는 event/invoice도 PostgreSQL transaction advisory lock으로 직렬화하고,
`(scope,event_id)`와 **계정 전체에 걸친 `(scope,invoice_id)`** UNIQUE 제약을 둔다.
원장 지급·invoice application·event 관찰은 함께 commit/rollback한다. 기존
application의 계정/가격 정책/지급량/원장 참조를 replay로 덮어쓰지 않는다.

기존 크레딧 계정은 `internal_budget`로 마이그레이션하며 잔액을 유지한다.
계정 종류와 sandbox owner는 DB에서 변경할 수 없다. 정상 grant/reserve/commit/
refund 경로는 sandbox를 거절한다. hosted 추출 설정이 sandbox owner를 잘못
가리키더라도 예약 단계에서 차단되어 provider 호출이 일어나지 않는다. 이미
읽어 둔 계정 객체도 FOR UPDATE 이후 새 잔액으로 다시 읽는다. sandbox 계정이
존재할 때 downgrade로 종류 열을 제거해 내부 예산으로 전환하는 것도 차단한다.

event의 `created` 초 단위 timestamp 또는 도착 순서로 현재 구독 상태를 판단하지
않는다. failed→paid는 지급할 수 있고, 뒤늦게 온 failed는 이미 지급한 원장을
취소하지 않는다. 실제 서비스에는 공급자 대사, 고객 인증, 구독/해지/현금 환불
정책과 보상 거래 설계가 추가로 필요하다.

## 검증

DB 없는 서명/형태/API 경계 검사는 다음 명령으로 재현한다.

```sh
pytest --noconftest -q tests/billing/test_contract.py tests/billing/test_http_contract.py
```

실제 PostgreSQL 테스트는 기존 테스트 DB guard와 마이그레이션 fixture를 사용한다.
API의 ASGI 라우터에서 합성 HMAC 요청을 실제 세션까지 연결해 지급·재전송·409
충돌과 잔액/원장 불변을 검사한다. 동시 동일 invoice, 같은 event의 서로 다른
invoice/고객, 다른 invoice의 동일 계정, 두 rollback 경계, DB 변경 금지,
hosted provider 0회, 기존 예산 마이그레이션 및 downgrade 차단을 포함한다.

```sh
pytest -q tests/billing tests/credits
```

실행 가능한 테스트가 존재한다는 사실과 통과 결과는 구분한다. 로컬 서명/API
계약과 typing/lint를 확인했으며 실제 PostgreSQL 결과는 이 변경의 CI 결과와
릴리스 증거에서 확인한다. 실제 Stripe 결제/수신 검증 건수는 **0**이다.

공식 계약 출처: [webhook 서명·재전송·순서](https://docs.stripe.com/webhooks),
[Basil invoice](https://docs.stripe.com/api/invoices/object?api-version=2025-03-31.basil),
[Basil invoice line](https://docs.stripe.com/api/invoice-line-item/object?api-version=2025-03-31.basil).

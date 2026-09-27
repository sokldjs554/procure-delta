# 나라장터 연동 계약과 검증 범위

## 현재 구현 범위

`koneps-services`는 **용역 입찰공고 및 관측한 변경 상태**만 수집한다.
사전규격·낙찰·계약의 실제 API 수집기는 아직 연결되지 않았다. 전체 생명주기 엔진과
합성 데모가 있다는 사실을 실제 나라장터 5단계 전체 연동으로 표현하지 않는다.

2026-09-18 기준: adapter 계약·합성 HTTP 계약·전체 격리 통합 검증은 통과했다. **실제 인증키를 이용한 API 응답 성공은 별도 live smoke 증거가 필요하다.**
키가 없으면 기존 mock 소스가 그대로 동작한다.

## 출처와 계약 버전

- 공식 목록: https://www.data.go.kr/data/15129394/openapi.do
  (`조달청_나라장터 입찰공고정보서비스`, 2026-09-16 웹 확인).
- 구현 기준은 공식 공개 API 문서와 저장소의 contract tests다.
- 실제 운영 전에는 최신 공식 문서 대조와 승인된 키로 live smoke를 다시 실행한다.
- API endpoint: `https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc`.
  임의 URL을 입력받는 크롤러가 아니다.

## 요청과 수집 위치

`serviceKey`는 환경변수에서 전달하며 명령줄 인수·로그·결과 JSON에 넣지 않는다.
해당 포털에서 받은 **디코딩된 키**를 사용한다. HTTP 클라이언트가 query encoding을 수행한다.
`type=json`, `numOfRows=100`을 기본으로, `pageNo`를 사용한다.

전달받은 계약의 `inqryDiv=1` 등록일시, `3` 변경일시를 같은 시간 창으로 각각 조회한다.
`2`는 공고번호로 정확한 차수를 찾는 조회에 사용한다. 날짜는 `YYYYMMDDHHMM`이다.
페이지 처리 중에는 시간 창을 고정한다. 창이 끝나면 이전 종료시각보다 한 시간 앞부터
겹쳐 읽는다. 중복 payload는 기존 raw/version 중복 방지 규칙으로 처리한다.

한 번의 cron polling은 소스별로 제한된 page budget 안에서 여러 페이지를 연속 처리한다.
기본 KONEPS budget은 5페이지이며 `KONEPS_PAGES_PER_POLL`로 1~100 사이에서 제한한다.
각 페이지는 별도 `IngestRun` 성공 checkpoint로 커밋한 뒤 다음 페이지로 진행하므로,
뒤 페이지가 실패해도 앞선 성공 cursor는 유지되고 다음 실행은 마지막 성공 지점에서 재개한다.
등록일시/변경일시 한 cycle이 끝나거나 budget을 소진하면 해당 실행을 종료한다.

이 기능은 backlog catch-up과 bounded batch 처리 계약을 강화하지만, 모든 과거 데이터를 한 번에
수집했다거나 실제 대규모 운영 처리량을 증명하지는 않는다. 실제 규모는 별도 queue/load gate와
운영 지표로 확인해야 한다. 변경일시 조회는 매 변경 순간의 스냅샷을 보장하지 않으며,
polling 사이에 덮어써진 중간 변경을 완벽하게 복원한다고 주장하지 않는다.

응답 `pageNo`, `numOfRows`, `totalCount`와 실제 레코드 수를 대조한다.
페이지가 잘렸거나 메타데이터가 어긋나면 예외를 발생시켜 완료 cursor를 반환하지 않는다.
이 정책은 **누락 방지 우선**이라 upstream 형식 변경 시 재시도/운영자 확인이 필요할 수 있다.
공식 데이터가 조회 중 바뀌어 생기는 페이지 간 이동까지 완전히 해결한 것은 아니다.

## 원문 보존과 매핑

raw 저장을 먼저 수행하고, 정규화 경계에서만 `map_payload()`를 호출한다.
원본 필드명과 값은 `RawRecord.payload_json`에 유지한다. 아래는 원본 JSON pointer다.

| 원본 필드 | 용도 |
|---|---|
| `bidNtceNo`, `bidNtceOrd` | `services:공고번호:차수`; 정규화된 공고 identity는 공고번호 기준 |
| `bidNtceNm` | 사업명 |
| `dminsttNm` (없으면 `ntceInsttNm`) | 수요기관 (없으면 공고기관) |
| `presmptPrce` | 추정가격; 배정예산·계약금액과 동일시하지 않음 |
| `bidNtceDt`, `bidClseDt` | 공고·마감 시각; KST 입력을 UTC로 저장 |
| `chgDt` → `rgstDt` → 공고 시각 | 관측 payload의 effective time 선택 순서 |
| `ntceKindNm` | 정확히 `변경공고`인 경우에만 amendment 분류 |
| `ntceSpecDocUrl1..10`, `ntceSpecFileNm1..10` | 첨부 원문 URL과 파일명 |

차수가 0보다 크다는 이유만으로 변경공고로 단정하지 않는다.
`bfSpecRgstNo`가 있어도 미구현 사전규격 identity를 지어내지 않는다.
지역 제한·필수 인증이 목록 응답에 없으면 `제한 없음`이 아니라 **근거 미확인**이다.
`required_certifications=[]` 등의 내부 기본값만으로 참가 가능 판정을 확정하지 않는다.
첨부 다운로드는 기존 public-host 검증, 크기 제한, native/OCR 경로를 사용한다.
HWP 파싱과 실제 OCR 품질은 별도 미검증 범위이며 실패 상태를 숨기지 않는다.

## 오류와 민감정보

HTTP 429/5xx 및 네트워크 오류는 기존 제한 재시도를 사용하고, 일반 4xx는 반복하지 않는다.
429/5xx의 `Retry-After`는 [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after)에 따라
0 이상의 정수 초 또는 HTTP-date로 읽는다. 실제 대기 시간은 서버 지시와 기존 지수 backoff/jitter
중 큰 값이다. 과거 날짜나 0은 backoff를 줄이지 않으며 잘못된 값은 기존 backoff를 사용한다.
대기가 요청의 남은 전체 deadline에 들어가지 않으면 즉시 `TimeoutError`로 종료한다.
서버 지시를 임의로 줄여 일찍 재요청하지 않으며 마지막 시도 뒤에는 추가 대기를 하지 않는다.

deadline 예외는 `TimeoutError`의 하위 타입으로 안전한 UTC `retry_not_before`를 보존한다.
마지막 HTTP 시도에서 발생한 오류도 같은 정보를 보존한다. source poll은 서버 시각과
worker backoff 중 늦은 시각을 `JobFailure.next_retry_at`에 커밋하고, ARQ defer에도 같은
시각을 사용한다. cron·재등록된 queue job이 먼저 도착해도 이 시각 전에는 원문 API를 호출하거나
`IngestRun`을 새로 만들지 않는다. 성공하면 실패 시도 수와 cooldown을 함께 해제한다.
서버 지시가 수신 시점부터 **24시간을 초과하거나 유한한 값으로 표현되지 않으면** 자동 재시도하지
않고 명시적 manual review 사유를 가진 terminal/DLQ로 남긴다. 24시간으로 줄여 일찍 호출하지 않는다.
운영자는 안내된 시간·할당량·서비스 상태를 확인한 뒤 기존 수동 재실행 절차를 사용한다.

동일 source의 cron/worker 경합은 PostgreSQL `pg_try_advisory_lock`로 직렬화한다.
잠금은 polling 전체에서 checkout한 동일 연결에 유지하고 `finally`에서 해제한다.
이미 실행 중이면 `in_progress`로 건너뛰어 다른 source의 실행을 막지 않는다.
해제할 수 없는 연결은 pool에 돌려보내지 않고 폐기한다. 재조정기는 이미 도래한 poll의
`next_retry_at`을 다시 미래로 옮기지 않는다. 이 변경은 source poll 경계에 한정되며,
다른 worker 작업 전체의 cooldown 정책을 변경한 것은 아니다.

HTTP 200 안의 API 오류 코드도 성공으로 간주하지 않는다. [공식 오류 안내](https://www.data.go.kr/data/15129394/openapi.do)를
2026-09-27 다시 확인하여 다음처럼 보수적으로 분류한다.

| `resultCode` | 의미와 처리 |
|---|---|
| `01`, `05`, `23` | 내부 오류, 응답 시간 초과, 초당 호출 한도. `KonepsTransientApplicationError`로 기존 worker의 최대 3회 시도/backoff 정책에 전달 |
| `22` | 일일 호출 한도. 즉시 재시도를 소진하지 않고 terminal 처리; 한도 초기화 또는 운영자 조치 후 재실행 |
| 나머지 코드 | 인증·권한·요청 오류 및 미확인 코드. `KonepsApplicationError`로 terminal 처리 |

adapter 안에는 API 오류용 추가 retry loop가 없다. 실패한 페이지의 완료 cursor를 반환하지 않으며,
기존 durable worker retry/dead-letter 경로를 사용한다. 예외에는 두 자리 숫자 코드만 보존하고
그 외 값은 `unknown`으로 대체한다. 이 분류는 합성 HTTP 응답 계약이며 실제 인증 호출 성공 증거가 아니다.
요청 키가 들어갈 수 있는 서버 메시지 및 transport 예외 문자열을 출력하지 않는다.
이 보호는 임의 외부 디버깅 프록시나 모든 third-party DEBUG 로그까지 보장하는 것은 아니다.

## 설정

`.env.example`은 예시이며 비밀값이 없다. 기존 `.env`를 덮어쓰지 말고 필요한 항목만 넣는다.

```dotenv
KONEPS_ENABLED=false
KONEPS_SERVICE_KEY=
KONEPS_LOOKBACK_DAYS=1
```

키를 설정하고 실제 polling을 켤 때만 `KONEPS_ENABLED=true`로 바꾼다.
API/worker/scheduler가 같은 환경설정을 받으며 web에는 키를 전달하지 않는다.
키를 이슈, 채팅, 커밋, 공개 캡처에 쓰지 않는다.

## 실행 확인

프로젝트 루트, 기존 Python 환경에 backend dependencies를 설치한 경우:

```powershell
# Windows, 오프라인 합성 계약. PostgreSQL/Redis/외부 키 불필요.
$env:PYTHONPATH = "$PWD\apps\api"
.\.venv\Scripts\python.exe -m app.sources.koneps_smoke --fixture

# 실제 API는 명시적으로 실행. KONEPS_SERVICE_KEY가 환경에 있어야 함.
.\.venv\Scripts\python.exe -m app.sources.koneps_smoke --live --max-pages 2
```

Compose를 이용하면 `.env` 설정이 컨테이너에 전달된다:

```bash
docker compose build api
docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --fixture
docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --live --max-pages 2
```

`--fixture`는 `mode=synthetic_contract`, `live_verified=false`를 반환한다.
`--live` 성공의 `live_verified=true`는 **해당 호출의 응답 구조 확인**만 뜻한다.
DB 저장, 문서 파싱, 추천 정확도, 전체 데이터 수집 완료를 뜻하지 않는다.
요약에는 원문 대신 payload hash와 처리 건수만 기록한다. 최대 10페이지까지만 허용한다.
키 누락 시 요청 없이 종료코드 2, 호출/계약 실패 시 안전한 오류 클래스만 출력하고 1이다.

## 테스트 구분

```bash
cd apps/api
python -m unittest discover -s contract_tests -v
pytest tests/sources/test_koneps_mapping.py
```

첫 명령은 DB 없는 adapter/배포파일 계약 검사다. 두 번째는 전용 PostgreSQL 테스트 DB가
필요하며 raw 저장 → 정규화 → 재수집 → 문서 처리의 기존 통합 검사를 포함한다.
첫 명령의 성공을 두 번째 명령 또는 Docker/전체 CI 성공으로 대신하지 않는다.
합성 fixture는 실제 응답 녹화본이 아니며, `provenance` 필드에 이를 명시했다.

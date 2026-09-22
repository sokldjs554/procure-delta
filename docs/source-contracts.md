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

한 번의 scheduler tick은 KONEPS에 대해 **최대 10페이지(기본값)**까지만 순차적으로
backfill한다. `KONEPS_PAGE_BUDGET`으로 1~100페이지 범위에서 상한을 정하고,
페이지 사이에는 `KONEPS_INTER_PAGE_DELAY_MS` 지연을 둘 수 있다. 한 페이지가 성공할 때마다
`IngestRun.cursor_after`가 커밋되므로 이후 페이지에서 timeout/429/5xx가 발생해도 이미 성공한
페이지를 다시 처음부터 읽지 않고 마지막 성공 cursor부터 재개한다. page budget에 도달하면 다음
scheduler tick이 같은 cursor에서 이어서 처리한다.

이 bounded backfill은 무제한 크롤링이나 실제 나라장터 대규모 운영 처리량을 증명하는 계약이 아니다.
격리 release gate에서는 합성 paginated source로 `discovery → cursor → raw ingest → normalize`
경로를 별도 측정하며, 실제 public-network latency·API quota·OCR·hosted LLM은 그 측정에서 제외한다.
변경일시 조회는 매 변경 순간의 스냅샷을 보장하지 않으며, polling 사이에 덮어써진
중간 변경을 완벽하게 복원한다고 주장하지 않는다.

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
HTTP 200 안에 들어 있는 API 오류 코드도 성공으로 간주하지 않는다. 그 오류는 현재
안전한 일반 ValueError로 분류되므로 운영자가 인증/일일 할당량/호출 빈도를 확인해야 한다.
요청 키가 들어갈 수 있는 서버 메시지 및 transport 예외 문자열을 출력하지 않는다.
이 보호는 임의 외부 디버깅 프록시나 모든 third-party DEBUG 로그까지 보장하는 것은 아니다.

## 설정

`.env.example`은 예시이며 비밀값이 없다. 기존 `.env`를 덮어쓰지 말고 필요한 항목만 넣는다.

```dotenv
KONEPS_ENABLED=false
KONEPS_SERVICE_KEY=
KONEPS_LOOKBACK_DAYS=1
KONEPS_PAGE_BUDGET=10
KONEPS_INTER_PAGE_DELAY_MS=100
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

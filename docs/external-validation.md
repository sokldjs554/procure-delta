# 외부 실측 실행 절차

2026-09-24 기준 실행 기록과 절차다. 첫 Claude 평가는 HTTP 오류로 실패했으며
[원본과 검증 결함 수정](hosted-evaluation-attempt.md)을 보존했다. 유효한 hosted 품질
실측과 전체 Render 백엔드 배포는 아직 완료하지 않았다. 공개 `procure-delta-demo`는
합성 데이터를 사용하는 읽기 전용 웹이다.

## 1. Hosted LLM 비교

현재 어댑터는 Chat Completions를 사용하고, 응답을 별도의 스키마·근거 검증기에
통과시킨다. Claude 공식 호환 endpoint에서는 JSON mode 옵션을 생략한다.
다음은 재현을 위해 모델 버전을 고정한 **실행 입력 예시**다.
다른 OpenAI-compatible provider를 쓰면 endpoint와 provider/model을 함께 바꾼다.

| Workflow 입력 | 값 |
| --- | --- |
| branch | `main` |
| endpoint | `https://api.openai.com/v1/chat/completions` |
| provider | `openai` |
| model | `gpt-4.1-mini-2025-04-14` |
| max_completion_tokens | `4096` |

공식 [모델 문서](https://developers.openai.com/api/docs/models/gpt-4.1-mini)에서
Chat Completions와 고정 snapshot 지원을 확인했다. 계정의 모델 사용 권한과 API
결제가 필요하다.

Claude 실행에는 다음 값을 사용했다. 9월 24일 연결 진단에서 최소 요청 두 개는
성공했지만 기존 추출 요청은 HTTP 400으로 실패했다. 요청 옵션 수정 후 전체 평가는
실행 오류 0건이었으나 schema failure와 토큰 누락으로 검증에 실패했다. 응답 처리
수정 후 실제 외부 성공은 아직 미확인이다.

| Workflow 입력 | Claude 입력 |
| --- | --- |
| branch | `main` |
| endpoint | `https://api.anthropic.com/v1/chat/completions` |
| provider | `anthropic` |
| model | `claude-haiku-4-5-20251001` |
| max_completion_tokens | `4096` |

[Anthropic 호환 API 문서](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk)는
Bearer 인증, `max_completion_tokens`, prompt/completion usage를 지원한다고 명시한다.
문서는 `response_format`을 무시한다고 설명하지만, [실제 진단](hosted-evaluation-attempt.md#claude-연결-진단과-요청-수정)은
이 필드와 관련된 HTTP 400을 기록했다. 따라서 `https://api.anthropic.com/v1/chat/completions`
요청에서는 해당 필드를 보내지 않는다. JSON 출력은 프롬프트로 요청하고 기존 스키마·근거
검증기로 검사한다. 다른 endpoint에는 기존 JSON mode를 유지한다. `provider`는 기록용
이름이며 요청 형식을 선택하지 않는다. 호환 API는 모델 비교용이며 native Claude structured outputs
어댑터를 구현·검증했다는 뜻은 아니다. 위 OpenAI 가격 예시는 Claude에 적용하지 않는다.

1. [저장소 Actions secrets](https://github.com/sokldjs554/procure-delta/settings/secrets/actions)에
   해당 provider의 키를 `PROCURE_DELTA_LLM_API_KEY`로 등록한다.
2. [Hosted LLM Evaluation](https://github.com/sokldjs554/procure-delta/actions/workflows/hosted-eval.yml)의
   **Run workflow**에서 위 입력을 지정하고 `diagnostics_only`는 끈다.
   키는 workflow 입력이나 문서에 넣지 않는다.
3. 완료 후 `procure-delta-hosted-llm-evaluation` artifact의 `hosted.json`, `hosted.md`,
   `hosted-summary.json`과 실행 URL·commit SHA를 보존한다.
4. `scripts/validate_hosted_eval.py`의 통과 여부와 개별 사례 오류를 확인한다.
   인증/시간초과/잘린 응답이 있으면 정상 실측으로 발표하지 않는다.
   row의 `rejection_stage`, `response_diagnostics`, `schema_error_fields`로 거절 원인을
   구분하고 사례별 토큰과 합계를 확인한다. 측정 validator 통과와 추출 품질 합격을
   구분한다. 받은 사용량은 거절 결과에서도 보존하므로 정확도·거절 수를 함께 확인한다.
5. 저장 결과를 검토한 뒤 README와 공개 평가 패널에 반영한다. 기존 OCR 결과는
   별도 실험이므로 hosted 실행 결과로 덮어써서 소실시키지 않는다.

### Playground는 응답하지만 평가 요청이 실패할 때

같은 workflow에서 `diagnostics_only`를 켜면 전체 평가 대신 Claude 연결 진단만 실행한다.
현재 이 진단은 `anthropic`과 공식 `https://api.anthropic.com/v1/chat/completions` 조합만
허용하며, GitHub Secret의 동일한 키로 다음 순서로 요청한다.

1. native Messages API 최소 요청: 출력 한도 16 tokens.
2. OpenAI-compatible 최소 요청: 출력 한도 16 tokens.
3. 2번의 HTTP 응답이 성공한 경우에만 기존 `HostedExtractor`로 frozen dataset 첫 사례
   요청: workflow의 `max_completion_tokens` 한도를 그대로 사용.

최대 3회 요청이고 재시도는 하지 않는다. 각 최소 요청은 총 25초, 실제 extractor
요청은 30초 안에 종료한다. redirect를 따라가지 않으며, 키의 공백·지원하지 않는
credential 종류·다른 endpoint를 발견하면 네트워크 요청 전에 중단한다.

`hosted-probe.json`은 상태 코드, 허용 목록의 오류 분류/parameter, 사용량만 보존한다.
오류 문장에서는 고정된 공개 프로토콜 용어의 집합만 추출한다. 원문의 단어 순서,
임의 값, URL, header, key, 응답 본문은 저장하지 않는다. `message_terms`는 정확한 오류
문장을 재현하지 않으므로 단독으로 원인을 확정하는 근거로 사용하지 않는다.

프로젝트 요청의 HTTP 성공은 `http_success: true`로 기록하고, 응답 처리 진단은
`response_diagnostics`에 분리한다. 그 안의 HTTP 상태는 실제 응답에서 읽으며, 값이
없을 때 `200`이라고 추정해서 채우지 않는다. 거절 결과도 반환된 사용량을 보존한다.

이 진단 결과의 `quality_evaluated`는 항상 false다. HTTP 성공이나 진단 workflow의
성공을 hosted 품질/정확도/절감률 실측으로 취급하지 않는다. 원인을 해결한 뒤
`diagnostics_only`를 끈 일반 평가가 별도로 통과해야 한다. 기본값은 false이며,
일반 push/PR CI에서는 진단도 외부 모델 호출도 실행하지 않는다.

### 호출 규모와 비용 해석

현재 frozen dataset SHA-256:
`60915644e3d3d36a7aca72a410d40a3075eb472809ed014e50c77f8ecab78116`

`explicit-labels-v2` 검증기로 provider 호출 없이 라우팅만 확인한 결과:

| 항목 | 1회 workflow의 계획 |
| --- | --- |
| 합성 평가 사례 | 정상 5건 + 거절 5건 |
| hosted_all | 논리 호출 10회 |
| hosted_gated | 논리 호출 5회 |
| 합계 | 논리 호출 15회 |
| HTTP 재시도 포함 상한 | 45회 시도, 논리 호출당 최대 3회 |
| 출력 토큰 제한 | 시도당 최대 4,096 |

이는 **호출 계획**이며 실제 호출·절감률 실측이 아니다. `hosted_calls`는 논리 호출
수로, HTTP 재시도 횟수와 다르다. 전체 workflow 제한은 20분, 논리 요청별 전체
deadline은 30초다. 재실행하면 별도 비용이 발생할 수 있다. Idempotency-Key의
과금 중복 방지 여부는 provider에 따라 다르다.

위 모델의 확인 당시 단가는 입력 100만 토큰당 $0.40, 출력 $1.60이다.
재시도 45회가 모두 출력 한도를 쓴다는 가정에서 **출력 부분만** $0.294912이고,
입력 비용은 별도다. 이것은 청구서나 전체 비용 상한이 아니다. 실제 응답의 usage로
토큰을 집계하고, provider가 비용을 반환하지 않으면 평가 artifact의 비용은 null로
남긴다. 가격표 추산을 provider 실측 비용에 섞지 않는다.

## 2. 전체 Render 스택

[Blueprint 열기](https://dashboard.render.com/blueprint/new?repo=https://github.com/sokldjs554/procure-delta)

기존 공개 데모와 구분되는 API·worker·scheduler·web·Postgres·Key Value 6개 리소스다.
`render.yaml`은 아직 배포되지 않은 참고 구성이고 유료 리소스가 포함된다.

### 비용 검토

2026-09-23 [Render 공식 가격표](https://render.com/pricing)와
[Blueprint 기본값](https://render.com/docs/blueprint-spec)을 확인했다.
현재 YAML은 plan을 생략하므로 **새 리소스**에 다음 기본값이 적용된다.

| 리소스 | 기본 compute / 저장공간 | 월 환산 USD |
| --- | --- | ---: |
| API | `0.5c-512mb` | 7.00 |
| Worker | `0.5c-512mb` | 7.00 |
| Scheduler | `0.5c-512mb` | 7.00 |
| Web | `0.5c-512mb` | 7.00 |
| Key Value | `256mb` | 10.00 |
| PostgreSQL | `0.1c-256mb` | 6.00 |
| PostgreSQL 저장공간 | 기본 15 GB × $0.30 | 4.50 |
| 위 리소스 합계 | 신규 6개 리소스, 각 1개 인스턴스 | **48.50** |

외부 S3, LLM, workspace 요금, 추가 build/트래픽 사용량, 세금은 별도다.
월 전체를 실행하는 가정이며 짧은 실험의 실제 청구액은 사용시간과 사용량에 따른다.
무료 worker는 없고 무료 Key Value는 영속 저장을 제공하지 않으므로, 이 토폴로지를
무료 운영으로 표시하지 않는다. 기본 크기가 실제 부하를 견딘다는 검증도 아직 없다.
Apply 전에 Dashboard의 현재 가격과 리소스 목록을 최종 확인한다.

### 입력해야 하는 설정

| 위치 | 설정 |
| --- | --- |
| API·worker·scheduler | 같은 `ATTACHMENT_S3_BUCKET`, `ATTACHMENT_S3_REGION`, S3 access key / secret key |
| API·worker·scheduler | S3-compatible 서비스이면 `ATTACHMENT_S3_ENDPOINT_URL`; AWS S3 기본 endpoint이면 비워 둠 |
| API | `CORS_ORIGINS`를 실제 web origin의 JSON 배열로 입력 |
| Web | `API_PROXY_ORIGIN`에 실제 API의 HTTPS origin 입력; `/api/v1` 경로는 붙이지 않음 |
| Web | `NEXT_PUBLIC_API_URL`은 YAML의 빈 문자열 유지 |
| API·worker | 외부 Sentry 실측 시에만 해당 프로젝트 DSN 및 enabled 설정 |

S3 prefix는 `procure-delta`다. 해당 prefix의 객체 읽기·쓰기가 필요하고 readiness는
`procure-delta/_health/*`에 작은 객체를 쓰고 삭제한다. 따라서 probe 삭제 권한도
필요하다. 버킷 공개 읽기는 필요하지 않다. API readiness가 storage=true여도 실제
공고 첨부파일을 worker가 저장하고 API가 읽은 증거는 별도로 확인해야 한다.

Blueprint는 DB/Redis 연결값과 operator secret을 생성·주입한다. Operator secret은
로그나 공개 결과에 포함하지 않는다. API origin이 확정되면 web proxy와 CORS를
설정하고 web을 다시 빌드한다. 자세한 세션 경계는
[cloud deployment contract](cloud-deployment.md#browser-session-routing)에 있다.

### 배포 후 수집할 증거

1. 4개 실행 서비스의 live deploy ID와 같은 commit SHA를 기록한다.
2. API `/api/v1/release`의 revision이 그 SHA인지 확인한다.
3. API `/health/ready`에서 database, schema, redis, worker, scheduler, storage,
   extraction_config가 모두 true인지 확인한다. `/health/live`만으로 통과시키지 않는다.
4. 실제 HTTPS web에서 로그인, 프로필 저장, 운영자 조회, 로그아웃을 확인한다.
   브라우저 API 요청은 모두 web origin의 `/api/v1/*`이어야 한다.
5. 나라장터 service key와 제한된 수집 범위를 설정한 뒤 polling → worker → DB
   반영을 확인하고, 원본 첨부파일을 API로 받아 DB의 SHA-256과 대조한다.
6. worker/scheduler의 재배포 후 heartbeat·대기 작업 회복을 확인하고, DB 변경이
   호환되는 범위에서 이전 이미지로 복귀한 뒤 정상 revision으로 재배포한다.
7. 증거의 실행 환경·시각·source/dataset SHA와 한계를 기록한다.

기존 `app.demo.seed`와 container E2E는 로컬 DB만 허용한다. 이를 cloud 검증에
그대로 실행하거나 로컬 제한을 우회하지 않는다. 실수집 key가 없는 동안에는
인프라·브라우저 확인과 실수집 증거를 구분해 기록한다.

## 남은 계정 설정

첫 Actions 실행에서 LLM secret이 비어 있지 않은 것은 확인했다. 키의 유효성은 HTTP
실패 때문에 확인하지 못했다. 로컬 작업 환경에는 해당 키, S3 버킷/자격증명, Sentry
DSN이 없다. GitHub secret 값이나 목록은 이 연결에서 조회하지 않는다. 연결된 GitHub
도구에는 workflow dispatch 기능이 없어 수정된 main의 새 실행은 위 Actions 화면에서
시작해야 한다. 과거 run의 Re-run은 이전 commit을 사용한다. Render Blueprint의 최초
Apply는 Dashboard에서 비용과 secret을 확인한 뒤 진행한다.

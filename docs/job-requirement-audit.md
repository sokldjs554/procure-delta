# 스텝에이아이 채용 공고 대조

기준일: **2026-09-26**. 대상은 **[팀 스케일업] AI 풀스택 개발자 (LLM 파이프라인 · 대규모 데이터 수집)**,
[원티드 공고 381607](https://www.wanted.co.kr/wd/381607)이다.
사용자가 9월 23일 보관한 공고 원문의 주요업무·자격요건·우대사항·협업 기준 **34개 항목**을 대조했다.
9월 26일 원티드 검색 결과에서도 회사·직무·주요업무를 확인했다. 채용 상태나 마감 연장을 판단하는 문서는 아니다.
검토 시작 코드는 `b549ba5`이며, 변경의 정확한 SHA와 검증 실행은 해당 PR 기록을 따른다.

## 판단 기준

- **구현 근거 있음**: 코드와 회귀 검사가 있다. 회사에서의 실무 경력을 뜻하지 않는다.
- **부분 충족**: 경계 구현이나 합성·로컬 검증은 있지만 요구 범위 전체를 입증하지 못한다.
- **미구현 / 미실측**: 코드가 없거나 실제 외부 실행 증거가 없다. 설정 파일이나 성공 배지로 대체하지 않는다.

개인 포트폴리오로 자립성과 설계 판단을 설명할 수 있지만 실제 고객 운영·팀 협업·유료 결제·GCP/AWS 실무 경험을 새로 만들어 주지는 않는다.

## 주요업무 9개

| ID | 공고 요구 | 코드·검증 근거 | 판단과 부족한 점 |
|---|---|---|---|
| D01 | FastAPI 비동기 서버: 수집·추출·추천·알림·결제 | [`app/main.py`](../apps/api/app/main.py), [`api`](../apps/api/app/api), [`workers`](../apps/api/app/workers), [`credits`](../apps/api/app/credits) | **부분 충족.** 수집→알림과 내부 크레딧 원장은 있다. 결제 승인·청구·구독 갱신 API는 없다. |
| D02 | Redis 큐·cron·대용량 배치 | [`workers/jobs.py`](../apps/api/app/workers/jobs.py), [`workers/settings.py`](../apps/api/app/workers/settings.py), [checkpoint/resume](data-pipeline.md), [성능 조건](performance.md) | **부분 충족.** ARQ·별도 scheduler·재시도·DLQ·checkpoint. 합성 queue 1,000건, backfill 2,000건 측정. 이번에 정규화 배치를 제한했다. 다른 단계 전체 스캔과 실제 공개 데이터 규모는 남아 있다. |
| D03 | PostgreSQL 설계·migration·쿼리 최적화 | [`models/schema.py`](../apps/api/app/models/schema.py), [`alembic/versions`](../apps/api/alembic/versions), [`scripts/query_plans.py`](../scripts/query_plans.py) | **구현 근거 있음 / 규모 제한.** FK·unique·원장 불변성·동시성·cursor·실행 계획 실험. 1,007행 단일 실험의 인덱스 후보는 미채택이다. 대규모 운영 최적화 경험으로 확대하지 않는다. |
| D04 | Next.js·TypeScript 사용자 웹·admin | [`apps/web/app`](../apps/web/app), [`components/admin`](../apps/web/components/admin), [`e2e/lifecycle.mjs`](../apps/web/e2e/lifecycle.mjs), [`e2e/demo-workspace.mjs`](../apps/web/e2e/demo-workspace.mjs) | **구현 근거 있음.** 탐색·비교·상세·프로필·알림·운영 콘솔, 실제 API와 별도 정적 데모 E2E. 공개 데모의 상태 변경은 현재 탭 범위다. |
| D05 | LLM 프롬프트·구조화·검증·평가·비용 | [`extraction`](../apps/api/app/extraction), [`evaluation`](../apps/api/app/evaluation), [hosted 기록](hosted-evaluation-success.md) | **부분 충족.** 과거 Claude 합성 실측이 있다. 생략을 이용한 검증 우회·허위 절감률을 차단하고 현재 계약 적용 여부를 분리했다. 현재 계약 외부 평가·독립 holdout·LLM 추가 효용·실제 비용은 미실측이다. |
| D06 | 비정형 파싱·OCR 정확도 개선 | [`documents`](../apps/api/app/documents), [원본 스캔](public-scan-ocr.md), [후보 비교](ocr-candidate-evaluation.md), [서식 해석](korean-form-spans.md) | **부분 충족 / 품질 부족.** 파싱·라우팅·프로세스 제한·진단·실패 분석. 공식 원본 스캔의 검증 통과 필드는 **0/6**이다. 일부 개발 사례 개선을 전체 품질로 말할 수 없다. HWP 내용 추출도 없다. |
| D07 | 이메일·메신저와 구독·크레딧 결제 | [알림](notifications.md), [원장](credits.md), [추출 차감](extraction-credits.md) | **부분 충족.** SMTP loopback·outbox·재시도·Slack 형식 계약. 실제 외부 수신은 미실측이다. 내부 크레딧과 달리 PG·정기결제·구독 운영은 **미구현**이다. |
| D08 | 클라우드 컨테이너·로그·에러 추적·장애 대응 | [`Dockerfile`](../apps/api/Dockerfile), [`render.yaml`](../render.yaml), [운영 절차](operations.md), [배포 경계](cloud-deployment.md) | **부분 충족.** 실제 Docker CI와 Render 공개 프런트엔드는 있다. full backend Blueprint는 미배포이며 공개 웹은 전체 컨테이너 서비스 운영 증거가 아니다. 외부 Sentry 수신도 미실측이다. |
| D09 | 불완전한 요구 구조화·결정 기록 | [아키텍처](architecture.md), [source 계약](source-contracts.md), [Delta](DELTA_ENGINE.md), [설계·계획](superpowers), PR | **구현 근거 있음.** 데이터 시점·모호성·실패·비용 경계를 코드와 문서로 남겼다. 이번 대조도 빠진 요구를 그대로 기록한다. |

## 자격요건 14개

| ID | 공고 요구 | 근거 | 판단과 한계 |
|---|---|---|---|
| B01 | Python 비동기 API 개발·운영 | [`db.py`](../apps/api/app/db.py), [`api`](../apps/api/app/api), [`sources/http.py`](../apps/api/app/sources/http.py), API 테스트 | **구현 근거 있음.** AsyncSession·비동기 외부 I/O. 고객 운영은 별개이며 일부 local 파일 I/O는 동기식이다. |
| B02 | PostgreSQL schema·migration·query | [`tests/db`](../apps/api/tests/db), [`tests/domain`](../apps/api/tests/domain), D03 | **구현 근거 있음.** 실 DB migration·동시성·버전 무결성·실행 계획. 목록 API의 측정 지연과 N+1 가능성은 추가 최적화 과제다. |
| B03 | 큐·scheduler·batch·cron 운영 | [`tests/workers`](../apps/api/tests/workers), [`tests/documents/test_reconciliation.py`](../apps/api/tests/documents/test_reconciliation.py), pause/resume gate | **구현 근거 있음.** 영속 상태·재실행·bounded retry·recovery. 운영 트래픽 처리량/SLO는 미실측이다. |
| B04 | 외부 API timeout·retry·fallback | [`tests/sources/test_http_resilience.py`](../apps/api/tests/sources/test_http_resilience.py), [`sources/http.py`](../apps/api/app/sources/http.py), [`documents/download.py`](../apps/api/app/documents/download.py) | **부분 충족.** 제한 시간·429/5xx 재시도·일반 4xx 중단·원문 보존·재처리. deterministic은 명시적 모드이며 hosted 장애 자동 fallback이 아니다. Retry-After와 실제 KONEPS 장애 대응은 남아 있다. |
| F01 | 엄격한 TypeScript | [`tsconfig.json`](../apps/web/tsconfig.json), [`lib/api.ts`](../apps/web/lib/api.ts), CI typecheck | **구현 근거 있음.** strict 타입·DTO. 개인 프로젝트 근거이며 실무 연차 증명은 아니다. |
| F02 | Next.js·React 앱 개발 | [`app`](../apps/web/app), [`components`](../apps/web/components), 정적/실제 API browser gate | **구현 근거 있음.** App Router·React 상태/이벤트·모바일 동선. |
| F03 | 서버 상태 관리·API 연동 | [`lib/api.ts`](../apps/web/lib/api.ts), [`inbox/page.tsx`](../apps/web/app/(product)/inbox/page.tsx), [`session-gate.tsx`](../apps/web/components/session-gate.tsx) | **구현 근거 있음.** 로딩/오류/재시도·cursor·오래된 응답 무효화·세션/CSRF·same-origin API. 공개 합성 응답과 실제 API 검증을 구분한다. |
| F04 | 컴포넌트 기반 UI | [`app-shell.tsx`](../apps/web/components/app-shell.tsx), [`opportunities`](../apps/web/components/opportunities), [`pipeline`](../apps/web/components/pipeline), [`admin`](../apps/web/components/admin) | **구현 근거 있음.** 공통 화면·카드·비교·단계 검사·운영 콘솔. 전체 접근성 준수 인증은 아니다. |
| I01 | GCP 또는 AWS 컨테이너 운영 | [배포 계약](cloud-deployment.md), [`render.yaml`](../render.yaml), S3 adapter | **미실측.** Render와 Docker를 GCP/AWS 운영 경험으로 쓸 수 없다. S3 mock 검증도 실제 AWS 운영 증거가 아니다. |
| I02 | Docker 개발 환경 | [`docker-compose.yml`](../docker-compose.yml), 앱 Dockerfile, [`scripts/verify_containers.py`](../scripts/verify_containers.py) | **구현 근거 있음.** PostgreSQL·Redis·API·worker·scheduler·web·migration. 운영 컨테이너 권한·의존성 lock 등 강화 여지가 있다. |
| I03 | 로그·오류 추적 기반 장애 대응 | [`observability.py`](../apps/api/app/observability.py), [`api/health.py`](../apps/api/app/api/health.py), [`scripts/failure_drill.py`](../scripts/failure_drill.py), [runbook](operations.md) | **부분 충족.** JSON 로그·readiness·DLQ/admin·장애 주입. 스택 내부 값 노출을 수정했다. 외부 DSN 수신·온콜·운영 장애 이력은 없다. |
| C01 | Git branch·code review 협업 | [개발 방식](development-workflow.md), PR #32/#33 및 이번 PR, CI | **부분 충족.** branch→AI review→test→PR→main 절차. 개인+AI 작업은 여러 사람의 팀 협업 경력이 아니다. |
| C02 | 테스트·정적 타입 습관 | [검증 계약](verification.md), [`ci.yml`](../.github/workflows/ci.yml), pytest/Ruff/mypy/TS/ESLint/E2E | **구현 근거 있음.** 이번 결함도 회귀 실패를 먼저 재현한다. 테스트 수는 실제 데이터 품질을 증명하지 않는다. |
| C03 | 불완전한 명세 구조화·문서화 | [아키텍처](architecture.md), [한계](limitations.md), [이번 설계](superpowers/specs/2026-09-26-job-requirement-audit.md) | **구현 근거 있음.** raw/normalized/trusted 구분·불확실성·비용·외부 운영의 경계를 기록한다. |

## 우대사항 7개

| ID | 공고 요구 | 근거 | 판단과 한계 |
|---|---|---|---|
| P01 | LLM 앱·구조화·검증·평가 | D05, [`tests/extraction`](../apps/api/tests/extraction), [`tests/evaluation`](../apps/api/tests/evaluation) | **부분 충족.** 과거 provider 실측과 로컬 검증기. 현재 버전 재실측·독립 문서 평가가 필요하다. |
| P02 | 문서 파싱·수집·정규화 | [`sources/koneps.py`](../apps/api/app/sources/koneps.py), [`documents/parsers.py`](../apps/api/app/documents/parsers.py), [`services/normalize.py`](../apps/api/app/services/normalize.py) | **부분 충족.** 수집 계약·SHA dedupe·시간대·정규화·문서 분기. 대규모 실크롤링·HWP·전체 lifecycle collector는 미구현/미실측이다. |
| P03 | OCR 구축·정확도 개선 | [실문서 진단](public-document-ocr.md), [원본 스캔](public-scan-ocr.md), [서식 해석](korean-form-spans.md) | **부분 충족.** 실제 엔진과 자원 실패 수정·일부 개발 사례 개선. 원본 스캔 필드 0/6을 해결한 것은 아니다. |
| P04 | 검색·추천·랭킹 설계 | [`ranking`](../apps/api/app/ranking), [`tests/ranking`](../apps/api/tests/ranking), [설계](RANKING.md) | **구현 근거 있음 / 품질 미실측.** hard eligibility·결정적 점수·시간 재현. 검색은 제목/기관 문자열 필터다. semantic 검색·실제 기업 관련도/수주 성과 평가는 없다. |
| P05 | 결제·구독·크레딧 연동 | [`tests/credits`](../apps/api/tests/credits), [원장](credits.md), [추출 연결](extraction-credits.md) | **부분 충족.** 내부 grant/reserve/commit/refund·중복/동시성·호출 전 예약. PG·webhook·구독 갱신·고객 청구는 **미구현**이다. |
| P06 | AI 코딩 에이전트 활용 | [개발 워크플로](development-workflow.md), 설계·회귀·AI 리뷰·CI 수정 기록 | **구현 근거 있음.** 생성 코드를 검증하고 실패를 기록한다. AI 활용을 숨기거나 AI 리뷰를 사람 리뷰로 표시하지 않는다. |
| P07 | 대규모 외부 공개 데이터 | [source 계약](source-contracts.md), [성능 범위](performance.md), 실제 PDF 진단 | **미실측.** CPU 50,000건과 queue/backfill은 합성이다. 공개 공고 다량 수집·운영 처리량은 입증하지 못한다. |

## 함께 일하는 기준 4개

| ID | 공고 기준 | 판단 근거 | 남은 제한 |
|---|---|---|---|
| W01 | 지저분한 외부 데이터 처리 | 원문 보존·중복·늦은 변경·모호한 lifecycle·OCR 실패·근거 거절 코드 | 소수 실제 문서 진단이며 여러 기관/서식 일반화가 아니다. |
| W02 | 안정적으로 재현되는 코드 | 컨테이너·동시성·장애 주입·고정 측정과 최신 gate 분리·RED→GREEN | 운영 규모·가동률은 별도 실측이 필요하다. |
| W03 | 백엔드·프런트엔드·인프라 경계 | UI→세션/CSRF→API→DB→queue→worker→evidence·proxy·배포 검증 | full backend cloud는 아직 없고 개인 프로젝트 범위다. |
| W04 | 문제 정의부터 끝까지 진행 | Delta 중심 문제 정의·결정 기록·PR·회귀·배포 후 확인·이번 감사 | 실제 팀의 일정/고객 요구 조율 경험까지 증명하지 않는다. |

## 이번 감사로 보완한 것

| 문제 | 보완 | 확인 방법 |
|---|---|---|
| 대기 raw를 한꺼번에 조회·처리 | ready 행 선별 후 기본 100건 제한, fetched_at/ID 순서 | 여러 배치·재시작·retry/terminal 앞행·타 source 격리 |
| 잘못된 예산·역전 날짜를 모델이 빼면 승인 | 출력과 별도로 명시적 원문 제약 검사, grounding 계약 버전 변경 | 부분 출력 거절·정상 선택 항목 생략 허용 |
| 과거 hosted 결과와 현재 prompt 혼동 | 기록/현재 계약 hash와 applicability, 화면 안내 | 일치/불일치/metadata 부재/미실행 구분, 과거 수치 보존 |
| 합계와 다른 절감률을 artifact가 허용 | 실제 합계로 비율 검증, 증가는 음수 절감률로 허용 | 조작 비율·실제 증가·0/누락 사용량 경계 |
| 오류 추적 스택에 내부 값이 남음 | SDK locals 끄기, 모든 스택의 vars/source context 제거 | 가짜 secret 제거 + 파일/줄/함수 유지 |
| generic만 있어 Slack 수신 계약 없음 | owner별 Slack 형식과 bounded 성공 응답 검증 | payload·멘션 억제·2xx 오류·429/5xx·outbox·비활성 |

## 우선순위가 높은 미완료 항목

| 우선순위 | 남은 일 | 완료로 인정할 근거 | 필요한 입력/결정 |
|---|---|---|---|
| 1 | 외부 결제·구독 | sandbox 승인/실패/중복/순서 역전/갱신/해지/환불과 원장의 원자적 반영 | 결제사·테스트 계정·상품/주기·크레딧 지급/회수 정책·고객 계정 경계. 합성 세션에 임의 청구 정책을 붙이지 않는다. |
| 1 | 실제 문서 OCR 품질 | 여러 기관 독립 holdout의 실패 포함 정확도/거절률·메모리·지연·원문 근거 | 공개 원문·수작업 라벨·품질 기준. 현 원본 스캔 **0/6** 유지. |
| 1 | 현재 LLM 계약 평가 | 현재 hash의 반복 all/gated/rules 비교·실문서 holdout·사용량/실패 | provider 호출 실행과 비용 범위. 기존 합성 30/30으로 추가 효용을 추정하지 않는다. |
| 2 | GCP/AWS 또는 full backend cloud | readiness·실수집 창·롤백/재배포·로그 | 계정·region·비용·object store·비밀값. Render YAML로 대체할 수 없다. |
| 2 | 실제 공개 데이터 규모·query 성능 | 인증된 KONEPS smoke/수집 산출물·오류율·checkpoint 재개·DB/HTTP profile | 서비스키·호출량. 다음 코드 과제: inbox N+1, 다른 reconciliation 전체 스캔, graph 전역 lock, Retry-After. |
| 2 | 외부 알림·Sentry 수신 | 지정된 테스트 수신처 receipt/event ID와 재시도 | 발송이 허용된 Slack/SMTP 수신처·Sentry DSN. 계약 검증은 실발송이 아니다. |
| 3 | 추천 품질 | 블라인드 관련도 라벨·eligibility 오판·랭킹 품질 별도 평가 | 검증용 기업 조건과 관련도 기준. 점수 함수 회귀와 구분한다. |

## 면접에서 먼저 보여 줄 근거

1. 정정→Delta→hard eligibility→ranking→알림을 실행하고 왜 LLM이 참여 조건을 뒤집지 못하는지 설명한다.
2. checkpoint·중복 수집·재시도·DLQ·배치 제한과 실패 재현을 보여 준다.
3. Claude/OCR의 성공과 실패 수치를 함께 제시하고 현재 계약 적용 여부를 설명한다.
4. 크레딧 예약/확정/환불과 외부 결제/구독의 차이를 명확히 말한다.
5. 개인+AI 개발, Docker 실검증, Render 공개 웹, 아직 없는 GCP/AWS 운영 경험을 구분한다.

# ProcureDelta

**공고를 한 번 요약하는 대신, 수집부터 정정·변경·낙찰·계약까지의 연결과 조건 변화를 추적하는 B2B 조달 인텔리전스 시스템입니다.**

FastAPI · PostgreSQL/Alembic · Redis/ARQ · Next.js/TypeScript 기반의 개인 개발 프로젝트입니다.

현재 전체 5단계 lifecycle은 **합성 데이터로 재현**하며, 실제 공개 API adapter는 **나라장터 용역 입찰공고와 관측 변경 상태**까지 구현되어 있습니다. 실제 고객·기업 내부 자료·결제 정보는 사용하지 않습니다.

## Live Demo

**https://procure-delta-demo.onrender.com**

공개 웹은 비용 없는 포트폴리오 시연을 위해 `NEXT_PUBLIC_STATIC_DEMO=true`인 **읽기전용 합성 데이터 모드**로 배포합니다.

- Pipeline Control Room의 시나리오와 contract는 실제 backend 구현과 맞춰 둡니다.
- 화면에 보이는 performance 값은 저장된 격리 검증 snapshot입니다.
- 공개 웹이 현재 나라장터를 polling하거나 hosted LLM/OCR/Redis worker/외부 알림을 실시간 실행하는 것처럼 표시하지 않습니다.
- 실제 FastAPI · PostgreSQL · Redis/ARQ 경로는 Docker release gate와 GitHub Actions에서 별도로 검증합니다.

![ProcureDelta landing](docs/images/landing.png)

## 60초 데모

면접관이 프로젝트를 처음 봤을 때 가장 먼저 볼 동선입니다.

1. **파이프라인**으로 이동
2. **정정으로 조건 변경** 선택
3. **재생** 클릭
4. **Delta** 단계에서 이전/현재 값과 deterministic reason code 확인
5. **참여 조건**에서 참여 가능 → 불가로 바뀐 이유 확인
6. 관련도 점수가 높아도 hard eligibility를 뒤집지 못하는지 확인
7. **Scale / Failure / HTTP / Query Plan** 카드에서 실제 측정 범위 확인
8. **평가·한계**에서 deterministic / hosted / OCR 측정 여부 확인

핵심은 이 한 줄입니다.

```text
collect → dedupe → normalize → document/OCR → structured extraction
→ validation → lifecycle → Delta → eligibility → ranking → notification
```

![Pipeline Control Room](docs/images/pipeline-control-room.webp)

## 왜 이 구조인가

일반적인 공고 AI 데모는 “문서를 올리고 요약하거나 질문한다”에서 끝나는 경우가 많습니다.

ProcureDelta는 한 공고가 시간이 지나며 바뀌는 문제를 중심으로 잡았습니다.

- 사전규격이 공고로 이어졌는가
- 같은 공고의 정정이 새 version으로 들어왔는가
- 예산·마감·지역·필수 인증·첨부가 무엇이 바뀌었는가
- 그 변화가 우리 회사의 **참여 가능 여부**를 바꿨는가
- 참여 가능 여부와 별개로 **관련도 순위**는 어떻게 변했는가
- 관심 공고라면 어떤 알림 판단이 생기는가
- 수집·파싱·추출·queue가 실패했을 때 retry/DLQ 경계가 무엇인가
- 과거 시점 판단을 replay할 때 미래 정보를 섞지 않았는가

즉, 챗봇이 아니라 **외부 데이터가 서비스 판단으로 바뀌는 전체 lifecycle**을 구현 대상으로 삼았습니다.

## 제품 / 데이터 흐름

```text
공개 source / 합성 source
        ↓
raw payload 보존 + idempotent ingest
        ↓
dedupe + normalization + immutable opportunity versions
        ↓
attachment download → native parse / OCR routing
        ↓
structured extraction + schema/evidence validation
        ↓
lifecycle linking + deterministic Delta Engine
        ↓
company hard eligibility
        ↓
relevance ranking
        ↓
watch / outbox / notification receipt / retry / DLQ
```

### 설계에서 의도적으로 분리한 것

- **Raw first** — 외부 payload를 먼저 보존하고 정규화 실패가 원문 손실로 이어지지 않게 했습니다.
- **Append-only versioning** — 늦게 도착한 과거 자료는 이력에 남지만 최신 상태를 되돌리지 않습니다.
- **Deterministic Delta** — 예산·마감·지역·자격·첨부 변화는 LLM 설명이 아니라 규칙 기반 비교와 evidence pointer로 계산합니다.
- **Eligibility before ranking** — 필수 조건 실패나 미확인 상태를 관련도 점수가 뒤집지 못합니다.
- **Evidence-validated extraction** — 구조화 출력은 schema·원문 근거·conflict 검증을 통과해야 downstream 판단에 들어갑니다.
- **Durable async pipeline** — Redis/ARQ 작업과 PostgreSQL 상태를 분리하고 bounded retry, reconcile, DLQ 경계를 둡니다.
- **Historical replay** — `effective_at / observed_at / created_at / available_at`을 구분해 당시 알 수 없던 정보를 과거 판단에 넣지 않습니다.
- **Operational visibility** — source freshness, parser/OCR/extraction, queue, retry/DLQ, runtime 상태를 운영자 화면에서 확인합니다.

![Admin console](docs/images/admin-console.png)

## Pipeline Control Room

Reviewer-facing `/pipeline`은 실제 기능을 단순한 아키텍처 그림이 아니라 **단계별로 열어볼 수 있는 replay**로 보여줍니다.

### 1. 신규 공고

최초 관측이 들어와 정규화·문서 처리·추출·검증·eligibility·ranking·알림 판단으로 이어집니다. 최초 version이므로 Delta는 비교 대상 없음으로 표시합니다.

### 2. 정정으로 조건 변경

가장 중요한 시나리오입니다.

```text
amendment
→ immutable new version
→ Delta
→ hard eligibility changed
→ ranking cannot override the hard failure
→ notification decision
```

각 단계에서 **입력 / 출력 / 근거 / 판단**을 볼 수 있습니다.

### 3. 장애와 복구

저장된 synthetic transport failure 결과를 이용해 다음 경계를 보여줍니다.

- timeout → bounded retry 후 회복
- 429 → retry 후 회복
- 반복 5xx → bounded attempts 후 terminal
- 403 → non-retry

실제 공공 API 장애가 발생했다고 주장하지 않습니다.

## 검증된 engineering evidence

기존 CPU·queue·HTTP·query-plan 카드는 **GitHub Actions run 35565162198**의 격리 Docker 측정을 reference snapshot으로 고정했습니다. 새 paginated backfill 측정은 수집 checkpoint/resume 경로를 추가 검증하기 위해 **GitHub Actions run 35810323430**에서 별도 측정했습니다. CI마다 달라지는 timing을 가장 잘 나온 값으로 계속 갈아끼우지 않습니다.

| 영역 | 관측값 | 범위 |
|---|---:|---|
| CPU production functions | 50,000 normalize/rank + 5,000 Delta, 약 7,148 records/s | DB·Redis·HTTP·OCR·LLM 제외 |
| Redis/ARQ/PostgreSQL | 1,000/1,000 완료, 46.59s, 약 21.46 records/s | 합성 ingest, 문서/OCR/외부 LLM 제외 |
| Paginated backfill | 2,000/2,000 정규화, 20페이지, 17.46s, 약 114.55 records/s | 5페이지 후 중단 → cursor 500에서 15페이지 재개, local synthetic PostgreSQL |
| Local HTTP | 총 200요청, 200성공, 0실패 | endpoint별 50요청, concurrency 5 |
| inbox HTTP p95 | 약 1,219.2 ms | local container / synthetic data |
| search HTTP p95 | 약 1,210.4 ms | local container / synthetic data |
| detail HTTP p95 | 약 195.7 ms | local container / synthetic data |
| admin HTTP p95 | 약 71.6 ms | local container / synthetic data |
| PostgreSQL query experiment | 0.331 → 0.041 ms, 이번 실행 약 8.07× | 1,007 rows, fixed-order/warm-cache |
| candidate index | 미채택, rollback 확인 | 단일 실험을 migration 근거로 사용하지 않음 |

자세한 조건은 [Performance](docs/performance.md)에 기록했습니다.

## AI / OCR 평가

평가 화면은 “AI를 썼다”가 아니라 **어떤 경로를 실제 측정했고 어떤 경로를 실행하지 않았는지**를 구분합니다.

| 경로 | 상태 | 관측 |
|---|---|---|
| deterministic extraction | 측정됨 | 30/30 labeled fields, 작은 합성 회귀셋 |
| OCR · English synthetic | 측정됨 | Tesseract 17/18 fields, 영어 합성 이미지 3장 |
| OCR · Korean synthetic | 측정됨 | Tesseract 18/18 fields, `kor+eng`, clean/blurred/low-resolution 3장 |
| OCR · 실제 공고 PDF 렌더 | 측정됨 · 품질 미달 | 원문 2건/이미지 6장, 문자열 anchor 11/24, 검증 통과 구조화 필드 **0/12**; 자연 스캔 아님 |
| OCR · 공식 공고 원본 스캔 | 런타임 수정 후 2회 측정 · 품질 미달 | 원본 2건/8쪽 처리, 첫 페이지 anchor **4/8**, 검증 통과 필드 **0/6**; [메모리 실패·수정·반복 기록](docs/public-scan-ocr.md) |
| 한국어 공고 항목 해석 v2 | 제한적 개선 | 별도 2건의 원문 텍스트 **0/6 → 3/6**, 같은 문서의 OCR은 **0/18**; [조건·실패 포함 비교](docs/korean-form-grounding.md) |
| hosted all | **외부 실측 완료 · 합성 회귀** | Claude Haiku 4.5, v3 검증 통과 필드 **30/30**, 호출 10회, 22,343 tokens |
| hosted gated | **외부 실측 완료** | **30/30은 로컬 규칙 결과**, 호출 5회, 10,149 tokens; 전체 호출 대비 호출 50%·토큰 54.6% 감소 |

첫 [Claude 실행 실패 기록](docs/hosted-evaluation-attempt.md)은 원본 artifact와 함께
보존했습니다. 해당 Actions의 초록색 표시는 결과 검증 실패가 가려진 결함이었으며,
유효한 실측으로 인정하지 않습니다. 요청 옵션·응답 처리·사용량 보존을 수정한 뒤
[9월 24일 v3 실제 평가](docs/hosted-evaluation-success.md)는 외부 요청과 측정 검증을 모두 통과했습니다.
같은 합성 10건에서 단독 경로의 검증 통과 필드는 v2 **18/30 → v3 30/30**,
정상 문서 거절은 **2건 → 0건**이었습니다. 각 버전 1회 관측이며 반복성·인과 효과는 미확인입니다.
단독 경로 전체 토큰은 **15,654 → 22,343**, p95는 **4.40s → 10.86s**로 늘었습니다.
gated의 정상 필드는 로컬 규칙에서 나왔고, 같은 셋의 순수 규칙도 30/30·외부 호출 0회입니다.
이 결과로 LLM의 추가 효용이나 실제 문서 일반화를 주장하지 않습니다. provider 보고 비용은
없어 **비용·비용 절감률은 미측정**입니다. API와 정적 데모는 같은 저장된 공개 projection을 사용합니다.

Delta는 합성 비교 8쌍에서 expected changed field 7개를 검증했고, lifecycle link는 합성 사례 5개 중 2개를 resolve하고 ambiguous/missing/incompatible 사례는 unresolved로 남겼습니다.

이 숫자는 일반화 benchmark가 아니라 **작은 작성자 제작 regression set**입니다.


## Release gate

저장소의 `artifacts/verification/release-gate.json`은 **2026-09-21 GitHub Actions run 35568528869**의 고정 reference snapshot이며 `passed=true`입니다. 이후 추가된 Korean OCR gate는 main run **35750906271**, paginated backfill gate는 branch run **35810323430**에서 별도로 통과했습니다. 최신 기능을 과거 snapshot에 소급해서 기록하지 않습니다.

현재까지 확인된 통과 범위:

- Compose contract / image build
- PostgreSQL + Redis
- Ruff / strict mypy / DB isolation regression / backend tests
- source contracts / evaluation / **Korean OCR 18/18 regression** / fault drill
- runtime start / full readiness
- frontend test / typecheck / lint
- 실제 browser lifecycle E2E
- **Pipeline Control Room desktop/mobile/reduced-motion E2E**
- Redis/ARQ queue scale
- **paginated backfill 2,000건 · 20페이지 · checkpoint/resume 검증**
- PostgreSQL query-plan experiment
- local HTTP load
- worker/scheduler pause → resume

Readiness snapshot에서 database, schema, redis, worker, scheduler, storage, extraction_config가 모두 `true`였습니다.

검증 방식: [Verification](docs/verification.md)

## 로컬 실행

Docker Desktop이 실행되는 환경에서:

```bash
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env

docker compose up --build -d
docker compose exec api python -m app.demo.seed --run-id review --phase base
```

- Web: `http://localhost:3000`
- Pipeline: `http://localhost:3000/pipeline`
- API readiness: `http://localhost:8000/health/ready`

정정과 outcome lifecycle을 순서대로 시연:

```bash
docker compose exec api python -m app.demo.seed --run-id review --phase amendment
docker compose exec api python -m app.demo.seed --run-id review --phase outcome
```

전체 격리 통합 검증:

```bash
python scripts/verify_containers.py --scale-records 1000
```

## 실제 나라장터 adapter

현재 실제 adapter는 조달청 나라장터 **용역 입찰공고 조회와 관측 변경 상태**까지 연결되어 있습니다.

수집은 등록/변경 시간 창을 고정한 cursor 기반 pagination이며, 기본 한 주기에서 최대 5페이지를
연속 처리합니다. 각 페이지를 별도 checkpoint로 커밋해 뒤 페이지 실패 시에도 마지막 성공 cursor부터
재개합니다. 이 경로는 합성 local PostgreSQL benchmark에서 2,000건/20페이지를 처리하고,
5페이지 이후 저장된 cursor에서 나머지 15페이지를 재개하는 것까지 측정했습니다. 다만 이 결과는
실제 나라장터 네트워크·운영 규모·실문서 OCR/LLM 처리량을 증명하는 값으로 표현하지 않습니다.

사전규격·낙찰·계약의 실제 collector는 아직 구현하지 않았으며, 합성 5단계 lifecycle과 구분합니다.

키 없이 source contract 확인:

```bash
docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --fixture
```

공식 서비스키가 있는 로컬 환경에서만 live smoke를 명시적으로 실행합니다.

```bash
docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --live --max-pages 2
```

서비스키는 커밋·로그·결과 JSON에 기록하지 않습니다.

자세한 계약: [Source contracts](docs/source-contracts.md)

## 기술 구성

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy async, Alembic, Pydantic v2
- **Data/Queue**: PostgreSQL 16, Redis 7, ARQ
- **Frontend**: Next.js 16, React 19, TypeScript strict
- **Document/AI**: PyMuPDF, OCR adapter boundary, deterministic extractor, provider-neutral structured extraction adapter
- **Quality**: pytest, Ruff, strict mypy, ESLint, TypeScript, Playwright
- **Infra**: Docker Compose, GitHub Actions, Render reference Blueprint, local/S3-compatible attachment storage
- **Notifications**: PostgreSQL outbox, ARQ delivery, local receipt, HTTPS webhook, bounded SMTP email transport
- **Observability**: structured JSON logs, readiness/admin diagnostics, optional privacy-scrubbed Sentry SDK integration
- **Development**: AI-assisted implementation with branch/PR review, static checks, regression tests, repeated release gates, and explicit measured/not_run evidence boundaries

## 범위와 한계

- 전체 5단계 lifecycle demo는 합성입니다.
- 실제 나라장터 연동은 현재 용역 입찰공고와 관측 변경 범위입니다.
- 실제 사전규격·낙찰·계약 collector는 아직 없습니다.
- HWP 내용 추출과 실제 나라장터 한국어 자연 스캔 OCR 일반화 성능은 검증하지 않았습니다. 한국어 합성 18/18과 별도로 [실제 공고 PDF 2건의 지면 렌더 진단](docs/public-document-ocr.md)을 수행했지만, 검증 통과 구조화 필드는 **0/12**였습니다. 합성 회귀 통과를 실문서 정확도로 확대 해석하지 않습니다. 로컬 기본값은 fixture이며, 실제 워커에는 [제한된 Tesseract 런타임](docs/runtime-ocr.md)을 선택할 수 있습니다. 런타임 연결 검증과 인식 정확도는 별개입니다.
- [공식 사이트의 원본 스캔 2건](docs/public-scan-ocr.md)은 워커 어댑터의 페이지 간 메모리 문제를 수정한 뒤 두 번 모두 8쪽 처리를 완료했습니다. 같은 기관·유사 서식의 작은 표본이며, 첫 페이지의 검증 통과 필드는 **0/6**입니다. 추가 진단 재실측에서도 같은 결과이며, 두 건 모두 제목·발주기관·분류 누락으로 스키마 단계에서 거절됐습니다. 전체 PDF 추출 승인·DB 저장·클라우드 성능·나라장터 첨부 수집 실측을 뜻하지 않습니다.
- hosted LLM은 합성 10건에서 v2·v3 각 1회의 외부 정확도·호출·토큰·지연시간을 실측했습니다. 최신 단독 경로는 30/30이며 gated의 30/30은 로컬 규칙 결과입니다. 같은 버전 반복 평가·실문서 일반화·LLM 추가 효용·실제 비용은 미검증입니다.
- ranking은 deterministic baseline이며 수주확률 모델이 아닙니다.
- performance snapshot은 격리 합성 실행이며 production capacity가 아닙니다.
- 공개 Render web은 static/read-only synthetic demo입니다. full backend용 Render Blueprint와 S3-compatible shared storage 경계는 구현했지만, 해당 stack을 실제 cloud 운영했다는 증거는 아닙니다.
- 내부 크레딧 원장과 [hosted 추출 워커의 선택적 예산 연결](docs/extraction-credits.md)을 구현했습니다. 호출 전 예약, 결과·차감의 원자적 저장, 불명확한 실행의 자동 재호출 차단을 제공합니다. 공유 파이프라인 예산이며 실제 provider 비용이나 고객별 결제는 아닙니다. 외부 PG·정기구독 연동, 운영용 인증/기관 격리, 무중단 운영은 별도 운영화 과제입니다.
- SMTP email은 CI loopback 서버로 실제 TCP 전송까지 검증했습니다. 실제 Gmail/SES/SendGrid 등 public provider 전송 성공을 주장하지 않습니다.
- Sentry SDK 경계와 redaction은 CI에서 검증하지만 실제 Sentry DSN으로 외부 이벤트 전송을 운영했다는 증거는 아닙니다.

자세한 내용: [Limitations](docs/limitations.md)

## 문서

- [Architecture](docs/architecture.md)
- [Data pipeline](docs/data-pipeline.md)
- [Source contracts](docs/source-contracts.md)
- [Extraction](docs/extraction.md)
- [Delta Engine](docs/DELTA_ENGINE.md)
- [Ranking](docs/RANKING.md)
- [Notifications](docs/notifications.md)
- [Credit ledger](docs/credits.md)
- [Evaluation](docs/evaluation.md)
- [Performance](docs/performance.md)
- [Operations](docs/operations.md)
- [Cloud deployment contract](docs/cloud-deployment.md)
- [Verification](docs/verification.md)
- [Limitations](docs/limitations.md)

Copyright © 2026 윤기혁. All rights reserved. Portfolio project.

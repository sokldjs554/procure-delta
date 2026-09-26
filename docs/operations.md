# 로컬 운영과 장애 확인

## 일반 로컬 데모

프로젝트 루트에서 `.env.example`을 `.env`로 복사한 뒤 필요한 값만 설정한다. 키 없이 합성 데모를 쓸 수 있다.
`DEMO_OPERATOR_SECRET`을 개인 로컬 값으로 정하면 `/admin`에서 해당 값으로 로그인할 수 있다. 이를 GitHub나 ZIP에 넣지 않는다.

```sh
docker compose up --build -d
docker compose exec api python -m app.demo.seed --run-id review --phase base
```

일반 포트는 웹 3000/API 8000/DB 5432/Redis 6379이다.
DB가 뜬 것과 서비스 전체가 준비된 것은 다르다. `/health/live`는 생존 확인이고 `/health/ready`는 DB·마이그레이션·Redis·worker·scheduler·저장소·추출 설정을 모두 확인한다.

```sh
docker compose ps
docker compose logs --tail 100 api worker scheduler migrate
```

API와 worker/scheduler는 동일한 JSON logging formatter를 사용한다. `SENTRY_ENABLED=false`가 기본이며,
실제 error tracking을 켜려면 `SENTRY_ENABLED=true`와 `SENTRY_DSN`을 모두 설정해야 한다.
Sentry 전송 시 request/user는 제거하고 exception message와 secret-shaped extra/tag/breadcrumb data를
redact한다. SDK의 지역 변수 수집을 끄고 exception·thread·top-level stack frame의
`vars`, `pre_context`, `context_line`, `post_context`도 제거한다. 파일·줄·함수 위치는 유지한다.
가짜 비밀값을 넣은 회귀로 이 경계를 확인하며 실제 외부 DSN 수신 증거는 아니다.
`SENTRY_TRACES_SAMPLE_RATE` 기본값은 0이다.

기본 알림은 로컬 영수증이다. 이메일·웹훅을 실제 발송했다고 해석하지 않는다.
평가용 OCR이 있는 것과 기본 서비스에 실제 OCR 공급자가 연결된 것은 다르다.
나라장터/외부 LLM 설정과 스모크는 `source-contracts.md` 및 `evaluation.md`에 분리했다.

## 격리된 최종 검증

Windows PowerShell 또는 일반 터미널에서 프로젝트 루트의 명령을 실행한다.

```sh
python scripts/verify_containers.py
```

필요한 도구는 Docker Desktop, Node.js 22.6 이상, Python이다. 의존성·이미지는 이 컴퓨터에서 내려받는다.
검증 프로젝트 이름은 `procure-delta-verify-<random>`이며 포트 13000/18000/15432/16379를 로컬에서만 사용한다.
원본 `.env`를 읽지 않고 일회성 운영자 비밀값을 메모리에서 생성한다. 기존 프로젝트 DB/볼륨/.git/origin을 바꾸지 않는다.
검증 종료 시 생성한 격리 스택과 볼륨만 정리한다. `--keep-running`이면 격리 스택을 유지한다.
로그에 임시 비밀값이 있으면 기록 전에 제거한다. HAR/세션 쿠키/브라우저 trace는 저장하지 않는다.

`artifacts/container/release-gate.json`에 각 단계 통과/실패와 프로젝트 이름이 남는다.
백엔드 실패는 `checks.json`, `backend-tests.log`와 `pytest.xml`을 본다.
E2E는 `artifacts/e2e/result.json`과 화면 캡처를 본다. 파일이 없거나 passed=false이면 통과한 것이 아니다.

## 장애 판단

- 공공 소스 실패: 마지막 정상 수집과 실패 클래스 확인. 원본을 삭제하지 않고 cursor/JobFailure를 확인한다.
- worker 중단: DB outbox와 원본은 유지한다. Redis 세션 장애는 API 로그인을 방해할 수 있으므로 읽기 무중단이라고 주장하지 않는다.
- 문서/OCR 실패: 원본 checksum, document generation, 재처리 예산을 확인한다. 오래된 작업이 새 작업 결과를 덮지 않게 한다.
- 중복 알림: event의 dedupe key/lease/영수증으로 실제 발송 상태를 확인한다. 외부 채널의 정확히 한 번 전달을 보장하지 않는다.
- 스키마 오류: migrate 로그를 먼저 확인한다. DB 볼륨 삭제로 고치려 하지 않는다.

## 배포 계약과 보안 경계

이 저장소는 컨테이너 실행 계약과 Render reference Blueprint를 제공하지만 full backend cloud stack을 실제 운영했다고 주장하지 않는다.
클라우드 구성은 PostgreSQL·Key Value, 별도 API/worker/scheduler/web, S3-compatible 공용 문서 저장소, 비밀값, HTTPS/CORS, readiness와 migration 순서를 분리한다.
worker/scheduler는 schema head가 적용될 때까지 시작을 기다리며, API와 worker는 같은 S3-compatible blob store를 사용한다. 로컬 Docker Compose는 기존 파일시스템 backend를 유지한다.
운영 인증·기관 격리 검증·보존 정책, 실제 Sentry 프로젝트/알림 규칙 운영과 실제 cloud sync는 별도 운영화 과제다.

자세한 배포 경계: [Cloud deployment contract](cloud-deployment.md)

## 공개 저장소 원칙

실제 비밀값이 있는 `.env`는 커밋하지 않는다. `.env.example`만 예시로 유지한다. 공개 저장소는 소스·테스트·재현 문서·검증 증거만 포함하고, 개발 중간 handoff/prompt 파일은 포함하지 않는다.

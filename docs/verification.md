# Verification

## Current release gate

2026-09-21에 `python scripts/verify_containers.py --scale-records 1000`으로 원본 `.env`, 기존 DB/Redis 볼륨, 기존 서비스와 분리된 Compose 프로젝트에서 전체 검증을 실행했다.

현재 저장된 `artifacts/verification/release-gate.json`은 GitHub Actions run **35568528869**의 성공 결과다. 이 파일은 고정 reference snapshot이라 이후 gate를 소급해서 덮어쓰지 않는다.

후속 검증:
- Korean OCR 실제 Tesseract `kor+eng` 합성 회귀 gate: main run **35750906271**, 18/18 fields
- paginated backfill checkpoint/resume gate: branch run **35810323430**, 2,000건 · 20페이지 · 5→15페이지 재개

- `passed: true`
- `status: passed`
- scope: `isolated_container_integration`
- web readiness status: 200
- database / schema / redis / worker / scheduler / storage / extraction_config: 모두 `true`

## 통과한 gate

1. compose contract
2. image build
3. PostgreSQL + Redis
4. backend integration
   - Ruff lint
   - strict mypy
   - DB isolation regression
   - backend tests
   - source contracts
   - evaluation
   - fault drill
5. runtime start
6. full readiness
7. web install
8. web unit tests
9. web typecheck
10. web lint
11. browser install
12. real lifecycle E2E
13. **Pipeline Control Room E2E**
    - 정정 시나리오
    - Delta before/after
    - hard eligibility 변화
    - 장애/재시도 설명
    - 평가 화면
    - 390px mobile overflow
    - reduced-motion replay
14. pause background jobs
15. Redis/ARQ queue scale
16. PostgreSQL query plans
17. HTTP load
18. resume background jobs

이후 release-contract에는 다음 gate가 추가됐다.

19. Korean OCR regression
    - Tesseract 5.5.0
    - `kor+eng`
    - clean / blurred / low-resolution 합성 이미지 3장
    - 구조화 필드 18/18
20. paginated backfill scale
    - production `poll_source_pages()` 경로
    - 2,000건 / page size 100 / 총 20페이지
    - 첫 5페이지 이후 저장 cursor에서 15페이지 재개
    - IngestRun 20/20 성공, normalized 2,000/2,000

Pipeline E2E는 request interception이나 fake HTTP response를 사용하지 않고 검증 Compose의 실제 web/API에 접근한다.

## Public engineering evidence

성능 카드는 CI 실행마다 변하는 timing 값을 실시간 마케팅 수치처럼 보여주지 않는다.

기존 CPU·queue·HTTP·query-plan 숫자는 GitHub Actions run **35565162198**을 reference measurement로 고정했다. paginated backfill 수치는 run **35810323430**에서 추가 측정했고, 기존 timing을 새 실행값으로 갈아끼우지 않았다.

- `artifacts/performance/*.json`
- `apps/api/app/evaluation/results/engineering.json`
- public static demo

Backend/API checkout에서는 원본 artifact가 우선이며, Docker image에서 repo-level artifact가 없을 때 packaged snapshot을 사용한다. 테스트에서 packaged snapshot과 committed public performance artifact, static demo의 핵심 값이 서로 일치하는지 확인한다.

reference measurement의 상세 범위는 `docs/performance.md`에 있다.

## Browser evidence

검증 run은 실제 브라우저 캡처도 남긴다.

- landing
- opportunity lifecycle
- Delta
- notifications
- admin/operator console
- evaluation
- Pipeline Control Room amendment replay

README에 사용되는 screenshot은 mockup이 아니라 이 검증 run의 실제 브라우저 출력이다.

## 무엇을 증명하지 않는가

이 release gate는 격리 컨테이너 환경에서 현재 저장소의 실행 계약을 검증한다. 다음을 자동으로 증명하지 않는다.

- 실제 나라장터 서비스키로 모든 운영 데이터를 수집했다는 주장
- 실제 사전규격·낙찰·계약 API 전체 연동
- 실제 한국어 OCR 일반화 성능
- hosted LLM 정확도·토큰·비용
- 실제 고객 트래픽이나 운영 SaaS capacity
- 클라우드 무중단 운영 안정성
- 실제 결제/구독
- 실제 외부 notification delivery

실제 공개 API smoke와 public Render static demo는 release gate와 별도 증거로 관리한다.

공식 원본 스캔 2건의 [로컬 워커 OCR 진단](public-scan-ocr.md)도 별도 증거다.
첫 2회 메모리 실패와 수정 후 2회 실측을 각각 보존한다. CI의 고해상도 합성 PDF 회귀는
페이지 간 리소스 해제를 검증하며, 공개 원본의 재다운로드나 정확도 재측정을 대신하지 않는다.

[PP-OCRv5 후보 평가](ocr-candidate-evaluation.md)는 별도 로컬 가상환경의 첫 페이지
실험이다. 두 번 모두 6건 중 5건 완료·1건 실패였고, 실패가 있는 그룹은 점수를
`null`로 남긴다. CI는 후보 응답 검증, 실패·분모 보존, 가상환경 경로 처리를
검증한다. 선택 의존성·모델·공개 PDF를 설치하거나 실문서 인식을 재실행하지 않으므로
초록색 CI를 후보 인식 성능 또는 운영 적용 승인으로 해석하지 않는다.

## Node standalone 배포의 정적 파일 검증

2026-09-24 `60d4772` 공개 배포는 Render에서 live였지만, HTML에 포함된
`/_next/static/chunks/19mx3mg6lkumu.js`가 HTTP 404여서 세션 준비 화면에 머물렀다.
Dockerfile은 `.next/static`과 `public`을 복사하지만 기존 Node build/start는 이 단계를
빠뜨렸다. 따라서 컨테이너 gate 통과와 Render live만으로 브라우저 준비를 판단할 수 없다.

`npm run build`의 `postbuild`는 생성된 `.next/standalone`에 static/public을 복사한다.
`npm run test:standalone`은 그 `server.js`를 직접 시작하고 `/about`의 실제 HTML에서
찾은 모든 JS/CSS 파일이 HTTP 200·올바른 content-type·비어 있지 않은 내용인지 확인한다.
수정 전 빌드에서는 CSS 404를 재현했고 복사 후 같은 검사에서 10개 JS/CSS가 통과했다.
이 검사는 frontend CI의 production build 다음에 실행된다. 파일 복사 unit test,
컨테이너 브라우저 E2E, 배포 후 실제 공개 브라우저 확인은 각각 별도 검증이다.

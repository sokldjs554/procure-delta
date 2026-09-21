# Verification

## Current release gate

2026-09-21에 `python scripts/verify_containers.py --scale-records 1000`으로 원본 `.env`, 기존 DB/Redis 볼륨, 기존 서비스와 분리된 Compose 프로젝트에서 전체 검증을 실행했다.

현재 저장된 `artifacts/verification/release-gate.json`은 GitHub Actions run **35568528869**의 성공 결과다.

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

Pipeline E2E는 request interception이나 fake HTTP response를 사용하지 않고 검증 Compose의 실제 web/API에 접근한다.

## Public engineering evidence

성능 카드는 CI 실행마다 변하는 timing 값을 실시간 마케팅 수치처럼 보여주지 않는다.

공개 성능 숫자는 GitHub Actions run **35565162198**을 reference measurement로 고정했고 다음 위치에 동기화했다.

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

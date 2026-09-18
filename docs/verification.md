# Verification

## Release gate

2026-09-18에 `python scripts/verify_containers.py`를 사용해 원본 `.env`, 기존 DB/Redis 볼륨, 기존 Git 저장소와 분리된 Compose 프로젝트에서 검증했습니다.

`artifacts/verification/release-gate.json`의 최종 상태:

- `passed: true`
- `status: passed`
- scope: `isolated_container_integration`

통과한 gate:

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
7. web install / test / typecheck / lint
8. browser install
9. real lifecycle E2E
10. pause background jobs
11. queue scale
12. query plans
13. HTTP load
14. resume background jobs

Readiness snapshot의 database, schema, redis, worker, scheduler, storage, extraction_config가 모두 `true`였습니다.

## 무엇을 증명하지 않는가

이 release gate는 로컬 격리 컨테이너 환경에서 현재 저장소의 실행 계약을 검증합니다. 다음을 자동으로 증명하지 않습니다.

- 실제 나라장터 서비스키로 모든 운영 데이터를 수집했다는 주장
- 실제 사전규격·낙찰·계약 API 전체 연동
- 실제 한국어 OCR 일반화 성능
- 외부 LLM 정확도·비용
- 클라우드 운영 안정성이나 무중단 배포
- 실제 고객 데이터/트래픽 성능

실제 공개 API smoke와 클라우드 배포는 별도 증거로 관리합니다.

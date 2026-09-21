# 검증과 제품의 한계

## 검증된 범위

2026-09-21 격리 Docker reference release gate에서 Compose, 이미지 빌드, PostgreSQL/Redis, backend lint/type/tests, DB isolation regression, source contracts, evaluation, fault drill, runtime readiness, frontend 검사, 브라우저 lifecycle E2E, queue scale, query plan, HTTP load, worker/scheduler pause-resume가 모두 통과했다.

원본 결과는 `artifacts/verification/release-gate.json`, 검증 계약은 `docs/verification.md`에 있다.

## 데이터와 AI

전체 5단계 lifecycle 데모는 합성이다. 실제 adapter는 용역 입찰공고/관측 변경까지만 구현되어 있다.
공식 참가자격을 판단하는 법률·계약 자문 서비스가 아니며 최종 원문과 담당자 확인이 필요하다.
현재 라벨 추출+문자 기반 검증은 자유형 한국어 문서의 의미 이해를 충분히 평가하지 못한다.
평가셋은 작은 저자 작성 회귀 사례이며 실제 기업 추천 품질이나 수주 결과 검증이 아니다.
기본 OCR fixture는 분기·복구 테스트용 합성 fixture다. 별도 Tesseract 영어 3장 결과는 한국어 OCR 성능 근거가 아니다.
HWP 내용 추출은 구현하지 않았다.

## 실제 공개 데이터

나라장터 용역 입찰공고 adapter와 실제 호출 smoke 도구는 구현되어 있지만, 저장소에는 서비스키를 포함하지 않는다.
실제 서비스키 기반 호출 성공은 로컬에서 별도 실행하고 증거를 남겨야 한다.
실제 사전규격·낙찰·계약 수집기는 아직 연결하지 않았다.

## 서비스와 운영

실제 결제·구독·크레딧 차감, 운영용 인증, 기관별 강한 격리, 외부 Sentry/OpenTelemetry 연동, full backend 클라우드 운영을 완료했다고 주장하지 않는다. 공개 Render 데모는 client-only 합성 snapshot이다.
CPU 5만 건 루프는 DB/Redis/HTTP 처리량이 아니며 실제 공개 문서 5만 건을 수집했다는 의미도 아니다.
query-plan gate는 현재 쿼리의 실행 계획을 확인하는 검증 도구이며, 별도 인덱스 변경 효과를 과장하지 않는다.
외부 알림은 기본 비활성이고, local receipt 경로가 기본이다.

## 완료 기준

로컬 구현/통합 검증은 `artifacts/verification/release-gate.json`의 `passed=true`로 확인한다.
실데이터 smoke, 원격 CI, 공개 클라우드 배포는 각각 별도의 증거가 있어야 완료로 표시한다.

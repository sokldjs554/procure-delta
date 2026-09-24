# 검증과 제품의 한계

## 검증된 범위

격리 Docker release gate에서 Compose, 이미지 빌드, PostgreSQL/Redis, backend lint/type/tests, DB isolation regression, source contracts, evaluation, fault drill, runtime readiness, frontend 검사, 브라우저 lifecycle E2E, queue scale, query plan, HTTP load, worker/scheduler pause-resume가 통과했다. 저장된 reference snapshot의 시점과 이후 별도 검증은 README에서 구분한다.

원본 결과는 `artifacts/verification/release-gate.json`, 검증 계약은 `docs/verification.md`에 있다.

## 데이터와 AI

전체 5단계 lifecycle 데모는 합성이다. 실제 adapter는 용역 입찰공고/관측 변경까지만 구현되어 있다.
공식 참가자격을 판단하는 법률·계약 자문 서비스가 아니며 최종 원문과 담당자 확인이 필요하다.
현재 라벨 추출+문자 기반 검증은 자유형 한국어 문서의 의미 이해를 충분히 평가하지 못한다.
평가셋은 작은 저자 작성 회귀 사례이며 실제 기업 추천 품질이나 수주 결과 검증이 아니다.
[실제 Claude 평가](hosted-evaluation-success.md)는 같은 합성 10건의 v2·v3 각 1회 실행이다.
단독 추출은 18/30에서 30/30으로 바뀌었지만 토큰과 p95 지연시간도 늘었다. 같은 버전의
반복성과 인과 효과는 확인하지 않았다. gated의 30/30은 모두 로컬 규칙 결과다. 같은 셋의
순수 규칙도 30/30이므로 LLM 추가 효용은 미증명이다. 비용은 provider가 보고하지 않아 미측정이다.
로컬 기본 OCR fixture는 분기·복구 테스트용 합성 fixture다. 실제 워커용 [Tesseract 어댑터](runtime-ocr.md)는 별도 프로세스·실행 제한·저장을 제공하지만 실문서 정확도나 클라우드 운영을 증명하지 않는다. 영어 합성 17/18, 한국어 합성 18/18은 작은 회귀셋의 결과다.
[실제 공고 PDF 지면 렌더 진단](public-document-ocr.md)에서는 지정 문자열 11/24,
검증을 통과한 title/buyer 필드 0/12로 품질 미달이었다. 자연 스캔의 일반화 성능은 아직 검증하지 않았다.
[항목 해석 v2](korean-form-grounding.md)는 별도 2건의 원문 텍스트를 0/6 → 3/6으로
개선했지만, 해당 문서의 이미지 OCR은 0/18이다. 이 개발 진단은 독립 holdout이 아니다.
[공식 원본 스캔 진단](public-scan-ocr.md)은 다른 2건의 8쪽을 워커 어댑터로 처리했다.
페이지 간 메모리 문제를 수정한 뒤 2회 모두 처리됐지만, 첫 페이지 anchor는 4/8,
검증 통과 필드는 0/6이다. 같은 기관·유사 서식의 개발 진단이며 전체 PDF 추출 승인,
DB 저장, G2B 첨부 수집이나 클라우드 처리량의 증거가 아니다.
HWP 내용 추출은 구현하지 않았다.

## 실제 공개 데이터

나라장터 용역 입찰공고 adapter와 실제 호출 smoke 도구는 구현되어 있지만, 저장소에는 서비스키를 포함하지 않는다.
실제 서비스키 기반 호출 성공은 로컬에서 별도 실행하고 증거를 남겨야 한다.
실제 사전규격·낙찰·계약 수집기는 아직 연결하지 않았다.

## 서비스와 운영

크레딧 grant/reserve/commit/refund와 불변 ledger는 구현·CI 검증했다. [hosted 워커 연결](extraction-credits.md)은 운영자가 지정한 공유 파이프라인 예산에 한정하며, 실제 provider 비용·고객별 과금·OCR 과금·외부 결제사 청구·유료 구독 운영 증거는 아니다.
운영용 인증, 기관별 강한 격리, 실제 DSN으로 외부 Sentry event 수신, full backend 클라우드 운영을 완료했다고 주장하지 않는다.
CPU 5만 건 루프는 DB/Redis/HTTP 처리량이 아니며 실제 공개 문서 5만 건을 수집했다는 의미도 아니다.
query-plan gate는 현재 쿼리의 실행 계획을 확인하는 검증 도구이며, 별도 인덱스 변경 효과를 과장하지 않는다.
외부 알림은 기본 비활성이고, local receipt 경로가 기본이다. SMTP는 loopback TCP 전송까지 검증했으며 public provider 실발송 증거는 없다.

## 완료 기준

고정 reference의 통합 검증은 `artifacts/verification/release-gate.json`의 `passed=true`로 확인하며, 최신 변경의 통과 여부는 해당 commit의 CI에서 별도 확인한다.
실데이터 smoke, 원격 CI, 공개 클라우드 배포는 각각 별도의 증거가 있어야 완료로 표시한다.

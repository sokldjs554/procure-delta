# Claude v3 외부 실측: 정확도 변화와 비용·지연 한계

2026-09-24의 [전체 평가 36016974477](https://github.com/sokldjs554/procure-delta/actions/runs/36016974477)은
최신 main에서 실제 외부 호출과 측정 validator를 모두 통과했다. `diagnostics_only=false`이며
연결 probe는 건너뛰었다. 같은 작성자 제작 합성 10건에서 단독 Claude 경로의 검증 통과
필드가 v2 **18/30 → v3 30/30**, 정상 문서 거절이 **2건 → 0건**으로 바뀌었다.

각 요청 버전의 실행은 1회다. 프롬프트 보완 후의 관측 차이이며 반복 실험이나 인과 효과,
실제 조달 문서 일반화 성능을 증명하지 않는다. [v2 보고서와 원본](hosted-evaluation-v2.md)을
별도로 보존했다. 새 실행을 과거 실행의 재검증이나 같은 버전의 반복으로 세지 않는다.

## 원본과 출처

- 측정 commit: `ae63b0474800067ebc2c3432c5ade0b7f754a7cc` (clean checkout)
- 측정 시각: `2026-09-24T15:02:01.497536+00:00`
- 모델: `claude-haiku-4-5-20251001`, provider: `anthropic`
- endpoint: `https://api.anthropic.com/v1/chat/completions`
- 요청 버전: `chat-prompt-json-v3-a522d812a6f15e65`; 출력 한도 4,096 tokens
- 원본 artifact ID: `10814957009`
- [변경하지 않은 hosted.json](../artifacts/evaluation/hosted.json)
- [workflow 검증 요약](../artifacts/evaluation/hosted-summary.json)

| SHA-256 대상 | 값 |
| --- | --- |
| 다운로드 ZIP | `d894bddd58d2821c6ee71c671a7a671ab9b9f5e90b3cc33f1a39579006462d48` |
| hosted.json | `cbb0980d7947151ac1a15a1530d6e14d530c21c3b2937a24efbbf6d5a0b7d7fc` |
| frozen dataset | `60915644e3d3d36a7aca72a410d40a3075eb472809ed014e50c77f8ecab78116` |
| 측정 당시 Python + scripts | `c22db758569713764e07828700caf93906aa560dfd0001365f7d5a16ad4f60f3` |

ZIP digest는 GitHub와 일치했고, dataset/source hash는 측정 commit의 실제 파일과 대조했다.
사례별 토큰·호출 수·정답 필드·거절 수·p50/p95를 재계산하고 workflow 요약과 대조했다.
공개 원본에는 합성 정답과 검증된 필드, 제한된 진단만 있으며 provider 응답 원문·키·header는 없다.

## 같은 회귀셋의 두 요청 버전

정상 5건의 정답 필드 30개와 의도적 거절 5건이다. 필드 정확도는 근거 검증까지 통과한
정답만 센다. 정상 문서의 거절은 해당 필드 전체를 오답 처리한다.

| 항목 | v2 전체 호출 | v3 전체 호출 | v2 규칙 우선 | v3 규칙 우선 |
| --- | ---: | ---: | ---: | ---: |
| 검증 통과 정답 필드 | 18/30 | **30/30** | 30/30 | 30/30 |
| 정상 문서 exact match | 3/5 | **5/5** | 5/5 | 5/5 |
| 정상 문서 검증 거절 | 2/5 | **0/5** | 0/5 | 0/5 |
| 거절 대상 차단 | 5/5 | 5/5 | 5/5 | 5/5 |
| 논리 provider 호출 | 10 | 10 | 5 | 5 |
| 입력 토큰 | 10,058 | 18,788 | 4,975 | 9,340 |
| 출력 토큰 | 5,596 | 3,555 | 2,342 | 809 |
| 전체 토큰 | 15,654 | **22,343** | 7,317 | **10,149** |
| 문서별 전체 경로 p50 | 2,612.01 ms | 2,545.85 ms | 1,050.39 ms | 607.09 ms |
| 문서별 전체 경로 p95 | 4,396.15 ms | **10,864.45 ms** | 3,547.70 ms | 3,058.34 ms |
| 실행 예외 | 0 | 0 | 0 | 0 |
| provider 보고 비용 | 미측정 | 미측정 | 미측정 | 미측정 |

v3 안에서 전체 호출 대비 규칙 우선 경로는 논리 호출 **50%**, 전체 토큰 **54.576377%** 감소다.
이는 v2 대비 토큰 감소가 아니다. v3의 전체 토큰은 두 경로 모두 v2보다 많고 단독 경로
p95도 증가했다. 프롬프트가 길어진 영향과 실행 변동을 분리한 실험은 하지 않았다.
각 p95의 표본은 10개뿐이며 규칙 우선 경로에는 로컬 처리 5건이 포함된다.
provider API 자체의 지연 개선이나 안정된 운영 p95로 해석하지 않는다.
비용·비용 절감률은 null이다. 토큰 감소를 provider 청구 비용 감소로 바꾸지 않는다.

## 품질과 거절 해석

- 단독 경로에서 이전에 거절됐던 `korean-labels`와 `qualified-omission`이 이번에는
  각각 9/9, 3/3 정답 필드로 수용됐다. 다른 정상 3건도 모두 정답이었다.
- 15개 외부 논리 호출은 모두 HTTP 200과 사용량 보고를 기록했다. 단독 경로의 거절 5건과
  규칙 우선 경로의 거절 4건은 `invalid_json`이었다. 차단 5/5가 모델의 의미적 거절
  능력이나 올바른 구조화 거절 프로토콜을 증명하지는 않는다.
- 규칙 우선의 `unstructured-prose`는 JSON/schema를 통과했지만 근거 검증에서 거절됐다.
  title/buyer/type/amount/currency에 `evidence_not_on_page`와 `unsupported_value`가 기록됐다.
  요청 보완 후에도 근거 검증기를 생략할 수 없다. 원래 응답은 저장되지 않았다.
- 규칙 우선의 정상 5건 **30/30은 전부 로컬 규칙 결과**이며 외부 모델의 추가 수용은 0건이다.
  같은 실행의 순수 deterministic도 30/30·외부 호출 0회다. 이 셋에서는 LLM의 추가 효용이나
  규칙 우선 LLM이 순수 규칙보다 효율적이라는 주장을 뒷받침하지 못한다.
- 다음 품질 평가는 규칙이 놓치는 실제 문서와 독립 정답, 같은 요청 버전의 반복이 필요하다.
  자연 스캔 OCR, 실제 provider 비용, 크레딧 워커의 외부 운영은 이번 실험 범위가 아니다.

## 공개 반영과 재현

영어·한국어 OCR과 로컬 평가의 기존 artifact는 유지했다. API는 최신 hosted 두 경로만
합치며, 정적 데모는 같은 허용 목록 projection을 사용한다. 개별 예측·응답 진단 원문은
공개 API/화면으로 보내지 않는다. v2 원본은 `artifacts/evaluation/history/claude-35949777404/`에 있다.

```sh
python scripts/validate_hosted_eval.py artifacts/evaluation/hosted.json
python scripts/publish_evaluation_snapshot.py
```

위 명령은 저장 결과 검증과 화면 데이터 생성이며 외부 호출을 하지 않는다.
추가 외부 평가에는 별도의 수동 workflow 실행이 필요하다.

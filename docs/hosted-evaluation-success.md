# Claude 외부 실측: 측정 완료와 품질 한계

2026-09-24의 [전체 평가 실행 35949777404](https://github.com/sokldjs554/procure-delta/actions/runs/35949777404)은
외부 요청과 측정 validator를 모두 통과했다. `diagnostics_only=false`이며 연결 확인용 probe는 건너뛰었다.
이는 **작성자 제작 합성 10건을 1회 평가한 결과**다. 실제 조달 문서 일반화나 운영 품질 합격을 뜻하지 않는다.

## 원본과 출처

- 측정 commit: `fe6b8357b575a2b6b1c41e72e4cb2997533e77ad` (clean checkout)
- 측정 시각: `2026-09-24T03:03:51.325613+00:00`
- 모델: `claude-haiku-4-5-20251001`, provider: `anthropic`
- endpoint: `https://api.anthropic.com/v1/chat/completions`
- 어댑터: `chat-prompt-json-v2-b8c1273e927806c1`
- 원본 artifact ID: `10787932232`
- [변경하지 않은 hosted.json](../artifacts/evaluation/hosted.json)
- [workflow에서 생성한 검증 요약](../artifacts/evaluation/hosted-summary.json)

| SHA-256 대상 | 값 |
| --- | --- |
| 다운로드 ZIP | `75b998263d8d0b85031c82afa7fe2e4edc479da49d4d5d458d3aacc8ef3ccc0c` |
| hosted.json | `bde21efd01262df4d2f5c2920370a091ba904d376c36c7087300fcc0bec9d2c5` |
| frozen dataset | `60915644e3d3d36a7aca72a410d40a3075eb472809ed014e50c77f8ecab78116` |
| 측정 당시 Python + scripts | `8757a392b2d09fb0bca74812d75669df48cbbdf1a46d4ec82aac2b7797a1b861` |

ZIP은 GitHub artifact digest와 대조했고, JSON의 source/dataset hash는 해당 commit의 실제 파일과 대조했다.
사례별 토큰 합계·정답 필드·호출 수·절감률을 재계산하고 workflow 요약과 일치하는지 확인했다.
원본에는 합성 정답과 검증된 필드, 고정 진단만 있으며 provider 응답 원문·키·header는 없다.

## 같은 10건의 경로 비교

정상 5건의 정답 필드 30개와 의도적 거절 5건이다. 필드 정확도는 검증까지 통과한 정답 필드를 센다.
정상 문서가 거절되면 그 문서의 필드는 오답이며, 원래 모델의 모든 필드가 틀렸다는 뜻은 아니다.

| 항목 | 전체 Claude 호출 | 규칙 검증 → 필요 시 Claude |
| --- | ---: | ---: |
| 검증 통과 정답 필드 | 18/30 (60%) | 30/30 (100%) |
| 정상 문서 exact match | 3/5 | 5/5 |
| 정상 문서 검증 거절 | 2/5 | 0/5 |
| 거절 대상 차단 | 5/5 | 5/5 |
| 논리 provider 호출 | 10 | 5 |
| 입력 토큰 | 10,058 | 4,975 |
| 출력 토큰 | 5,596 | 2,342 |
| 전체 토큰 | 15,654 | 7,317 |
| 문서별 전체 경로 p50 | 2,612.01 ms | 1,050.39 ms |
| 문서별 전체 경로 p95 | 4,396.15 ms | 3,547.70 ms |
| 실행 예외 | 0 | 0 |
| provider 보고 비용 | 미측정 | 미측정 |

전체 호출 대비 논리 호출은 **50%**, 전체 토큰은 **53.257953%** 감소했다. 비용 절감률은 null이다.
입력·출력 단가와 청구 금액을 확인하지 않았으므로 토큰 감소를 비용 절감률로 바꾸지 않는다.
지연시간은 각 경로의 10개 문서를 대상으로 하며 gated에는 빠른 로컬 처리 5건이 포함된다.
이를 Claude API 자체의 p50/p95 개선으로 해석하지 않는다. 반복 외부 실험이나 신뢰구간은 없다.

## 남은 품질 문제

- 전체 호출에서 `korean-labels`, `qualified-omission`은 JSON·스키마를 통과했지만 근거 검증에서 거절됐다.
  현재 기록은 거절 단계를 알려 주며, 원래 응답의 어느 값·증거가 문제였는지까지 복원하지는 못한다.
- 15개 호출의 진단은 모두 HTTP 200과 사용량 보고를 기록했다. 11개는 단일 JSON fence를 읽었고,
  나머지 4개는 plain content의 JSON 파싱에서 거절됐다. 이번 실행의 관측을 이전 실패 응답에 소급하지 않는다.
- 모든 거절 대상이 차단됐지만, 일부는 JSON 파싱 실패 때문이다. 모델이 문제 문서를 의미적으로 모두 이해했다고 주장하지 않는다.
- gated 정상 5건의 **30/30은 로컬 규칙 결과**다. Claude는 거절 후보 5건에 호출됐고 정상 문서를 추가로 복구하지 못했다.
  같은 실행의 순수 deterministic도 30/30, provider 호출 0회다. 따라서 이 회귀셋에서는 LLM의 증분 효용이 증명되지 않았으며,
  gated가 순수 규칙보다 효율적이라고 주장하지 않는다. 추가 효용 평가는 규칙이 놓치는 실제 문서와 독립 정답이 필요하다.

## 공개 결과 반영과 재현

`local.json`의 영어 OCR과 `korean-ocr.json`은 별도 실험으로 그대로 유지한다.
API는 검증한 `results/hosted.json`의 두 hosted 경로만 합치고, 데이터 SHA가 다르거나 사용량이 누락되면 게시하지 않는다.
정적 데모는 같은 공개 projection에서 생성하며 원문·개별 예측은 내려보내지 않는다.

```sh
python scripts/validate_hosted_eval.py artifacts/evaluation/hosted.json
python scripts/publish_evaluation_snapshot.py
```

위 명령은 저장 결과 검증·화면 데이터 생성이며 외부 모델을 다시 호출하지 않는다.
새 외부 측정은 수동 workflow opt-in이 필요하다. 이전 실패 원본은 [실패 기록](hosted-evaluation-attempt.md)에 그대로 남아 있다.

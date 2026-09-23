# 첫 Claude 평가 시도와 실패 처리 수정

## 보존한 실행

- 시각: 2026-09-23 17:02:20 UTC (한국 2026-09-24 02:02:20)
- [Actions run 35892878368](https://github.com/sokldjs554/procure-delta/actions/runs/35892878368)
- source commit: `bbe619746f5c2fae0c465bdcb844ec171c480dfb`
- provider/model: `anthropic` / `claude-haiku-4-5-20251001`
- endpoint: `https://api.anthropic.com/v1/chat/completions`
- completion token limit: 4,096
- frozen dataset SHA-256: `60915644e3d3d36a7aca72a410d40a3075eb472809ed014e50c77f8ecab78116`
- [변경하지 않은 hosted.json 원본](../artifacts/evaluation/failed/claude-35892878368.json)
- JSON SHA-256: `97d8fa0fef078bd28c00b46e1aca9358335db56098f7f2567f56400d032088a5`
- Actions artifact ID: `10765856993`
- 원본 ZIP SHA-256: `121c4182fa430177040f69d66d343fa0d6661791472032201bf81d032e967d73`

ZIP 다운로드 후 digest를 대조하고 원본 JSON을 그대로 보존했다. 이 JSON의
`status: measured`는 수정 전 runner가 사용한 표시이며 유효한 실측 판정이 아니다.

| 확인 항목 | 관측 |
| --- | --- |
| hosted_all | 논리 호출 10회, `HTTPStatusError` 10건 |
| hosted_gated | 논리 호출 5회, `HTTPStatusError` 5건 |
| provider prompt/completion tokens | 두 경로 모두 null |
| provider 비용 | null |
| 검증 프로그램 | `HostedEvaluationError: hosted_all prompt tokens are not measured` |
| Actions 표시 | success — 검증 실패가 pipeline에서 가려짐 |

실패 요청의 왕복 시간이 모델의 성공 응답 지연 시간을 증명하지 않는다. gated 경로의
정상 필드 30/30은 로컬 deterministic 경로가 처리한 결과다. 이를 Claude 정확도나
검증된 호출·토큰·비용 절감으로 발표하지 않는다. 원본에는 HTTP 상태 코드나 provider
오류 내용이 없으므로 인증, 권한, 청구, 요청 형식 중 원인을 확정할 수 없다.

## 원인과 수정

검증 명령이 `python ... | tee ...`인데 shell을 명시하지 않아 `bash -e`로 실행됐다.
`tee`가 0으로 종료하면서 앞쪽 Python 오류가 Actions 실패로 전파되지 않았다.
[GitHub의 shell 동작](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepsshell)에
따라 해당 단계에 `shell: bash`를 명시해 `-o pipefail`을 적용한다.

실제 YAML의 검증 명령을 subprocess로 실행하는 회귀 테스트가 수정 전 exit 0,
수정 후 의도한 실패 코드 23을 확인한다. 성공 코드 0도 유지되는지 확인한다.
HTTP 요청 실패는 `failed`로 기록하고, 허용 목록의 상태/오류 분류와 고정 진단 hint만
남긴다. 응답 원문은 기록하지 않는다. CLI 공개 반영도 동일한 validator로 차단한다.

## 다음 확인

수정본 main에서 새 **Run workflow**로 같은 입력을 실행한다. 과거 run의 Re-run은
과거 commit을 다시 사용하므로 이 수정이 적용되지 않는다. 새 실행의 `Run paid/network
hosted evaluation` 로그와 artifact에서 HTTP 상태/진단을 확인한 뒤 원인을 해결한다.
키를 변경하거나 다시 등록해야 한다고 현재 증거만으로 단정하지 않는다.

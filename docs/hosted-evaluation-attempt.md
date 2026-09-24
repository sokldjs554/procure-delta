# Claude 평가 실행과 실패 처리 수정

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

## Claude 연결 진단과 요청 수정

- [Actions run 35938774940](https://github.com/sokldjs554/procure-delta/actions/runs/35938774940)
- 실행: 2026-09-24 00:31:06 UTC, `diagnostics_only=true`
- source commit: `7d60d8ddb425da4c02e67087d7ec4d3623169bee`
- 위와 같은 provider/model/endpoint 및 frozen dataset 사용
- [변경하지 않은 진단 JSON](../artifacts/evaluation/failed/claude-probe-35938774940.json)
- JSON SHA-256: `ace45359379b09f9275279a06f846900be14dcc8b84fbd9e05daeaf49d892c69`
- Actions artifact ID: `10784141710`
- 원본 ZIP SHA-256: `f4d751da1733c73703b9925ee96242381498357776011c7f0f9600b7e15335cd`

| 같은 Secret을 사용한 요청 | 관측 |
| --- | --- |
| native Messages 최소 요청 | HTTP 200, input 11 / output 5 tokens |
| OpenAI-compatible 최소 요청 | HTTP 200, prompt 11 / completion 5 tokens |
| 기존 extractor의 frozen 첫 사례 | HTTP 400, `invalid_request_error` |
| 허용 목록에서 기록한 오류 용어 | `input`, `response_format`, `type` |

이 실행에서 인증과 최소 모델 호출은 성공했다. 추출 요청에만 있던 JSON mode 옵션
`response_format: {"type":"json_object"}`이 실패 원인으로 지목된다. 원문을 보존하지
않았으므로 오류 용어만으로 provider 내부 검증 내용을 단정하지 않는다.
[공식 호환 API 문서](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk)는
해당 필드를 무시한다고 설명하지만 실제 실행은 거부됐으므로 이 옵션에 의존하지 않는다.

수정은 공식 Claude HTTPS Chat Completions endpoint에서 해당 필드만 생략한다.
프롬프트, 모델, 토큰 한도와 JSON·스키마·근거 검증은 유지한다. `provider` 이름을
바꿔도 같은 공식 endpoint에는 동일한 처리를 적용하며, 다른 endpoint는 기존 JSON
mode를 유지한다. 요청 변경을 반영해 extractor version을 `chat-prompt-json-v1`로
구분하여 이전 캐시·idempotency identity를 재사용하지 않는다.

회귀 테스트에서는 JSON mode 필드를 받으면 HTTP 400을 반환하는 transport로 실패를
재현한 뒤 필드 생략으로 성공하는지 검사한다. 이 테스트는 실제 provider 재호출이
아니다. 위 진단 역시 `quality_evaluated=false`이므로 품질·절감률의 실측 근거가 아니다.

## 응답 거절과 사용량 누락

- [Actions run 35940406108](https://github.com/sokldjs554/procure-delta/actions/runs/35940406108)
- 실행: 2026-09-24 00:52:45 UTC, `diagnostics_only=false`
- source commit: `3d9f31523f125fded6cd9904326a608b14bc94f8`
- [변경하지 않은 평가 JSON](../artifacts/evaluation/failed/claude-35940406108.json)
- JSON SHA-256: `ba625def715290c3d21820d692c9651adc7b58f556b7d146d39483d928dc28a1`
- Actions artifact ID: `10784143912`
- 원본 ZIP SHA-256: `9aa95ee662ef6697402aedf1a935d82780841c5a335a7628f0073b10bf9dcc25`

| 항목 | 관측 |
| --- | --- |
| HTTP/실행 예외 | 두 경로 모두 0건 |
| hosted_all | 10회, schema failure 10건, 검증 통과 필드 0/30 |
| hosted_gated | hosted 5회, 정상 필드 30/30은 로컬 deterministic 결과 |
| prompt/completion tokens | 두 경로 모두 null |
| 최종 validator | `hosted_all prompt tokens are not measured`로 실패 |

HTTP 오류가 없어졌다고 추출 품질이나 완전한 측정이 확보된 것은 아니다. 당시 artifact는
모델 응답과 파싱/거절 진단을 기록하지 않아 코드 블록, 잘린 답변, 잘못된 envelope 중
무엇이 실제 원인이었는지 확정할 수 없다. 누락된 토큰을 사후 추정해 원본에 채우지 않는다.

코드 재현에서는 사용량이 들어 있는 응답도 JSON 파싱 실패·refusal·불완전한 종료·잘못된
envelope 경로에서 `ExtractionResult`를 조기 반환하며 사용량을 버리는 결함을 확인했다.
이 결함은 응답의 품질 판정과 provider 사용량 판정을 분리해 수정한다. 유효한 정수 토큰만
보존하고 bool/문자열/음수/누락은 알 수 없는 값으로 남긴다. 잘못된 비용 값은 토큰이나
유효한 추출 값을 지우지 않는다. 비용을 반환하지 않는 provider의 비용은 계속 null이다.

응답 전체가 하나의 JSON 또는 단일 JSON 코드 블록이면 같은 스키마·근거 검증을 거친다.
코드 블록 내부 값은 바꾸지 않으며 설명문, 여러 블록, 잘린 JSON, 비유한 수, 근거 없는
값은 수용하지 않는다. 이는 제한된 응답 형식 지원이며 **이번 실제 응답이 코드 블록이었다는
주장이 아니다**. 파싱·사용량 처리 변경을 반영해 extractor version은 `chat-json-v2` /
`chat-prompt-json-v2`로 올려 이전 캐시를 재사용하지 않는다.

새 평가 row와 CLI는 다음의 안전한 진단만 추가한다.

- 거절 단계: execution / response / schema / grounding
- 실제 HTTP 상태, 고정된 파싱·종료·코드 블록·사용량 상태
- 공개 스키마의 오류 필드 이름. 임의 필드 이름은 `unknown`으로 표시
- 사례별 provider prompt/completion tokens. 불명확한 값을 0으로 채우지 않음

임의 응답 본문·오류 문장·refusal 내용·header·API key는 이 진단에 포함하지 않는다.
validator가 통과해도 품질 합격을 뜻하지 않는다. 사용량이 측정된 거절도 비용을 소비한
관측이므로 별도 집계하고, 필드 정확도·검증 통과 수·거절 단계를 함께 읽는다.
이전 validator의 미측정 토큰 차단 규칙은 유지한다.

## 다음 확인

수정본 main에서 새 **Run workflow**로 같은 입력을 지정하고 `diagnostics_only`를
끄고 전체 평가를 실행한다. 과거 run의 Re-run은 과거 commit을 사용하므로 새 수정이
적용되지 않는다. 실제 품질 평가·token 집계·validator 통과를 확인한 뒤에만 결과를
발표한다. 이후 [실제 평가 35949777404](hosted-evaluation-success.md)는 측정 검증을
통과했다. 이 문서의 과거 실패 기록은 변경하지 않으며 새 측정과 구분한다.

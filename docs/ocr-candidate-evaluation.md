# 한국어 OCR 후보 비교 실험

현재 워커의 Tesseract는 원본 스캔 두 건을 처리하지만, 첫 페이지 anchor는
4/8이고 신뢰 필드는 0/6이다. 글자 순서 재구성만으로는 이 결과가 개선되지
않았고, `tessdata_best` 모델은 두 전체 PDF 모두 기존 40초 제한을 넘겼다.
따라서 탐지와 한국어 인식을 분리한 PP-OCRv5를 **오프라인 후보**로 평가한다.
생산 워커·배포 이미지·기본 OCR 설정에는 추가하지 않는다.

## 비교 범위와 기준

- `public_scan_manifest.json`: 원본 이미지 PDF 2건의 지정된 첫 페이지.
- `public_ocr_manifest.json`: 다른 기관의 텍스트 PDF 2건을 이미지로 변환한 대조군.
- `public_ocr_forms_manifest.json`: 한국어 라벨 공고와 표지/표 서식 PDF 2건의 대조군.
- 기존 문서의 정답·선택 기록·SHA-256을 그대로 사용한다. 이미 관찰한 작은
  편의 표본이며 독립적인 신규 문서나 학습에 사용하지 않은 평가셋이 아니다.
- 페이지 전체를 RGB 300 dpi로 렌더링한다. 임의 크롭·문자 교정·라벨별 처리를
  하지 않는다. RapidOCR의 버전 고정 기본값에는 최대 변 2,000픽셀로의 축소,
  탐지 최소 변 736, 문자 점수 0.5가 포함된다. 분류기는 로드하지만 실행하지 않는다.
- 인식된 줄을 순서대로 개행으로 연결한 뒤 기존 결정적 추출기와 검증기로 평가한다.
  anchor는 지정 문자열 재현율이며 문자 정확도/CER가 아니다. 제안 필드와 신뢰
  필드는 구분한다. 한 사례라도 실패하면 해당 그룹의 정확도를 `null`로 남기고
  분모를 보존한다. 서로 다른 그룹을 합친 성공 사례만의 종합 점수는 만들지 않는다.

## 2026-09-24 실측과 반복 결과

공개 소스 커밋 `b9bb80d51c6eaafdc1c96ea970c441dc3da22b05`의 변경 없는 작업 트리에서
[첫 실행](../artifacts/evaluation/ocr-candidate.json)과
[반복 실행](../artifacts/evaluation/ocr-candidate-repeat.json)을 수행했다.
두 결과의 코드 해시는 `df6f9b1a44000004971117623ac84c414a2ccf7cfab5d025fe1e63bc3577b879`이며,
manifest·모델·패키지·설정도 동일하다. 두 번 모두 **6건 중 5건 완료·1건 실패**였다.
완료된 5건의 인식 텍스트 해시와 모든 품질 점수, 실패 사례의 상태·오류 종류가 일치했다.
같은 문서를 반복한 것이므로 독립 표본이 12건으로 늘어난 것은 아니다.

| 그룹과 채점 범위 | 기존 Tesseract anchor | 후보 anchor (두 번 동일) | 후보 검증 통과 필드 | 후보 완료 |
| --- | ---: | ---: | ---: | ---: |
| 원본 이미지 PDF 2건, 각 첫 페이지 | 4/8 | **8/8** | **0/6** | 2/2 |
| 광주·한국인터넷진흥원 PDF의 첫 페이지 렌더 | 4/8 | **6/8** | **0/4** | 2/2 |
| 여주·중앙근로자복지센터 PDF의 첫 페이지 렌더 | 0/4 | **미완료 (`null`, 분모 4 보존)** | **미완료 (`null`, 분모 6 보존)** | 1/2 |

기존 비교값의 출처는 [원본 스캔 진단](../artifacts/evaluation/public-scan-diagnostics.json),
[다른 기관 대조군](../artifacts/evaluation/public-ocr-v2-original-cases.json),
[서식 대조군](../artifacts/evaluation/public-ocr-forms-v2.json)이다. 렌더 대조군에서는
`/300dpi` 행만 비교하며 blurred/150dpi 결과를 합치지 않는다. 두 역사적 렌더 결과는
`git_dirty=true`와 당시 코드 해시를 그대로 보존한다. 기존 렌더는 grayscale·Tesseract
CLI, 후보는 RGB·RapidOCR 내부 축소를 사용한다. 원본 스캔 기준선은 전체 PDF 8쪽을
처리한 뒤 첫 페이지를 채점했고 후보는 첫 페이지만 처리했다. 따라서 이 표는
**각 파이프라인의 관측 결과 비교**이며, 모델 하나만 교체한 통제 실험이나 속도 비교가 아니다.

원본 스캔의 제목·발주기관 문자열이 인식되어도 발주기관과 분류를 필수 구조화
필드로 얻지 못해 스키마에서 거절됐다. 제목의 공백·괄호 차이도 엄격한 필드 일치에는
실패한다. 여주 문서는 anchor 2/2·제안 필드 1/3(발주기관)이지만 분류가 누락되어
검증 통과 필드는 0/3이다. 이 부분 결과를 실패한 다른 문서 대신 그룹 점수로 쓰지 않는다.
중앙근로자복지센터 문서는 두 실행 모두 공개 기록상 `ValidationError`다. 후보 자식
프로세스의 안전한 실패 응답이 정상 결과 스키마에 맞지 않아 생기는 부모 측 오류이며,
추출 필드의 스키마 거절과 구분한다. 별도 로컬 진단에서는 탐지 단계의
`ONNXRuntimeError`와 `bad_alloc`을 확인했다. 원문 오류 메시지는 공개하지 않는다.

완료 사례의 페이지별 경과 시간은 첫 실행 **5.45~9.52초**, 반복 **5.38~11.84초**였다.
두 실행의 완료 사례 최대 RSS는 **693.46~716.48 MiB**였다. 실패 사례에는 RSS나
품질 점수를 채워 넣지 않았다. 표본 수가 작아 p95·처리량·클라우드 용량으로 환산하지 않는다.
두 명령은 결과 파일을 남기고 모두 **종료 코드 1**로 끝났다. 실패 문서가 있어
전체 후보 평가를 성공으로 처리하지 않는 의도된 동작이다.

### 함께 보존한 Tesseract 고정밀 모델 실패

기존 워커를 그대로 두고 `tessdata_best`의
[`e12c65a915945e4c28e237a9b52bc4a8f39a0cec`](https://github.com/tesseract-ocr/tessdata_best/tree/e12c65a915945e4c28e237a9b52bc4a8f39a0cec)
`kor`/`eng` 파일로 실행한 [별도 기록](../artifacts/evaluation/public-scan-best-model-timeout.json)도
보존한다. 소스는 `459e60d3ece3083ba446a2368fac7c23990198e0`, 작업 트리는 clean,
300 dpi·512 MiB·전체 PDF당 40초 조건이다. 원본 두 문서 모두 약 **40.05/40.07초**에
`TimeoutError`가 발생했다. 완료 0/2, 정확도 `null`, 필드 6개·anchor 8개의 분모를
보존한다. 시간 제한을 늘리거나 이 모델의 정확도가 좋다고 추정하지 않았다.

| 파일 | SHA-256 |
| --- | --- |
| `kor.traineddata` | `f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff` |
| `eng.traineddata` | `8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba` |

## 별도 실행 경계

후보는 Python 3.12/Linux의 별도 가상환경에서 실행한다. `rapidocr==3.9.2`,
`onnxruntime==1.23.2`, `pymupdf==1.28.2`와 세 모델의 해시를 실행 시 확인한다.
[실험 의존성 목록](../data/eval/requirements-ocr-candidate.txt)은 API 의존성이 아니다.
후보 모듈은 모델을 자동 설치하거나 내려받지 않는다. Python socket 연결을 차단해
예상하지 못한 다운로드를 거절하지만, 이를 OS 수준의 네트워크 샌드박스로 보지 않는다.

각 페이지마다 새 프로세스를 띄워 40초의 외부 제한, 42초 CPU 제한,
**1 GiB 주소 공간 제한**, 최대 12MP 렌더링, 250,000자, 2 MiB 응답 제한을 적용한다.
초기 512 MiB 실험에서는 이미지 배열 할당이 실패했으므로 생산 워커의
512 MiB 한도에 맞는 대안이라고 주장하지 않는다. 프로세스 종료 시 메모리를
반환하고, 제한 초과·취소 시 기존의 종료/회수 경로를 이용한다.

후보 시간에는 새 프로세스의 import·모델/원본 해시·렌더링·인식·부모의 평가가
포함된다. 기존 전체 PDF 처리 시간과 직접 비교하지 않는다. Linux 프로세스의
최대 RSS는 클라우드 동시 처리 용량이나 전체 컨테이너 메모리 측정값이 아니다.
원문·모델 응답·근거 문장을 저장소에 공개하지 않는다. 고정 정답과 출처,
텍스트 해시, 메타데이터, 점수, 안전한 오류 분류만 결과 파일에 저장한다.

## 재현

원본 파일은 각 기존 manifest의 URL과 SHA-256으로 별도 준비한다. 모델은
[RapidOCR v3.9.2 모델 목록](https://github.com/RapidAI/RapidOCR/blob/v3.9.2/python/rapidocr/default_models.yaml)
의 ONNX 파일을 다음 이름으로 한 디렉터리에 준비한다.

| 파일 | 출처 |
| --- | --- |
| `ch_PP-OCRv5_det_mobile.onnx` | [버전 고정 탐지 모델](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx) |
| `korean_PP-OCRv5_rec_mobile.onnx` | [버전 고정 한국어 인식 모델](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx) |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | `rapidocr==3.9.2` 패키지의 `models/` 디렉터리에 포함된 파일 |

`scripts/rapid_ocr_candidate.py`의 `MODEL_SHA256`과 해시가 다르면 거절한다.
모델 이름이 같아도 해시가 다르면 같은 실험으로 취급하지 않는다. 모델 파일을
모두 준비한 뒤, API 개발 환경에서 부모 평가기를 실행한다.

```sh
python3.12 -m venv /tmp/procure-delta-ocr-candidate
/tmp/procure-delta-ocr-candidate/bin/pip install -r data/eval/requirements-ocr-candidate.txt
RUN_ENVIRONMENT=local-korean-ocr-candidate PYTHONPATH=apps/api \
python scripts/run_ocr_candidate_eval.py \
  --source-dir /path/to/original-pdfs --models /path/to/verified-models \
  --candidate-python /tmp/procure-delta-ocr-candidate/bin/python \
  --manifest data/eval/public_scan_manifest.json \
  --manifest data/eval/public_ocr_manifest.json \
  --manifest data/eval/public_ocr_forms_manifest.json \
  --output /tmp/ocr-candidate.json
```

각 결과는 소스 커밋·코드 해시·데이터 해시·설치된 주요 패키지 버전·모델 해시를
기록한다. CI는 응답 검증·정보 노출·분모 보존·가상환경 선택을 테스트하며,
실제 외부 문서와 후보 모델의 실행은 별도로 기록한 로컬 실험이다.

## 적용 판단

**현재 후보의 운영 채택은 보류한다.** 원본 스캔의 anchor 인식은 개선됐지만
구조화 검증 통과는 개선되지 않았고, 자원 한도 내에서 6건 모두 완료하지도 못했다.
CI 통과는 이 결과 기록과 실패 처리의 회귀 검증이지 후보 모델의 운영 적합성 승인이 아니다.

후보가 글자를 더 잘 읽더라도 스키마를 충족하는 구조화 결과인지 별도로
판단해야 한다. 특히 관리기관의 의미, 표/표지의 라벨 없는 값, 업무 내용에
근거한 분류는 기존 검증기가 지원하지 않는다. 알려진 문서의 숫자를 올리기
위해 정답·필수 필드·거절 기준을 바꾸지 않는다. 생산 채택에는 독립적인 서식,
전체 PDF, 워커 저장 경로, 자원 예산과 배포 환경 검증이 추가로 필요하다.

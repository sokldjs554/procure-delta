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
  필드는 구분한다. 한 사례라도 실패하면 전체 정확도를 `null`로 남기고 분모를 보존한다.

## 별도 실행 경계

후보는 Python 3.12/Linux의 별도 가상환경에서 실행한다. `rapidocr==3.9.2`,
`onnxruntime==1.23.2`, `pymupdf==1.28.2`와 세 모델의 해시를 실행 시 확인한다.
[실험 의존성 목록](../data/eval/requirements-ocr-candidate.txt)은 API 의존성이 아니다.
후보 모듈은 모델을 자동 설치하거나 내려받지 않으며 네트워크 연결을 차단한다.

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

후보가 글자를 더 잘 읽더라도 스키마를 충족하는 구조화 결과인지 별도로
판단해야 한다. 특히 관리기관의 의미, 표/표지의 라벨 없는 값, 업무 내용에
근거한 분류는 기존 검증기가 지원하지 않는다. 알려진 문서의 숫자를 올리기
위해 정답·필수 필드·거절 기준을 바꾸지 않는다. 생산 채택에는 독립적인 서식,
전체 PDF, 워커 저장 경로, 자원 예산과 배포 환경 검증이 추가로 필요하다.

# 평가 방법과 재현

## 실행

```sh
python -m pip install -e "./apps/api[dev]"
python scripts/run_eval.py --output artifacts/evaluation/new-run.json
# 실제 인식기 설치된 환경에서만 선택
python scripts/run_eval.py --with-ocr --output artifacts/evaluation/new-ocr.json
# 환경 설정과 명시적인 유료 호출 허용 후에만
python scripts/run_eval.py --allow-hosted --output artifacts/evaluation/hosted.json
```

기본 명령은 네트워크/유료 LLM을 호출하지 않는다. hosted 전체 호출과 deterministic 검증을 먼저 통과시키고 필요한 입력에만 provider를 호출하는 gated 경로를 같은 사례로 비교한다.
두 hosted 경로가 모두 실제 실행되면 provider 호출 수, prompt+completion token 수, provider가 직접 보고한 비용의 절감률을 별도로 기록한다.
사용량/비용이 공급자 응답에 없으면 null이다. 모델 가격표를 추정해 비용을 채우지 않으며, 로컬 deterministic 경로를 유료 호출 수에 포함하지 않는다.
CLI에서 `--publish`를 주면 해당 실행의 JSON을 공개 평가 패널에 복사한다. OCR 없이 재평가하면 OCR은 '미측정'이 된다.

## 데이터와 분모

`data/eval/manifest.json`은 모든 평가 입력의 SHA-256을 고정한다. 입력 파일이 바뀌면 평가를 중단한다.
`benchmark.json`은 정상 추출 5건·의도적 거절 5건, Delta 8쌍, 연결 5건, 역사 재생 3개 시점으로 구성된다.
원본 공개 조달 데이터는 0건이다. 시스템 작성자가 만든 회귀셋이므로 독립 테스트셋이나 일반화 벤치마크가 아니다.

필드 정확도는 정상 정답 문서의 필수 정답 필드가 분모다. 추가 필드는 `unexpected`, 문서 exact-match에서 별도로 드러난다.
거절 탐지는 정상/비정상 전체를 비교하고, 필수 조건은 집합 정밀도/재현율을 기록한다.
지원 사례가 0이면 정확도/정밀도는 null이다. 결과가 없다는 이유로 100%를 반환하지 않는다.

Delta는 (case-id,field) 쌍의 precision/recall과 high-impact 탐지를 분리한다. 무변경 사례의 오경보율도 별도 기록한다.
연결은 해소된 링크의 정확도와 미해결 수를 함께 본다. 무조건 연결해야 높은 점수를 받는 구조가 아니다.
랭킹 Recall@K/nDCG@K는 frozen relevance 라벨에 대해 계산한다. 낙찰 사실만으로 기업 참가 자격 정답을 만들지 않는다.


## Pipeline Control Room과 hosted LLM 평가는 별개다

`/pipeline`의 세 시나리오는 파이프라인 구조와 판단 경계를 보여 주기 위한 **합성 deterministic replay**다.

- 신규 공고: 수집 → 정규화 → 문서 → 추출/검증 → eligibility → ranking → 알림 판단
- 정정 시나리오: immutable version → Delta → hard eligibility 변화 → ranking 차단 → notification decision
- 장애 시나리오: 저장된 synthetic transport failure classification

이 replay가 움직인다고 해서 hosted LLM을 호출한 것은 아니다. 공개 demo의 scenario stage timing도 backend latency로 사용하지 않는다.

현재 저장된 평가 artifact에서:

- deterministic extraction: measured
- OCR: measured, 영어 합성 이미지 3장
- hosted all: `not_run`
- hosted gated: `not_run`

UI는 네 경로를 같은 표에 두되 hosted 경로가 실행되지 않았으면 정확도·latency·token·cost를 **미실행/미측정**으로 남긴다.

## 과거 시점 재생

버전의 effective_at, observed_at, created_at이 모두 as_of 이하일 때만 사용할 수 있다.
후속 추출의 available_at과 기업 프로필의 available_at도 같은 조건으로 제한한다.
늦게 수집된 과거 자료, 최신 프로필, 미래 낙찰 정보를 과거 판단에 주입하지 않는 반례 테스트가 있다.
정답 라벨·outcome 정보는 ranking 허용 입력 목록에 없다. missing historical profile은 현재 프로필로 대체하지 않고 실패한다.

## 실제 OCR 측정의 한계

`artifacts/evaluation/local.json`은 Tesseract 5.5.0을 한 번의 배치 인식으로 실행한 저장 결과다.
영어 이미지 3장/18개 필드 중 17개가 맞았다. 저해상도 이미지에서 Region이 잘못 인식되어 지역 필드가 누락됐다.

평가기는 manifest의 언어 설정을 사용하고, 실행 전에 Tesseract의 실제 설치 언어 목록을 확인한다.
예를 들어 향후 한국어 회귀셋은 `kor` 또는 `kor+eng`로 명시할 수 있지만, 해당 언어 데이터가
설치되어 있지 않으면 측정하지 않고 `not_run`으로 남긴다.

현재 저장 artifact는 여전히 영어 합성 이미지 결과이며 **한국어 OCR 측정값은 없다**.
한글 실문서·표·복잡한 레이아웃·다양한 스캐너에 대한 결과로 해석하지 않는다.
서비스의 기본 fake fixture OCR도 이 정확도로 평가하지 않는다. 반복 측정으로 잘 나온 결과만 고르지 않았고,
입력 이미지와 실패 인식 텍스트를 함께 보존했다.

## provenance

각 실행은 생성 시각, 데이터 SHA, Python 구현+scripts SHA, Git commit/dirty, 설정과 실행환경을 남긴다.
현재 UI는 저장된 실험을 보여 주며 현재 서버 성능으로 해석하면 안 된다.
OCR 포함 저장 실행과 이후 새 회귀 실행은 서로 다른 시각/소스 해시의 산출물로 보존한다.
하드웨어가 다른 실행끼리 지연시간을 직접 우열 비교하지 않는다.

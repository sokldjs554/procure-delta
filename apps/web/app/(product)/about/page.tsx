"use client";

import { useEffect, useState } from "react";

import {
  getEvaluationSummary,
  type EvaluationRouteSummary,
  type EvaluationSummary,
} from "../../../lib/api";

const percent = (n: number | null) =>
  n === null ? "미측정" : `${(100 * n).toFixed(1)}%`;

function routeStatus(route: EvaluationRouteSummary) {
  if (route.status !== "measured") return "미실행";
  return route.prompt_contract_status === "different" || route.prompt_contract_status === "unknown"
    ? "과거 측정"
    : "측정됨";
}

function numberMetric(value: number | null, suffix = "") {
  return value === null ? "미측정" : `${value.toLocaleString("ko-KR")}${suffix}`;
}

const routeRows: Array<
  [
    "deterministic" | "hosted_all" | "hosted_gated" | "ocr" | "ocr_korean",
    string,
  ]
> = [
  ["deterministic", "deterministic"],
  ["hosted_all", "hosted all"],
  ["hosted_gated", "hosted gated"],
  ["ocr", "OCR · English synthetic"],
  ["ocr_korean", "OCR · Korean synthetic"],
];

export default function About() {
  const [data, setData] = useState<EvaluationSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    getEvaluationSummary()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="product narrow">
      <header className="page-head">
        <div>
          <p className="eyebrow">EVALUATION & LIMITS</p>
          <h1>평가와 제품 한계</h1>
          <p>운영 수치와 저장된 합성 회귀 실험을 구분합니다.</p>
        </div>
      </header>

      <section className="panel prose">
        <h2>저장된 평가 결과</h2>
        {failed ? (
          <p role="alert">
            평가 파일을 불러오지 못했습니다. 이전 수치를 대신 표시하지 않습니다.
          </p>
        ) : !data ? (
          <p role="status">평가 결과를 확인하고 있습니다.</p>
        ) : data.status !== "measured" ? (
          <p>아직 저장된 측정 결과가 없습니다.</p>
        ) : (
          <>
            <div className="honesty">
              <b>합성 회귀 평가 · {data.dataset_version}</b>
              <p>{data.notice}</p>
              <p>
                실제 공개 공고 {data.public_real_records}건 · 저장 시각{" "}
                {data.measured_at}
              </p>
            </div>

            <h2>추출 경로 비교</h2>
            <p>
              같은 표에 표시하되, 실행하지 않은 hosted 경로는 결과를 추정하지 않고
              <strong> 미실행</strong>으로 남깁니다.
            </p>
            <div className="evaluation-route-table" role="table" aria-label="추출 경로 비교">
              <div className="evaluation-route-row head" role="row">
                <span role="columnheader">경로</span>
                <span role="columnheader">상태</span>
                <span role="columnheader">지원 필드</span>
                <span role="columnheader">필드 정확도</span>
                <span role="columnheader">스키마 실패</span>
                <span role="columnheader">p95 지연</span>
                <span role="columnheader">호출</span>
                <span role="columnheader">비용</span>
              </div>
              {routeRows.map(([id, label]) => {
                const route = data.routes[id];
                return (
                  <div className="evaluation-route-row" role="row" key={id}>
                    <strong role="cell">{label}</strong>
                    <span role="cell">{routeStatus(route)}</span>
                    <span role="cell">{route.status === "measured" ? route.support : "미실행"}</span>
                    <span role="cell">
                      {route.status === "measured"
                        ? percent(route.field_accuracy)
                        : "미실행"}
                    </span>
                    <span role="cell">
                      {route.status === "measured"
                        ? numberMetric(route.schema_failures)
                        : "미실행"}
                    </span>
                    <span role="cell">
                      {route.status === "measured"
                        ? numberMetric(route.p95_latency_ms, " ms")
                        : "미실행"}
                    </span>
                    <span role="cell">
                      {route.status === "measured"
                        ? numberMetric(route.hosted_calls)
                        : "미실행"}
                    </span>
                    <span role="cell">
                      {route.status === "measured"
                        ? route.reported_cost === null
                          ? "미측정"
                          : numberMetric(route.reported_cost)
                        : "미실행"}
                    </span>
                  </div>
                );
              })}
            </div>

            {data.hosted_evaluated && (
              <div className="honesty" style={{ overflowWrap: "anywhere" }} aria-label="외부 Claude 실측">
                <h3>저장된 외부 Claude 실측 · 합성 회귀</h3>
                <p>{data.routes.hosted_all.notice}</p>
                <p>{data.routes.hosted_gated.notice}</p>
                <p>
                  필드 정확도는 근거 검증까지 통과한 결과입니다.
                  정상 문서가 거절되면 해당 필드는 오답으로 집계합니다.
                </p>
                <dl>
                  <dt>전체 호출 → 규칙 우선 호출</dt>
                  <dd>
                    {numberMetric(data.hosted_optimization.all_calls)}회 →{" "}
                    {numberMetric(data.hosted_optimization.gated_calls)}회 ·{" "}
                    {percent(data.hosted_optimization.call_reduction_rate)} 감소
                  </dd>
                  <dt>입력 + 출력 토큰</dt>
                  <dd>
                    {numberMetric(data.hosted_optimization.all_tokens)} →{" "}
                    {numberMetric(data.hosted_optimization.gated_tokens)} ·{" "}
                    {percent(data.hosted_optimization.token_reduction_rate)} 감소
                  </dd>
                  <dt>provider 보고 비용 절감률</dt>
                  <dd>{percent(data.hosted_optimization.reported_cost_reduction_rate)}</dd>
                </dl>
                <p>{data.hosted_optimization.notice}</p>
                <a href="https://github.com/sokldjs554/procure-delta/blob/main/docs/hosted-evaluation-success.md">
                  원본·실행 출처와 품질 한계 확인
                </a>
              </div>
            )}

            <div className="evaluation-boundary">
              <article>
                <small>DATASET</small>
                <strong>synthetic regression</strong>
                <span>실제 공개 공고 {data.public_real_records}건</span>
              </article>
              <article>
                <small>OCR · 한국어</small>
                <strong>
                  {data.routes.ocr_korean.status === "measured"
                    ? `${data.routes.ocr_korean.support} 필드 · ${percent(
                        data.routes.ocr_korean.field_accuracy,
                      )}`
                    : "미측정"}
                </strong>
                <span>
                  {data.routes.ocr_korean.language ?? "미측정"} · 합성 한글 이미지 3장
                </span>
              </article>
              <article>
                <small>HOSTED LLM</small>
                <strong>{data.hosted_current_contract_evaluated ? "현재 계약 측정됨" : "현재 계약 미측정"}</strong>
                <span>현재 프롬프트·검증 규칙 기준 · 과거 측정값은 위 표에 보존</span>
              </article>
            </div>

            <dl>
              <dt>명시 라벨 추출</dt>
              <dd>
                {data.extraction_correct}/{data.extraction_support} 필드 (
                {percent(data.extraction_accuracy)})
              </dd>
              <dt>Delta 필드 탐지</dt>
              <dd>
                정밀도 {percent(data.delta_precision)} · 재현율{" "}
                {percent(data.delta_recall)} · 변경 필드 {data.delta_support}개
              </dd>
              <dt>생명주기 연결</dt>
              <dd>
                {data.lifecycle_cases}개 사례 중 {data.lifecycle_resolved}개 연결 ·
                정밀도 {percent(data.lifecycle_precision)}
              </dd>
              <dt>과거 시점 재생</dt>
              <dd>{data.replay_queries}개 시점 · 이후 수집·처리된 정보 제외</dd>
              <dt>별도 OCR 실험</dt>
              <dd>
                영어 {data.ocr_correct}/{data.ocr_support} 필드 (
                {percent(data.ocr_accuracy)}) · 한국어{" "}
                {data.routes.ocr_korean.support} 필드 (
                {percent(data.routes.ocr_korean.field_accuracy)}) · 언어{" "}
                {data.routes.ocr_korean.language ?? "미측정"}
              </dd>
              <dt>외부 LLM 비교</dt>
              <dd>
                {data.hosted_evaluated
                  ? "측정 파일 참조"
                  : "미실행 · 비용/정확도 수치 없음"}
              </dd>
            </dl>

            <details>
              <summary>재현 정보</summary>
              <p>데이터 SHA-256</p>
              <code style={{ overflowWrap: "anywhere" }}>{data.dataset_sha256}</code>
              <p>측정 당시 Python 소스 SHA-256</p>
              <code style={{ overflowWrap: "anywhere" }}>{data.source_sha256}</code>
            </details>
          </>
        )}

        <h2>알려진 한계</h2>
        <ul>
          <li>
            직접 작성한 작은 평가셋입니다. 실무 적합도나 미지의 문서에 대한 일반화
            성능을 뜻하지 않습니다.
          </li>
          <li>
            OCR 실험은 영어 합성 이미지 3장과 한국어 합성 이미지 3장입니다. 실제
            나라장터 스캔·표·필기·다양한 문서 레이아웃의 일반화 성능은 아닙니다.
          </li>
          <li>
            실제 나라장터 연동 범위는 용역 입찰공고와 관측 변경입니다.
            사전규격·낙찰·계약의 실제 연동은 아직 없습니다.
          </li>
          <li>공개 운영 트래픽·실제 결제·운영 인증은 검증하지 않았습니다.</li>
          <li>
            자료가 처리 중이거나 필수 조건을 알 수 없으면 참여 가능으로 확정하지
            않습니다.
          </li>
        </ul>

        <h2>판단 방법</h2>
        <p>
          기업 프로필, 공고 버전과 추출기 지문이 일치할 때만 최신 판단을
          사용합니다. 과거 버전과 철회된 연결은 이력에 남고 현재 추천과
          분리됩니다.
        </p>
      </section>
    </main>
  );
}

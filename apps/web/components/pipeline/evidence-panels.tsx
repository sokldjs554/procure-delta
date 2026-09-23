"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getEngineeringEvidence,
  type EngineeringEvidence,
} from "../../lib/api";
import { displayMetric } from "../../lib/pipeline";

const importantGates = new Set([
  "database-and-redis",
  "backend-integration",
  "full-readiness",
  "real-lifecycle-e2e",
  "pipeline-demo-e2e",
  "queue-scale",
  "backfill-scale",
  "query-plans",
  "http-load",
]);

function statusLabel(status: "measured" | "not_run") {
  return status === "measured" ? "측정됨" : "미측정";
}

function numberMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return typeof value === "number" ? value : null;
}

function booleanMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return typeof value === "boolean" ? value : null;
}

function textMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return typeof value === "string" ? value : null;
}

function recordMetric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function EvidencePanels() {
  const [data, setData] = useState<EngineeringEvidence | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getEngineeringEvidence()
      .then((value) => {
        if (active) {
          setData(value);
          setError("");
        }
      })
      .catch(() => {
        if (active) setError("검증 증거를 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, []);

  const releaseGates = useMemo(
    () => data?.release.gates.filter((gate) => importantGates.has(gate.gate)) ?? [],
    [data],
  );

  return (
    <section className="evidence-section" aria-labelledby="engineering-evidence-title">
      <header className="evidence-heading">
        <div>
          <p className="eyebrow">MEASURED ENGINEERING EVIDENCE</p>
          <h2 id="engineering-evidence-title">대규모 처리와 장애 대응, 어디까지 검증했나</h2>
        </div>
        <p>
          실제 저장된 검증 artifact만 표시합니다. 없는 지표는 0으로 채우지 않고
          미측정으로 남깁니다.
        </p>
      </header>

      {error ? (
        <p role="alert" className="danger-copy">
          {error}
        </p>
      ) : !data ? (
        <p role="status">검증 증거를 확인하고 있습니다.</p>
      ) : (
        <div className="evidence-grid">
          <article className="evidence-card scale-evidence">
            <header>
              <span>Scale</span>
              <b>{statusLabel(data.cpu.status)}</b>
            </header>
            <h3>CPU-only production-function benchmark</h3>
            <div className="evidence-metrics">
              <span>
                <strong>{displayMetric(data.cpu.normalized_records)}</strong>
                정규화
              </span>
              <span>
                <strong>{displayMetric(data.cpu.ranked_records)}</strong>
                랭킹
              </span>
              <span>
                <strong>{displayMetric(data.cpu.delta_pairs)}</strong>
                Delta 쌍
              </span>
              <span>
                <strong>
                  {data.cpu.records_per_second === null
                    ? "미측정"
                    : Math.round(data.cpu.records_per_second).toLocaleString("ko-KR")}
                </strong>
                건/초
              </span>
            </div>
            <p>{data.cpu.limitation ?? "측정 범위 미확인"}</p>
          </article>

          <article className="evidence-card queue-evidence">
            <header>
              <span>Queue</span>
              <b>{statusLabel(data.queue.status)}</b>
            </header>
            <h3>실제 Redis · ARQ · PostgreSQL 큐 처리</h3>
            {data.queue.status === "measured" ? (
              <>
                <div className="evidence-metrics">
                  <span>
                    <strong>{displayMetric(numberMetric(data.queue.metrics, "records"))}</strong>
                    투입
                  </span>
                  <span>
                    <strong>
                      {displayMetric(numberMetric(data.queue.metrics, "completed_records"))}
                    </strong>
                    정규화 완료
                  </span>
                  <span>
                    <strong>
                      {numberMetric(data.queue.metrics, "records_per_second") === null
                        ? "미측정"
                        : numberMetric(data.queue.metrics, "records_per_second")!.toFixed(2)}
                    </strong>
                    건/초
                  </span>
                  <span>
                    <strong>
                      {numberMetric(data.queue.metrics, "elapsed_seconds") === null
                        ? "미측정"
                        : `${numberMetric(data.queue.metrics, "elapsed_seconds")!.toFixed(2)}s`}
                    </strong>
                    worker
                  </span>
                </div>
                <p>
                  {textMetric(data.queue.metrics, "limitation") ??
                    "측정 범위를 확인할 수 없습니다."}
                </p>
              </>
            ) : (
              <p>별도 공개 queue 측정 artifact가 없어 미측정으로 남깁니다.</p>
            )}
          </article>

          <article className="evidence-card backfill-evidence">
            <header>
              <span>Backfill</span>
              <b>{statusLabel(data.backfill.status)}</b>
            </header>
            <h3>페이지 수집 · cursor checkpoint · 재개</h3>
            {data.backfill.status === "measured" ? (
              <>
                <div className="evidence-metrics">
                  <span>
                    <strong>{displayMetric(numberMetric(data.backfill.metrics, "records"))}</strong>
                    수집·정규화
                  </span>
                  <span>
                    <strong>
                      {displayMetric(numberMetric(data.backfill.metrics, "expected_pages"))}
                    </strong>
                    페이지
                  </span>
                  <span>
                    <strong>
                      {numberMetric(data.backfill.metrics, "records_per_second") === null
                        ? "미측정"
                        : numberMetric(data.backfill.metrics, "records_per_second")!.toFixed(2)}
                    </strong>
                    건/초
                  </span>
                  <span>
                    <strong>
                      {booleanMetric(data.backfill.metrics, "resumed_from_checkpoint")
                        ? "확인"
                        : "미확인"}
                    </strong>
                    cursor 재개
                  </span>
                </div>
                <p>
                  {displayMetric(numberMetric(data.backfill.metrics, "first_batch_pages"))}페이지 후
                  중단 → {displayMetric(numberMetric(data.backfill.metrics, "resumed_pages"))}페이지
                  재개 · IngestRun {displayMetric(numberMetric(data.backfill.metrics, "ingest_runs"))}개
                </p>
                <p>
                  {textMetric(data.backfill.metrics, "limitation") ??
                    "측정 범위를 확인할 수 없습니다."}
                </p>
              </>
            ) : (
              <p>별도 paginated backfill 측정 artifact가 없어 미측정으로 남깁니다.</p>
            )}
          </article>

          <article className="evidence-card failure-evidence">
            <header>
              <span>Failure</span>
              <b>{statusLabel(data.failure_drill.status)}</b>
            </header>
            <h3>합성 HTTP transport 장애 주입</h3>
            <div className="failure-case-list">
              {data.failure_drill.cases.map((item) => (
                <span key={item.name}>
                  <b>{item.name}</b>
                  {item.attempts}회 · {item.succeeded ? "회복" : "종료"}
                </span>
              ))}
            </div>
            <p>{data.failure_drill.limitation ?? "측정 범위 미확인"}</p>
          </article>

          <article className="evidence-card http-evidence">
            <header>
              <span>HTTP</span>
              <b>{statusLabel(data.http.status)}</b>
            </header>
            <h3>실제 로컬 HTTP 부하</h3>
            {data.http.status === "measured" ? (
              <>
                <div className="evidence-metrics">
                  <span>
                    <strong>{displayMetric(numberMetric(data.http.metrics, "requests"))}</strong>
                    요청
                  </span>
                  <span>
                    <strong>
                      {displayMetric(numberMetric(data.http.metrics, "successful_requests"))}
                    </strong>
                    성공
                  </span>
                  <span>
                    <strong>
                      {displayMetric(numberMetric(data.http.metrics, "failed_requests"))}
                    </strong>
                    실패
                  </span>
                  <span>
                    <strong>
                      {booleanMetric(data.http.metrics, "client_observed_only") === true
                        ? "client"
                        : "미확인"}
                    </strong>
                    관측 기준
                  </span>
                </div>
                <div className="http-endpoint-list">
                  {Object.entries(recordMetric(data.http.metrics, "endpoints")).map(
                    ([name, value]) => {
                      const row =
                        value && typeof value === "object" && !Array.isArray(value)
                          ? (value as Record<string, unknown>)
                          : {};
                      const p95 = numberMetric(row, "p95_ms");
                      return (
                        <span key={name}>
                          <b>{name}</b>
                          p95 {p95 === null ? "미측정" : `${p95.toFixed(1)} ms`}
                        </span>
                      );
                    },
                  )}
                </div>
                <p>격리된 로컬 API · 합성 데이터 · 동시성 5의 client-observed 측정입니다.</p>
              </>
            ) : (
              <p>별도 공개 HTTP 측정 artifact가 없어 미측정으로 남깁니다.</p>
            )}
          </article>

          <article className="evidence-card query-evidence">
            <header>
              <span>Query plan</span>
              <b>{statusLabel(data.query_plans.status)}</b>
            </header>
            <h3>PostgreSQL EXPLAIN 후보 인덱스 실험</h3>
            {data.query_plans.status === "measured" ? (
              <>
                <div className="evidence-metrics">
                  <span>
                    <strong>
                      {numberMetric(data.query_plans.metrics, "before") === null
                        ? "미측정"
                        : `${numberMetric(data.query_plans.metrics, "before")!.toFixed(3)} ms`}
                    </strong>
                    before median
                  </span>
                  <span>
                    <strong>
                      {numberMetric(data.query_plans.metrics, "after") === null
                        ? "미측정"
                        : `${numberMetric(data.query_plans.metrics, "after")!.toFixed(3)} ms`}
                    </strong>
                    after median
                  </span>
                  <span>
                    <strong>
                      {numberMetric(data.query_plans.metrics, "improvement_ratio") === null
                        ? "미측정"
                        : `${numberMetric(data.query_plans.metrics, "improvement_ratio")!.toFixed(2)}×`}
                    </strong>
                    이번 실행 비율
                  </span>
                  <span>
                    <strong>
                      {displayMetric(numberMetric(data.query_plans.metrics, "records"))}
                    </strong>
                    rows
                  </span>
                </div>
                <p>
                  후보 인덱스는 채택하지 않음 ·{" "}
                  {booleanMetric(data.query_plans.metrics, "candidate_rolled_back")
                    ? "ROLLBACK 확인"
                    : "rollback 미확인"}
                </p>
                <p>
                  {textMetric(data.query_plans.metrics, "caution") ??
                    "실험 한계를 확인할 수 없습니다."}
                </p>
              </>
            ) : (
              <p>별도 공개 query-plan artifact가 없어 미측정으로 남깁니다.</p>
            )}
          </article>

          <article className="evidence-card release-evidence">
            <header>
              <span>Release</span>
              <b>
                {data.release.status === "measured"
                  ? data.release.passed
                    ? "통과"
                    : "실패"
                  : "미측정"}
              </b>
            </header>
            <h3>격리 컨테이너 release gate</h3>
            <div className="release-gate-list">
              {releaseGates.map((gate) => (
                <span key={gate.gate}>
                  <b>{gate.gate}</b>
                  {gate.passed ? "PASS" : "FAIL"}
                </span>
              ))}
            </div>
            <p>readiness: {data.release.readiness ?? "미측정"}</p>
          </article>
        </div>
      )}
    </section>
  );
}

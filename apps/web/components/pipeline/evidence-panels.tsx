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
  "queue-scale",
  "query-plans",
  "http-load",
]);

function statusLabel(status: "measured" | "not_run") {
  return status === "measured" ? "측정됨" : "미측정";
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

          <article className="evidence-card optional-evidence">
            <header>
              <span>Service details</span>
              <b>정직한 공백</b>
            </header>
            <h3>세부 서비스 측정 artifact</h3>
            <dl>
              <div>
                <dt>Queue summary</dt>
                <dd>{statusLabel(data.queue.status)}</dd>
              </div>
              <div>
                <dt>HTTP summary</dt>
                <dd>{statusLabel(data.http.status)}</dd>
              </div>
              <div>
                <dt>Query-plan summary</dt>
                <dd>{statusLabel(data.query_plans.status)}</dd>
              </div>
            </dl>
            <p>
              release gate의 통과 여부와 상세 성능 수치는 구분합니다. 별도 공개
              요약 artifact가 없으면 수치를 만들지 않습니다.
            </p>
          </article>
        </div>
      )}
    </section>
  );
}

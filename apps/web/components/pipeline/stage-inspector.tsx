"use client";

import { useState } from "react";

import type { PipelineStage } from "../../lib/api";
import { AmendmentImpact } from "./amendment-impact";

type Tab = "input" | "output" | "evidence" | "decision";

function pretty(value: unknown) {
  if (
    value === null ||
    value === undefined ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === "object" &&
      !Array.isArray(value) &&
      Object.keys(value as object).length === 0)
  ) {
    return "표시할 값이 없습니다.";
  }
  return JSON.stringify(value, null, 2);
}

export function StageInspector({ stage }: { stage: PipelineStage | null }) {
  const [tab, setTab] = useState<Tab>("output");
  if (!stage)
    return (
      <section className="stage-inspector">
        <p>단계를 선택하세요.</p>
      </section>
    );

  const values: Record<Tab, unknown> = {
    input: stage.input,
    output: stage.output,
    evidence: stage.evidence,
    decision: stage.decision,
  };
  const labels: Array<[Tab, string]> = [
    ["input", "입력"],
    ["output", "출력"],
    ["evidence", "근거"],
    ["decision", "판단"],
  ];

  return (
    <section className="stage-inspector" aria-live="polite">
      <header>
        <div>
          <p className="eyebrow">{stage.kind.toUpperCase()}</p>
          <h2>{stage.label}</h2>
        </div>
        <span className={`stage-status status-${stage.status}`}>
          {stage.status}
        </span>
      </header>
      <p className="stage-measurement">
        측정 지연:{" "}
        {stage.measured_duration_ms === null
          ? "미측정"
          : `${stage.measured_duration_ms.toFixed(2)} ms`}
      </p>
      {stage.notice && <p className="honesty">{stage.notice}</p>}
      {["delta", "eligibility", "ranking", "notification"].includes(stage.id) && (
        <AmendmentImpact stage={stage} />
      )}
      <div className="inspector-tabs" role="tablist" aria-label="단계 세부 정보">
        {labels.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <pre className="pipeline-json">{pretty(values[tab])}</pre>
    </section>
  );
}

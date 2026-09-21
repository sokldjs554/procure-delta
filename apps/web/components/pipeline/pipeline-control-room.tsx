"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getPipelineScenario,
  type PipelineScenario,
  type PipelineScenarioSummary,
} from "../../lib/api";
import { PipelineStageMap } from "./pipeline-stage-map";
import { StageInspector } from "./stage-inspector";

export function nextReplayIndex(current: number, length: number): number {
  if (length <= 0) return -1;
  return Math.min(current + 1, length - 1);
}

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function PipelineControlRoom({
  scenarios,
}: {
  scenarios: PipelineScenarioSummary[];
}) {
  const [scenarioId, setScenarioId] = useState(scenarios[0]?.id ?? "");
  const [scenario, setScenario] = useState<PipelineScenario | null>(null);
  const [selectedStageId, setSelectedStageId] = useState("");
  const [replayIndex, setReplayIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(Boolean(scenarioId));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!scenarioId) return;
    let active = true;
    setLoading(true);
    setError("");
    setPlaying(false);
    setReplayIndex(-1);
    getPipelineScenario(scenarioId)
      .then((value) => {
        if (!active) return;
        setScenario(value);
        setSelectedStageId(value.stages[0]?.id ?? "");
      })
      .catch(() => {
        if (active) setError("선택한 시나리오를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scenarioId]);

  useEffect(() => {
    if (!playing || !scenario || prefersReducedMotion()) return;
    const timer = window.setInterval(() => {
      setReplayIndex((current) => {
        const next = nextReplayIndex(current, scenario.stages.length);
        setSelectedStageId(scenario.stages[next]?.id ?? "");
        if (next >= scenario.stages.length - 1) setPlaying(false);
        return next;
      });
    }, 700);
    return () => window.clearInterval(timer);
  }, [playing, scenario]);

  const selectedStage = useMemo(
    () => scenario?.stages.find((stage) => stage.id === selectedStageId) ?? null,
    [scenario, selectedStageId],
  );

  function play() {
    if (!scenario) return;
    if (prefersReducedMotion()) {
      const next = nextReplayIndex(replayIndex, scenario.stages.length);
      setReplayIndex(next);
      setSelectedStageId(scenario.stages[next]?.id ?? "");
      return;
    }
    if (replayIndex >= scenario.stages.length - 1) setReplayIndex(-1);
    setPlaying(true);
  }

  function reset() {
    setPlaying(false);
    setReplayIndex(-1);
    setSelectedStageId(scenario?.stages[0]?.id ?? "");
  }

  return (
    <section className="pipeline-control-room">
      <div className="scenario-switcher" aria-label="파이프라인 시나리오">
        {scenarios.map((item) => (
          <button
            key={item.id}
            className={scenarioId === item.id ? "active" : ""}
            aria-pressed={scenarioId === item.id}
            onClick={() => setScenarioId(item.id)}
          >
            <strong>{item.title}</strong>
            <small>{item.description}</small>
          </button>
        ))}
      </div>

      <div className="pipeline-toolbar">
        <div>
          <span className="demo-chip">합성 시나리오</span>
          <strong>{scenario?.title ?? "시나리오 선택"}</strong>
        </div>
        <div className="pipeline-controls">
          <button onClick={play} disabled={!scenario || loading}>
            재생
          </button>
          <button className="ghost" onClick={() => setPlaying(false)} disabled={!playing}>
            일시정지
          </button>
          <button className="ghost" onClick={reset} disabled={!scenario}>
            초기화
          </button>
        </div>
      </div>

      {loading ? (
        <div className="state" role="status">
          시나리오를 불러오는 중입니다.
        </div>
      ) : error ? (
        <div className="state error" role="alert">
          {error}
        </div>
      ) : scenario ? (
        <div className="pipeline-workspace">
          <PipelineStageMap
            stages={scenario.stages}
            selectedStageId={selectedStageId}
            replayIndex={replayIndex}
            onSelect={setSelectedStageId}
          />
          <StageInspector stage={selectedStage} />
        </div>
      ) : null}
    </section>
  );
}

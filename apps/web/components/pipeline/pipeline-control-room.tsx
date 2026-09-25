"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getPipelineScenario,
  type PipelineScenario,
  type PipelineScenarioSummary,
} from "../../lib/api";
import { nextReplayIndex } from "../../lib/pipeline";
import { PipelineStageMap } from "./pipeline-stage-map";
import { StageInspector } from "./stage-inspector";

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
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [speed, setSpeed] = useState(700);

  useEffect(() => {
    if (!scenarioId) return;
    let active = true;
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
  }, [scenarioId, loadAttempt]);

  useEffect(() => {
    if (!playing || !scenario || prefersReducedMotion()) return;
    const timer = window.setInterval(() => {
      setReplayIndex((current) => {
        const next = nextReplayIndex(current, scenario.stages.length);
        setSelectedStageId(scenario.stages[next]?.id ?? "");
        if (next >= scenario.stages.length - 1) setPlaying(false);
        return next;
      });
    }, speed);
    return () => window.clearInterval(timer);
  }, [playing, scenario, speed]);

  function selectScenario(id: string) {
    if (id === scenarioId) return;
    setScenarioId(id);
    setScenario(null);
    setSelectedStageId("");
    setLoading(true);
    setError("");
    setPlaying(false);
    setReplayIndex(-1);
  }

  const selectedStage = useMemo(
    () =>
      scenario?.stages.find((stage) => stage.id === selectedStageId) ?? null,
    [scenario, selectedStageId],
  );
  const stageIndex =
    scenario?.stages.findIndex((stage) => stage.id === selectedStageId) ?? -1;

  function selectStage(id: string) {
    if (!scenario) return;
    setPlaying(false);
    setSelectedStageId(id);
    setReplayIndex(scenario.stages.findIndex((stage) => stage.id === id));
  }

  function step(offset: number) {
    if (!scenario?.stages.length) return;
    const next = Math.max(
      0,
      Math.min(stageIndex + offset, scenario.stages.length - 1),
    );
    setPlaying(false);
    setReplayIndex(next);
    setSelectedStageId(scenario.stages[next].id);
  }

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
            onClick={() => selectScenario(item.id)}
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
          <label className="pipeline-speed">
            재생 속도
            <select
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            >
              <option value={700}>빠르게 · 0.7초</option>
              <option value={1000}>보통 · 1초</option>
              <option value={1500}>천천히 · 1.5초</option>
            </select>
          </label>
          <button onClick={play} disabled={!scenario || loading}>
            재생
          </button>
          <button
            className="ghost"
            onClick={() => setPlaying(false)}
            disabled={!playing}
          >
            일시정지
          </button>
          <button className="ghost" onClick={reset} disabled={!scenario}>
            초기화
          </button>
        </div>
      </div>

      {scenario && !loading && !error && (
        <div className="pipeline-progress">
          <span aria-live="polite">
            {Math.max(1, stageIndex + 1)} / {scenario.stages.length} 단계
          </span>
          <progress
            aria-label="파이프라인 진행"
            value={Math.max(0, stageIndex + 1)}
            max={scenario.stages.length}
          />
          <div className="pipeline-step-controls">
            <button
              className="ghost"
              onClick={() => step(-1)}
              disabled={stageIndex <= 0}
            >
              이전 단계
            </button>
            <button
              className="ghost"
              onClick={() => step(1)}
              disabled={stageIndex >= scenario.stages.length - 1}
            >
              다음 단계
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="state" role="status">
          시나리오를 불러오는 중입니다.
        </div>
      ) : error ? (
        <div className="state error" role="alert">
          {error}
          <button
            onClick={() => {
              setLoading(true);
              setError("");
              setLoadAttempt((attempt) => attempt + 1);
            }}
          >
            다시 시도
          </button>
        </div>
      ) : scenario ? (
        <div className="pipeline-workspace">
          <PipelineStageMap
            stages={scenario.stages}
            selectedStageId={selectedStageId}
            replayIndex={replayIndex}
            onSelect={selectStage}
          />
          <StageInspector stage={selectedStage} />
        </div>
      ) : null}
    </section>
  );
}

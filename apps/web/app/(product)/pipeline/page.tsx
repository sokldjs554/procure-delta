"use client";

import { useEffect, useState } from "react";

import {
  getPipelineScenarios,
  type PipelineScenarioSummary,
} from "../../../lib/api";
import { PipelineControlRoom } from "../../../components/pipeline/pipeline-control-room";

export default function PipelinePage() {
  const [scenarios, setScenarios] = useState<PipelineScenarioSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getPipelineScenarios()
      .then((rows) => {
        if (active) {
          setScenarios(rows);
          setError("");
        }
      })
      .catch(() => {
        if (active) setError("파이프라인 시나리오를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="product pipeline-page">
      <header className="page-head pipeline-hero">
        <div>
          <p className="eyebrow">PIPELINE CONTROL ROOM</p>
          <h1>파이프라인을 직접 재생해보세요</h1>
          <p>
            합성 시나리오를 통해 수집부터 Delta·참여 조건·추천·알림 판단까지
            단계별 입력과 근거를 확인할 수 있습니다.
          </p>
        </div>
      </header>
      {loading ? (
        <div className="state" role="status">
          파이프라인 시나리오를 준비하고 있습니다.
        </div>
      ) : error ? (
        <div className="state error" role="alert">
          {error}
        </div>
      ) : (
        <PipelineControlRoom scenarios={scenarios} />
      )}
    </main>
  );
}

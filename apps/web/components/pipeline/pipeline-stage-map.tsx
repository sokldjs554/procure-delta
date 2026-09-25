import type { PipelineStage } from "../../lib/api";

const statusText: Record<PipelineStage["status"], string> = {
  passed: "처리됨",
  warning: "주의",
  blocked: "중단됨",
  not_run: "미실행",
};

export function PipelineStageMap({
  stages,
  selectedStageId,
  replayIndex,
  onSelect,
}: {
  stages: PipelineStage[];
  selectedStageId: string;
  replayIndex: number;
  onSelect: (id: string) => void;
}) {
  return (
    <ol className="pipeline-stage-map" aria-label="파이프라인 단계">
      {stages.map((stage, index) => {
        const progress =
          replayIndex < 0
            ? "future"
            : index < replayIndex
              ? "complete"
              : index === replayIndex
                ? "current"
                : "future";
        return (
          <li key={stage.id}>
            <button
              className={`pipeline-stage ${progress} status-${stage.status}`}
              data-stage-id={stage.id}
              aria-pressed={selectedStageId === stage.id}
              onClick={() => onSelect(stage.id)}
            >
              <span className="pipeline-stage-index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span>
                <strong>{stage.label}</strong>
                <small>{statusText[stage.status]}</small>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

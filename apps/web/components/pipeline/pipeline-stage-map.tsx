import type { PipelineStage } from "../../lib/api";

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
              aria-pressed={selectedStageId === stage.id}
              onClick={() => onSelect(stage.id)}
            >
              <span className="pipeline-stage-index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span>
                <strong>{stage.label}</strong>
                <small>
                  {stage.kind} · {stage.status}
                </small>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

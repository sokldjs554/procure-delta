import type { PipelineStage } from "./api";

export function nextReplayIndex(current: number, length: number): number {
  if (length <= 0) return -1;
  return Math.min(current + 1, length - 1);
}

export type DecisionHeadlineInput = {
  allows_recommendation?: boolean;
  hard_failure_codes?: string[];
  score?: number;
  recommended?: boolean;
};

export function decisionHeadline(value: DecisionHeadlineInput): string {
  if (
    value.allows_recommendation === false ||
    (value.hard_failure_codes?.length ?? 0) > 0
  )
    return "참여 불가 · 관련도와 별개";
  if (value.recommended) return "추천 가능";
  if (value.allows_recommendation === true) return "참여 가능";
  if (
    value.allows_recommendation === undefined &&
    value.recommended === undefined
  )
    return "판단 정보 없음";
  return "추천 기준 미충족";
}

export function displayMetric(
  value: string | number | null | undefined,
): string {
  return value === null || value === undefined ? "미측정" : String(value);
}

type StageSummary = { description: string; result: string };
type StageOutputLayout = "comparison" | "single" | "unavailable";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function validDecision(
  stageId: string,
  value: Record<string, unknown>,
): boolean {
  if (stageId === "eligibility")
    return typeof value.allows_recommendation === "boolean";
  return (
    typeof value.score === "number" &&
    Number.isFinite(value.score) &&
    typeof value.recommended === "boolean"
  );
}

export function stageOutputLayout(stage: PipelineStage): StageOutputLayout {
  if (stage.status === "not_run" || stage.status === "blocked")
    return "unavailable";
  if (stage.id !== "eligibility" && stage.id !== "ranking")
    return "unavailable";
  const before = record(stage.output.before);
  const after = record(stage.output.after);
  if (validDecision(stage.id, before) && validDecision(stage.id, after))
    return "comparison";
  return validDecision(stage.id, stage.output) ? "single" : "unavailable";
}

const explanations: Record<string, string> = {
  collect: "공고 원본을 관측하고 이후 처리에 사용할 출처 식별자를 확인합니다.",
  dedupe:
    "같은 원본이 이미 들어왔는지 확인하고 변경본이면 새 버전으로 보냅니다.",
  normalize: "기관별 공고 형식을 제목·금액·지역 등 공통 필드로 정리합니다.",
  documents: "첨부 문서에서 읽을 수 있는 텍스트와 페이지를 파싱합니다.",
  "ocr-route":
    "문서의 일반 파싱 결과를 보고 OCR 추가 실행이 필요한지 판단합니다.",
  extract: "파싱한 텍스트에서 구조화 필드를 추출합니다.",
  validate: "추출 필드가 스키마와 원문 근거에 맞는지 검증합니다.",
  lifecycle: "이번 관측이 신규 공고인지 기존 공고의 변경본인지 연결합니다.",
  delta: "이전 버전과 현재 버전을 비교해 달라진 필드와 영향도를 찾습니다.",
  eligibility:
    "기업의 필수 참여 조건과 공고를 대조해 추천 허용 여부를 정합니다.",
  ranking: "참여 조건을 통과한 공고의 관련도를 평가하고 추천 여부를 정합니다.",
  notification:
    "새 추천이나 관심 공고 변경이 알림 조건에 해당하는지 판단합니다.",
};

function value(value: unknown): string | null {
  if (typeof value === "string" && value.length) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function eligibilityResult(output: Record<string, unknown>): string {
  if (
    output.allows_recommendation !== true &&
    output.allows_recommendation !== false
  )
    return "참여 가능 여부를 판단할 정보가 없습니다.";
  const codes = Array.isArray(output.hard_failure_codes)
    ? output.hard_failure_codes
    : [];
  return output.allows_recommendation
    ? "참여 가능 · 필수 조건 불일치 없음"
    : `참여 불가${codes.length ? ` · 사유: ${codes.map(String).join(", ")}` : " · 필수 조건 미충족"}`;
}

function rankingResult(output: Record<string, unknown>): string {
  if (
    typeof output.score !== "number" ||
    !Number.isFinite(output.score) ||
    typeof output.recommended !== "boolean"
  )
    return "관련도와 추천 여부를 판단할 정보가 없습니다.";
  return `관련도 ${output.score} · ${output.recommended ? "추천 가능" : "추천 안 함"}`;
}

export function stageSummary(stage: PipelineStage): StageSummary {
  const description =
    explanations[stage.id] ?? "이 단계의 입력과 판단을 확인합니다.";
  if (stage.status === "blocked")
    return {
      description,
      result:
        stage.notice ?? "앞선 단계에서 처리가 중단되어 실행하지 않았습니다.",
    };
  if (stage.status === "not_run")
    return {
      description,
      result: stage.notice ?? "이 시나리오에서는 실행하지 않았습니다.",
    };

  const output = stage.output;
  const decision = stage.decision;
  const fallback = `${stage.label} 단계는 ${stage.status === "warning" ? "주의 상태" : "처리됨"}으로 표시됐지만 구체적인 결과 값은 제공되지 않았습니다.`;
  let result = fallback;
  switch (stage.id) {
    case "collect": {
      const cases = Array.isArray(output.transport_cases)
        ? output.transport_cases
        : [];
      result = cases.length
        ? `${cases.length}개 전송 사례: ${cases.filter((item) => record(item).succeeded === true).length}건 복구, ${cases.filter((item) => record(item).succeeded === false).length}건 종료`
        : output.observed_revision
          ? `변경본 ${String(output.observed_revision)}을 관측했습니다.`
          : output.source_record_id
            ? `원본 ${String(output.source_record_id)}을 관측했습니다.`
            : fallback;
      break;
    }
    case "dedupe":
      result =
        output.new_version_required === true
          ? "중복이 아니며 새 버전으로 처리합니다."
          : output.duplicate === false
            ? "중복이 아니므로 후속 처리로 보냅니다."
            : output.duplicate === true
              ? "동일한 원본이 있어 중복 처리하지 않습니다."
              : fallback;
      break;
    case "normalize": {
      const normalized = Object.keys(record(output.after)).length
        ? record(output.after)
        : output;
      result = value(normalized.title)
        ? `정규화된 제목: ${value(normalized.title)}`
        : Object.keys(normalized).length
          ? `정규화 결과 ${Object.keys(normalized).length}개 필드를 확인할 수 있습니다.`
          : fallback;
      break;
    }
    case "documents":
      result = value(output.parser_kind)
        ? `${String(output.parser_kind)} 파서로 ${value(output.page_count) ?? "페이지 수 미기록"} 페이지를 읽었습니다.`
        : fallback;
      break;
    case "ocr-route":
      result =
        decision.route_to_ocr === true
          ? "OCR 경로를 선택했습니다."
          : decision.route_to_ocr === false
            ? "일반 파싱 경로를 선택해 OCR을 실행하지 않았습니다."
            : fallback;
      break;
    case "extract":
      result =
        value(output.extractor) &&
        Object.keys(output).every((key) =>
          ["extractor", "hosted_llm"].includes(key),
        )
          ? `${output.extractor} 로컬 추출 경로를 사용했습니다. 추출 필드는 응답에 포함되지 않았습니다.`
          : Object.keys(output).length
            ? `추출 결과 ${Object.keys(output).length}개 필드를 확인할 수 있습니다.`
            : fallback;
      break;
    case "validate":
      result =
        output.valid === true
          ? "스키마와 근거 검증을 통과했습니다."
          : output.valid === false
            ? "스키마 또는 근거 검증을 통과하지 못했습니다."
            : fallback;
      break;
    case "lifecycle":
      result = value(output.version_transition)
        ? `버전 흐름: ${output.version_transition}`
        : value(output.link_state)
          ? `연결 상태: ${output.link_state}`
          : fallback;
      break;
    case "delta": {
      const fields = Object.keys(record(output.changed_fields));
      result = fields.length
        ? `${fields.length}개 필드 변경${value(decision.impact) ? ` · 영향도 ${decision.impact}` : ""}: ${fields.join(", ")}`
        : fallback;
      break;
    }
    case "eligibility": {
      const layout = stageOutputLayout(stage);
      result =
        layout === "comparison"
          ? `변경 전 ${eligibilityResult(record(output.before))} → 변경 후 ${eligibilityResult(record(output.after))}`
          : eligibilityResult(layout === "single" ? output : {});
      break;
    }
    case "ranking": {
      const layout = stageOutputLayout(stage);
      result =
        layout === "comparison"
          ? `변경 전 ${rankingResult(record(output.before))} → 변경 후 ${rankingResult(record(output.after))}`
          : rankingResult(layout === "single" ? output : {});
      break;
    }
    case "notification":
      result = value(output.trigger)
        ? `${output.trigger === "new_high_relevance" ? "신규 공고의 높은 관련도를 알림 조건으로 판단했습니다." : output.trigger === "watched_material_change" ? "관심 공고의 중요한 변경을 알림 조건으로 판단했습니다." : `알림 조건 ${output.trigger}를 판단했습니다.`} 외부 발송은 수행하지 않습니다.`
        : "알림 트리거가 기록되지 않았습니다. 외부 발송은 수행하지 않습니다.";
      break;
  }
  return { description, result };
}

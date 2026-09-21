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
  return "추천 기준 미충족";
}


export function displayMetric(
  value: string | number | null | undefined,
): string {
  return value === null || value === undefined ? "미측정" : String(value);
}

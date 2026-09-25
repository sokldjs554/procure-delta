import type { Opportunity, Ranking } from "./api";

export type InboxView = "all" | "strict" | "review" | "amendment";
export type InboxSort = "recommendation" | "deadline" | "budget";

export function filterInbox(items: Opportunity[], view: InboxView): Opportunity[] {
  if (view === "all") return items;
  if (view === "amendment") return items.filter(item => item.lifecycle_stage === "amendment");
  if (view === "strict") return items.filter(item =>
    item.decision_status === "ready" && item.eligibility?.eligible === true &&
    item.eligibility.hard_failures.length === 0 && item.eligibility.warnings.length === 0,
  );
  return items.filter(item => {
    if (item.decision_status !== "ready" || !item.eligibility) return true;
    return item.eligibility.hard_failures.length === 0 &&
      (item.eligibility.warnings.length > 0 || !item.eligibility.eligible);
  });
}

function finiteNumber(value: string | null | undefined): number | null {
  if (value == null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function scorePercent(ranking: Ranking | null): number | null {
  const score = finiteNumber(ranking?.final_score);
  return score === null ? null : Math.round(score * 100);
}

function knownFirst(a: number | null, b: number | null, direction: 1 | -1): number {
  if (a === null) return b === null ? 0 : 1;
  if (b === null) return -1;
  return (a - b) * direction;
}

export function sortInbox(items: Opportunity[], sort: InboxSort): Opportunity[] {
  if (sort === "budget") {
    // Currency buckets follow the order encountered in the loaded results. No conversion is implied.
    const currencyOrder = new Map<string, number>();
    for (const item of items) {
      if (finiteNumber(item.estimated_amount) !== null && !currencyOrder.has(item.currency)) {
        currencyOrder.set(item.currency, currencyOrder.size);
      }
    }
    return [...items].sort((a, b) => {
      const amountA = finiteNumber(a.estimated_amount), amountB = finiteNumber(b.estimated_amount);
      if (amountA === null || amountB === null) return knownFirst(amountA, amountB, -1);
      return (currencyOrder.get(a.currency)! - currencyOrder.get(b.currency)!) || knownFirst(amountA, amountB, -1);
    });
  }
  if (sort === "deadline") return [...items].sort((a, b) => {
    const aDate = a.closes_at ? Date.parse(a.closes_at) : NaN;
    const bDate = b.closes_at ? Date.parse(b.closes_at) : NaN;
    return knownFirst(Number.isFinite(aDate) ? aDate : null, Number.isFinite(bDate) ? bDate : null, 1);
  });
  return [...items].sort((a, b) => {
    const scoreA = finiteNumber(a.ranking?.final_score), scoreB = finiteNumber(b.ranking?.final_score);
    if (scoreA === null || scoreB === null) return knownFirst(scoreA, scoreB, -1);
    return Number(Boolean(b.ranking?.recommended)) - Number(Boolean(a.ranking?.recommended)) || knownFirst(scoreA, scoreB, -1);
  });
}

export function toggleComparison(current: string[], id: string, availableIds: string[]): string[] {
  if (current.includes(id)) return current.filter(value => value !== id);
  if (!availableIds.includes(id) || current.length >= 3) return current;
  return [...current, id];
}

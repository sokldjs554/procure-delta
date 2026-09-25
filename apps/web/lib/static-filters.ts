import type { Opportunity } from "./api";

/** The public fixture supports the same visible filters without inventing server totals. */
export function filterStaticOpportunities(items: Opportunity[], query: URLSearchParams) {
  const amount = (key: string) => {
    const raw = query.get(key);
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) throw Error("금액 필터를 확인해 주세요.");
    return value;
  };
  const date = (key: string) => {
    const raw = query.get(key);
    if (!raw) return null;
    const value = Date.parse(raw);
    if (!Number.isFinite(value)) throw Error("날짜 필터를 확인해 주세요.");
    return value;
  };
  const min = amount("amount_min"), max = amount("amount_max");
  const from = date("deadline_from"), to = date("deadline_to"), changed = date("changed_since");
  if ((min !== null && max !== null && min > max) || (from !== null && to !== null && from > to)) {
    throw Error("필터의 시작 값은 끝 값보다 클 수 없습니다.");
  }
  const q = (query.get("q") ?? "").trim().toLocaleLowerCase();
  const buyer = (query.get("buyer") ?? "").trim().toLocaleLowerCase();
  const category = (query.get("category") ?? "").trim().toLocaleLowerCase();
  const stage = query.get("lifecycle_stage");
  const eligibleOnly = query.get("eligible_only") === "true";
  return items.filter(item => {
    const value = item.estimated_amount === null ? null : Number(item.estimated_amount);
    const deadline = item.closes_at ? Date.parse(item.closes_at) : null;
    const changedAt = item.changed_at ? Date.parse(item.changed_at) : null;
    return (!q || `${item.title} ${item.buyer_name}`.toLocaleLowerCase().includes(q))
      && (!buyer || item.buyer_name.toLocaleLowerCase().includes(buyer))
      && (!category || item.procurement_type?.toLocaleLowerCase() === category)
      && (!stage || item.lifecycle_stage === stage)
      && (min === null || (value !== null && value >= min))
      && (max === null || (value !== null && value <= max))
      && (from === null || (deadline !== null && deadline >= from))
      && (to === null || (deadline !== null && deadline <= to))
      && (changed === null || (changedAt !== null && changedAt > changed))
      && (!eligibleOnly || (item.decision_status === "ready" && item.eligibility?.eligible === true
        && !item.eligibility.hard_failures.length && !item.eligibility.warnings.length));
  });
}
